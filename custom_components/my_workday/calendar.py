"""日历实体：把工作日 / 放假 / 补班输出成全天事件，HA 自带日历卡片可直接显示。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ENTITY_CALENDAR
from .coordinator import CnWorkdayCoordinator

MAX_DAYS = 400


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CnWorkdayCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WorkdayCalendar(coordinator, entry)])


class WorkdayCalendar(CoordinatorEntity[CnWorkdayCoordinator], CalendarEntity):
    """每个工作日一条全天事件，summary 说明性质。"""

    _attr_has_entity_name = True
    _attr_name = "工作日日历"
    _attr_icon = "mdi:calendar-month"

    def __init__(self, coordinator: CnWorkdayCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entity_id = ENTITY_CALENDAR
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="我的工作日",
            manufacturer="holiday-cn",
            model="法定节假日 + 调休",
        )

    # ------------------------------------------------------------ 事件
    def _event_for(self, day: date) -> CalendarEvent | None:
        coord = self.coordinator
        if not coord.is_workday(day):
            return None

        key = day.isoformat()
        summary = "工作日"
        if key in coord.custom_work:
            summary = "上班（自定义）"
        elif coord.is_makeup(day):
            summary = "补班"
        return CalendarEvent(
            start=day,
            end=day + timedelta(days=1),
            summary=summary,
            description=None,
            uid=f"my_workday_{key}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """当前进行中的事件（今天）。"""
        return self._event_for(dt_util.now().date())

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        first = start_date.date()
        last = end_date.date()
        if (last - first).days > MAX_DAYS:
            last = first + timedelta(days=MAX_DAYS)
        events: list[CalendarEvent] = []
        day = first
        while day < last:
            event = self._event_for(day)
            if event is not None:
                events.append(event)
            day += timedelta(days=1)
        return events
