"""核心逻辑单测：用桩模块模拟 HA，不需要装 Home Assistant。"""
from __future__ import annotations

import datetime
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if (ROOT / 'core.py').exists():
    sys.path.insert(0, str(ROOT.parent))          # 本地工作目录布局
else:
    sys.path.insert(0, str(ROOT / 'custom_components'))   # HACS 仓库布局


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


try:
    import aiohttp  # noqa: F401
except ImportError:
    _mod('aiohttp', ClientError=type('ClientError', (Exception,), {}),
         ClientTimeout=lambda **kw: None)

TZ = datetime.timezone(datetime.timedelta(hours=8))


class _DUC:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None


class _UpdateFailed(Exception):
    pass


class _Store:
    def __init__(self, *a, **k):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, d):
        self.data = d


class _SupportsResponse:
    OPTIONAL = 'optional'


class _Platform:
    SENSOR = 'sensor'
    BINARY_SENSOR = 'binary_sensor'
    CALENDAR = 'calendar'


class _HomeAssistantError(Exception):
    pass


_mod('homeassistant')
_mod('homeassistant.config_entries', ConfigEntry=type('ConfigEntry', (), {}))
_mod('homeassistant.const', Platform=_Platform)
_mod('homeassistant.core', HomeAssistant=object, ServiceCall=object,
     SupportsResponse=_SupportsResponse)
_mod('homeassistant.exceptions', HomeAssistantError=_HomeAssistantError)
_mod('homeassistant.helpers')
_mod('homeassistant.helpers.aiohttp_client', async_get_clientsession=lambda hass: None)
_mod('homeassistant.helpers.storage', Store=_Store)
_mod('homeassistant.helpers.update_coordinator', DataUpdateCoordinator=_DUC,
     UpdateFailed=_UpdateFailed, CoordinatorEntity=object)
_mod('homeassistant.helpers.event', async_track_time_change=lambda *a, **k: (lambda: None))
_mod('homeassistant.helpers.entity_platform', AddEntitiesCallback=object)
_mod('homeassistant.helpers.device_registry', DeviceInfo=dict)
_mod('homeassistant.helpers.selector', TextSelector=object, TextSelectorConfig=dict,
     TimeSelector=object)
_util = _mod('homeassistant.util')
_dt = _mod('homeassistant.util.dt',
           now=lambda: datetime.datetime(2026, 11, 12, 9, 0, tzinfo=TZ),
           utcnow=lambda: datetime.datetime(2026, 11, 12, 1, 0, tzinfo=datetime.timezone.utc))
_util.dt = _dt

import my_workday as pkg                    # noqa: E402
from my_workday import core                 # noqa: E402
from my_workday import coordinator as coord  # noqa: E402


class _Entry:
    entry_id = 'test'
    options = {}


class TestDateValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(pkg._to_iso('2026-11-28'), '2026-11-28')
        self.assertEqual(pkg._to_iso(datetime.date(2026, 11, 28)), '2026-11-28')
        self.assertEqual(
            pkg._to_iso(datetime.datetime(2026, 11, 28, 15, 30)), '2026-11-28'
        )

    def test_invalid(self):
        for bad in ('2026-13-45', '2026-02-30', 'abc', ''):
            with self.subTest(bad=bad):
                with self.assertRaises(_HomeAssistantError):
                    pkg._to_iso(bad)


class TestCoordinator(unittest.TestCase):
    def make(self):
        return coord.CnWorkdayCoordinator(object(), _Entry())

    def test_next_year_retry_initial_state(self):
        c = self.make()
        self.assertIsNone(c._next_try)
        self.assertTrue(c._needs_refresh())

    def test_year_specific_sets(self):
        c = self.make()
        c._loaded_year = 2026
        c._loaded_from = 'network'
        c._off = {'2026-01-01'}
        c._makeup = {'2026-01-04'}
        c._next_year = 2027
        c._off_next = {'2027-01-01'}
        c._makeup_next = {'2027-01-04'}
        self.assertFalse(c.is_workday(datetime.date(2026, 1, 1)))
        self.assertFalse(c.is_workday(datetime.date(2027, 1, 1)))
        self.assertTrue(c.is_workday(datetime.date(2027, 1, 4)))
        self.assertTrue(c.is_makeup(datetime.date(2027, 1, 4)))

    def test_tomorrow_across_year_boundary(self):
        c = self.make()
        c._loaded_year = 2026
        c._loaded_from = 'network'
        c._next_year = 2027
        c._off_next = {'2027-01-01'}
        snap = c.snapshot(datetime.date(2026, 12, 31))
        self.assertFalse(snap['tomorrow_work'])

    def test_next_year_prefetch_on_startup(self):
        async def run():
            async def fake_fetch(year):
                return ({'2027-01-01'}, {'2027-02-06'}, {'2027-01-01': '元旦'})

            c = self.make()
            c._async_fetch = fake_fetch
            await c._async_ensure_next_year(2027)
            self.assertEqual(c._next_year, 2027)
            self.assertEqual(c._makeup_next, {'2027-02-06'})

        import asyncio
        asyncio.run(run())


