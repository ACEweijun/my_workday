"""提醒推送：读取设置、计算纪念日/维护项、调用 magicpush、去重。

独立模块，不依赖前端；由 coordinator 的定时任务与服务调用。
"""
from __future__ import annotations

import datetime as dt
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import maintenance as mnt
from . import workday as wd

_LOGGER = logging.getLogger(__name__)


class NotifyManager:
    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.store = coordinator.settings_store

    async def get_settings(self) -> dict:
        return await self.store.async_load()

    async def save_settings(self, payload: dict) -> dict:
        """前端提交的设置：白名单合并，避免误写任意字段。"""
        current = await self.store.async_load()
        for section in ("magicpush", "anniversary", "maintenance"):
            src = payload.get(section)
            if not isinstance(src, dict):
                continue
            for k in list(current[section].keys()):
                if k == "version":
                    continue
                if k in src:
                    current[section][k] = src[k]
        # advance_days 规整：去重、只保留 0~365、排序
        adv = current["anniversary"].get("advance_days")
        if isinstance(adv, list):
            clean = sorted({int(x) for x in adv if str(x).lstrip('-').isdigit() and 0 <= int(x) <= 365})
            current["anniversary"]["advance_days"] = clean
        await self.store.async_save(current)
        return current

    # ── 去重 ─────────────────────────────────────────────────
    @staticmethod
    def _day_key(prefix: str, target: str, today: dt.date) -> str:
        return f"{prefix}:{target}:{today.isoformat()}"

    async def _should_send(self, key: str, today: dt.date) -> bool:
        settings = await self.store.async_load()
        return settings.get("sent", {}).get(key) != today.isoformat()

    async def _mark_sent(self, key: str, today: dt.date) -> None:
        settings = await self.store.async_load()
        sent = settings.setdefault("sent", {})
        # 只保留最近 60 天的记录，避免无限增长
        limit = (today - dt.timedelta(days=60)).isoformat()
        settings["sent"] = {k: v for k, v in sent.items() if v >= limit}
        settings["sent"][key] = today.isoformat()
        await self.store.async_save(settings)

    # ── 推送 ─────────────────────────────────────────────────
    async def _push(self, title: str, content: str) -> bool:
        settings = await self.store.async_load()
        cfg = settings.get("magicpush") or {}
        if not cfg.get("enabled") or not cfg.get("url") or not cfg.get("token"):
            _LOGGER.debug("magicpush 未启用或配置不全，跳过推送")
            return False
        url = str(cfg["url"]).rstrip("/") + "/api/push"
        payload = {"title": title, "content": content, "type": "text"}
        headers = {"Authorization": "Bearer " + str(cfg["token"]),
                   "Content-Type": "application/json"}
        try:
            session = async_get_clientsession(self.hass)
            async with session.post(url, json=payload, headers=headers,
                                    timeout=10) as resp:
                if resp.status == 200:
                    return True
                text = await resp.text()
                _LOGGER.warning("magicpush 推送失败 %s: %s", resp.status, text[:200])
                return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("magicpush 推送异常：%s", err)
            return False

    # ── 纪念日：提前 N 天 ────────────────────────────────────
    async def check_anniversaries(self) -> int:
        settings = await self.store.async_load()
        cfg = settings.get("anniversary") or {}
        if not cfg.get("enabled"):
            return 0
        advances = [int(x) for x in (cfg.get("advance_days") or [])]
        if not advances:
            return 0
        raw = await self.coordinator.store.async_load()
        anniversaries = (raw.get("workday") or {}).get("anniversaries") or []
        today = dt_util.now().date()
        sent = 0
        for a in anniversaries:
            day = wd.anniversary_next(a, today)
            if not day:
                continue
            days = (day - today).days
            if days not in advances:
                continue
            key = self._day_key("ann", str(a.get("id") or a.get("name")), today)
            if not await self._should_send(key, today):
                continue
            title = "纪念日提醒"
            content = f"{a.get('name','')} · {days} 天后（{day.isoformat()}）"
            if await self._push(title, content):
                await self._mark_sent(key, today)
                sent += 1
        return sent

    # ── 维护项：按到期状态汇总 ───────────────────────────────
    async def check_maintenance(self) -> int:
        settings = await self.store.async_load()
        cfg = settings.get("maintenance") or {}
        if not cfg.get("enabled"):
            return 0
        raw = await self.coordinator.store.async_load()
        projects = (raw.get("maintenance") or {}).get("projects") or []
        today = dt_util.now().date()
        due = mnt.all_due_items(projects, today, self.coordinator.soon_days)
        if not due:
            return 0
        key = self._day_key("maint", "all", today)
        if not await self._should_send(key, today):
            return 0
        lines = [f"· {d['project']} / {d['name']}" for d in due[:12]]
        if len(due) > 12:
            lines.append(f"…… 另有 {len(due) - 12} 项")
        title = f"维护提醒 · {len(due)} 项待处理"
        content = "\n".join(lines)
        if await self._push(title, content):
            await self._mark_sent(key, today)
            return 1
        return 0
