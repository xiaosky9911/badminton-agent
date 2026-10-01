"""并发安全的报名核心：读 -> 校验 -> 写 -> 再校验，带随机位置与抖动重试。

不变量(本模块严格保证):
  * 只会向“刚刚读到为空”的单元格写入；
  * 绝不向已经有名字的单元格写入(不覆盖别人);
  * 写入后立即回读，确认自己的名字真实存在，否则判为冲突并换位重试;
  * 重复运行幂等：名字已在表内则不再写。

局限(诚实说明): Sheets API 无单元格级 CAS。若别人的写入恰好落在
“本 Agent 最后一次校验读”和“写入”之间的极短盲区里，理论上仍可能互相覆盖。
我们用“随机挑空位 + 写前再读目标格 + 写后回读重试”把这个窗口压到最小，
并在与其他同类协作 Agent 之间做到最终一致(见 tests/test_registrar.py)。
"""
from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Dict, List, Optional

from .a1 import col_to_a1
from .config import Config
from .models import RegistrationResult, Slot, Venue


def _read_slots(client, venue: Venue, cfg: Config) -> List[Slot]:
    """回读该场地一行的全部报名位置，返回最新 Slot 列表。"""
    first = col_to_a1(cfg.player_first_col_index)
    last = col_to_a1(cfg.player_last_col_index)
    a1 = f"'{cfg.sheet_name}'!{first}{venue.row_index}:{last}{venue.row_index}"
    rows = client.read_range(a1)
    row = rows[0] if rows else []
    slots: List[Slot] = []
    for p in range(cfg.player_count):
        col_index = cfg.player_first_col_index + p
        raw = row[p] if p < len(row) and row[p] is not None else ""
        slots.append(Slot(
            player_index=p + 1,
            col_index=col_index,
            a1=f"'{cfg.sheet_name}'!{col_to_a1(col_index)}{venue.row_index}",
            value=str(raw).strip(),
        ))
    return slots


def _names_present(slots: List[Slot]) -> Dict[str, int]:
    """已存在的名字(小写) -> player_index。"""
    present: Dict[str, int] = {}
    for s in slots:
        v = s.value.strip().lower()
        if v and v not in present:
            present[v] = s.player_index
    return present


def _jitter_sleep(cfg: Config) -> None:
    lo = cfg.write_retry_jitter_ms_min / 1000.0
    hi = max(cfg.write_retry_jitter_ms_max / 1000.0, lo)
    time.sleep(random.uniform(lo, hi))


def _choose_slots(empty: List[Slot], count: int) -> List[Slot]:
    """挑要写入的空位。

    两个人时：优先挑一对"相邻"的空位，让两人挨着写(第一个人在前、第二个人紧跟)；
    若有多对相邻空位，则在其中随机选一对(保留一点防撞车的随机性)。
    实在没有相邻空位时，退回随机挑不相邻的空位。
    """
    # empty 已按 player_index 升序排列
    if count == 2:
        by_idx = {s.player_index: s for s in empty}
        pairs = [(s, by_idx[s.player_index + 1]) for s in empty if s.player_index + 1 in by_idx]
        if pairs:
            lo, hi = random.choice(pairs)
            return [lo, hi]  # 升序：第一个人在前，第二个人紧邻其后
    return random.sample(empty, count)


