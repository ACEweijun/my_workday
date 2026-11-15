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
PKG = ROOT / 'custom_components' / 'my_workday'

_pkg = types.ModuleType('my_workday')
_pkg.__path__ = [str(PKG)]
sys.modules['my_workday'] = _pkg


def _load(name):
    spec = importlib.util.spec_from_file_location('my_workday.' + name, PKG / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['my_workday.' + name] = module
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
        self.assertEqual(manifest['domain'], 'my_workday')

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
        self.assertIn('my_workday_updated', shared)

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
        self.assertIn('kept.indexOf(i.id)', html)
        self.assertNotIn('Number(this.value)', html)

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
        for token in ('projStep1', 'projStep2', 'projNext', 'projUnitLabel',
                      'data-pm=', 'logtable', 'mt-side', 'contextmenu',
                      'counterValue', 'data-lognote'):
            self.assertIn(token, html)

    def test_layout_css_fixes(self):
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.mt-layout{display:flex;flex-direction:row;', css)
        self.assertIn('#overview{grid-template-columns:repeat(4,', css)

    def test_stats_follow_month_and_jump_today(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function monthStats()', 'function jumpToday()',
                      'data-jump-today', '月工作日 · 剩余/总数',
                      'renderStats(); renderCal();'):
            self.assertIn(token, html)
        self.assertNotIn('dateLabel', html)
        self.assertNotIn('本月工作日', html)

    def test_next_special_day_merges_holidays_and_anniversaries(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function nextSpecialDay()', '<div class="lbl">距离</div>',
                      'S.workday.anniversaries', 'h.off || []'):
            self.assertIn(token, html)
        self.assertNotIn('next_holiday', html)

    def test_day_label_and_menu_modes(self):
        html = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('function dayLabel(', 'function baseWork(', 'function customMode(',
                      'if (!curWork)', 'if (cm) modes +='):
            self.assertIn(token, html)
        self.assertNotIn("' · ' + (c.work ? '上班' : '休息')", html)
        css = (PKG / 'frontend' / 'shared.css').read_text(encoding='utf-8')
        self.assertIn('.stat .sub2', css)

    def test_delete_project_confirmation_works(self):
        html = (PKG / 'frontend' / 'maintenance.html').read_text(encoding='utf-8')
        self.assertIn('var armed = deleteArmed;', html)
        self.assertIn('if (!armed)', html)
        self.assertNotIn("write('delete_project', { slug: target }).then(function ()", html)

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

    def test_menu_two_stage_and_order(self):
        w = (PKG / 'frontend' / 'workday.html').read_text(encoding='utf-8')
        for token in ('data-madd', 'menuAdding', 'menu-existing', 'menu-add'):
            self.assertIn(token, w)
        self.assertLess(w.index("'+ 新增'"), w.index('menu-existing'))
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
                      '日期格式应为', '无放假数据'):
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

    def test_frontend_routing_and_ws_snapshot(self):
        init = (PKG / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('FrontendFileView', init)
        self.assertNotIn('StaticPathConfig', init)
        self.assertIn('my_workday/snapshot', init)
        shared = (PKG / 'frontend' / 'shared.js').read_text(encoding='utf-8')
        self.assertIn("type: 'my_workday/snapshot'", shared)
        self.assertIn('snapshotViaWS', shared)
        manifest = json.loads((PKG / 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('websocket_api', manifest['dependencies'])


if __name__ == '__main__':
    unittest.main()
