"""日历：工作日 / 补班 / 节假日 + 维护到期项，同一个日历实体。"""
from __future__ import annotations

import datetime as dt

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import workday as wd
from .const import DOMAIN, ENTITY_CALENDAR
from .coordinator import MergedCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator: MergedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MergedCalendar(coordinator, entry)])


class MergedCalendar(CoordinatorEntity[MergedCoordinator], CalendarEntity):
    _attr_name = "我的日程"
    _attr_has_entity_name = True

    def __init__(self, coordinator: MergedCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entity_id = ENTITY_CALENDAR
        self._attr_unique_id = f"{entry.entry_id}_calendar"

    def _events_between(self, start: dt.date, end: dt.date) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        w = data.get("workday") or {}
        h = data.get("holidays") or {}
        holidays = {"off": set(h.get("off") or []),
                    "makeup": set(h.get("makeup") or []),
                    "names": h.get("names") or {}}
        work_set = set(w.get("custom_work") or [])
        rest_set = set(w.get("custom_rest") or [])
        events: list[CalendarEvent] = []
        day = start
        while day <= end and (day - start).days < 400:
            is_work, label = wd.classify(day, holidays, work_set, rest_set)
            if label and label != "休":
                title = f"上班 · {label}" if is_work else str(label)
                events.append(CalendarEvent(
                    start=day, end=day + dt.timedelta(days=1),
                    summary=title, description="my_workday 工作日安排"))
            day += dt.timedelta(days=1)
        for item in (data.get("maintenance") or {}).get("due_items") or []:
            try:
                due = dt.date.fromisoformat(item.get("due_date"))
            except (ValueError, TypeError):
                continue
            if start <= due <= end:
                marker = "已到期" if item.get("status") == "due" else "快到了"
                events.append(CalendarEvent(
                    start=due, end=due + dt.timedelta(days=1),
                    summary=f"[维护·{marker}] {item.get('project')} · {item.get('name')}",
                    description=f"my_workday 维护项目 {item.get('slug')}"))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        today = dt.date.today()
        events = self._events_between(today, today + dt.timedelta(days=365))
        return events[0] if events else None

    async def async_get_events(self, hass: HomeAssistant,
                               start_date: dt.datetime,
                               end_date: dt.datetime) -> list[CalendarEvent]:
        return self._events_between(start_date.date(), end_date.date())
