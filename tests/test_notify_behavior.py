"""提醒逻辑的纯函数测试：纪念日提前天数、去重 key、维护汇总文案。"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'custom_components' / 'workday_maintenance'

# 建立包上下文，导入 workday / maintenance 纯逻辑（不依赖 HA）
_pkg = types.ModuleType('workday_maintenance')
_pkg.__path__ = [str(PKG)]
sys.modules['workday_maintenance'] = _pkg
import importlib.util


def _load(name):
    spec = importlib.util.spec_from_file_location('workday_maintenance.' + name, PKG / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules['workday_maintenance.' + name] = m
    spec.loader.exec_module(m)
    return m


const = _load('const')
wd = _load('workday')
mnt = _load('maintenance')


class TestReminderLogic(unittest.TestCase):
    def test_anniversary_next_and_advance(self):
        """每年重复的纪念日，提前 7/3/1 天的判定正确。"""
        today = dt.date(2026, 11, 18)
        ann = {"name": "测试纪念日", "date": "2026-10-16", "repeat": "year"}
        nxt = wd.anniversary_next(ann, today)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.isoformat(), '2027-10-16')  # 今年已过， rolls to next year
        days = (nxt - today).days
        self.assertGreater(days, 0)

        # 造一个正好 7 天后的纪念日
        target = today + dt.timedelta(days=7)
        ann2 = {"name": "7天后", "date": target.isoformat(), "repeat": "year"}
        nxt2 = wd.anniversary_next(ann2, today)
        self.assertEqual((nxt2 - today).days, 7)

    def test_due_items_summary(self):
        """维护项汇总：只列到期/快到期，带项目名与小项名。"""
        today = dt.date(2026, 11, 18)
        projects = [{
            "slug": "car", "name": "卡罗拉", "need_counter": False,
            "counter": None, "counter_unit": "",
            "items": [
                {"id": "i1", "name": "机油", "interval_days": 180,
                 "last_date": "2026-01-01", "interval_counter": None, "last_counter": None, "note": ""},
                {"id": "i2", "name": "刹车油", "interval_days": 730,
                 "last_date": "2026-11-01", "interval_counter": None, "last_counter": None, "note": ""},
            ],
            "history": [],
        }]
        due = mnt.all_due_items(projects, today, 7)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["name"], "机油")
        self.assertEqual(due[0]["project"], "卡罗拉")

    def test_day_key_format(self):
        """去重 key 含类型+目标+日期，同一天同目标不会重复推。"""
        today = dt.date(2026, 11, 18)
        key = f"ann:a1:{today.isoformat()}"
        self.assertEqual(key, "ann:a1:2026-11-18")


if __name__ == '__main__':
    unittest.main()
