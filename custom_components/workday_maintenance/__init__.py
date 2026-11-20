"""workday_maintenance：工作日 / 待办 / 维护台账合并集成，两个独立网页共用一份数据。"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import logging
from pathlib import Path

from aiohttp import web

from homeassistant.components import frontend, websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from . import maintenance as mnt
from . import workday as wd
from .const import (
    DOMAIN, EVENT_UPDATED, MODE_AUTO, MODE_REST, MODE_WORK,
    PANEL_MAINTENANCE, PANEL_MAINTENANCE_PATH, PANEL_URL, PANEL_WORKDAY,
    SCOPE_ALL, SCOPE_MAINTENANCE, SCOPE_WORKDAY, SERVICE_ADD_ITEM, SERVICE_ADD_PROJECT,
    SERVICE_CLEAR_CUSTOM, SERVICE_DELETE_ITEM, SERVICE_DELETE_PROJECT,
    SERVICE_DELETE_RECORD, SERVICE_EXPORT, SERVICE_EXPORT_ALL, SERVICE_GET_SNAPSHOT,
    SERVICE_LIST_PROJECTS, SERVICE_LOG_SERVICE, SERVICE_REFRESH,
    SERVICE_GET_SETTINGS, SERVICE_SET_SETTINGS,
    SERVICE_SET_ANNIVERSARIES, SERVICE_SET_BASELINE, SERVICE_SET_COUNTER,
    SERVICE_SET_CUSTOM, SERVICE_SET_DAY, SERVICE_SET_TODOS, SERVICE_SET_YEAR,
    SERVICE_IMPORT_PROJECTS, SERVICE_SYNC_TODOS, SERVICE_UPDATE_ITEM, SERVICE_UPDATE_PROJECT,
    SERVICE_UPDATE_RECORD, CONF_SYNC_DUE_TO_TODOS,
)
from .coordinator import MergedCoordinator
from .services import async_register_services
from .notify import NotifyManager
from . import push_rule as _pr

_LOGGER = logging.getLogger(__name__)


# 前端静态资源缓存：启动阶段一次性异步读入内存，避免事件循环内同步 IO。
_FRONTEND_CACHE: dict = {"version": "0", "html": {}, "static": {}}


def _frontend_version() -> str:
    """返回缓存的集成版本号（启动阶段预热），用于前端缓存破坏。"""
    return _FRONTEND_CACHE.get("version", "0")


PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR]
# demo-data.js 也在页面中被引用：本地预览时提供虚拟数据，HA 下脚本自检测失效。
# 必须放进白名单，否则 HA 会返回 404 并在浏览器控制台报错。
_FRONTEND_FILES = frozenset({
    "workday.html", "maintenance.html", "shared.js", "shared.css", "demo-data.js",
})


def _load_frontend_cache() -> dict:
    """在线程池执行：读 manifest 与前端文件，预生成注入版本号后的 HTML。"""
    base = Path(__file__).parent
    try:
        version = json.loads(
            (base / "manifest.json").read_text(encoding="utf-8")
        ).get("version", "0")
    except Exception:  # noqa: BLE001
        version = "0"
    html, static = {}, {}
    for filename in _FRONTEND_FILES:
        path = base / "frontend" / filename
        if not path.is_file():
            continue
        if filename.endswith(".html"):
            text = path.read_text(encoding="utf-8")
            for asset in ("shared.css", "shared.js"):
                text = text.replace('="' + asset + '"',
                                    '="' + asset + '?v=' + version + '"')
            html[filename] = text
        else:
            static[filename] = path.read_bytes()
    return {"version": version, "html": html, "static": static}


async def _async_warm_frontend_cache(hass: HomeAssistant) -> None:
    """启动时预热前端缓存（文件读取放到线程池）。"""
    try:
        loaded = await hass.async_add_executor_job(_load_frontend_cache)
        _FRONTEND_CACHE.update(loaded)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("前端缓存预热失败，页面可能不可用：%s", err)


class FrontendFileView(HomeAssistantView):
    url = PANEL_URL + "/{filename}"
    name = "api:workday_maintenance:frontend"
    requires_auth = False

    async def get(self, request, filename):
        if filename not in _FRONTEND_FILES:
            raise web.HTTPNotFound()
        # 全部从启动阶段预热的缓存读取，事件循环内无同步文件 IO。
        headers = {"Cache-Control": "no-cache"}
        if filename.endswith(".html"):
            text = _FRONTEND_CACHE["html"].get(filename)
            if text is None:
                raise web.HTTPNotFound()
            return web.Response(
                text=text, content_type="text/html", headers=headers
            )
        content = _FRONTEND_CACHE["static"].get(filename)
        if content is None:
            raise web.HTTPNotFound()
        # 必须显式给 MIME 类型：浏览器会拒绝把 application/octet-stream 当 CSS/JS 加载。
        mime = "text/css" if filename.endswith(".css") else "application/javascript"
        return web.Response(body=content, content_type=mime, headers=headers)


@websocket_api.websocket_command({"type": "workday_maintenance/snapshot"})
@websocket_api.async_response
async def _ws_snapshot(hass: HomeAssistant, connection, msg) -> None:
    coordinator = _get(hass)
    if not coordinator.data:
        await coordinator.async_refresh()
    connection.send_result(msg["id"], dict(coordinator.data or {}))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_warm_frontend_cache(hass)
    coordinator = MergedCoordinator(hass, entry)
    await coordinator.async_warm_snapshots()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    notifier = NotifyManager(hass, coordinator)
    hass.data.setdefault(f"{DOMAIN}_notifier", {})[entry.entry_id] = notifier
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _midnight(_now) -> None:
        await coordinator.async_refresh()
        if bool(entry.options.get(CONF_SYNC_DUE_TO_TODOS, False)):
            await coordinator.async_sync_due_todos(True)
            await coordinator.async_refresh()

    entry.async_on_unload(
        async_track_time_change(hass, _midnight, hour=0, minute=0, second=30)
    )

    async def _check_reminders(_now) -> None:
        # 每分钟扫描。时间/星期判断已下放到各检查函数内部逐项做：
        # 因为细项可覆盖全局时间，调度器不能再按全局时间提前拦截。
        settings = await notifier.get_settings()
        now = dt_util.now()
        if (settings.get("anniversary") or {}).get("enabled"):
            try:
                await notifier.check_anniversaries(now)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("纪念日提醒失败：%s", err)
        if (settings.get("maintenance") or {}).get("enabled"):
            try:
                await notifier.check_maintenance(now)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("维护提醒失败：%s", err)

    entry.async_on_unload(
        async_track_time_change(hass, _check_reminders, second=0)
    )
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    async_register_services(hass, coordinator, notifier)
    # WebSocket 命令按 handler 名做幂等注册；标志在卸载时清理，保证重新加载后可再次注册。
    if not hass.data.get(f"{DOMAIN}_ws"):
        websocket_api.async_register_command(hass, _ws_snapshot)
        hass.data[f"{DOMAIN}_ws"] = True
    await _async_register_panels(hass)
    return True


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coordinator = _get(hass)
    await coordinator.async_force_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            for name in list(hass.services.async_services().get(DOMAIN, {})):
                hass.services.async_remove(DOMAIN, name)
            _async_remove_panels(hass)
            # 清理全局标志：下次加载时重新走 WS 注册，避免标志残留导致跳过注册。
            hass.data.pop(f"{DOMAIN}_ws", None)
        hass.data.get(f"{DOMAIN}_notifier", {}).pop(entry.entry_id, None)
    return unloaded


def _get(hass: HomeAssistant) -> MergedCoordinator:
    bucket = hass.data.get(DOMAIN) or {}
    for value in bucket.values():
        if isinstance(value, MergedCoordinator):
            return value
    raise HomeAssistantError("workday_maintenance 尚未加载完成")


async def _async_register_panels(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_panels"):
        return
    try:
        hass.http.register_view(FrontendFileView())
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("前端文件路由注册失败（重载时可能已存在）：%s", err)
    for path, title, icon, page in (
        (DOMAIN, "我的工作日", "mdi:calendar-check", PANEL_WORKDAY),
        (PANEL_MAINTENANCE_PATH, "维护台账", "mdi:wrench-outline", PANEL_MAINTENANCE),
    ):
        try:
            result = frontend.async_register_built_in_panel(
                hass,
                component_name="iframe",
                sidebar_title=title,
                sidebar_icon=icon,
                frontend_url_path=path,
                config={"url": f"{PANEL_URL}/{page}?v={_frontend_version()}"},
                require_admin=False,
            )
            if inspect.isawaitable(result):
                await result
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("侧边栏面板 %s 注册失败：%s", title, err)
    hass.data[f"{DOMAIN}_panels"] = True


def _async_remove_panels(hass: HomeAssistant) -> None:
    for path in (DOMAIN, PANEL_MAINTENANCE_PATH):
        try:
            frontend.async_remove_panel(hass, path)
        except Exception:  # noqa: BLE001
            pass
    hass.data.pop(f"{DOMAIN}_panels", None)
