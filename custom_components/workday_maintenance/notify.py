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
from . import push_rule as pr

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
    def _day_key(prefix: str, target: str, today: dt.date, rule: dict | None = None) -> str:
        # 带规则指纹：用户改了提醒规则后，同一天会按新规则重新推送。
        fp = pr.push_fingerprint(rule) if rule else "none"
        return f"{prefix}:{target}:{fp}:{today.isoformat()}"

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

    async def test_push(self, url: str, token: str) -> dict:
        """用临时传入的配置发测试消息，返回可展示给用户的结果。"""
        if not url or not token:
            return {"ok": False, "error": "请先填服务地址和接口 Token"}
        endpoint = url.rstrip("/") + "/api/push"
        payload = {"title": "workday_maintenance 测试", "content": "如果你收到这条消息，说明魔法推送配置正确。",
                   "type": "text"}
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        try:
            session = async_get_clientsession(self.hass)
            async with session.post(endpoint, json=payload, headers=headers,
                                    timeout=10) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return {"ok": True, "detail": f"推送成功（HTTP {resp.status}）"}
                _LOGGER.warning("测试推送失败 %s: %s", resp.status, text[:200])
                return {"ok": False, "error": f"HTTP {resp.status}：{text[:120]}"}
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("测试推送异常：%s", err)
            return {"ok": False, "error": f"连接失败：{type(err).__name__} {str(err)[:120]}"}

    # ── 纪念日：提前 N 天 ────────────────────────────────────
    async def check_anniversaries(self, now: dt.datetime | None = None) -> int:
        """逐条纪念日按各自规则判断是否推送（规则可覆盖时间/提前天数）。"""
        settings = await self.store.async_load()
        cfg = settings.get("anniversary") or {}
        if not cfg.get("enabled"):
            return 0
        now = now or dt_util.now()
        today = now.date()
        hhmm = f"{now.hour:02d}:{now.minute:02d}"
        raw = await self.coordinator.store.async_load()
        anniversaries = (raw.get("workday") or {}).get("anniversaries") or []
        sent = 0
        for a in anniversaries:
            rule = pr.resolve_push(cfg, a)
            if not rule or rule.get("time") != hhmm:
                continue
            advances = [int(x) for x in (rule.get("advance_days") or [])]
            if not advances:
                continue
            day = wd.anniversary_next(a, today)
            if not day:
                continue
            days = (day - today).days
            if days not in advances:
                continue
            key = self._day_key("ann", str(a.get("id") or a.get("name")), today, rule)
            if not await self._should_send(key, today):
                continue
            title = "纪念日提醒"
            content = f"{a.get('name','')} · {days} 天后（{day.isoformat()}）"
            if await self._push(title, content):
                await self._mark_sent(key, today)
                sent += 1
        return sent

    # ── 维护项：按到期状态汇总 ───────────────────────────────
    async def check_maintenance(self, now: dt.datetime | None = None) -> int:
        """按小项各自的规则逐条提醒（时间/星期可覆盖全局）。"""
        settings = await self.store.async_load()
        cfg = settings.get("maintenance") or {}
        if not cfg.get("enabled"):
            return 0
        now = now or dt_util.now()
        today = now.date()
        hhmm = f"{now.hour:02d}:{now.minute:02d}"
        raw = await self.coordinator.store.async_load()
        projects = (raw.get("maintenance") or {}).get("projects") or []
        states = []
        for project in projects:
            summary = mnt.project_summary(project, today, self.coordinator.soon_days)
            for st in summary["items"]:
                if st["status"] in (mnt.STATUS_DUE, mnt.STATUS_SOON):
                    states.append((project, st))
        sent = 0
        for project, st in states:
            # 找到原始 item 以读取 push 字段
            item = next((i for i in project.get("items", []) if i.get("id") == st["id"]), None)
            rule = pr.resolve_push(cfg, item or {})
            if not rule or rule.get("time") != hhmm:
                continue
            wd = rule.get("weekday")
            if wd is not None and not isinstance(wd, bool) and now.weekday() != int(wd):
                continue
            title = "维护提醒"
            content = f"{project.get('name')} / {st['name']} · {st['status']}"
            if st.get("remaining_days") is not None:
                rd = st["remaining_days"]
                content += f" · {'已超期 ' + str(abs(rd)) + ' 天' if rd <= 0 else '还剩 ' + str(rd) + ' 天'}"
            key = self._day_key("maint", st["id"], today, rule)
            if not await self._should_send(key, today):
                continue
            if await self._push(title, content):
                await self._mark_sent(key, today)
                sent += 1
        return sent
