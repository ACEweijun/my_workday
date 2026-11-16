/* demo-data.js —— 本地预览专用虚拟数据层
 * 部署到 Home Assistant 后自动失效（有 hassTokens 或页面路径为 /workday_maintenance/ 时立即退出）。
 * 所有日期基于"今天"动态生成，示例数据不会过期。
 */
(function () {
  'use strict';
  var MW = window.MW;
  if (!MW) return;

  // 真 HA 环境立即退出，不接管
  try {
    if (window.localStorage && localStorage.getItem('hassTokens')) return;
  } catch (e) { /* 沙箱无 localStorage，继续 */ }
  if (String(window.location && window.location.pathname).indexOf('/workday_maintenance/') >= 0) return;

  var SOON_DAYS = 7;
  var NOW = new Date();
  function pad(n) { return String(n).padStart(2, '0'); }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function dayOffset(n) { var d = new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate() + n); return iso(d); }
  var TODAY = iso(NOW);
  function parse(s) { return new Date(s + 'T00:00:00'); }
  function dayDiff(a, b) { return Math.round((parse(a) - parse(b)) / 86400000); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  // ---------- 虚拟项目数据（日期全部相对今天） ----------
  var PROJECTS = [
    {
      slug: 'car', name: '公司车 · 粤B12345', type: 'vehicle',
      need_counter: true, counter_unit: '公里', counter_label: '里程', counter: 68500,
      items: [
        { id: 'ci1', name: '机油 + 机油滤芯', interval_days: 180, interval_counter: 10000, last_date: dayOffset(-180), last_counter: 61000, note: '全合成' },
        { id: 'ci2', name: '空调滤芯', interval_days: 365, interval_counter: 20000, last_date: dayOffset(-380), last_counter: 42000, note: '' },
        { id: 'ci3', name: '轮胎换位', interval_days: 365, interval_counter: 20000, last_date: dayOffset(-360), last_counter: 55000, note: '四轮交叉' }
      ],
      history: [
        { id: 'hr1', date: dayOffset(-180), counter: 61000, entries: [{ item_id: 'ci1', note: '更换全合成机油 + 机滤' }] },
        { id: 'hr2', date: dayOffset(-360), counter: 55000, entries: [{ item_id: 'ci3', note: '前后交叉换位' }] },
        { id: 'hr3', date: dayOffset(-380), counter: 42000, entries: [{ item_id: 'ci2', note: '更换空调滤芯' }] },
        { id: 'hr0', date: dayOffset(-400), counter: 38000, entries: [{ item_id: 'ci1', note: '首次保养' }] }
      ]
    },
    {
      slug: 'washer', name: '办公室洗衣机', type: 'appliance',
      need_counter: false, counter_unit: '', counter_label: '', counter: null,
      items: [
        { id: 'wi1', name: '清洗筒内 / 过滤器', interval_days: 90, interval_counter: null, last_date: dayOffset(-93), last_counter: null, note: '' },
        { id: 'wi2', name: '机身内外擦拭', interval_days: 30, interval_counter: null, last_date: dayOffset(-6), last_counter: null, note: '顺手清洁' }
      ],
      history: [
        { id: 'hw1', date: dayOffset(-93), counter: null, entries: [{ item_id: 'wi1', note: '拆洗过滤器' }] },
        { id: 'hw2', date: dayOffset(-6), counter: null, entries: [{ item_id: 'wi2', note: '里外擦拭一遍' }] }
      ]
    },
    {
      slug: 'restroom', name: '三楼洗手间', type: 'area',
      need_counter: false, counter_unit: '', counter_label: '', counter: null,
      items: [
        { id: 'ri1', name: '刷洗马桶', interval_days: 7, interval_counter: null, last_date: dayOffset(-4), last_counter: null, note: '' },
        { id: 'ri2', name: '擦洗玻璃与镜面', interval_days: 30, interval_counter: null, last_date: dayOffset(-27), last_counter: null, note: '' }
      ],
      history: [
        { id: 'hb1', date: dayOffset(-4), counter: null, entries: [{ item_id: 'ri1', note: '深度刷洗' }] },
        { id: 'hb2', date: dayOffset(-27), counter: null, entries: [{ item_id: 'ri2', note: '擦洗玻璃镜面' }] }
      ]
    }
  ];

  // ---------- 从项目推导 summaries / due_items（与后端口径一致） ----------
  function itemState(item, project) {
    var lastDate = item.last_date, intervalDays = item.interval_days, remainingDays = null;
    if (lastDate && intervalDays) remainingDays = Number(intervalDays) - dayDiff(TODAY, lastDate);
    var counter = project.counter, lastCounter = item.last_counter, intervalCounter = item.interval_counter, remainingCounter = null;
    if (project.need_counter && counter != null && lastCounter != null && intervalCounter)
      remainingCounter = Number(lastCounter) + Number(intervalCounter) - Number(counter);
    var status;
    if (!lastDate && lastCounter == null) status = 'unset';
    else if ((remainingDays != null && remainingDays <= 0) || (remainingCounter != null && remainingCounter <= 0)) status = 'due';
    else if (remainingDays != null && remainingDays <= SOON_DAYS) status = 'soon';
    else status = 'ok';
    var dueDate = null;
    if (lastDate && intervalDays) {
      var d = parse(lastDate); d.setDate(d.getDate() + Number(intervalDays)); dueDate = iso(d);
    }
    return {
      id: item.id, name: item.name, status: status,
      remaining_days: remainingDays, remaining_counter: remainingCounter,
      due_date: dueDate, last_date: lastDate, last_counter: lastCounter,
      interval_days: intervalDays, interval_counter: intervalCounter, note: item.note || ''
    };
  }
  function projectSummary(p) {
    var states = (p.items || []).map(function (i) { return itemState(i, p); });
    var due = states.filter(function (s) { return s.status === 'due'; });
    var soon = states.filter(function (s) { return s.status === 'soon'; });
    var unset = states.filter(function (s) { return s.status === 'unset'; });
    var ranked = due.concat(soon), next = ranked[0] || unset[0] || null;
    return {
      slug: p.slug, name: p.name,
      due_count: due.length, soon_count: soon.length, unset_count: unset.length,
      due_names: due.map(function (s) { return s.name; }),
      soon_names: soon.map(function (s) { return s.name; }),
      next: next, items: states
    };
  }
  function recompute(S) {
    var m = S.maintenance;
    m.summaries = (m.projects || []).map(projectSummary);
    var dueItems = [];
    (m.projects || []).forEach(function (p) {
      (p.items || []).map(function (i) { return itemState(i, p); }).forEach(function (s) {
        if (s.status === 'due' || s.status === 'soon') {
          dueItems.push({
            slug: p.slug, project: p.name, item_id: s.id, name: s.name,
            status: s.status, due_date: s.due_date || TODAY, remaining_days: s.remaining_days
          });
        }
      });
    });
    m.due_total = m.summaries.reduce(function (a, s) { return a + s.due_count; }, 0);
    m.soon_total = m.summaries.reduce(function (a, s) { return a + s.soon_count; }, 0);
    m.due_items = dueItems;
    S.tasks_today = (S.workday.todos || []).filter(function (t) { return t.date === TODAY && !t.done; }).length
      + dueItems.filter(function (d) { return d.status === 'due'; }).length;
  }

  // ---------- 完整快照 ----------
  var SNAP = {
    today: TODAY,
    workday: {
      today_work: true, today_label: '', tomorrow_work: true,
      stats: { total: 21, left: 9 },
      next_holiday: null,
      next_event: { name: '女儿生日', date: dayOffset(2), days: 2 },
      custom_work: [dayOffset(5)],
      custom_rest: [dayOffset(3)],
      todos: [
        { id: 't1', date: dayOffset(-3), text: '提交 10 月电费波动分析', done: false },
        { id: 't2', date: dayOffset(0), text: '核对本月箱量台账', done: false },
        { id: 't3', date: dayOffset(0), text: '回复审计补充材料', done: true },
        { id: 't4', date: dayOffset(2), text: '季度预算评审会', done: false },
        { id: 't5', date: dayOffset(6), text: '预约设备年检', done: false },
        { id: 't6', date: dayOffset(14), text: '月度存货盘点', done: false }
      ],
      anniversaries: [
        { id: 'a1', name: '结婚纪念日', date: dayOffset(4), repeat: 'year' },
        { id: 'a2', name: '女儿生日', date: dayOffset(2), repeat: 'year' },
        { id: 'a3', name: '发工资', date: dayOffset(9), repeat: 'month' },
        { id: 'a4', name: '团队例会', date: dayOffset(0), repeat: 'week' }
      ],
      holiday_source: 'network',
      year_override: {}
    },
    maintenance: { projects: clone(PROJECTS), summaries: [], due_total: 0, soon_total: 0, due_items: [] },
    tasks_today: 0,
    holidays: {
      off: [dayOffset(10)],
      makeup: [dayOffset(12)],
      names: {}
    }
  };
  SNAP.holidays.names[dayOffset(10)] = '示例假期';
  recompute(SNAP);

  // ---------- 写操作：改内存数据后广播刷新 ----------
  function findProject(slug) {
    return (SNAP.maintenance.projects || []).filter(function (p) { return p.slug === slug; })[0] || null;
  }
  function findItem(p, id) {
    return p ? (p.items || []).filter(function (i) { return i.id === id; })[0] || null : null;
  }
  function splitDates(s) { return String(s == null ? '' : s).split(',').filter(function (x) { return x; }); }
  function scopeOf(service) {
    if (service.indexOf('todo') >= 0 || service.indexOf('anniv') >= 0 || service === 'set_day' || service === 'set_custom' || service === 'clear_custom') return 'workday';
    return 'maintenance';
  }
  function applyWrite(service, data) {
    data = data || {};
    var result = null;
    var w = SNAP.workday, m = SNAP.maintenance, p, it;
    switch (service) {
      case 'set_todos': w.todos = clone(data.todos || []); break;
      case 'set_anniversaries': w.anniversaries = clone(data.anniversaries || []); w.next_event = null; break;
      case 'set_day':
        var d = data.date, mode = data.mode;
        w.custom_work = w.custom_work.filter(function (x) { return x !== d; });
        w.custom_rest = w.custom_rest.filter(function (x) { return x !== d; });
        if (mode === 'work') w.custom_work.push(d);
        else if (mode === 'rest') w.custom_rest.push(d);
        break;
      case 'set_custom':
        w.custom_work = splitDates(data.work); w.custom_rest = splitDates(data.rest); break;
      case 'clear_custom': w.custom_work = []; w.custom_rest = []; break;
      case 'add_project':
        m.projects.push({
          slug: data.slug || ('p_' + Date.now().toString(36)),
          name: data.name || '新项目', type: data.type || 'custom',
          need_counter: !!data.need_counter,
          counter_unit: data.counter_unit || '', counter_label: data.counter_label || '',
          counter: (data.counter === '' || data.counter == null) ? null : Number(data.counter),
          items: [], history: []
        });
        break;
      case 'update_project':
        p = findProject(data.slug);
        if (p) {
          if (data.name != null) p.name = data.name;
          if (data.need_counter != null) p.need_counter = !!data.need_counter;
          if (data.counter_unit != null) p.counter_unit = data.counter_unit;
          if (data.counter_label != null) p.counter_label = data.counter_label;
        }
        break;
      case 'delete_project':
        m.projects = m.projects.filter(function (x) { return x.slug !== data.slug; }); break;
      case 'set_counter':
        p = findProject(data.slug); if (p) p.counter = (data.value === '' || data.value == null) ? null : Number(data.value); break;
      case 'add_item':
        p = findProject(data.slug);
        if (p) p.items.push({
          id: 'i' + Date.now().toString(36), name: data.name || '新小项',
          interval_days: (data.interval_days === '' || data.interval_days == null) ? null : Number(data.interval_days),
          interval_counter: (data.interval_counter === '' || data.interval_counter == null) ? null : Number(data.interval_counter),
          last_date: null, last_counter: null, note: data.note || ''
        });
        break;
      case 'update_item':
        p = findProject(data.slug); it = findItem(p, data.item_id);
        if (it) {
          if (data.name != null) it.name = data.name;
          if (data.interval_days !== undefined) it.interval_days = (data.interval_days === '' || data.interval_days == null) ? null : Number(data.interval_days);
          if (data.interval_counter !== undefined) it.interval_counter = (data.interval_counter === '' || data.interval_counter == null) ? null : Number(data.interval_counter);
          if (data.note != null) it.note = data.note;
        }
        break;
      case 'delete_item':
        p = findProject(data.slug); if (p) p.items = p.items.filter(function (i) { return i.id !== data.item_id; }); break;
      case 'set_baseline':
        p = findProject(data.slug); it = findItem(p, data.item_id);
        if (it) { it.last_date = data.date || TODAY; it.last_counter = p.counter; }
        break;
      case 'log_service':
        p = findProject(data.slug);
        if (p) {
          var ids = data.item_ids || [];
          var value = (data.counter === '' || data.counter == null) ? null : Number(data.counter);
          var rec = {
            id: 'r' + Date.now().toString(36), date: data.date || TODAY, counter: value,
            entries: ids.map(function (id) { return { item_id: id, note: (data.item_notes || {})[id] || '' }; })
          };
          p.history.push(rec);
          if (value != null) p.counter = value;
          ids.forEach(function (id) {
            var t = findItem(p, id);
            if (t) { t.last_date = rec.date; if (value != null) t.last_counter = value; }
          });
        }
        break;
      case 'update_record':
        p = findProject(data.slug);
        if (p) {
          var ur = (p.history || []).filter(function (r) { return r.id === data.record_id; })[0];
          if (ur) {
            if (data.date) ur.date = data.date;
            if (data.counter !== '' && data.counter != null) ur.counter = Number(data.counter);
            (ur.entries || []).forEach(function (e) { if (e.item_id === data.item_id && data.note != null) e.note = data.note; });
            (p.items || []).forEach(function (itm) {
              var recs = p.history.filter(function (r) {
                return (r.entries || []).some(function (e) { return e.item_id === itm.id; });
              }).sort(function (a, b) { return b.date.localeCompare(a.date); });
              itm.last_date = recs.length ? recs[0].date : null;
              itm.last_counter = recs.length ? recs[0].counter : null;
            });
          }
        }
        break;
      case 'import_projects': {
        var list = [];
        try { list = JSON.parse(data.json || data.projects || '[]'); } catch (e) {}
        if (!Array.isArray(list)) list = [];
        var imp = { added: [], errors: [] };
        list.forEach(function (pr) {
          pr = pr || {};
          var pname = String(pr.name || '').trim();
          if (!pname) { imp.errors.push('项目缺少名称'); return; }
          var pslug = pr.slug || slugifyDemo(pname);
          if (m.projects.some(function (x) { return x.slug === pslug; })) { imp.errors.push('项目标识已存在：' + pslug); return; }
          m.projects.push({
            slug: pslug, name: pname, type: pr.type || 'custom',
            need_counter: !!pr.need_counter,
            counter_unit: pr.counter_unit || '', counter_label: pr.counter_label || '',
            counter: (pr.counter === '' || pr.counter == null) ? null : Number(pr.counter),
            items: (pr.items || []).map(function (it, idx) {
              it = it || {};
              return { id: 'i' + idx + Date.now().toString(36), name: it.name || ('小项' + (idx + 1)),
                interval_days: (it.interval_days === '' || it.interval_days == null) ? null : Number(it.interval_days),
                interval_counter: (it.interval_counter === '' || it.interval_counter == null) ? null : Number(it.interval_counter),
                last_date: it.last_date || null,
                last_counter: (it.last_counter === '' || it.last_counter == null) ? null : Number(it.last_counter),
                note: it.note || '' };
            }),
            history: []
          });
          imp.added.push({ slug: pslug, name: pname, items: (pr.items || []).length });
        });
        result = imp;
        break;
      }
      case 'delete_record':
        p = findProject(data.slug);
        if (p) {
          var dr = (p.history || []).filter(function (r) { return r.id === data.record_id; })[0];
          if (dr) {
            dr.entries = (dr.entries || []).filter(function (e) { return e.item_id !== data.item_id; });
            if (!dr.entries.length) p.history = p.history.filter(function (r) { return r.id !== dr.id; });
          }
        }
        break;
      default: break;
    }
    recompute(SNAP);
    return result;
  }

  var ITEM_PRESETS = {
    vehicle: [
      { name: '机油 + 机油滤芯', interval_days: 180, interval_counter: 10000 },
      { name: '空调滤芯', interval_days: 365, interval_counter: 20000 },
      { name: '空气滤芯', interval_days: 365, interval_counter: 20000 },
      { name: '轮胎换位', interval_days: 365, interval_counter: 20000 },
      { name: '刹车油', interval_days: 730, interval_counter: null },
      { name: '冷却液', interval_days: 730, interval_counter: null }
    ],
    appliance: [
      { name: '清洗筒内 / 过滤器', interval_days: 90, interval_counter: null },
      { name: '清理排水口 / 滤网', interval_days: 90, interval_counter: null },
      { name: '检查密封圈与水管', interval_days: 180, interval_counter: null },
      { name: '机身内外擦拭', interval_days: 30, interval_counter: null }
    ],
    furniture: [
      { name: '清洗坐垫与靠背', interval_days: 180, interval_counter: null },
      { name: '检查气压杆升降', interval_days: 365, interval_counter: null },
      { name: '紧固螺丝与检查脚轮', interval_days: 365, interval_counter: null },
      { name: '扶手与头枕除尘', interval_days: 30, interval_counter: null }
    ],
    area: [
      { name: '刷洗马桶', interval_days: 7, interval_counter: null },
      { name: '擦洗玻璃与镜面', interval_days: 30, interval_counter: null },
      { name: '清理地漏与下水口', interval_days: 30, interval_counter: null },
      { name: '除霉与通风', interval_days: 30, interval_counter: null }
    ],
    custom: [{ name: '例行检查', interval_days: 180, interval_counter: null }]
  };

  function slugifyDemo(name) {
    var clean = String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return clean || 'p_' + Date.now().toString(36);
  }

  // ---------- 拦截 MW ----------
  MW.isHA = function () { return true; };
  MW.snapshot = function () { return Promise.resolve(clone(SNAP)); };
  MW.call = function (service, data) {
    var out = applyWrite(service, data || {});
    MW.broadcast(scopeOf(service));
    return Promise.resolve({ service_response: out || { ok: true } });
  };
  MW.start = function () {
    // 本地预览：不连 WebSocket、不弹"预览模式"横幅；数据由 snapshot 立即提供
    setTimeout(function () { var el = MW.$('msg'); if (el) el.hidden = true; }, 0);
  };

  window.__DEMO_DATA__ = SNAP;
})();