def register_venue(
    client,
    venue: Venue,
    cfg: Config,
    logger,
    names: Optional[List[str]] = None,
    now: Optional[datetime] = None,
    verbose: bool = True,
) -> RegistrationResult:
    names = names or cfg.register_names
    now = now or datetime.now()
    lower_names = [n.strip().lower() for n in names]
    # verbose=False 时，例行"还是满的/已存在"这类噪声降到 DEBUG，不刷屏；
    # 但真正的报名成功、冲突、校验事件始终保持 INFO。
    quiet = logger.debug if not verbose else logger.info

    attempts = 0
    for attempt in range(1, cfg.max_retries + 1):
        attempts = attempt

        # 1) 新鲜读取整行的 24 个位置
        slots = _read_slots(client, venue, cfg)
        present = _names_present(slots)

        # 幂等：已经在表里的名字不再写
        still_needed = [n for n, low in zip(names, lower_names) if low not in present]
        if not still_needed:
            quiet(f"Idempotent: all target names already present at "
                  f"{venue.date} {venue.start}-{venue.end} {venue.field}")
            return _build_result(venue, names, present, {}, attempts,
                                 msg="already registered")

        empty = [s for s in slots if s.value == ""]
        quiet(f"Available slots: {len(empty)} at "
              f"{venue.date} {venue.start}-{venue.end} {venue.field}")

        if not empty:
            quiet(f"No free slot for {venue.field}; needed={still_needed}")
            return _build_result(venue, names, present, {}, attempts, msg="no free slot")

        # 2/3) 位置不足时按 REGISTER_NAMES 顺序截断(靠前的优先)，优先挑相邻空位让大家挨着写
        to_place = still_needed[: len(empty)]
        chosen = _choose_slots(empty, len(to_place))

        # 4) 写前再次读取“恰好这些目标格”，确认仍为空
        target_a1 = [s.a1 for s in chosen]
        fresh = client.batch_get(target_a1)
        conflict = False
        for vals in fresh:
            cell = ""
            if vals and vals[0]:
                cell = str(vals[0][0]).strip()
            if cell != "":
                conflict = True
                break
        if conflict:
            logger.info("Slot conflict detected, refreshing sheet")
            _jitter_sleep(cfg)
            continue

        # 5) 一次批量写入(尽量缩小盲区窗口)
        if cfg.dry_run:
            for name, s in zip(to_place, chosen):
                logger.info(f"[DRY-RUN] would register {name} -> slot {s.player_index} ({s.a1})")
            assigned = {name: s.player_index for name, s in zip(to_place, chosen)}
            # dry-run 直接返回“假设成功”的结果，但不写状态为已报
            present_after = dict(present)
            for name, s in zip(to_place, chosen):
                present_after[name.lower()] = s.player_index
            return _build_result(venue, names, present_after, assigned, attempts,
                                 msg="dry-run (no write)")

        updates = [{"range": s.a1, "values": [[name]]} for name, s in zip(to_place, chosen)]
        client.batch_update(updates)

        # 6) 写后立即回读校验
        slots2 = _read_slots(client, venue, cfg)
        present2 = _names_present(slots2)

        verified = {}
        lost = []
        for name, s in zip(to_place, chosen):
            low = name.lower()
            idx = present2.get(low)
            if idx is not None:
                verified[name] = idx
            else:
                lost.append(name)

        for name, idx in verified.items():
            logger.info(f"Registered {name} -> slot {idx}")

        if not lost:
            logger.info("Registration verified successfully")
            return _build_result(venue, names, present2, verified, attempts, msg="verified")

        # 7/8) 有人在盲区里把我们覆盖了 -> 换位重试
        logger.info(f"Verify failed for {lost} (overwritten in race); refreshing and retrying")
        _jitter_sleep(cfg)

    logger.error(f"Registration failed after {cfg.max_retries} attempts for "
                 f"{venue.date} {venue.start}-{venue.end} {venue.field}")
    # 最后再读一次给出真实结论
    final = _names_present(_read_slots(client, venue, cfg))
    return _build_result(venue, names, final, {}, attempts, msg="failed after retries")


def _build_result(venue, names, present_lower, assigned, attempts, msg) -> RegistrationResult:
    """根据最终“谁在表里”计算每个人的状态和总状态。"""
    name_status: Dict[str, str] = {}
    got = 0
    for name in names:
        low = name.lower()
        if low in present_lower:
            name_status[name] = "registered" if name in assigned else "already"
            got += 1
        else:
            name_status[name] = "no_slot"

    if got == len(names):
        status = "complete"
    elif got >= 1:
        status = "partial"
    else:
        status = "failed"

    return RegistrationResult(
        venue=venue, status=status, name_status=name_status,
        assigned=assigned, attempts=attempts, message=msg,
    )
