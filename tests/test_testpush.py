"""test_push 行为测试：用 mock HTTP session 验证返回值与 URL 拼装。"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'custom_components' / 'workday_maintenance'


class FakeResp:
    def __init__(self, status, text=''):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, resp=None, err=None):
        self.resp, self.err, self.calls = resp, err, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers, timeout))
        if self.err:
            raise self.err
        return self.resp


class TestTestPush(unittest.TestCase):
    def setUp(self):
        # 干净的模块上下文，mock HA 依赖
        for k in [m for m in sys.modules if m.startswith('workday_maintenance')]:
            sys.modules.pop(k, None)

        def mkmod(name, **kw):
            m = types.ModuleType(name)
            for k2, v in kw.items():
                setattr(m, k2, v)
            sys.modules[name] = m
            return m

        mkmod('homeassistant')
        mkmod('homeassistant.core', HomeAssistant=type('H', (), {}))
        mkmod('homeassistant.exceptions')
        mkmod('homeassistant.util')
        mkmod('homeassistant.util.dt', now=lambda: None)
        mkmod('homeassistant.helpers')
        self.session_holder = {}
        mkmod('homeassistant.helpers.aiohttp_client',
              async_get_clientsession=lambda hass: self.session_holder.get('s'))

        pkg = types.ModuleType('workday_maintenance')
        pkg.__path__ = [str(PKG)]
        sys.modules['workday_maintenance'] = pkg

        def load(name):
            spec = importlib.util.spec_from_file_location('workday_maintenance.' + name, PKG / (name + '.py'))
            m = importlib.util.module_from_spec(spec)
            sys.modules['workday_maintenance.' + name] = m
            spec.loader.exec_module(m)
            return m

        const = load('const')
        wd = load('workday')
        mnt = load('maintenance')
        pr = load('push_rule')
        self.notify = load('notify')

        class Cfg:
            async def async_load(self):
                return {}

        class Coord:
            settings_store = Cfg()

        self.mgr = self.notify.NotifyManager(type('H', (), {})(), Coord())

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_missing_config(self):
        r = self._run(self.mgr.test_push('', ''))
        self.assertFalse(r['ok'])
        self.assertIn('地址和', r['error'])

    def test_success_builds_correct_request(self):
        sess = FakeSession(FakeResp(200, 'ok'))
        self.session_holder['s'] = sess
        r = self._run(self.mgr.test_push('http://192.168.2.2:2818/', 'TOK'))
        self.assertTrue(r['ok'])
        url, payload, headers, timeout = sess.calls[0]
        self.assertEqual(url, 'http://192.168.2.2:2818/api/push')  # 去掉尾斜杠 + 拼路径
        self.assertEqual(headers['Authorization'], 'Bearer TOK')
        self.assertEqual(payload['title'], 'workday_maintenance 测试')
        self.assertIn('HTTP 200', r['detail'])

    def test_http_error_reported(self):
        sess = FakeSession(FakeResp(400, 'bad token'))
        self.session_holder['s'] = sess
        r = self._run(self.mgr.test_push('http://x', 'TOK'))
        self.assertFalse(r['ok'])
        self.assertIn('HTTP 400', r['error'])
        self.assertIn('bad token', r['error'])

    def test_connection_error_reported(self):
        sess = FakeSession(err=OSError('refused'))
        self.session_holder['s'] = sess
        r = self._run(self.mgr.test_push('http://x', 'TOK'))
        self.assertFalse(r['ok'])
        self.assertIn('连接失败', r['error'])
        self.assertIn('OSError', r['error'])


if __name__ == '__main__':
    unittest.main()
