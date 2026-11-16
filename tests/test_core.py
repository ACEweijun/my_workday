"""纯逻辑与仓库一致性单测，不需要安装 Home Assistant。"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'custom_components' / 'workday_maintenance'

_pkg = types.ModuleType('workday_maintenance')
_pkg.__path__ = [str(PKG)]
sys.modules['workday_maintenance'] = _pkg


def _load(name):
    spec = importlib.util.spec_from_file_location('workday_maintenance.' + name, PKG / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['workday_maintenance.' + name] = module
    spec.loader.exec_module(module)
    return module


const = _load('const')
wd = _load('workday')
mnt = _load('maintenance')


class TestWorkday(unittest.TestCase):
    def setUp(self):
        self.h = {'off': set(), 'makeup': set(), 'names': {}}

    def test_weekend_and_weekday(self):
        self.assertTrue(wd.classify(dt.date(2026, 11, 13), self.h, set(), set())[0])
        self.assertFalse(wd.classify(dt.date(2026, 11, 14), self.h, set(), set())[0])

    def test_makeup_day(self):
        self.h['makeup'].add('2026-11-14')
        work, label = wd.classify(dt.date(2026, 11, 14), self.h, set(), set())
        self.assertTrue(work)
        self.assertEqual(label, '补班')

    def test_custom_overrides_holiday(self):
        self.h['off'].add('2026-11-13')
        self.assertFalse(wd.classify(dt.date(2026, 11, 13), self.h, set(), set())[0])
        self.assertTrue(wd.classify(dt.date(2026, 11, 13), self.h,
                                    {'2026-11-13'}, set())[0])
        self.assertFalse(wd.classify(dt.date(2026, 11, 13), self.h,
                                     {'2026-11-13'}, {'2026-11-13'})[0])

    def test_month_stats(self):
        stats = wd.month_stats(2026, 11, dt.date(2026, 11, 1), self.h, set(), set())
        self.assertGreater(stats['total'], 15)
        self.assertEqual(stats['left'], stats['total'])
        self.assertEqual(stats['passed'], 0)

    def test_todos_roundtrip(self):
        text = '2026-11-13 交月度报表\n[x] 2026-11-10 提交巡检记录'
        items = wd.parse_todos(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[1]['done'])
        self.assertEqual(wd.parse_todos(wd.todos_text(items)), items)

    def test_anniversaries(self):
        items = wd.parse_anniversaries('生日: 05-20\n项目上线: 2026-12-01')
        self.assertTrue(items[0]['repeat'])
        self.assertFalse(items[1]['repeat'])

    def test_year_text_range(self):
        parsed = wd.parse_year_text('2026-10-01~2026-10-03 国庆放假\n2026-10-11 补班')
        self.assertEqual(len(parsed['off']), 3)
        self.assertIn('2026-10-11', parsed['makeup'])

    def test_holiday_payload(self):
        payload = {'2026': {'01-01': {'name': '元旦', 'isOffDay': True},
                            '02-07': {'name': '补班', 'isOffDay': False}}}
        parsed = wd.holiday_payload_to_holidays(payload, 2026)
        self.assertIn('2026-01-01', parsed['off'])
        self.assertIn('2026-02-07', parsed['makeup'])

    def test_next_holiday(self):
        self.h['off'].update({'2026-12-25', '2026-12-26'})
        self.h['names']['2026-12-25'] = '圣诞'
        found = wd.next_holiday(dt.date(2026, 12, 1), self.h)
        self.assertEqual(found['name'], '圣诞')
        self.assertEqual(found['total_days'], 2)

    def test_clean_todos(self):
        items = [{'id': 'a', 'date': '2020-01-01', 'text': '旧', 'done': True},
                 {'id': 'b', 'date': '2026-11-13', 'text': '新', 'done': False}]
        self.assertEqual(len(wd.clean_todos(items, dt.date(2026, 11, 13))), 1)


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 11, 13)
        self.project = mnt.make_project('corolla', '卡罗拉', 'vehicle', True,
                                        '公里', '里程', 82000, self.today)

    def test_preset_items(self):
        self.assertGreater(len(self.project['items']), 3)
        self.assertTrue(self.project['need_counter'])

    def test_unset_status(self):
        state = mnt.item_state(self.project['items'][0], self.project, self.today, 7)
        self.assertEqual(state['status'], 'unset')

    def test_log_and_due(self):
        item = self.project['items'][0]
        rid = mnt.log_service(self.project, [item['id']], '2026-05-12', 80000,
                              {item['id']: '4S 店'}, self.today)
        self.assertTrue(rid)
        self.assertEqual(item['last_date'], '2026-05-12')
        self.assertEqual(len(self.project['history']), 1)
        item['interval_days'] = 30
        state = mnt.item_state(item, self.project, self.today, 7)
        self.assertEqual(state['status'], 'due')

    def test_delete_recomputes_baseline(self):
        item = self.project['items'][0]
        rid = mnt.log_service(self.project, [item['id']], '2026-10-01', 81000, {}, self.today)
        mnt.delete_record_entry(self.project, rid, item['id'])
        self.assertIsNone(item['last_date'])
        self.assertEqual(self.project['history'], [])

    def test_summary_counts(self):
        item = self.project['items'][0]
        item['last_date'] = '2026-11-01'
        item['interval_days'] = 5
        summary = mnt.project_summary(self.project, self.today, 7)
        self.assertEqual(summary['due_count'], 1)
        self.assertIn(item['name'], summary['due_names'])

    def test_all_due_items(self):
        self.project['items'][0]['last_date'] = '2026-01-01'
        self.project['items'][0]['interval_days'] = 30
        items = mnt.all_due_items([self.project], self.today, 7)
        self.assertTrue(any(i['slug'] == 'corolla' for i in items))

    def test_export(self):
        text = mnt.export_markdown(self.project, self.today, 7)
        self.assertIn('卡罗拉', text)
        self.assertIn('维护小项', text)


class TestRepo(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((PKG / 'manifest.json').read_text(encoding='utf-8'))
        for key in ('domain', 'name', 'version', 'config_flow', 'documentation',
                    'issue_tracker', 'codeowners', 'requirements', 'dependencies'):
            self.assertIn(key, manifest)
        self.assertEqual(manifest['domain'], 'workday_maintenance')

    def test_services_match_yaml(self):
        declared = set(re.findall(r'^SERVICE_[A-Z_]+\s*=\s*"([^"]+)"',
                                  (PKG / 'const.py').read_text(encoding='utf-8'), re.M))
        defined = set(re.findall(r'^([a-z_]+):\s*$',
                                 (PKG / 'services.yaml').read_text(encoding='utf-8'), re.M))
        self.assertEqual(declared, defined)

    def test_two_pages_share_layer(self):
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertIn('shared.js', html)
            self.assertIn('shared.css', html)
            self.assertIn('M.onUpdate', html)
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('subscribe_events', shared)
        self.assertIn('workday_maintenance_updated', shared)

    def test_no_inline_page_links(self):
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertNotIn('href="workday.html"', html)
            self.assertNotIn('href="maintenance.html"', html)
            self.assertNotIn('dueBadge', html)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertNotIn('.link{', css)

    def test_refresh_guard_present(self):
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        for token in ('setReady', 'installGuards', 'beforeunload',
                      "addEventListener('click', guard, true)"):
            self.assertIn(token, shared)
        for page in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / page).read_text(encoding='utf-8')
            self.assertIn('M.setReady(true)', html)
            self.assertIn('M.setReady(false)', html)
            self.assertIn('retryLoad()', html)

    def test_project_tab_reset(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('resetForms()', html)
        self.assertIn('if (target === slug)', html)
        self.assertIn('renderRecEntries(', html)
        self.assertIn("openRecForm(null)", html)
        self.assertNotIn('Number(this.value)', html)

    def test_item_name_vs_blank_click(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        # 点名称=编辑小项；点行空白=给该小项记一次新维护
        self.assertIn('data-itemname', html)
        self.assertIn("var nm = t.closest && t.closest('[data-itemname]')", html)
        self.assertIn("openItemForm(title.dataset.item)", html)
        self.assertIn("openRecForm(null, title.dataset.item)", html)
        # 聚焦单小项时标题不再叫“记录多项维护”
        self.assertIn('记录维护 · ', html)

    def test_options_flow_constructor(self):
        src = (PKG / 'config_flow.py').read_text(encoding='utf-8')
        self.assertIn('return MyWorkdayOptionsFlow()', src)
        self.assertIn('async_get_entry(self.handler)', src)

    def test_service_response_unwrap(self):
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn('x.service_response', shared)
        self.assertIn('x.response', shared)

    def test_workday_legacy_ui(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('FOLD_KEY', 'data-fold="todos"', 'applyFolds', 'contextmenu',
                      'touchstart', 'calYear', 'data-donegroup', 'cellMenu',
                      'todoSummary', 'customSummary'):
            self.assertIn(token, html)

    def test_maintenance_legacy_ui(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="projMask"', 'id="itemMask"', 'id="recMask"',
                      'id="unitBox"', 'syncUnit', 'autoSlug', 'data-item=',
                      '记录多项维护', 'mt-side', 'counterValue',
                      'data-recheck=', 'renderRecEntries(', 'id="recDelete"'):
            self.assertIn(token, html)
        for gone in ('projStep1', 'projStep2', 'projNext', 'projUnitLabel',
                     'data-baseline=', 'data-logone=', 'data-edit=', 'set_baseline',
                     'id="projMenu"', 'data-pm=', 'renderMenu(',
                     'id="logMask"', 'renderLogItems(', 'data-lognote',
                     'data-history=', 'expanded['):
            self.assertNotIn(gone, html)

    def test_layout_css_fixes(self):
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.mt-layout{display:flex;flex-direction:row;', css)
        self.assertIn('#overview{grid-template-columns:repeat(2,', css)
        self.assertNotIn('#overview{grid-template-columns:repeat(4,', css)

    def test_stats_follow_month_and_jump_today(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function monthStats()', 'function jumpToday()',
                      'data-jump-today', '月 · 剩余/总数',
                      'renderStats(); renderCal();'):
            self.assertIn(token, html)
        self.assertNotIn('dateLabel', html)
        self.assertNotIn('本月工作日', html)

    def test_next_special_day_merges_holidays_and_anniversaries(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function nextSpecialDay()', '>距离 - ',
                      'S.workday.anniversaries', 'h.off || []'):
            self.assertIn(token, html)
        self.assertNotIn('next_holiday', html)

    def test_day_label_and_menu_modes(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function dayLabel(', 'function baseWork(', 'function customMode('):
            self.assertIn(token, html)
        for gone in ('data-mday=', '算上班</button>',
                     '算休息</button>', '恢复安排</button>', 'function inlineEdit('):
            self.assertNotIn(gone, html)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertNotIn('.stat .sub2', css)
        self.assertIn('.stat .lbl.ellip', css)
        self.assertIn('.cell .d{font-size:19px', css)
        self.assertIn('.cal-head div{font-size:13px', css)

    def test_delete_project_confirmation_works(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn("armDel('project')", html)
        self.assertIn("$('projDelete').textContent = '确认删除这个项目'", html)
        self.assertIn("write('delete_project', { slug: target })", html)
        self.assertNotIn('var armed = deleteArmed;', html)

    def test_backend_next_special_day(self):
        h = {'off': {'2027-01-01'}, 'names': {'2027-01-01': '元旦'}, 'makeup': set()}
        anns = [{'name': '结婚纪念日', 'date': '11-16', 'repeat': True}]
        found = wd.next_special_day(dt.date(2026, 11, 15), h, anns)
        self.assertEqual(found['name'], '结婚纪念日')
        self.assertEqual(found['days'], 1)
        self.assertEqual(found['kind'], '纪念日')
        self.assertIn('next_event', (PKG / 'coordinator.py').read_text(encoding='utf-8'))
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        self.assertIn('workday.next_event', w)

    def test_menu_add_opens_modal_directly(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-madd', 'openAddForm(', 'switchAddType(', 'bindAddTypes(',
                      'data-addtype', 'id="todoTypes"', 'id="annTypes"',
                      'menu-existing', 'menu-add'):
            self.assertIn(token, w)
        self.assertNotIn('menuAdding', w)
        self.assertNotIn('data-mtype', w)
        self.assertNotIn('收起新增', w)
        self.assertLess(w.index('+ 新增</button>'), w.index('menu-existing'))
        self.assertNotIn('这天还没有安排', w)
        self.assertNotIn('id="thisM"', w)
        self.assertNotIn('<header class="bar">', w)

    def test_top_bars_removed_and_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="projMask"', 'class="modal"', 'id="projClose"',
                      "$('projMask').hidden = false", 'projMask', 'resetForms'):
            self.assertIn(token, m)
        self.assertNotIn('<header class="bar">', m)
        self.assertNotIn('taskLabel', m)
        self.assertNotIn("$('projForm')", m)
        self.assertIn('.modal-mask', (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_guards_and_validations(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('fingerprint(', '数据已被其他页面修改', 'armDel(', 'customDirty',
                      '请用日期控件选择日期'):
            self.assertIn(token, w)
        for token in ('请填写有效的计数值', '间隔天数要填', '维护日期要填',
                      'btn.disabled = true', '确认删除'):
            self.assertIn(token, m)

    def test_font_and_mobile_css(self):
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('--fs:', '--tap:', 'var(--fs)', 'month-nav', 'month-center',
                      'nav-arrow', '@media (max-width:620px)', 'stat[data-jump-today]:hover'):
            self.assertIn(token, css)
        self.assertIn('.mt-side .tab.add', css)

    def test_workday_add_modals(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="todoMask"', 'id="annMask"', 'function openTodo(',
                      'function openAnn(', 'id="todoSave"', 'id="annSave"',
                      'closeTodo()', 'closeAnn()'):
            self.assertIn(token, html)
        self.assertNotIn('id="todoForm"', html)
        self.assertNotIn('id="annForm"', html)

    def test_slugify_cjk_fallback(self):
        mnt = _load('maintenance')
        self.assertTrue(mnt.slugify('卡罗拉').startswith('p_'))
        self.assertEqual(mnt.slugify('Corolla'), 'corolla')

    def test_todo_list_flat_sorted_and_click_to_edit(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function todoWhen(', 'function todoRow(', 'class="sub todo-when"',
                      'data-todo-edit=', 'function openTodo(', 'editingTodo',
                      'data-donegroup'):
            self.assertIn(token, html)
        self.assertNotIn("groups = [['逾期'", html)
        self.assertNotIn("'未来 7 天'", html)
        self.assertIn('.todo-when', (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_unified_edit_paths(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-mtodo-open=', 'data-mann-open=', 'data-ann-edit=',
                      'function openAnn(id, date)', 'function openTodo(id, date)',
                      'function saveAnn()'):
            self.assertIn(token, w)
        for gone in ('menuInput', 'menu-x', 'data-mclose', 'data-mtodo-done=',
                     'data-mtodo-edit=', 'data-mann-edit=',
                     'inlineEdit(', 'saveAnns('):
            self.assertNotIn(gone, w)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="projDelete"', m)
        for gone in ('id="projEdit"', 'data-pm="edit"', 'data-pm="log"', '导出 JSON 备份',
                     '导出当前项目 JSON', '导出 Markdown', 'projExportJson', 'projExportMd'):
            self.assertNotIn(gone, m)

    def test_backend_anniversary_repeat_types(self):
        today = dt.date(2026, 11, 15)
        cases = [
            ({'name': '周会', 'date': '2026-11-02', 'repeat': 'week'}, dt.date(2026, 11, 16)),
            ({'name': '月结', 'date': '2026-10-05', 'repeat': 'month'}, dt.date(2026, 12, 5)),
            ({'name': '季检', 'date': '2026-08-15', 'repeat': 'quarter'}, dt.date(2026, 11, 15)),
            ({'name': '结婚', 'date': '2026-11-16', 'repeat': 'year'}, dt.date(2026, 11, 16)),
            ({'name': '交付', 'date': '2027-03-18', 'repeat': 'none'}, dt.date(2027, 3, 18)),
            ({'name': '旧格式', 'date': '11-16', 'repeat': True}, dt.date(2026, 11, 16)),
        ]
        for item, expect in cases:
            self.assertEqual(wd.anniversary_next(item, today), expect, item['name'])

    def test_anniversary_form_controls(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('type="date" id="annDate"', '重复类型',
                      '<option value="week">每周</option>',
                      '<option value="month">每月</option>',
                      '<option value="quarter">每季度</option>',
                      '<option value="year">每年</option>',
                      'ANN_TYPES', 'function annNext(', 'function annOn('):
            self.assertIn(token, html)
        self.assertNotIn('每年重复', html)
        self.assertNotIn("value=\"1\">是</option>", html)

    def test_third_stat_jumps_to_next_event(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-jump-event', 'function jumpToEvent()', 'selectedCell = ev.date'):
            self.assertIn(token, html)
        self.assertIn('.stat[data-jump-event]:hover',
                      (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_project_name_click_edits_and_modal_has_delete(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("if (target === slug) { openForm(true); return; }",
                      'openForm(true)', 'id="projDelete"', 'function deleteProject()',
                      'id="projExtra"', 'function renderCounter()'):
            self.assertIn(token, m)
        for gone in ('id="projMenu"', 'contextmenu', 'id="projectHead"',
                     'id="projectType"', 'id="overview"', 'data-del=',
                     'id="projExportJson"', 'id="projExportMd"'):
            self.assertNotIn(gone, m)

    def test_history_rows_open_record_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("$('history').onclick", 'data-rec=', 'function openRecForm(recordId, focusItem)',
                      'id="recEntries"', 'data-renote=', 'data-recheck=',
                      'function saveRecForm()', 'rec-row', '一次维护一行',
                      'function deleteRec()', 'renderRecEntries('):
            self.assertIn(token, m)
        for gone in ('data-redit=', 'data-rdel=', 'id="recItem"', 'id="recNote"',
                     '整次维护的流水，只读', 'data-renotedel=', 'data-history='):
            self.assertNotIn(gone, m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.proj-title:hover', css)
        self.assertIn('.rec-row:hover', css)
        self.assertIn('.rec-ent', css)

    def test_removed_hints_and_menu_close_button(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for gone in ('sourceLabel', '放假数据：', 'holiday-cn 自动获取',
                     'menu-x', 'data-mclose'):
            self.assertNotIn(gone, w)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertNotIn('离开输入框自动保存', m)
        self.assertIn('document.addEventListener(\'click\'', w)

    def test_project_tabs_horizontal_top(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertLess(m.index('class="mt-side"'), m.index('class="mt-main"'))
        self.assertIn('data-tab=', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('.mt-layout{flex-direction:column}',
                      '.mt-side{width:100%;flex:none;flex-direction:row',
                      '.mt-side .tab.on{',
                      '.mt-side .tab{min-width:84px}'):
            self.assertIn(token, css)

    def test_interval_counter_hidden_without_project_counter(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="itemIntervalBox" hidden', m)
        self.assertIn("$('itemIntervalBox').hidden = !p.need_counter", m)
        self.assertIn("p.need_counter && i && i.interval_counter != null", m)

    def test_unified_record_modal_modes(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ("var fItem = focusItem ? (p.items || []).filter(function (x) { return x.id === focusItem; })[0] : null;",
                      "记录维护 · ", "M.call('log_service', data)", 'function collectRecForm()',
                      'function deleteRec()', '本次未记录', '取消勾选即从这次记录中移除'):
            self.assertIn(token, m)
        self.assertIn("openRecForm(null)", m)
        self.assertIn("openRecForm(row.dataset.rec)", m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.rec-check', css)
        self.assertIn('.modal-actions', css)

    def test_single_item_record_hides_redundant_checkbox(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        # 聚焦单小项新记录：不再为那唯一的小项显示勾选框
        self.assertIn('var singleNew = focusItem && !rec;', m)
        self.assertIn("'<div class=\"rec-name\">' + M.esc(i.name) + '</div>'", m)
        # 收集逻辑改为按行遍历，无勾选框即视为已勾选
        self.assertIn("row.getAttribute('data-renoterow')", m)
        self.assertIn('var checked = cb ? cb.checked : true;', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.rec-name', css)

    def test_date_picker_whole_row_clickable(self):
        for f in ('workday.html', 'maintenance.html'):
            html = (PKG / 'frontend' / f).read_text(encoding='utf-8')
            # 点输入框本身 / 标签 / 整行都触发 showPicker（去掉 input 跳过判断）
            self.assertNotIn("el.addEventListener('click', open)", html)
            self.assertNotIn('if (e.target === el) return;', html)
            self.assertIn('if (typeof el.showPicker ===', html)

    def test_workday_stat_labels_simplified(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        # 今天卡片：只显示「今天」，不再带日期与星期
        self.assertIn("'<div class=\"lbl\">今天</div></div>'", w)
        self.assertNotIn("'今天 · ' + S.today", w)
        # 距离卡片：只显示名称，日期移到 title
        self.assertIn("M.esc(ev.name) + '</div>'", w)

    def test_import_projects_interface(self):
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('async def import_projects', init)
        self.assertIn('if isinstance(raw_projects, dict):', init)
        self.assertIn('(SERVICE_IMPORT_PROJECTS, import_projects)', init)
        sv = (PKG / 'services.yaml').read_text(encoding='utf-8')
        self.assertIn('import_projects:', sv)
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn("M.call('import_projects', { json: text }, true)", m)
        self.assertIn('id="importMask"', m)
        self.assertIn('id="importText"', m)
        self.assertIn('id="projImport"', m)

    def test_delete_labels_are_explicit(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('删除这个项目', '删除这个小项', '删除这次记录'):
            self.assertIn(token, m)

    def test_menu_todo_checkbox_and_delete(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        self.assertIn("if (e && e.stopPropagation) e.stopPropagation();", w)
        for token in ('data-mtodo-check=', 'data-mtodo-del=', 'data-mann-del=',
                      "$('cellMenu').onchange", 'menu-check', 'saveTodos('):
            self.assertIn(token, w)
        self.assertIn('.menu .mrow input[type=checkbox]',
                      (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8'))

    def test_due_items_open_record_modal(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="dueMask"', 'id="dueInfo"', 'function openDueForm(pslug, itemId)',
                      'function saveDue()', 'data-mdueslug=', 'data-dueitem=',
                      "write('log_service', data)", "dueList').onclick",
                      'due-click', 'due-row'):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.due-info', css)
        self.assertIn('.due-row:hover', css)

    def test_item_delete_moved_into_edit_modal(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('id="itemDelete" hidden', 'function deleteItem()',
                      "$('itemDelete').hidden = !id", '确认删除这个小项'):
            self.assertIn(token, m)
        self.assertNotIn("data-del=", m)

    def test_project_card_header_stripped(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for gone in ('id="projectHead"', 'id="projectType"', 'id="overview"',
                     'renderOverview(', '已到期</div>', '快到了</div>'):
            self.assertNotIn(gone, m)
        self.assertIn('function renderCounter()', m)

    def test_action_buttons_moved_to_items_head(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertNotIn('id="logOpen"', m)
        self.assertEqual(m.count('id="itemAdd"'), 1)
        self.assertIn('id="itemsHead"', m)
        self.assertIn('class="card-head items-head" id="itemsHead"', m)
        self.assertIn("$('itemsHead').onclick", m)
        self.assertIn("closest('#itemAdd')", m)
        self.assertIn('openRecForm(null)', m)

    def test_history_collapsed_by_default(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('id="histHead"', m)
        self.assertIn('id="histBody" hidden', m)
        self.assertIn('id="histArrow"', m)
        self.assertIn('$(\'histHead\').onclick', m)
        self.assertIn('histOpen = !histOpen', m)
        self.assertIn("histOpen ? '▾' : '▸'", m)

    def test_date_field_picker_indicator(self):
        for f in ('workday.html', 'maintenance.html'):
            h = (PKG / 'frontend' / f).read_text(encoding='utf-8')
            self.assertNotIn('if (e.target === el) return;', h)
            self.assertIn('el.showPicker()', h)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('::-webkit-calendar-picker-indicator', css)
        self.assertIn('width:100%;height:100%', css)

    def test_item_own_records_clickable(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('function itemRecords(', 'data-recitem=', 'item-records',
                      'data-rectoggle=', 'itemOpen', 'class="item-note"',
                      'item-meta-toggle', "'上次 ' + M.esc(last.date)", '暂无维护记录',
                      'openRecForm(recordId, focusItem)', 'id="recFocus"',
                      '编辑这条维护记录', '移除这条记录', 'renderRecEntries(p, rec, focusItem)',
                      'if (!focus || e.item_id === focus)'):
            self.assertIn(token, m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.item-records{', css)
        self.assertIn('.item-note{', css)
        self.assertNotIn('维护记录 (', m)

    def test_cell_tooltip_multiline(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('id="cellTip"', 'data-tip=', "parts.join('\\n')",
                      'function showTip(', 'function positionTip(',
                      "'mouseover'", "'mousemove'", "'mouseout'", 'tip-todo'):
            self.assertIn(token, w)
        self.assertNotIn("parts.join(' / ')", w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.cell-tip{', css)
        self.assertIn('.cell-tip div+div{', css)

    def test_frontend_routing_and_ws_snapshot(self):
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('FrontendFileView', init)
        self.assertNotIn('StaticPathConfig', init)
        self.assertIn('workday_maintenance/snapshot', init)
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn("type: 'workday_maintenance/snapshot'", shared)
        self.assertIn('snapshotViaWS', shared)
        manifest = json.loads((PKG / 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('websocket_api', manifest['dependencies'])

    def test_add_modal_type_switch(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('openAddForm(date,', "openAddForm(S.today, 'todo')",
                      "openAddForm(S.today, 'ann')", '$(\'todoTypes\').hidden = !!id',
                      '$(\'annTypes\').hidden = !!id', "if (type === 'ann')"):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.add-types{', css)
        self.assertIn('.add-types button.on{', css)

    def test_tooltip_flips_near_viewport_edge(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ("el.style.left = '0px'", 'if (left > maxLeft) left = px - w - 14;',
                      'if (top > maxTop) top = py - h - 14;', 'e.relatedTarget && cell.contains'):
            self.assertIn(token, w)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        for token in ('width:max-content', 'max-height:min(60vh,420px)',
                      'box-sizing:border-box', 'overflow:hidden'):
            self.assertIn(token, css)

    def test_item_meta_shows_latest_record(self):
        m = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        for token in ('var last = recs[0] || null', "'上次 ' + M.esc(last.date)",
                      '暂无维护记录', 'item-meta-static', 'lastEntry'):
            self.assertIn(token, m)
        self.assertNotIn('上次维护：', m)
        self.assertNotIn('var left = st.remaining_days', m)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.item-meta-static{', css)


if __name__ == '__main__':
    unittest.main()
