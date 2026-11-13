"""集成入口：装载协调器、注册平台/服务、自带界面、提醒任务。"""
from __future__ import annotations

import inspect
import logging
from datetime import date
from datetime import time as dtime
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from . import core
from .const import (
    CONF_HOLIDAY_LEAD,
    CONF_MONTH_END_AT,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TIME,
    DEFAULT_HOLIDAY_LEAD,
    DEFAULT_MONTH_END_AT,
    DEFAULT_NOTIFY_TIME,
    DOMAIN,
    MODE_AUTO,
    MODE_REST,
    MODE_WORK,
    PANEL_FILE,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    SERVICE_CLEAR,
    SERVICE_REFRESH,
    SERVICE_SET_ANNIVERSARY,
    SERVICE_SET_CUSTOM,
    SERVICE_SET_DAY,
    SERVICE_SET_TODOS,
    SERVICE_SET_YEAR,
)
from .coordinator import CnWorkdayCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """装载一个配置条目。"""
    coordinator = CnWorkdayCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _at_midnight(_now) -> None:
        """每天 0 点重算，跨天自动翻页。"""
        await coordinator.async_refresh()

    entry.async_on_unload(
        async_track_time_change(hass, _at_midnight, hour=0, minute=0, second=30)
    )
    hass.data[f"{DOMAIN}_reminder"] = _async_setup_reminder(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _async_register_services(hass)
    await _async_register_panel(hass)
    _LOGGER.debug("我的工作日已加载")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目。"""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        reminder = hass.data.pop(f"{DOMAIN}_reminder", None)
        if reminder:
            reminder()
        bucket = hass.data.get(DOMAIN, {})
        bucket.pop(entry.entry_id, None)
        if not bucket:
            for service in (
                SERVICE_SET_DAY,
                SERVICE_SET_CUSTOM,
                SERVICE_CLEAR,
                SERVICE_SET_YEAR,
                SERVICE_SET_ANNIVERSARY,
                SERVICE_SET_TODOS,
                SERVICE_REFRESH,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
            _async_remove_panel(hass)
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """选项改了只重建提醒。数据源地址是每帧从 options 读的，不必重载集成。"""
    key = f"{DOMAIN}_reminder"
    previous = hass.data.pop(key, None)
    if previous:
        previous()
    hass.data[key] = _async_setup_reminder(hass, entry, _get_coordinator(hass))


# ---------------------------------------------------------------- 提醒
def _parse_clock(raw) -> tuple[int, int]:
    if isinstance(raw, dtime):
        return raw.hour, raw.minute
    parts = str(raw or DEFAULT_NOTIFY_TIME).strip().split(":")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 8, 0


def _parse_ints(raw) -> set[int]:
    out: set[int] = set()
    for chunk in str(raw or "").replace("，", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.add(int(chunk))
    return out


def _async_setup_reminder(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: CnWorkdayCoordinator
):
    """每天定时推送：假期倒计时 + 月末剩余工作日。没配 notify 服务就不启用。"""
    service = str(entry.options.get(CONF_NOTIFY_SERVICE) or "").strip()
    if "." not in service:
        return lambda: None

    lead_days = _parse_ints(entry.options.get(CONF_HOLIDAY_LEAD) or DEFAULT_HOLIDAY_LEAD)
    month_end_raw = str(entry.options.get(CONF_MONTH_END_AT) or DEFAULT_MONTH_END_AT)
    month_end_at = int(month_end_raw) if month_end_raw.strip().isdigit() else 3
    hour, minute = _parse_clock(entry.options.get(CONF_NOTIFY_TIME))
    domain, _, name = service.partition(".")

    async def _job(_now) -> None:
        data = coordinator.data or {}
        messages: list[str] = []

        holiday = data.get("next_holiday")
        if holiday and holiday.get("days") in lead_days:
            messages.append(
                f"距{holiday['name']}还有 {holiday['days']} 天"
                f"（{holiday['start']} 起，共 {holiday['total_days']} 天）"
            )

        left = data.get("left")
        if month_end_at > 0 and isinstance(left, int) and 0 < left <= month_end_at:
            today = dt_util.now().date()
            last_day = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            messages.append(f"本月还剩 {left} 个工作日（含今天），月末 {last_day.day} 号")

        if not messages:
            return
        try:
            await hass.services.async_call(
                domain,
                name,
                {"title": "工作日提醒", "message": "\n".join(messages)},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("提醒发送失败：%s", err)

    return async_track_time_change(hass, _job, hour=hour, minute=minute, second=0)


# ---------------------------------------------------------------- 自带界面
async def _async_register_panel(hass: HomeAssistant) -> None:
    """把 frontend/workday.html 挂到 /my_workday，并加进侧边栏。"""
    flag = f"{DOMAIN}_panel"
    if hass.data.get(flag):
        return

    folder = Path(__file__).parent / "frontend"
    if not (folder / PANEL_FILE).exists():
        _LOGGER.warning("找不到界面文件 %s，跳过侧边栏注册", folder / PANEL_FILE)
        return

    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_URL, str(folder), False)]
        )
    except ImportError:
        try:
            hass.http.register_static_path(PANEL_URL, str(folder), cache_headers=False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("静态目录注册失败：%s", err)
            return
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("静态目录注册失败：%s", err)
        return

    try:
        from homeassistant.components import frontend

        _panel_result = frontend.async_register_built_in_panel(
            hass,
            component_name="iframe",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            frontend_url_path=DOMAIN,
            config={"url": f"{PANEL_URL}/{PANEL_FILE}"},
            require_admin=False,
        )
        if inspect.isawaitable(_panel_result):
            await _panel_result
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "侧边栏面板注册失败（不影响实体）：%s。可改用 Webpage 仪表盘打开 %s/%s",
            err,
            PANEL_URL,
            PANEL_FILE,
        )
        return

    hass.data[flag] = True


def _async_remove_panel(hass: HomeAssistant) -> None:
    try:
        from homeassistant.components import frontend

        frontend.async_remove_panel(hass, DOMAIN)
    except Exception:  # noqa: BLE001
        pass
    hass.data.pop(f"{DOMAIN}_panel", None)


# ---------------------------------------------------------------- 服务
def _get_coordinator(hass: HomeAssistant) -> CnWorkdayCoordinator:
    bucket = hass.data.get(DOMAIN) or {}
    for coordinator in bucket.values():
        if isinstance(coordinator, CnWorkdayCoordinator):
            return coordinator
    raise HomeAssistantError("我的工作日还没加载完，请稍后再试")


def _to_iso(value) -> str:
    """兼容 date / datetime / 字符串，并校验是真日期。"""
    raw = value.isoformat() if hasattr(value, "isoformat") else str(value).strip()
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError as err:
        raise HomeAssistantError(f"日期格式不对：{raw}（应为 2026-11-28）") from err


def _async_register_services(hass: HomeAssistant) -> None:
    """逐个补齐，避免某次异常后其它服务永久缺注册。"""

    async def handle_set_day(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        day = _to_iso(call.data.get("date"))
        mode = str(call.data.get("mode") or MODE_WORK)

        if mode == MODE_WORK:
            coordinator.custom_rest.discard(day)
            coordinator.custom_work.add(day)
        elif mode == MODE_REST:
            coordinator.custom_work.discard(day)
            coordinator.custom_rest.add(day)
        elif mode == MODE_AUTO:
            coordinator.custom_work.discard(day)
            coordinator.custom_rest.discard(day)
        else:
            raise HomeAssistantError(f"不认识的 mode：{mode}")

        await coordinator.async_save_state()
        await coordinator.async_refresh()
        data = coordinator.data or {}
        return {
            "date": day,
            "mode": mode,
            "month_left": data.get("left"),
            "month_total": data.get("total"),
        }

    async def handle_set_custom(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        try:
            work = core.normalize_dates(call.data.get("work"))
            rest = core.normalize_dates(call.data.get("rest"))
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        both = work & rest
        if both:
            raise HomeAssistantError(f"同一天不能既算上班又算休息：{sorted(both)}")
        await coordinator.async_set_custom(work, rest)
        return {"work": len(work), "rest": len(rest)}

    async def handle_set_anniversary(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        text = str(call.data.get("data") or "")
        try:
            items = core.parse_anniversaries(text)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_set_anniversaries(items)
        return {"count": len(items)}

    async def handle_set_todos(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        text = str(call.data.get("data") or "")
        try:
            items = core.parse_todos(text)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_set_todos(items)
        return {"count": len(items)}

    async def handle_clear(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        await coordinator.async_set_custom(set(), set())
        return {"cleared": True}

    async def handle_refresh(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        try:
            off_count, makeup_count, cleared = await coordinator.async_force_refresh()
        except UpdateFailed as err:
            raise HomeAssistantError(f"刷新失败：{err}") from err
        _LOGGER.info("已重新拉取放假数据：放假 %s 天，补班 %s 天", off_count, makeup_count)
        return {
            "year": dt_util.now().year,
            "off_days": off_count,
            "makeup_days": makeup_count,
            "manual_data_cleared": cleared,
        }

    async def handle_set_year(call: ServiceCall) -> dict:
        coordinator = _get_coordinator(hass)
        year_raw = call.data.get("year")
        year = int(year_raw) if year_raw not in (None, "") else dt_util.now().year
        text = str(call.data.get("data") or "")
        if not text.strip():
            coordinator.year_override.pop(year, None)
            await coordinator.async_save_state()
            await coordinator.async_refresh()
            _LOGGER.info("%s 年已恢复为自动获取", year)
            return {"year": year, "cleared": True}
        try:
            off_count, makeup_count, assumed = await coordinator.async_set_year_data(year, text)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        _LOGGER.info("%s 年安排已更新：放假 %s 天，补班 %s 天", year, off_count, makeup_count)
        if assumed:
            _LOGGER.warning(
                "%s 年第 %s 行没写「休/假/班」，已按放假处理，请核对", year, assumed
            )
        return {
            "year": year,
            "off_days": off_count,
            "makeup_days": makeup_count,
            "assumed_lines": assumed,
        }

    reg = hass.services.async_register
    for name, handler in (
        (SERVICE_SET_DAY, handle_set_day),
        (SERVICE_SET_CUSTOM, handle_set_custom),
        (SERVICE_CLEAR, handle_clear),
        (SERVICE_SET_YEAR, handle_set_year),
        (SERVICE_SET_ANNIVERSARY, handle_set_anniversary),
        (SERVICE_SET_TODOS, handle_set_todos),
        (SERVICE_REFRESH, handle_refresh),
    ):
        if not hass.services.has_service(DOMAIN, name):
            reg(DOMAIN, name, handler, supports_response=SupportsResponse.OPTIONAL)
