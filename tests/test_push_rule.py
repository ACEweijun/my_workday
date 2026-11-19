"""push_rule 纯函数测试：优先级、边界、指纹。"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'custom_components' / 'workday_maintenance'
_spec = importlib.util.spec_from_file_location('pr', PKG / 'push_rule.py')
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

GLOBAL = {"enabled": True, "advance_days": [7, 3, 1], "time": "08:00", "weekday": 6}


class TestPushRule(unittest.TestCase):
    def test_inherit_by_default(self):
        self.assertEqual(pr.resolve_push(GLOBAL, {}), GLOBAL)
        self.assertEqual(pr.resolve_push(GLOBAL, {"push": {}}), GLOBAL)
        self.assertEqual(pr.resolve_push(GLOBAL, {"push": None}), GLOBAL)

    def test_off_suppresses(self):
        self.assertIsNone(pr.resolve_push(GLOBAL, {"push": {"mode": "off"}}))

    def test_custom_overrides_only_present_fields(self):
        r = pr.resolve_push(GLOBAL, {"push": {"mode": "custom", "time": "07:30"}})
        self.assertEqual(r["time"], "07:30")
        self.assertEqual(r["advance_days"], [7, 3, 1])  # 继承全局
        self.assertEqual(r["weekday"], 6)

    def test_invalid_mode_falls_back(self):
        self.assertEqual(pr.normalize_push({"mode": "bogus"})["mode"], "inherit")

    def test_invalid_time_dropped(self):
        out = pr.normalize_push({"mode": "custom", "time": "99:99",
                                 "advance_days": [-1, 0, 3, 400, 3]})
        self.assertNotIn("time", out)
        self.assertEqual(out["advance_days"], [0, 3])

    def test_weekday_boundary(self):
        self.assertIn("weekday", pr.normalize_push({"mode": "custom", "weekday": 0}))
        self.assertIn("weekday", pr.normalize_push({"mode": "custom", "weekday": 6}))
        self.assertNotIn("weekday", pr.normalize_push({"mode": "custom", "weekday": 7}))
        self.assertNotIn("weekday", pr.normalize_push({"mode": "custom", "weekday": True}))

    def test_fingerprint_changes_with_rule(self):
        a = pr.push_fingerprint(GLOBAL)
        self.assertNotEqual(a, pr.push_fingerprint({**GLOBAL, "time": "09:00"}))
        self.assertNotEqual(a, pr.push_fingerprint({**GLOBAL, "advance_days": [1]}))
        self.assertEqual(a, pr.push_fingerprint(dict(GLOBAL)))  # 相同规则指纹稳定


if __name__ == '__main__':
    unittest.main()
