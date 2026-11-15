"""工作日、调休、待办、纪念日的纯逻辑，不依赖 Home Assistant。"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

from .const import KEEP_DAYS


def parse_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raw = str(value or "").strip()[:10]
    return dt.date.fromisoformat(raw)


def normalize_dates(text) -> set[str]:
    out: set[str] = set()
    for chunk in str(text or "").replace("，", ",").split(","):
        s = chunk.strip()
        if not s:
            continue
        if "~" in s:
            a, b = s.split("~", 1)
            try:
                start, end = parse_date(a), parse_date(b)
            except ValueError:
                continue
            cur = start
            while cur <= end and (end - cur).days < 400:
                out.add(cur.isoformat())
                cur += dt.timedelta(days=1)
        else:
            try:
                out.add(parse_date(s).isoformat())
            except ValueError:
                continue
    return out


def parse_year_text(text) -> dict:
    off: set[str] = set()
    makeup: set[str] = set()
    names: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        assume_off = not any(k in line for k in ("班", "休", "假"))
        work = "班" in line and not assume_off
        dates: set[str] = set()
        for token in line.split():
            if re.match(r"^\d{4}-\d{2}-\d{2}", token):
                dates |= normalize_dates(token)
        if not dates:
            continue
        label = "补班" if work else re.sub(r"^\S+\s*", "", line).strip() or "放假"
        for iso in dates:
            if work:
                makeup.add(iso)
                off.discard(iso)
            else:
                off.add(iso)
                makeup.discard(iso)
            names[iso] = label
    return {"off": off, "makeup": makeup, "names": names}


def holiday_payload_to_holidays(payload, year: int) -> dict:
    off: set[str] = set()
    makeup: set[str] = set()
    names: dict[str, str] = {}
    if not isinstance(payload, dict):
        return {"off": off, "makeup": makeup, "names": names}
    for year_key, days in payload.items():
        if not isinstance(days, dict):
            continue
        try:
            y = int(str(year_key)[:4])
        except ValueError:
            y = year
        for key, info in days.items():
            if not isinstance(info, dict) or "isOffDay" not in info:
                continue
            raw = str(key)
            if len(raw) == 5:
                raw = f"{y}-{raw}"
            try:
                iso = dt.date.fromisoformat(raw[:10]).isoformat()
            except ValueError:
                continue
            name = str(info.get("name") or "")
            if info.get("isOffDay"):
                off.add(iso)
                names[iso] = name
            else:
                makeup.add(iso)
                names[iso] = name or "补班"
    return {"off": off, "makeup": makeup, "names": names}


def classify(day: dt.date, holidays: dict, custom_work: set, custom_rest: set) -> tuple[bool, str]:
    iso = day.isoformat()
    off = holidays.get("off") or set()
    makeup = holidays.get("makeup") or set()
    names = holidays.get("names") or {}
    if iso in custom_rest:
        return False, "休"
    if iso in custom_work:
        return True, "班"
    if iso in makeup:
        return True, "补班"
    if iso in off:
        return False, names.get(iso) or "放假"
    return day.weekday() < 5, ""


def month_stats(year: int, month: int, today: dt.date, holidays: dict,
                custom_work: set, custom_rest: set) -> dict:
    cur = dt.date(year, month, 1)
    end = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    total = 0
    remaining = 0
    remaining_dates: list[str] = []
    while cur < end:
        work, _label = classify(cur, holidays, custom_work, custom_rest)
        if work:
            total += 1
            if cur >= today:
                remaining += 1
                remaining_dates.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    passed = total - remaining
    return {
        "month": f"{year:04d}-{month:02d}",
        "total": total,
        "left": remaining,
        "passed": passed,
        "percent": round(passed * 100 / total) if total else 0,
        "remaining_dates": remaining_dates,
    }


def next_holiday(today: dt.date, holidays: dict) -> dict | None:
    off = holidays.get("off") or set()
    names = holidays.get("names") or {}
    if not off:
        return None
    for delta in range(0, 400):
        day = today + dt.timedelta(days=delta)
        iso = day.isoformat()
        if iso in off and (day - dt.timedelta(days=1)).isoformat() not in off:
            start = day
            end = day
            while (end + dt.timedelta(days=1)).isoformat() in off:
                end += dt.timedelta(days=1)
            return {
                "name": names.get(iso) or "假期",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "days": (start - today).days,
                "total_days": (end - start).days + 1,
            }
    return None


def next_special_day(today, holidays, anniversaries):
    candidates = []
    off = holidays.get("off") or set()
    names = holidays.get("names") or {}
    for iso in off:
        if iso >= today.isoformat():
            try:
                candidates.append((dt.date.fromisoformat(iso), str(names.get(iso) or "假期"), "节假日"))
            except ValueError:
                continue
    for item in anniversaries or []:
        name = str(item.get("name") or "")
        raw = str(item.get("date") or "")
        if item.get("repeat"):
            md = raw[-5:]
            for year in (today.year, today.year + 1):
                try:
                    day = dt.date.fromisoformat(f"{year:04d}-{md}")
                except ValueError:
                    continue
                if day >= today:
                    candidates.append((day, name, "纪念日"))
                    break
        else:
            try:
                day = dt.date.fromisoformat(raw)
            except ValueError:
                continue
            if day >= today:
                candidates.append((day, name, "纪念日"))
    if not candidates:
        return None
    day, name, kind = min(candidates, key=lambda x: x[0])
    return {"name": name, "date": day.isoformat(), "days": (day - today).days, "kind": kind}


def _uid(prefix: str, *parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return prefix + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def parse_todos(text) -> list[dict]:
    out: list[dict] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        done = False
        if line.startswith("[x]") or line.startswith("[X]"):
            done = True
            line = line[3:].strip()
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$", line)
        if not m:
            continue
        date, body = m.group(1), m.group(2).strip()
        out.append({"id": _uid("t", date, body), "date": date, "text": body, "done": done})
    return out


def todos_text(todos) -> str:
    lines = []
    for t in todos or []:
        lines.append(f"{'[x] ' if t.get('done') else ''}{t.get('date','')} {t.get('text','')}")
    return "\n".join(lines)


def parse_anniversaries(text) -> list[dict]:
    out: list[dict] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        name, date = line.split(":", 1)
        name, date = name.strip(), date.strip()
        if not name:
            continue
        repeat = len(date) == 5
        try:
            if repeat:
                dt.date(2000, int(date[:2]), int(date[3:]))
            else:
                dt.date.fromisoformat(date[:10])
        except ValueError:
            continue
        out.append({"id": _uid("a", name, date), "name": name,
                    "date": date, "repeat": repeat})
    return out


def anniversaries_text(items) -> str:
    return "\n".join(f"{i.get('name','')}: {i.get('date','')}" for i in items or [])


def clean_todos(todos, today: dt.date) -> list[dict]:
    limit = today - dt.timedelta(days=KEEP_DAYS)
    out = []
    for t in todos or []:
        if t.get("done"):
            try:
                if parse_date(t.get("date")) < limit:
                    continue
            except ValueError:
                pass
        out.append(t)
    return out
