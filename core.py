"""纯计算逻辑，不依赖 Home Assistant，方便单独测试。"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:~|～|至|到|—|--)\s*(\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _days_in_month(year: int, month: int) -> int:
    """本月天数。不用标准库 calendar，避免和本集成的 calendar.py 撞名。"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def parse_days(payload: dict) -> tuple[set[str], set[str], dict[str, str]]:
    """把 holiday-cn 的 JSON 拆成 (放假日期, 补班日期, 节日名)。"""
    off: set[str] = set()
    makeup: set[str] = set()
    names: dict[str, str] = {}
    if not isinstance(payload, dict):
        return off, makeup, names
    for item in payload.get("days") or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("date") or "").strip()
        if len(raw) != 10:
            continue
        if item.get("isOffDay"):
            off.add(raw)
            names[raw] = str(item.get("name") or "").strip()
        else:
            makeup.add(raw)
    return off, makeup, names


def _expand(start: str, end: str) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if last < first:
        first, last = last, first
    span = (last - first).days
    if span > 400:
        raise ValueError(f"日期区间太长（{span} 天）：{start} ~ {end}")
    return [(first + timedelta(days=i)).isoformat() for i in range(span + 1)]


def parse_pasted(
    text: str, year: int | None = None
) -> tuple[set[str], set[str], dict[str, str], list[int]]:
    """解析用户在界面上粘贴的年度安排。

    支持两种写法：
      1. holiday-cn 的 JSON（以 { 或 [ 开头）
      2. 逐行文本，每行一组日期 + 一个关键字：
             2026-01-01~2026-01-03 元旦放假
             2026-01-04 补班
             2026-02-14,2026-02-28 上班
         关键字含「班」→ 补班（算上班）；含「休」或「假」→ 放假。
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("内容不能为空")

    if raw[0] in "{[":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as err:
            raise ValueError(f"JSON 解析失败：{err}") from err
        if isinstance(payload, list):
            payload = {"days": payload}
        off, makeup, names = parse_days(payload)
        if year:
            off = {d for d in off if d.startswith(str(year))}
            makeup = {d for d in makeup if d.startswith(str(year))}
            names = {k: v for k, v in names.items() if k.startswith(str(year))}
        if not off and not makeup:
            raise ValueError("JSON 里没有解析到任何日期")
        return off, makeup, names, []

    off: set[str] = set()
    makeup: set[str] = set()
    names: dict[str, str] = {}
    assumed: list[int] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        dates: list[str] = []
        for match in RANGE_RE.finditer(stripped):
            dates.extend(_expand(match.group(1), match.group(2)))
        dates.extend(DATE_RE.findall(RANGE_RE.sub(" ", stripped)))
        if not dates:
            continue

        low = stripped.lower()
        if "班" in stripped or "work" in low:
            target = makeup
            is_off = False
        else:
            # 含「休/假/off」肯定是放假；什么关键字都没有时（例如只写「春节」）
            # 也按放假处理，但登记下来提醒用户核对。
            if not ("休" in stripped or "假" in stripped or "off" in low or "holiday" in low):
                assumed.append(lineno)
            target = off
            is_off = True

        for one in dates:
            try:
                date.fromisoformat(one)
            except ValueError as err:
                raise ValueError(f"第 {lineno} 行有不存在的日期：{one}") from err
            if year and not one.startswith(str(year)):
                continue
            target.add(one)
            if is_off:
                names.setdefault(one, "")

    if not off and not makeup:
        raise ValueError("没有解析到任何日期，检查一下格式")
    return off, makeup, names, assumed


def is_workday(
    day: date,
    off: set[str],
    makeup: set[str],
    custom_work: set[str],
    custom_rest: set[str],
) -> bool:
    """判定某天是不是工作日。

    优先级：自定义休息 > 自定义上班 > 法定放假 > 法定补班 > 周一至周五
    """
    key = day.isoformat()
    if key in custom_rest:
        return False
    if key in custom_work:
        return True
    if key in off:
        return False
    if key in makeup:
        return True
    return day.weekday() < 5


def month_stats(
    year: int,
    month: int,
    today: date,
    off: set[str],
    makeup: set[str],
    custom_work: set[str],
    custom_rest: set[str],
) -> tuple[int, int, list[str]]:
    """返回 (本月工作日总数, 本月剩余工作日数含今天, 剩余日期列表)。"""
    days_in_month = _days_in_month(year, month)
    total = 0
    left = 0
    remaining: list[str] = []
    for d in range(1, days_in_month + 1):
        cur = date(year, month, d)
        if not is_workday(cur, off, makeup, custom_work, custom_rest):
            continue
        total += 1
        if cur >= today:
            left += 1
            remaining.append(cur.isoformat())
    return total, left, remaining


def normalize_dates(raw: str | None) -> set[str]:
    """把 "2026-11-28, 2026-11-29" 变成集合；非法项抛 ValueError。"""
    result: set[str] = set()
    if not raw:
        return result
    for chunk in str(raw).replace("，", ",").split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            parsed = date.fromisoformat(text)
        except ValueError as err:
            raise ValueError(f"日期格式不对：{text}（应为 2026-11-28 这种）") from err
        result.add(parsed.isoformat())
    return result


def prune(dates: set[str], today: date, keep_days: int) -> set[str]:
    """丢掉太旧的日期。"""
    cutoff = today - timedelta(days=keep_days)
    return {d for d in dates if d >= cutoff.isoformat()}


def _fmt_run(run: list[str], names: dict[str, str], tag: str) -> str:
    label = names.get(run[0], "")
    span = run[0] if len(run) == 1 else f"{run[0]}~{run[-1]}"
    return f"{span} {tag}" + (f" {label}" if label else "")


def _fmt_group(dates: list[str], names: dict[str, str], tag: str) -> list[str]:
    lines: list[str] = []
    run: list[str] = []
    for one in dates:
        if run and (date.fromisoformat(one) - date.fromisoformat(run[-1])).days == 1:
            run.append(one)
        else:
            if run:
                lines.append(_fmt_run(run, names, tag))
            run = [one]
    if run:
        lines.append(_fmt_run(run, names, tag))
    return lines


def format_year(off: set[str], makeup: set[str], names: dict[str, str]) -> str:
    """把放假/补班集合排版成可以再粘回来的文本。"""
    lines = _fmt_group(sorted(off), names, "休")
    lines += _fmt_group(sorted(makeup), {}, "班")
    return "\n".join(lines)


def month_progress(
    year: int,
    month: int,
    today: date,
    off: set[str],
    makeup: set[str],
    custom_work: set[str],
    custom_rest: set[str],
) -> dict:
    """本月工作日进度：已过 / 总数 / 剩余 / 百分比。"""
    total, left, _ = month_stats(year, month, today, off, makeup, custom_work, custom_rest)
    passed = 0
    for d in range(1, today.day):
        if is_workday(date(year, month, d), off, makeup, custom_work, custom_rest):
            passed += 1
    percent = round(passed * 100 / total, 1) if total else 0.0
    return {"passed": passed, "total": total, "left": left, "percent": percent}


def next_holiday(
    off: set[str],
    names: dict[str, str],
    today: date,
) -> dict | None:
    """找出今天及以后最近的一段假期。今天在假期里则返回当前这段，days = 0。"""
    upcoming = sorted(d for d in off if d >= today.isoformat())
    if not upcoming:
        return None
    first = date.fromisoformat(upcoming[0])
    start = first
    for _ in range(400):
        prev = start - timedelta(days=1)
        if prev.year != first.year or prev.isoformat() not in off:
            break
        start = prev
    end = first
    for _ in range(400):
        nxt = end + timedelta(days=1)
        if nxt.year != first.year or nxt.isoformat() not in off:
            break
        end = nxt
    name = names.get(start.isoformat()) or names.get(first.isoformat()) or "假期"
    return {
        "name": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": max((start - today).days, 0),
        "total_days": (end - start).days + 1,
    }


# ---------------- 纪念日 ----------------
ANNIV_RE = re.compile(
    r"^\s*([^:：]+?)\s*[:：]\s*(\d{2}-\d{2}|\d{4}-\d{2}-\d{2})\s*$"
)


def parse_anniversaries(text: str) -> list[dict]:
    """解析每行「名称: 日期」，与「我自定义的工作日」同一套纯文本风格。

    日期写 MM-DD 表示每年重复（生日 / 周年），写 YYYY-MM-DD 表示一次性。
    返回 [{"name": str, "date": str, "repeat": bool}, ...]。
    """
    items: list[dict] = []
    for lineno, line in enumerate((text or "").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ANNIV_RE.match(stripped)
        if not match:
            raise ValueError(
                f"第 {lineno} 行格式不对：{stripped}（应为「生日: 05-20」或「项目上线: 2026-12-01」）"
            )
        name = match.group(1).strip()
        raw = match.group(2)
        if len(raw) == 5:  # MM-DD，每年重复
            month, day = int(raw[:2]), int(raw[3:])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                raise ValueError(f"第 {lineno} 行日期不存在：{raw}")
            try:
                date(2000, month, day)  # 2000 是闰年，02-29 也算合法
            except ValueError as err:
                raise ValueError(f"第 {lineno} 行日期不存在：{raw}") from err
            items.append({"name": name, "date": raw, "repeat": True})
        else:  # YYYY-MM-DD，一次性
            try:
                parsed = date.fromisoformat(raw)
            except ValueError as err:
                raise ValueError(f"第 {lineno} 行日期不存在：{raw}") from err
            items.append({"name": name, "date": parsed.isoformat(), "repeat": False})
    return items


def format_anniversaries(items: list[dict]) -> str:
    """把纪念日列表排版成可再粘回来的文本。"""
    return "\n".join(f"{it['name']}: {it['date']}" for it in items or [])


def _anniv_on(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None  # 02-29 落在非闰年，该年跳过


def next_anniversary(items: list[dict], today: date) -> dict | None:
    """找今天及以后最近的纪念日。

    每年重复的按今年算，已过就顺延到明年；一次性的过期后不再出现。
    返回 {name, date, days, repeat}，没有则 None。
    """
    best: dict | None = None
    for it in items or []:
        name = str(it.get("name") or "")
        raw = str(it.get("date") or "")
        repeat = bool(it.get("repeat"))
        if repeat and len(raw) == 5:
            month, day = int(raw[:2]), int(raw[3:])
            candidate = _anniv_on(today.year, month, day)
            if candidate is None:
                continue
            if candidate < today:
                candidate = _anniv_on(today.year + 1, month, day)
                if candidate is None:
                    continue
        else:
            try:
                candidate = date.fromisoformat(raw)
            except ValueError:
                continue
            if candidate < today:
                continue
        days = (candidate - today).days
        if best is None or days < best["days"]:
            best = {
                "name": name,
                "date": candidate.isoformat(),
                "days": days,
                "repeat": repeat,
            }
    return best


# ---------------- 待办 ----------------
# 每行「[x] 2026-11-13 交报告」，[x] 表示已完成，可省略（省略即未完成）
TODO_RE = re.compile(r"^\s*(?:\[( |x|X)\]\s*)?(\d{4}-\d{2}-\d{2})\s+(\S.*)$")


def parse_todos(text: str) -> list[dict]:
    """解析待办文本，返回 [{"date", "text", "done"}, ...]。"""
    items: list[dict] = []
    for lineno, line in enumerate((text or "").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = TODO_RE.match(stripped)
        if not match:
            raise ValueError(
                f"第 {lineno} 行格式不对：{stripped}（应为「2026-11-13 交报告」）"
            )
        done = (match.group(1) or " ").strip().lower() == "x"
        raw = match.group(2)
        content = match.group(3).strip()
        if not content:
            raise ValueError(f"第 {lineno} 行缺少待办内容：{stripped}")
        try:
            day = date.fromisoformat(raw)
        except ValueError as err:
            raise ValueError(f"第 {lineno} 行日期不存在：{raw}") from err
        items.append({"date": day.isoformat(), "text": content[:120], "done": done})
    return items


def format_todos(items: list[dict]) -> str:
    """把待办列表排版成可再贴回来的文本。"""
    return "\n".join(
        f"{'[x]' if it.get('done') else '[ ]'} {it.get('date')} {it.get('text')}"
        for it in items or []
    )
