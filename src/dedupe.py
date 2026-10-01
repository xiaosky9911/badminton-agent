"""同一时间段(date|start|end)多个场地时，只选一个来报名。

选择规则(优先级):
  1. 优先选“空位 >= 需要人数”的场地(能一次把两人都放进去);
  2. 其次空位越多越好;
  3. 条件相同时，选表格中最先出现的(row_index 最小)。
"""
from __future__ import annotations

from typing import Dict, List

from .models import Venue


def select_one(venues: List[Venue], needed: int = 2) -> Venue:
    """在同一 dedupe_key 的多个场地里选一个最合适的。"""
    def score(v: Venue):
        empties = len(v.empty_slots())
        can_fit_all = 1 if empties >= needed else 0
        # 排序键：能放下所有人的优先(降序) -> 空位多的优先(降序) -> 行号小的优先(升序)
        return (-can_fit_all, -empties, v.row_index)

    return sorted(venues, key=score)[0]


def group_by_dedupe(venues: List[Venue]) -> Dict[str, List[Venue]]:
    groups: Dict[str, List[Venue]] = {}
    for v in venues:
        groups.setdefault(v.dedupe_key, []).append(v)
    return groups
