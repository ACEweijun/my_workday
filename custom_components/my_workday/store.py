"""统一存储：一个 .storage 键承载工作日与维护台账的全部数据。"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION


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
