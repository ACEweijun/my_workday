"""传感器：工作日统计 + 维护到期汇总 + 今日待办总数。"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, ENTITY_DUE_MAINTENANCE, ENTITY_LEFT, ENTITY_NEXT_HOLIDAY,
    ENTITY_PROGRESS, ENTITY_TODAY_TASKS, ENTITY_TOTAL,
)
from .coordinator import MergedCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator: MergedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        LeftSensor(coordinator, entry), TotalSensor(coordinator, entry),
        ProgressSensor(coordinator, entry), NextHolidaySensor(coordinator, entry),
        DueMaintenanceSensor(coordinator, entry), TodayTasksSensor(coordinator, entry),
    ])


class Base(CoordinatorEntity[MergedCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: MergedCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="workday_maintenance", manufacturer="自建", model="工作日 + 维护台账",
        )

    @property
    def wd(self) -> dict:
        return (self.coordinator.data or {}).get("workday", {})

    @property
    def mt(self) -> dict:
        return (self.coordinator.data or {}).get("maintenance", {})


class LeftSensor(Base):
    _attr_name = "本月剩余工作日"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_LEFT
        self._attr_unique_id = f"{entry.entry_id}_left"

    @property
    def native_value(self):
        return (self.wd.get("stats") or {}).get("left")

    @property
    def extra_state_attributes(self):
        stats = self.wd.get("stats") or {}
        return {
            "date": (self.coordinator.data or {}).get("today"),
            "month": stats.get("month"),
            "month_total": stats.get("total"),
            "month_remaining_dates": stats.get("remaining_dates") or [],
            "custom_work": self.wd.get("custom_work") or [],
            "custom_rest": self.wd.get("custom_rest") or [],
            "holiday_source": self.wd.get("holiday_source"),
            "due_maintenance": self.mt.get("due_total", 0),
        }


class TotalSensor(Base):
    _attr_name = "本月工作日总数"
    _attr_icon = "mdi:calendar-month"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TOTAL
        self._attr_unique_id = f"{entry.entry_id}_total"

    @property
    def native_value(self):
        return (self.wd.get("stats") or {}).get("total")


class ProgressSensor(Base):
    _attr_name = "本月工作日进度"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_PROGRESS
        self._attr_unique_id = f"{entry.entry_id}_progress"

    @property
    def native_value(self):
        return (self.wd.get("stats") or {}).get("percent")

    @property
    def extra_state_attributes(self):
        stats = self.wd.get("stats") or {}
        return {"passed": stats.get("passed"), "total": stats.get("total"),
                "left": stats.get("left")}


class NextHolidaySensor(Base):
    _attr_name = "距下个节假日"
    _attr_icon = "mdi:beach"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_NEXT_HOLIDAY
        self._attr_unique_id = f"{entry.entry_id}_next_holiday"

    @property
    def native_value(self):
        holiday = self.wd.get("next_holiday") or {}
        return holiday.get("days")

    @property
    def extra_state_attributes(self):
        h = self.wd.get("next_holiday") or {}
        return {"name": h.get("name"), "start": h.get("start"),
                "end": h.get("end"), "total_days": h.get("total_days")}


class DueMaintenanceSensor(Base):
    _attr_name = "到期维护项"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = "项"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_DUE_MAINTENANCE
        self._attr_unique_id = f"{entry.entry_id}_due_maintenance"

    @property
    def native_value(self):
        return self.mt.get("due_total", 0)

    @property
    def extra_state_attributes(self):
        return {
            "soon_total": self.mt.get("soon_total", 0),
            "due_items": self.mt.get("due_items") or [],
            "projects": [
                {"slug": s.get("slug"), "name": s.get("name"),
                 "due_count": s.get("due_count"), "soon_count": s.get("soon_count")}
                for s in self.mt.get("summaries") or []
            ],
        }


class TodayTasksSensor(Base):
    _attr_name = "今天要做的事"
    _attr_icon = "mdi:format-list-checks"
    _attr_native_unit_of_measurement = "件"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TODAY_TASKS
        self._attr_unique_id = f"{entry.entry_id}_today_tasks"

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("tasks_today", 0)

    @property
    def extra_state_attributes(self):
        today = (self.coordinator.data or {}).get("today")
        todos = [t for t in self.wd.get("todos") or []
                 if t.get("date") == today and not t.get("done")]
        return {"open_todos": [t.get("text") for t in todos],
                "due_maintenance": [d["name"] for d in self.mt.get("due_items") or []
                                    if d["status"] == "due"]}
