window.MW = (function () {
  'use strict';
  var DOMAIN = 'workday_maintenance';
  var EVENT = 'workday_maintenance_updated';
  var token = null, tokenExp = 0, listeners = [], sock = null, closed = false, ready = false, pending = {}, seq = 0;
  var connSubscribed = false, connUnsub = null;

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function isHA() {
    return location.protocol === 'http:' || location.protocol === 'https:';
  }
  function readTokens() {
    try { var raw = localStorage.getItem('hassTokens'); return raw ? JSON.parse(raw) : null; }
    catch (e) { return null; }
  }
  // 从候选对象里取出"真正的" conn（带 callWS 的那个）。
  // 新版 HA 前端的 window.hassConnection 是 {auth, conn} 形态；旧版是裸 conn；
  // 也可能是 Promise。直接当 conn 用会拿到没有 callWS 的对象，导致静默退化到 REST 后 401。
  function extractConn(v) {
    if (!v) return null;
    if (typeof v.callWS === 'function') return v;          // 已经是 conn
    if (v.conn && typeof v.conn.callWS === 'function') return v.conn;  // {auth, conn}
    return null;
  }
  function parentHassConn() {
    var cands = [];
    try { if (window.hassConnection) cands.push(window.hassConnection); } catch (e) {}
    try {
      if (window.parent && window.parent !== window && window.parent.hassConnection) {
        cands.push(window.parent.hassConnection);
      }
    } catch (e) {}
    // 依次尝试：可能是 Promise，需 await 后再解包
    if (!cands.length) return null;   // 没有候选时返回 null（保持"无父连接"语义）
    var tries = cands.map(function (c) {
      return Promise.resolve(c).then(extractConn).catch(function () { return null; });
    });
    return Promise.all(tries).then(function (list) {
      for (var i = 0; i < list.length; i++) if (list[i]) return list[i];
      return null;
    });
  }
  function legacyToken() {
    var now = Math.floor(Date.now() / 1000);
    var t = readTokens();
    if (!t || !t.access_token) return Promise.resolve(null);
    if (!t.expires || Number(t.expires) > now + 60) {
      token = t.access_token;
      tokenExp = Number(t.expires) || now + 1800;
      return Promise.resolve(token);
    }
    if (!t.refresh_token || !isHA()) return Promise.resolve(null);
    var body = new URLSearchParams({
      grant_type: 'refresh_token', refresh_token: t.refresh_token,
      client_id: t.clientId || ''
    });
    return fetch(location.origin + '/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString()
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.access_token) return null;
        token = j.access_token;
        tokenExp = now + (Number(j.expires_in) || 1800);
        return token;
      }).catch(function () { return null; });
  }
  function resolveToken() {
    var now = Math.floor(Date.now() / 1000);
    if (token && tokenExp > now + 30) return Promise.resolve(token);
    token = null;
    var connP = parentHassConn();
    if (connP) {
      return connP.then(function (c) {
        // conn 上取 token：hass-websocket 的 conn 把认证放在 options.auth / auth
        var tk = (c && c.options && c.options.auth && c.options.auth.accessToken) ||
                 (c && c.auth && c.auth.accessToken) ||
                 (c && c.options && c.options.authToken);
        if (!tk) return legacyToken();
        token = tk;
        tokenExp = now + 60;
        return token;
      }).catch(function () { return legacyToken(); });
    }
    return legacyToken();
  }
  function callViaConn(c, service, data, wantResponse) {
    var msg = { type: 'call_service', domain: DOMAIN, service: service,
      service_data: data || {}, return_response: !!wantResponse };
    return c.callWS(msg).then(function (res) { return wantResponse ? unwrap(res) : res; });
  }
  function api(path, opt, retried) {
    return resolveToken().then(function (tk) {
      if (!tk) throw new Error('未获取到 HA 登录态');
      opt = opt || {};
      opt.headers = Object.assign({}, opt.headers || {}, {
        Authorization: 'Bearer ' + tk, 'Content-Type': 'application/json'
      });
      return fetch(location.origin + path, opt);
    }).then(function (r) {
      if (r.status === 401 && (retried || 0) < 3) {
        // 令牌可能刚好过期：清掉缓存重新取，并退避等待 HA 前端刷新令牌
        token = null; tokenExp = 0;
        var attempt = (retried || 0) + 1;
        return new Promise(function (r2) { setTimeout(r2, 300 * attempt); })
          .then(function () { return api(path, opt, attempt); });
      }
      if (r.status === 401) {
        throw new Error('登录态已失效，请刷新页面重新登录 Home Assistant');
      }
      if (!r.ok) return r.text().then(function (t) { throw new Error('请求失败 ' + r.status + ' ' + t.slice(0, 200)); });
      return r.text().then(function (t) { return t ? JSON.parse(t) : null; });
    });
  }
  function unwrap(x) {
    if (x && typeof x === 'object' && !Array.isArray(x)) {
      if (x.service_response !== undefined) return x.service_response;
      if (x.response !== undefined) return x.response;
    }
    return x;
  }
  function call(service, data, wantResponse) {
    var connP = parentHassConn();
    if (connP) {
      return connP.then(function (c) {
        if (!c) throw new Error('父页面连接不可用');
        return callViaConn(c, service, data, wantResponse);
      })
        .catch(function () {
          var path = '/api/services/' + DOMAIN + '/' + service + (wantResponse ? '?return_response=true' : '');
          return api(path, { method: 'POST', body: JSON.stringify(data || {}) })
            .then(wantResponse ? unwrap : function (x) { return x; });
        });
    }
    var path = '/api/services/' + DOMAIN + '/' + service + (wantResponse ? '?return_response=true' : '');
    return api(path, { method: 'POST', body: JSON.stringify(data || {}) })
      .then(wantResponse ? unwrap : function (x) { return x; });
  }
  function snapshotViaWS() {
    return new Promise(function (resolve, reject) {
      if (!sock || sock.readyState !== 1) { reject(new Error('WS 未连接')); return; }
      var id = 100 + (++seq);
      var timer = setTimeout(function () {
        delete pending[id];
        reject(new Error('WS 快照超时'));
      }, 3000);
      pending[id] = function (ok, result) {
        clearTimeout(timer);
        if (ok && result && result.workday) resolve(result);
        else reject(new Error('WS 快照无数据'));
      };
      try { sock.send(JSON.stringify({ type: 'workday_maintenance/snapshot', id: id })); }
      catch (e) { delete pending[id]; clearTimeout(timer); reject(e); }
    });
  }
  function snapshot() {
    var connP = parentHassConn();
    if (connP) {
      return connP.then(function (c) {
        if (!c) throw new Error('父页面连接不可用');
        return c.callWS({ type: DOMAIN + '/snapshot' });
      }).catch(function () {
        return snapshotViaWS().catch(function () { return call('get_snapshot', {}, true); });
      });
    }
    return snapshotViaWS().catch(function () { return call('get_snapshot', {}, true); });
  }
  function onUpdate(fn) { if (typeof fn === 'function') listeners.push(fn); }
  function broadcast(scope) {
    listeners.forEach(function (fn) { try { fn(scope); } catch (e) { console.warn(e); } });
  }
  function connect() {
    if (!isHA() || closed) return;
    var connP = parentHassConn();
    if (connP) {
      if (connSubscribed) return;
      connP.then(function (c) {
        if (closed || connSubscribed || !c) return;
        connSubscribed = true;
        try {
          c.subscribeEvents(function (ev) {
            broadcast((ev && ev.data && ev.data.scope) || 'all');
          }, EVENT).then(function (unsub) { connUnsub = unsub; });
        } catch (e) {}
      }).catch(function () {});
      return;
    }
    if (sock && (sock.readyState === 0 || sock.readyState === 1)) return;
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try { sock = new WebSocket(proto + '//' + location.host + '/api/websocket'); }
    catch (e) { return; }
    sock.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'auth_required') {
        resolveToken().then(function (tk) {
          if (tk && sock && sock.readyState === 1) {
            sock.send(JSON.stringify({ type: 'auth', access_token: tk }));
          }
        });
      } else if (msg.type === 'auth_ok') {
        sock.send(JSON.stringify({ type: 'subscribe_events', id: 1, event_type: EVENT }));
      } else if (msg.type === 'result' && pending[msg.id]) {
        var cb = pending[msg.id]; delete pending[msg.id];
        cb(msg.success, msg.result);
      } else if (msg.type === 'event') {
        broadcast((msg.event && msg.event.data && msg.event.data.scope) || 'all');
      } else if (msg.type === 'auth_invalid') {
        toast('HA 登录态失效，请重新登录', true);
      }
    };
    sock.onclose = function () {
      sock = null;
      Object.keys(pending).forEach(function (k) {
        pending[k](false, null); delete pending[k];
      });
      if (closed) return;
      setTimeout(function () { connect(); }, 5000);
    };
  }
  var toastTimer = null;
  function toast(text, isErr) {
    var el = $('msg');
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
    if (!el) return;
    el.textContent = text || '';
    el.hidden = !text;
    el.className = 'msg' + (isErr ? ' err' : '');
    // 自动消失：普通提示 2.5 秒，错误 4 秒；空文本立即隐藏无需定时器。
    if (text) {
      toastTimer = setTimeout(function () {
        el.textContent = ''; el.hidden = true; toastTimer = null;
      }, isErr ? 4000 : 2500);
    }
  }
  function setReady(value) {
    ready = !!value;
    if (ready) toast('');
  }
  function guard(e) {
    if (ready) return;
    e.preventDefault();
    e.stopPropagation();
    toast('数据还在加载，请稍候', true);
  }
  function installGuards() {
    document.addEventListener('click', guard, true);
    document.addEventListener('change', guard, true);
    document.addEventListener('keydown', guard, true);
    window.addEventListener('error', function (e) {
      toast('页面错误：' + (e.message || '未知错误'), true);
    });
    window.addEventListener('beforeunload', function () {
      closed = true;
      if (sock) { try { sock.close(); } catch (err) { } }
      if (connUnsub) { try { connUnsub(); } catch (err) { } }
    });
  }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function dateOf(iso) { return new Date(iso + 'T00:00:00'); }
  function dayDiff(a, b) {
    return Math.round((dateOf(a) - dateOf(b)) / 86400000);
  }
  function start() {
    installGuards();
    if (!isHA()) { toast('预览模式 · 部署到 Home Assistant 后从侧边栏打开', true); return; }
    toast('正在加载数据…');
    connect();
  }
  // ---- 页面公共助手（workday / maintenance 共用，避免重复实现分叉）----

  // 日期输入框：点整行任意位置都能弹出系统日历（原生日历图标铺满 + showPicker 双保险）。
  function bindDateFields() {
    var list = document.querySelectorAll('input[type=date]');
    Array.prototype.forEach.call(list, function (el) {
      var row = el.parentNode, last = 0;
      if (row && row.classList) {
        row.classList.add('date-field');
        var lab = row.querySelector && row.querySelector('label');
        if (lab && el.id && !lab.htmlFor) lab.htmlFor = el.id;
      }
      if (row) row.addEventListener('click', function (e) {
        if (el.disabled || el.readOnly) return;
        var now = Date.now();
        if (now - last < 250) return;
        last = now;
        try {
          if (typeof el.showPicker === 'function') el.showPicker();
          else el.focus();
        } catch (err) { el.focus(); }
      });
    });
  }

  // 通用加载骨架：两页 load() 的 busy/snapshot/重试逻辑完全相同，业务差异用回调注入。
  // opts: { validate(d)->bool, onData(d), render() }
  function createLoader(opts) {
    var busy = false, retries = 0;
    function retryLoad() {
      if (retries >= 3) return;
      retries++;
      setTimeout(load, 2000);
    }
    function load() {
      // 走 MW 对象动态取方法，保证 demo-data.js 等覆盖层能生效（本地预览取虚拟数据）。
      var api = window.MW;
      if (busy || !api.isHA()) return Promise.resolve();
      busy = true;
      return api.snapshot().then(function (d) {
        if (!d || !opts.validate(d)) {
          throw new Error('快照格式异常：' + JSON.stringify(d).slice(0, 160));
        }
        retries = 0;
        opts.onData(d);
        api.setReady(true);
        opts.render();
      }).catch(function (e) {
        api.setReady(false);
        api.toast('加载失败：' + e.message + '，自动重试中', true);
        retryLoad();
      }).finally(function () { busy = false; });
    }
    return { load: load, retryLoad: retryLoad };
  }

  // 二次确认删除：同一 key 连点两次才返回 true；reset() 供表单重置时清空。
  function createArmDel() {
    var pending = null;
    return {
      arm: function (key) {
        if (pending !== key) { pending = key; return false; }
        pending = null; return true;
      },
      peek: function (key) { return pending === key; },
      reset: function () { pending = null; }
    };
  }

  return {
    $: $, esc: esc, call: call, snapshot: snapshot, onUpdate: onUpdate,
    toast: toast, setReady: setReady, today: today, dateOf: dateOf,
    dayDiff: dayDiff, start: start, broadcast: broadcast, isHA: isHA,
    bindDateFields: bindDateFields, createLoader: createLoader, createArmDel: createArmDel
  };
})();
