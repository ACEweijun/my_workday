"""单条提醒规则：规范化与优先级解析（纯函数，不依赖 HA）。

数据契约：
  push = {"mode": "inherit" | "custom" | "off",   # 缺省 inherit
          "advance_days": [7,3,1],                # 纪念日提前天数
          "time": "08:00",                        # 提醒时刻 HH:MM
          "weekday": 6}                           # 维护项星期 0=周一..6=周日

优先级：mode=off 不发；mode=inherit 用全局；mode=custom 用自身字段覆盖全局。
"""
from __future__ import annotations

import re

MODE_INHERIT = "inherit"
MODE_CUSTOM = "custom"
MODE_OFF = "off"
VALID_MODES = (MODE_INHERIT, MODE_CUSTOM, MODE_OFF)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalize_push(value) -> dict:
    """把任意输入规整成合法 push 对象。空值 -> inherit（跟随全局）。"""
    if not isinstance(value, dict):
        return {"mode": MODE_INHERIT}
    mode = value.get("mode", MODE_INHERIT)
    if mode not in VALID_MODES:
        mode = MODE_INHERIT
    out = {"mode": mode}
    if mode == MODE_CUSTOM:
        days = value.get("advance_days")
        if isinstance(days, list):
            clean = sorted({int(x) for x in days
                            if str(x).lstrip('-').isdigit() and 0 <= int(x) <= 365})
            if clean:
                out["advance_days"] = clean
        t = str(value.get("time") or "")
        if _TIME_RE.match(t):
            out["time"] = t
        wd = value.get("weekday")
        if isinstance(wd, int) and not isinstance(wd, bool) and 0 <= wd <= 6:
            out["weekday"] = wd
    return out


def resolve_push(global_cfg: dict, item: dict) -> dict | None:
    """解析某条数据最终生效的提醒规则；返回 None 表示不发。"""
    push = normalize_push(item.get("push"))
    if push["mode"] == MODE_OFF:
        return None
    if push["mode"] == MODE_INHERIT:
        return dict(global_cfg or {})
    # custom：以自身字段覆盖全局
    merged = dict(global_cfg or {})
    for key in ("advance_days", "time", "weekday"):
        if key in push:
            merged[key] = push[key]
    merged["enabled"] = True  # 细项自定义即视为要发（除非全局总开关关闭，由调用方判断）
    return merged


def push_fingerprint(rule: dict) -> str:
    """规则指纹：规则任何变化都改变去重 key，避免改规则后当天不补推。"""
    import hashlib
    raw = "|".join(f"{k}={rule.get(k)}" for k in
                   ("mode", "advance_days", "time", "weekday", "enabled"))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
