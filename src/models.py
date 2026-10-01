"""核心数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Slot:
    """一个报名位置。"""
    player_index: int   # 1-based，第几个位置(Player 1..24)
    col_index: int      # 表格列号(1-based)
    a1: str             # 完整 A1 引用，例如 'Sheet1'!E3
    value: str          # 当前内容(去空格后)


@dataclass
class Venue:
    """一个场地记录(表格中的一行)。"""
    venue_id: str        # 唯一标识: date|start|end|field
    dedupe_key: str      # 去重键: date|start|end
    date: str            # ISO, 例如 2026-08-16
    start: str           # HH:MM
    end: str             # HH:MM
    field: str           # 场地名, 例如 TSH1
    day_of_week: str
    row_index: int       # 1-based 表格行号
    slots: List[Slot]
    start_dt: datetime
    end_dt: datetime

    def empty_slots(self) -> List[Slot]:
        return [s for s in self.slots if s.value == ""]

    def name_present(self, name: str) -> bool:
        low = name.strip().lower()
        return any(s.value.strip().lower() == low for s in self.slots)

    def is_future(self, now: datetime) -> bool:
        """只报名未来场地：开始时间晚于当前时间。"""
        return self.start_dt > now


@dataclass
class RegistrationResult:
    venue: Venue
    # complete=两人都在, partial=只报到一人(已占到场), no_slot=没空位, failed=失败, already=之前已完成
    status: str
    name_status: Dict[str, str] = field(default_factory=dict)  # name -> registered|already|no_slot|failed
    assigned: Dict[str, int] = field(default_factory=dict)     # name -> player_index
    attempts: int = 0
    message: str = ""

    @property
    def secured_court(self) -> bool:
        """是否至少占到了这个场地(用于同时间段去重)。"""
        return self.status in ("complete", "partial", "already")
