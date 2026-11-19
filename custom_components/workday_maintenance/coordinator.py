"""单一协调器：组装两个模块的数据，广播变更事件。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import maintenance as mnt
from . import workday as wd
from .const import (
    CONF_HOLIDAY_URL, CONF_SOON_DAYS, DEFAULT_HOLIDAY_URL, DEFAULT_SOON_DAYS,
    DOMAIN, EVENT_UPDATED, HOLIDAY_FALLBACK_URLS, SCOPE_ALL,
)
from .store import MergedStore, SettingsStore

_LOGGER = logging.getLogger(__name__)


class MergedCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = MergedStore(hass)
        self.settings_store = SettingsStore(hass)
        self._settings = None  # 启动/首次访问时加载
        self._holidays: dict[int, dict] = {}
        self._sources: dict[int, str] = {}
        self._snapshot_cache: dict[int, dict | None] = {}
        self._lock = asyncio.Lock()
        super().__init__(hass, _LOGGER, name=DOMAIN)

    async def async_warm_snapshots(self, years=None):
        """启动阶段在线程池预读节假日快照，避免事件循环内同步 IO。"""
        if years is None:
            now = dt_util.now().date()
            years = (now.year, now.year + 1)

        def load():
            out = {}
            for year in years:
                path = Path(__file__).parent / "holidays_snapshot" / f"{year}.json"
                if not path.is_file():
                    out[year] = None
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    ok, parsed = self._payload_has_data(payload, year)
                    out[year] = parsed if ok else None
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("读取 %s 年内置节假日快照失败：%s", year, err)
                    out[year] = None
            return out
        self._snapshot_cache.update(await self.hass.async_add_executor_job(load))

    @property
    def soon_days(self) -> int:
        try:
            return int(self.entry.options.get(CONF_SOON_DAYS, DEFAULT_SOON_DAYS))
        except (TypeError, ValueError):
            return DEFAULT_SOON_DAYS

    def _url(self, year: int) -> str:
        template = self.entry.options.get(CONF_HOLIDAY_URL) or DEFAULT_HOLIDAY_URL
        return str(template).replace("{year}", str(year))

    def _candidate_urls(self, year: int) -> list[str]:
        """数据源候选：用户自定义优先，其次默认 jsdelivr，再走多源兜底。"""
        custom = str(self.entry.options.get(CONF_HOLIDAY_URL) or "").strip()
        urls = [custom] if custom else []
        urls.append(DEFAULT_HOLIDAY_URL)
        urls.extend(HOLIDAY_FALLBACK_URLS)
        seen, out = set(), []
        for tpl in urls:
            if not tpl:
                continue
            url = str(tpl).replace("{year}", str(year))
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out

    @staticmethod
    def _payload_has_data(payload, year: int) -> bool:
        """确认解析结果非空，避免把"格式不对/空数据"当成成功。"""
        parsed = wd.holiday_payload_to_holidays(payload, year)
        return bool(parsed["off"] or parsed["makeup"]), parsed

    def _load_snapshot(self, year: int) -> dict | None:
        """返回启动阶段预读的节假日快照（网络全失败时的最终兜底）。"""
        return self._snapshot_cache.get(year)

    async def _ensure_holidays(self, raw: dict, now: dt.date) -> None:
        overrides = raw["workday"].get("year_override") or {}
        for year in (now.year, now.year + 1):
            text = overrides.get(str(year)) or overrides.get(year)
            if text is not None and str(text).strip():
                self._holidays[year] = wd.parse_year_text(text)
                self._sources[year] = "manual"
                continue
            if year in self._holidays:
                continue
            # 依次尝试各网络源，任一返回有效数据即用
            session = async_get_clientsession(self.hass)
            got = False
            for url in self._candidate_urls(year):
                try:
                    async with session.get(url, timeout=8) as resp:
                        resp.raise_for_status()
                        payload = await resp.json(content_type=None)
                    ok, parsed = self._payload_has_data(payload, year)
                    if ok:
                        self._holidays[year] = parsed
                        self._sources[year] = "network"
                        got = True
                        break
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("%s 年节假日源 %s 不可用：%s", year, url, err)
            if got:
                continue
            # 网络全失败 -> 内置快照
            snapshot = self._load_snapshot(year)
            if snapshot:
                self._holidays[year] = snapshot
                self._sources[year] = "snapshot"
                _LOGGER.info("%s 年放假数据使用内置快照", year)
                continue
            # 快照也没有 -> 周末规则降级
            self._holidays[year] = {"off": set(), "makeup": set(), "names": {}}
            self._sources[year] = "fallback"
            _LOGGER.warning("%s 年放假数据全部来源不可用，按周末规则降级", year)

    def _holidays_for(self, year: int) -> dict:
        base = self._holidays.get(year) or {"off": set(), "makeup": set(), "names": {}}
        nxt = self._holidays.get(year + 1) or {"off": set(), "makeup": set(), "names": {}}
        return {
            "off": base["off"] | nxt["off"],
            "makeup": base["makeup"] | nxt["makeup"],
            "names": {**nxt.get("names", {}), **base.get("names", {})},
        }

    async def _async_update_data(self) -> dict:
        raw = await self.store.async_load()
        now = dt_util.now().date()
        await self._ensure_holidays(raw, now)
        holidays = self._holidays_for(now.year)
        custom_work = set(raw["workday"].get("custom_work") or [])
        custom_rest = set(raw["workday"].get("custom_rest") or [])
        todos = wd.clean_todos(raw["workday"].get("todos") or [], now)
        anniversaries = raw["workday"].get("anniversaries") or []
        if todos != raw["workday"].get("todos"):
            raw["workday"]["todos"] = todos
            await self.store.async_save(raw)

        today_work, today_label = wd.classify(now, holidays, custom_work, custom_rest)
        tomorrow_work, _ = wd.classify(now + dt.timedelta(days=1), holidays,
                                       custom_work, custom_rest)
        stats = wd.month_stats(now.year, now.month, now, holidays,
                               custom_work, custom_rest)
        holiday = wd.next_holiday(now, holidays)
        event = wd.next_special_day(now, holidays, anniversaries)
        projects = raw["maintenance"].get("projects") or []
        summaries = [mnt.project_summary(p, now, self.soon_days) for p in projects]
        due_items = mnt.all_due_items(projects, now, self.soon_days)
        tasks_today = sum(1 for t in todos if t.get("date") == now.isoformat()
                          and not t.get("done"))
        tasks_today += sum(1 for d in due_items if d["status"] == "due")

        return {
            "today": now.isoformat(),
            "workday": {
                "today_work": today_work,
                "today_label": today_label,
                "tomorrow_work": tomorrow_work,
                "stats": stats,
                "next_holiday": holiday,
                "next_event": event,
                "custom_work": sorted(custom_work),
                "custom_rest": sorted(custom_rest),
                "todos": todos,
                "anniversaries": anniversaries,
                "holiday_source": self._sources.get(now.year, "none"),
                "year_override": raw["workday"].get("year_override") or {},
            },
            "maintenance": {
                "projects": projects,
                "summaries": summaries,
                "due_total": sum(s["due_count"] for s in summaries),
                "soon_total": sum(s["soon_count"] for s in summaries),
                "due_items": due_items,
            },
            "tasks_today": tasks_today,
            "holidays": {
                "off": sorted(holidays["off"]),
                "makeup": sorted(holidays["makeup"]),
                "names": holidays["names"],
            },
        }

    async def async_force_refresh(self) -> dict:
        self._holidays.clear()
        self._sources.clear()
        await self.async_refresh()
        return {"sources": dict(self._sources)}

    async def async_mutate(self, scope: str, fn):
        async with self._lock:
            raw = await self.store.async_load()
            result = fn(raw)
            await self.store.async_save(raw)
            await self.async_refresh()
            self.hass.bus.async_fire(EVENT_UPDATED, {"scope": scope})
            return result

    async def async_sync_due_todos(self, enabled: bool) -> int:
        if not enabled:
            return 0
        async with self._lock:
            raw = await self.store.async_load()
            now = dt_util.now().date()
            due = mnt.all_due_items(raw["maintenance"].get("projects") or [],
                                    now, self.soon_days)
            todos = [t for t in raw["workday"].get("todos", [])
                     if not str(t.get("id", "")).startswith("sync_")]
            added = 0
            for item in due:
                day = min(item["due_date"], now.isoformat()) if item["status"] == "due" \
                    else item["due_date"]
                todos.append({
                    "id": "sync_" + str(item["slug"]) + "_" + str(item["item_id"]),
                    "date": day,
                    "text": f"[维护] {item['project']} · {item['name']}",
                    "done": False,
                })
                added += 1
            raw["workday"]["todos"] = todos
            await self.store.async_save(raw)
        return added