class TestCore(unittest.TestCase):
    def test_parse_text_and_roundtrip(self):
        text = ('2026-01-01~2026-01-03 元旦放假\n'
                '2026-01-04 补班\n'
                '2026-02-15~2026-02-22 春节\n'
                '2026-02-14,2026-02-28 上班')
        off, mk, names, assumed = core.parse_pasted(text, 2026)
        self.assertEqual(len(off), 3 + 8)
        self.assertEqual(len(mk), 3)
        self.assertEqual(assumed, [3])
        formatted = core.format_year(off, mk, names)
        off2, mk2, _, _ = core.parse_pasted(formatted, 2026)
        self.assertEqual(off, off2)
        self.assertEqual(mk, mk2)

    def test_invalid_dates_rejected(self):
        for bad in ('2026-13-01 休', '2026-02-30 班', ''):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    core.parse_pasted(bad, 2026)

    def test_next_holiday_does_not_merge_across_years(self):
        off = {'2026-12-31', '2027-01-01', '2027-01-02'}
        result = core.next_holiday(off, {'2026-12-31': '跨年', '2027-01-01': '元旦'},
                                   datetime.date(2026, 12, 30))
        self.assertEqual(result['end'], '2026-12-31')
        self.assertEqual(result['total_days'], 1)

    def test_month_progress(self):
        progress = core.month_progress(
            2026, 11, datetime.date(2026, 11, 10), set(), set(), set(), set()
        )
        self.assertEqual(progress, {'passed': 6, 'total': 21, 'left': 15, 'percent': 28.6})

    def test_parse_anniversaries(self):
        items = core.parse_anniversaries('生日: 05-20\n项目上线: 2026-12-01\n结婚纪念日：10-01')
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], {'name': '生日', 'date': '05-20', 'repeat': True})
        self.assertEqual(items[1], {'name': '项目上线', 'date': '2026-12-01', 'repeat': False})
        self.assertTrue(items[2]['repeat'])

    def test_parse_anniversaries_invalid(self):
        for bad in ('生日 05-20', '生日: 13-01', '生日: 02-30', '生日: 2026-02-30'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    core.parse_anniversaries(bad)

    def test_anniversaries_roundtrip(self):
        text = '生日: 05-20\n项目上线: 2026-12-01'
        items = core.parse_anniversaries(text)
        self.assertEqual(core.format_anniversaries(items), text)

    def test_next_anniversary_picks_nearest(self):
        today = datetime.date(2026, 11, 12)
        items = [
            {'name': '生日', 'date': '05-20', 'repeat': True},            # 已过 → 明年
            {'name': '项目上线', 'date': '2026-12-01', 'repeat': False},  # 19 天后
            {'name': '旧事', 'date': '2026-01-01', 'repeat': False},      # 已过 → 忽略
        ]
        result = core.next_anniversary(items, today)
        self.assertEqual(result['name'], '项目上线')
        self.assertEqual(result['date'], '2026-12-01')
        self.assertEqual(result['days'], 19)

    def test_next_anniversary_repeat_rolls_next_year(self):
        today = datetime.date(2026, 12, 20)
        items = [{'name': '生日', 'date': '05-20', 'repeat': True}]
        result = core.next_anniversary(items, today)
        self.assertEqual(result['date'], '2027-05-20')
        self.assertEqual(result['days'], 151)

    def test_parse_todos(self):
        items = core.parse_todos('2026-11-13 交报告\n[x] 2026-11-14 开会\n\n# 注释行')
        self.assertEqual(len(items), 2)
        self.assertEqual(
            items[0], {'date': '2026-11-13', 'text': '交报告', 'done': False}
        )
        self.assertEqual(
            items[1], {'date': '2026-11-14', 'text': '开会', 'done': True}
        )

    def test_parse_todos_invalid(self):
        for bad in ('2026-11-13', '11-13 交报告', '2026-02-30 交报告', '[x]2026-11-13'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    core.parse_todos(bad)

    def test_todos_roundtrip(self):
        text = '[ ] 2026-11-13 交报告\n[x] 2026-11-14 开会'
        self.assertEqual(core.format_todos(core.parse_todos(text)), text)

    def test_next_anniversary_today_is_zero(self):
        today = datetime.date(2026, 11, 12)
        result = core.next_anniversary([{'name': '今天', 'date': '11-12', 'repeat': True}], today)
        self.assertEqual(result['days'], 0)

    def test_next_anniversary_empty(self):
        self.assertIsNone(core.next_anniversary([], datetime.date(2026, 11, 12)))


if __name__ == '__main__':
    unittest.main()
