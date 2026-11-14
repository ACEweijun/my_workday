window.MW = (function () {
  'use strict';
  var DOMAIN = 'my_workday';
  var EVENT = 'my_workday_updated';
  var token = null, tokenExp = 0, listeners = [], sock = null, closed = false;

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
  function resolveToken() {
    var now = Math.floor(Date.now() / 1000);
    if (token && tokenExp > now + 30) return Promise.resolve(token);
    token = null;
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
  function api(path, opt, retried) {
    return resolveToken().then(function (tk) {
      if (!tk) throw new Error('未获取到 HA 登录态');
      opt = opt || {};
      opt.headers = Object.assign({}, opt.headers || {}, {
        Authorization: 'Bearer ' + tk, 'Content-Type': 'application/json'
      });
      return fetch(location.origin + path, opt);
    }).then(function (r) {
      if (r.status === 401 && !retried) { token = null; tokenExp = 0; return api(path, opt, true); }
      if (!r.ok) return r.text().then(function (t) { throw new Error('请求失败 ' + r.status + ' ' + t.slice(0, 120)); });
      return r.text().then(function (t) { return t ? JSON.parse(t) : null; });
    });
  }
  function unwrap(x) {
    return (x && typeof x === 'object' && !Array.isArray(x) && 'response' in x) ? x.response : x;
  }
  function call(service, data, wantResponse) {
    var path = '/api/services/' + DOMAIN + '/' + service + (wantResponse ? '?return_response=true' : '');
    return api(path, { method: 'POST', body: JSON.stringify(data || {}) })
      .then(wantResponse ? unwrap : function (x) { return x; });
  }
  function snapshot() { return call('get_snapshot', {}, true); }
  function onUpdate(fn) { if (typeof fn === 'function') listeners.push(fn); }
  function broadcast(scope) {
    listeners.forEach(function (fn) { try { fn(scope); } catch (e) { console.warn(e); } });
  }
  function connect() {
    if (!isHA()) return;
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
        toast('');
      } else if (msg.type === 'event') {
        broadcast((msg.event && msg.event.data && msg.event.data.scope) || 'all');
      } else if (msg.type === 'auth_invalid') {
        toast('HA 登录态失效，请重新登录', true);
      }
    };
    sock.onclose = function () {
      if (closed) return;
      setTimeout(function () { connect(); }, 5000);
    };
  }
  function toast(text, isErr) {
    var el = $('msg');
    if (!el) return;
    el.textContent = text || '';
    el.hidden = !text;
    el.className = 'msg' + (isErr ? ' err' : '');
  }
  function go(page) { location.href = '/my_workday/' + page; }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function dateOf(iso) { return new Date(iso + 'T00:00:00'); }
  function dayDiff(a, b) {
    return Math.round((dateOf(a) - dateOf(b)) / 86400000);
  }
  function start() {
    if (!isHA()) toast('预览模式 · 部署到 Home Assistant 后从侧边栏打开', true);
    connect();
  }
  return {
    $: $, esc: esc, call: call, snapshot: snapshot, onUpdate: onUpdate,
    toast: toast, go: go, today: today, dateOf: dateOf, dayDiff: dayDiff,
    start: start, broadcast: broadcast, isHA: isHA
  };
})();
