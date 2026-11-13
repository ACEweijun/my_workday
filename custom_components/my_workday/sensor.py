"""传感器：剩余工作日 / 总数 / 下一个假期 / 本月进度。"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ENTITY_LEFT,
    ENTITY_NEXT_HOLIDAY,
    ENTITY_PROGRESS,
    ENTITY_TOTAL,
)
from .coordinator import CnWorkdayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CnWorkdayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LeftSensor(coordinator, entry),
            TotalSensor(coordinator, entry),
            NextHolidaySensor(coordinator, entry),
            ProgressSensor(coordinator, entry),
        ]
    )


class CnWorkdaySensor(CoordinatorEntity[CnWorkdayCoordinator], SensorEntity):
    """公共部分。"""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="我的工作日",
            manufacturer="holiday-cn",
            model="法定节假日 + 调休",
        )


class LeftSensor(CnWorkdaySensor):
    """本月剩余工作日（含今天）。"""

    _attr_name = "本月剩余工作日"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_LEFT
        self._attr_unique_id = f"{entry.entry_id}_left"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get("left")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "date": data.get("today"),
            "month": data.get("month"),
            "month_total": data.get("total"),
            "custom_work": data.get("custom_work"),
            "custom_rest": data.get("custom_rest"),
            "holiday_data_year": data.get("data_year"),
            "holiday_data_source": data.get("data_source"),
            "holiday_data_updated": data.get("data_updated"),
            "year_data_text": data.get("year_text"),  # 界面渲染用
            "next_year_data_text": data.get("next_year_text"),
            "anniversaries": data.get("anniversaries"),
            "anniversaries_text": data.get("anniversaries_text"),
            "next_anniversary": data.get("next_anniversary"),
            "todos": data.get("todos"),
            "todos_text": data.get("todos_text"),
        }


class TotalSensor(CnWorkdaySensor):
    """本月工作日总数。"""

    _attr_name = "本月工作日总数"
    _attr_icon = "mdi:calendar-month"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TOTAL
        self._attr_unique_id = f"{entry.entry_id}_total"

    @property
    def native_value(self) -> int | None:
        return (self.coordinator.data or {}).get("total")


class NextHolidaySensor(CnWorkdaySensor):
    """距下个节假日还有几天。"""

    _attr_name = "距下个节假日"
    _attr_icon = "mdi:beach"
    _attr_native_unit_of_measurement = "天"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_NEXT_HOLIDAY
        self._attr_unique_id = f"{entry.entry_id}_next_holiday"

    @property
    def native_value(self) -> int | None:
        holiday = (self.coordinator.data or {}).get("next_holiday")
        return holiday["days"] if holiday else None

    @property
    def extra_state_attributes(self) -> dict:
        holiday = (self.coordinator.data or {}).get("next_holiday") or {}
        return {
            "name": holiday.get("name"),
            "start": holiday.get("start"),
            "end": holiday.get("end"),
            "total_days": holiday.get("total_days"),
        }


class ProgressSensor(CnWorkdaySensor):
    """本月工作日进度百分比。"""

    _attr_name = "本月工作日进度"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_PROGRESS
        self._attr_unique_id = f"{entry.entry_id}_progress"

    @property
    def native_value(self) -> float | None:
        return ((self.coordinator.data or {}).get("progress") or {}).get("percent")

    @property
    def extra_state_attributes(self) -> dict:
        progress = (self.coordinator.data or {}).get("progress") or {}
        return {
            "passed": progress.get("passed"),
            "total": progress.get("total"),
            "left": progress.get("left"),
        }
