"""我的工作日 —— 协调器：拉取/解析放假数据 + 计算 + 持久化。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import core
from .const import (
    CONF_URL,
    DEFAULT_URL,
    DOMAIN,
    KEEP_DAYS,
    REFRESH_DAYS,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class CnWorkdayCoordinator(DataUpdateCoordinator[dict]):
    """维护放假数据与自定义日期，并算出今天 / 本月状态。

    数据优先级：
        1. 用户在界面上粘贴的年度安排（存在 .storage 里）
        2. 从 holiday-cn 网络拉取的年度 JSON
        3. 只有周末规则（工作日/休息日按星期几）
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")
        self._off: set[str] = set()
        self._makeup: set[str] = set()
        self._names: dict[str, str] = {}
        self._loaded_year: int | None = None
        self._loaded_from = "none"
        self._custom_loaded = False
        self._off_next: set[str] = set()
        self._makeup_next: set[str] = set()
        self._names_next: dict[str, str] = {}
        self._next_year: int | None = None
        self._next_try: float | None = None
        self._last_fetch: datetime | None = None
        self.custom_work: set[str] = set()
        self.custom_rest: set[str] = set()
        # 自定义纪念日：[{name, date, repeat}]，date 为 MM-DD（每年）或 YYYY-MM-DD（一次性）
        self.anniversaries: list[dict] = []
        # 待办：[{date, text, done}]，date 固定 YYYY-MM-DD
        self.todos: list[dict] = []
        # 粘贴进来的年度安排：{年份: (放假集合, 补班集合, 名称表)}
        self.year_override: dict[int, tuple[set[str], set[str], dict[str, str]]] = {}

    # ---------------- 持久化 ----------------
    @property
    def url_template(self) -> str:
        return self.entry.options.get(CONF_URL) or DEFAULT_URL

    async def async_load_custom(self) -> None:
        if self._custom_loaded:
            return
        data = await self._store.async_load() or {}
        today = dt_util.now().date()
        self.custom_work = core.prune(set(data.get("work") or []), today, KEEP_DAYS)
        self.custom_rest = core.prune(set(data.get("rest") or []), today, KEEP_DAYS)
        self.anniversaries = [
            dict(it) for it in (data.get("anniversaries") or []) if isinstance(it, dict)
        ]
        self.todos = [
            dict(it) for it in (data.get("todos") or []) if isinstance(it, dict)
        ]
        for year, blob in (data.get("year_data") or {}).items():
            try:
                year_int = int(year)
            except (TypeError, ValueError):
                continue
            self.year_override[year_int] = (
                set(blob.get("off") or []),
                set(blob.get("makeup") or []),
                dict(blob.get("names") or {}),
            )
        self._custom_loaded = True

    async def async_save_state(self) -> None:
        today = dt_util.now().date()
        self.custom_work = core.prune(self.custom_work, today, KEEP_DAYS)
        self.custom_rest = core.prune(self.custom_rest, today, KEEP_DAYS)
        await self._store.async_save(
            {
                "work": sorted(self.custom_work),
                "rest": sorted(self.custom_rest),
                "anniversaries": self.anniversaries,
                "todos": self.todos,
                "year_data": {
                    str(year): {
                        "off": sorted(blob[0]),
                        "makeup": sorted(blob[1]),
                        "names": blob[2],
                    }
                    for year, blob in self.year_override.items()
                },
            }
        )

    # ---------------- 网络数据 ----------------
    async def _async_fetch(self, year: int) -> tuple[set[str], set[str], dict[str, str]]:
        url = self.url_template.format(year=year)
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    raise UpdateFailed(f"{year} 年的放假安排还没发布（HTTP 404）")
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise UpdateFailed("下载放假数据超时") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"下载放假数据失败：{err}") from err
        except ValueError as err:
            raise UpdateFailed("放假数据不是合法 JSON") from err

        off, makeup, names = core.parse_days(payload)
        if not off:
            raise UpdateFailed("放假数据为空或格式不对")
        _LOGGER.debug("%s 年数据：放假 %s 天，补班 %s 天", year, len(off), len(makeup))
        return off, makeup, names

    def _needs_refresh(self) -> bool:
        if self._last_fetch is None:
            return True
        return dt_util.utcnow() - self._last_fetch > timedelta(days=REFRESH_DAYS)

    async def _async_refresh_year(self, year: int) -> None:
        """复查当年数据：上游年中若修订过，这里能跟上。"""
        try:
            off, makeup, names = await self._async_fetch(year)
        except UpdateFailed as err:
            _LOGGER.debug("%s 年数据复查失败：%s", year, err)
            return
        changed = off != self._off or makeup != self._makeup
        self._off, self._makeup, self._names = off, makeup, names
        self._last_fetch = dt_util.utcnow()
        if changed:
            _LOGGER.warning(
                "放假数据有变化，已更新：放假 %s 天，补班 %s 天", len(off), len(makeup)
            )
        else:
            _LOGGER.debug("%s 年数据复查完成，无变化", year)

    async def async_force_refresh(self) -> tuple[int, int, bool]:
        """服务调用：丢掉手贴数据，立刻从网络重新拉当年数据。"""
        year = dt_util.now().year
        off, makeup, names = await self._async_fetch(year)
        cleared = self.year_override.pop(year, None) is not None
        self._off, self._makeup, self._names = off, makeup, names
        self._loaded_year = year
        self._loaded_from = "network"
        self._last_fetch = dt_util.utcnow()
        await self.async_save_state()
        await self.async_refresh()
        return len(off), len(makeup), cleared

    async def _async_ensure_next_year(self, year: int) -> None:
        """顺手把明年的数据也拿来，用于跨年的“距下个节假日”。"""
        if self._next_year == year:
            return
        if year in self.year_override:
            off, makeup, names = self.year_override[year]
            self._off_next = off
            self._makeup_next = makeup
            self._names_next = names
            self._next_year = year
            return
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._next_try is not None and now - self._next_try < 6 * 3600:
            return
        self._next_try = now
        try:
            off, makeup, names = await self._async_fetch(year)
        except UpdateFailed as err:
            _LOGGER.debug("%s 年数据暂时拿不到：%s", year, err)
            return
        self._off_next = off
        self._makeup_next = makeup
        self._names_next = names
        self._next_year = year
        _LOGGER.debug("%s 年数据已预取：放假 %s 天，补班 %s 天", year, len(off), len(makeup))

    # ---------------- 主循环 ----------------
    async def _async_update_data(self) -> dict:
        await self.async_load_custom()
        today = dt_util.now().date()

        if today.year in self.year_override:
            off, makeup, names = self.year_override[today.year]
            self._off, self._makeup, self._names = off, makeup, names
            self._loaded_year = today.year
            self._loaded_from = "manual"
        elif self._loaded_year != today.year:
            try:
                off, makeup, names = await self._async_fetch(today.year)
                self._off, self._makeup, self._names = off, makeup, names
                self._loaded_year = today.year
                self._loaded_from = "network"
                self._last_fetch = dt_util.utcnow()
            except UpdateFailed:
                if self._loaded_year is None:
                    raise
                _LOGGER.warning("今年放假数据更新失败，先沿用 %s 年数据", self._loaded_year)
        elif self._loaded_from == "network" and self._needs_refresh():
            await self._async_refresh_year(today.year)

        await self._async_ensure_next_year(today.year + 1)
        return self.snapshot(today)

    # ---------------- 外部写入 ----------------
    async def async_set_year_data(self, year: int, text: str) -> tuple[int, int, list[int]]:
        """把界面上粘贴的年度安排存下来并立即生效。"""
        off, makeup, names, assumed = core.parse_pasted(text, year)
        self.year_override[year] = (off, makeup, names)
        await self.async_save_state()
        await self.async_refresh()
        return len(off), len(makeup), assumed

    async def async_set_custom(self, work: set[str], rest: set[str]) -> None:
        self.custom_work = set(work)
        self.custom_rest = set(rest)
        await self.async_save_state()
        await self.async_refresh()

    async def async_set_anniversaries(self, items: list[dict]) -> None:
        self.anniversaries = [dict(it) for it in items]
        await self.async_save_state()
        await self.async_refresh()

    async def async_set_todos(self, items: list[dict]) -> None:
        self.todos = [dict(it) for it in items]
        await self.async_save_state()
        await self.async_refresh()

    # ---------------- 对外查询 ----------------
    def _sets_for(self, year: int) -> tuple[set[str], set[str]]:
        """某一年该用哪套放假/补班数据（含次年与手贴数据）。"""
        if year == self._loaded_year:
            return self._off, self._makeup
        if year == self._next_year:
            return self._off_next, self._makeup_next
        if year in self.year_override:
            off, makeup, _names = self.year_override[year]
            return off, makeup
        return set(), set()

    def is_workday(self, day: date) -> bool:
        off, makeup = self._sets_for(day.year)
        return core.is_workday(day, off, makeup, self.custom_work, self.custom_rest)

    def is_makeup(self, day: date) -> bool:
        _off, makeup = self._sets_for(day.year)
        return day.isoformat() in makeup

    # ---------------- 快照 ----------------
    def snapshot(self, today: date) -> dict:
        total, left, remaining = core.month_stats(
            today.year,
            today.month,
            today,
            self._off,
            self._makeup,
            self.custom_work,
            self.custom_rest,
        )
        tomorrow = today + timedelta(days=1)
        return {
            "today": today.isoformat(),
            "today_work": core.is_workday(
                today, self._off, self._makeup, self.custom_work, self.custom_rest
            ),
            "title": self._names.get(today.isoformat(), ""),
            "month": f"{today.year}-{today.month:02d}",
            "total": total,
            "left": left,
            "remaining": remaining,
            "custom_work": sorted(self.custom_work),
            "custom_rest": sorted(self.custom_rest),
            "tomorrow": tomorrow.isoformat(),
            "tomorrow_work": self.is_workday(tomorrow),
            "next_holiday": core.next_holiday(
                self._off | self._off_next, {**self._names, **self._names_next}, today
            ),
            "progress": core.month_progress(
                today.year,
                today.month,
                today,
                self._off,
                self._makeup,
                self.custom_work,
                self.custom_rest,
            ),
            "data_year": self._loaded_year,
            "data_source": self._loaded_from,
            "data_updated": self._last_fetch.isoformat() if self._last_fetch else None,
            "year_text": core.format_year(self._off, self._makeup, self._names),
            "next_year_text": core.format_year(
                self._off_next, self._makeup_next, self._names_next
            ),
            "anniversaries": self.anniversaries,
            "anniversaries_text": core.format_anniversaries(self.anniversaries),
            "todos": self.todos,
            "todos_text": core.format_todos(self.todos),
            "next_anniversary": core.next_anniversary(self.anniversaries, today),
        }
