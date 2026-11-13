"""诊断：一键下载配置与数据快照，方便别人报 bug。"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
    if coordinator is None:
        return {"loaded": False, "hint": "集成当前未加载"}

    return {
        "loaded": True,
        "options": dict(entry.options),
        "snapshot": coordinator.data,
        "custom_work": sorted(coordinator.custom_work),
        "custom_rest": sorted(coordinator.custom_rest),
        "pasted_years": sorted(coordinator.year_override),
        "state": {
            "today": coordinator.data.get("today") if coordinator.data else None,
            "data_source": coordinator.data.get("data_source") if coordinator.data else None,
        },
        "version": entry.version,
    }
