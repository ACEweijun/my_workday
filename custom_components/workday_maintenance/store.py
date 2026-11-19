"""统一存储：一个 .storage 键承载工作日与维护台账的全部数据。"""
from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    SETTINGS_KEY, SETTINGS_VERSION, STORAGE_KEY, STORAGE_VERSION,
)


def default_data() -> dict:
    return {
        "version": STORAGE_VERSION,
        "workday": {
            "custom_work": [],
            "custom_rest": [],
            "year_override": {},
            "todos": [],
            "anniversaries": [],
        },
        "maintenance": {"projects": []},
    }


def normalize(raw) -> dict:
    data = default_data()
    if not isinstance(raw, dict):
        return data
    workday = raw.get("workday") or {}
    maintenance = raw.get("maintenance") or {}
    for key in ("custom_work", "custom_rest", "todos", "anniversaries"):
        value = workday.get(key)
        if isinstance(value, list):
            data["workday"][key] = value
    if isinstance(workday.get("year_override"), dict):
        data["workday"]["year_override"] = workday["year_override"]
    if isinstance(maintenance.get("projects"), list):
        data["maintenance"]["projects"] = maintenance["projects"]
    return data


class MergedStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> dict:
        return normalize(await self._store.async_load())

    async def async_save(self, data: dict) -> None:
        await self._store.async_save(data)


# ── 提醒设置（独立存储，不进导出存档）────────────────────────────

DEFAULT_SETTINGS = {
    "version": SETTINGS_VERSION,
    "magicpush": {
        "url": "",          # 例：https://push.example.com
        "token": "",        # 推送接口 token
        "enabled": False,
    },
    "anniversary": {
        "enabled": False,
        "advance_days": [7, 3, 1],
        "time": "08:00",
    },
    "maintenance": {
        "enabled": False,
        "weekday": 6,       # 0=周一 ... 6=周日
        "time": "09:00",
    },
    "sent": {},             # 去重：key -> ISO 日期，推送后记录
}


def normalize_settings(raw) -> dict:
    """容错合并：缺字段用默认，保留已保存的值。"""
    out = json.loads(json.dumps(DEFAULT_SETTINGS))  # 深拷贝
    if not isinstance(raw, dict):
        return out
    for section in ("magicpush", "anniversary", "maintenance"):
        src = raw.get(section)
        if isinstance(src, dict):
            for k, v in src.items():
                if k in out[section]:
                    out[section][k] = v
    if isinstance(raw.get("sent"), dict):
        out["sent"] = raw["sent"]
    return out


class SettingsStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, SETTINGS_VERSION, SETTINGS_KEY)

    async def async_load(self) -> dict:
        return normalize_settings(await self._store.async_load())

    async def async_save(self, data: dict) -> None:
        await self._store.async_save(data)
