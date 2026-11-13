"""二值传感器：今天 / 明天是否工作日。"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_TODAY, ENTITY_TOMORROW
from .coordinator import CnWorkdayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CnWorkdayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TodaySensor(coordinator, entry),
            TomorrowSensor(coordinator, entry),
        ]
    )


class _BaseWorkdayBinary(CoordinatorEntity[CnWorkdayCoordinator], BinarySensorEntity):
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


class TodaySensor(_BaseWorkdayBinary):
    """今天上班为 on，休息为 off。"""

    _attr_name = "今天是否工作日"
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TODAY
        self._attr_unique_id = f"{entry.entry_id}_today"

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("today_work")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "date": data.get("today"),
            "festival": data.get("title") or None,
        }


class TomorrowSensor(_BaseWorkdayBinary):
    """明天上班为 on —— 用于“明晚要不要早睡”。"""

    _attr_name = "明天是否工作日"
    _attr_icon = "mdi:briefcase-arrow-right-outline"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TOMORROW
        self._attr_unique_id = f"{entry.entry_id}_tomorrow"

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("tomorrow_work")

    @property
    def extra_state_attributes(self) -> dict:
        return {"date": (self.coordinator.data or {}).get("tomorrow")}
