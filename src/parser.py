"""把表格行解析成 Venue，并解析日期 / 时间段。

日期形如 "16/8"（d/m），时间形如 "14-16" / "15-17" / "18:30-20:30"。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from .a1 import col_to_a1
from .config import Config
from .models import Slot, Venue

# 允许多种分隔符：- – — ~ 以及 "to"
_RANGE_SEP = re.compile(r"\s*(?:-|–|—|~|to)\s*", re.IGNORECASE)


def parse_time_range(text: str):
    """'14-16' -> ('14:00','16:00'); '18:30-20:30' -> ('18:30','20:30')。失败返回 None。"""
    if not text:
        return None
    parts = _RANGE_SEP.split(text.strip())
    parts = [p for p in parts if p != ""]
    if len(parts) != 2:
        return None
    try:
        start = _normalize_hm(parts[0])
        end = _normalize_hm(parts[1])
    except ValueError:
        return None
    return start, end


def _normalize_hm(token: str) -> str:
    token = token.strip().replace("：", ":")
    if ":" in token:
        h, m = token.split(":", 1)
        hh, mm = int(h), int(m)
    else:
        hh, mm = int(token), 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"bad time: {token}")
    return f"{hh:02d}:{mm:02d}"


def parse_date(text: str, now: datetime, default_year: Optional[int]) -> Optional[datetime]:
    """解析 '16/8' 或 '2026-08-16' 或 '8/16'(容错)。返回当天 00:00 的 datetime(带时区)。

    只有 d/m 时的年份推断：优先 default_year；否则用 now 的年份，
    若这样得到的日期比 now 早很多(>180 天)，则认为是明年(跨年场景)。
    """
    if not text:
        return None
    text = text.strip()
    tz = now.tzinfo

    # ISO: YYYY-MM-DD
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d, tz)

    # d/m 或 m/d(默认按 d/m，符合截图 "16/8" = 8月16日)
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})$", text)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        year = default_year if default_year else now.year
        dt = _safe_date(year, mo, d, tz)
        if dt is None:
            return None
        if default_year is None and (now - dt) > timedelta(days=180):
            dt = _safe_date(year + 1, mo, d, tz)
        return dt

    return None


def _safe_date(y: int, mo: int, d: int, tz) -> Optional[datetime]:
    try:
        return datetime(y, mo, d, tzinfo=tz)
    except ValueError:
        return None


def build_venue(row: List[str], row_index: int, cfg: Config, now: datetime) -> Optional[Venue]:
    """从一行原始值构造 Venue。列布局：A=DayOfWeek B=Date C=Time D=Field, Player 从 player_first_col 起。

    无法解析日期/时间的行返回 None(异常记录，不报名)。
    """
    def cell(i: int) -> str:
        return row[i].strip() if i < len(row) and row[i] is not None else ""

    day_of_week = cell(0)
    date_raw = cell(1)
    time_raw = cell(2)
    field = cell(3)

    if not date_raw or not time_raw or not field:
        return None

    date_dt = parse_date(date_raw, now, cfg.default_year)
    tr = parse_time_range(time_raw)
    if date_dt is None or tr is None:
        return None
    start_hm, end_hm = tr

    sh, sm = map(int, start_hm.split(":"))
    eh, em = map(int, end_hm.split(":"))
    start_dt = date_dt.replace(hour=sh, minute=sm)
    end_dt = date_dt.replace(hour=eh, minute=em)
    if end_dt <= start_dt:  # 跨天(理论上不会，容错)
        end_dt += timedelta(days=1)

    date_iso = date_dt.strftime("%Y-%m-%d")
    dedupe_key = f"{date_iso}|{start_hm}|{end_hm}"
    venue_id = f"{dedupe_key}|{field}"

    slots: List[Slot] = []
    for p in range(cfg.player_count):
        col_index = cfg.player_first_col_index + p
        col_letter = col_to_a1(col_index)
        raw = row[col_index - 1] if (col_index - 1) < len(row) and row[col_index - 1] is not None else ""
        a1 = f"'{cfg.sheet_name}'!{col_letter}{row_index}"
        slots.append(Slot(
            player_index=p + 1,
            col_index=col_index,
            a1=a1,
            value=str(raw).strip(),
        ))

    return Venue(
        venue_id=venue_id,
        dedupe_key=dedupe_key,
        date=date_iso,
        start=start_hm,
        end=end_hm,
        field=field,
        day_of_week=day_of_week,
        row_index=row_index,
        slots=slots,
        start_dt=start_dt,
        end_dt=end_dt,
    )


def parse_table(values: List[List[str]], cfg: Config, now: datetime) -> List[Venue]:
    """values 为整个读取范围(从表格第 1 行开始)。返回所有可解析的 Venue。"""
    venues: List[Venue] = []
    for row_index in range(cfg.data_start_row, cfg.data_start_row + cfg.max_data_rows):
        idx = row_index - 1  # values 是 0-based，从表格第 1 行开始
        if idx >= len(values):
            break
        row = values[idx]
        if not any(c and str(c).strip() for c in row):
            continue  # 整行空 -> 跳过(不 break，中间可能有空行)
        v = build_venue(row, row_index, cfg, now)
        if v is not None:
            venues.append(v)
    return venues


def make_now(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))
