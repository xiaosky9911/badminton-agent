"""主编排：周期性扫描 -> 检测新场地 -> 同时间段去重 -> 报名 -> 通知。"""
from __future__ import annotations

import random
import signal
import time
from datetime import datetime

from . import notifier, registrar
from .a1 import col_to_a1
from .config import Config
from .dedupe import group_by_dedupe, select_one
from .models import Venue
from .parser import make_now, parse_table
from .state import RegRecord, State

_stop = False


def _install_signal_handlers(logger):
    def handler(signum, frame):
        global _stop
        _stop = True
        logger.info(f"Received signal {signum}, will stop after current cycle")
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _full_range(cfg: Config) -> str:
    last_col = col_to_a1(cfg.player_last_col_index)
    end_row = cfg.data_start_row + cfg.max_data_rows - 1
    return f"'{cfg.sheet_name}'!A1:{last_col}{end_row}"


def _attempt(client, cfg: Config, state: State, logger, venue: Venue, now: datetime) -> None:
    prior = state.get_by_venue(venue.venue_id)
    # 已经settled为 failed/partial 的场地，后续例行重试保持安静(DEBUG)，避免刷屏
    verbose = prior is None or prior.status not in ("failed", "partial")
    (logger.info if verbose else logger.debug)(
        f"Attempting registration: {venue.date} {venue.start}-{venue.end} {venue.field}")

    result = registrar.register_venue(client, venue, cfg, logger, now=now, verbose=verbose)

    if cfg.dry_run:
        logger.info(f"[DRY-RUN] result={result.status} names={result.name_status}")
        return  # dry-run 不落库、不发信，方便反复演练

    now_iso = now.isoformat()
    name_status = {n: result.name_status.get(n, "") for n in cfg.register_names}

    rec = RegRecord(
        venue_id=venue.venue_id, dedupe_key=venue.dedupe_key, date=venue.date,
        start=venue.start, end=venue.end, field=venue.field, status=result.status,
        name_status=name_status,
        detected_at=prior.detected_at if prior else now_iso,
        registered_at=now_iso if result.secured_court else (prior.registered_at if prior else ""),
    )

    changed = (
        prior is None
        or prior.status != rec.status
        or prior.name_status != rec.name_status
    )
    state.upsert_registration(rec)

    if not changed:
        return
    logger.info(f"Status changed -> {result.status} at {venue.date} "
                f"{venue.start}-{venue.end} {venue.field} ({result.name_status})")
    if result.status in ("complete", "partial"):
        notifier.report_registration(cfg, result, logger)
    elif result.status == "failed" and (prior is None or prior.status != "failed"):
        # 失败只在“首次变为失败”时通知一次，避免每个周期刷屏
        notifier.report_registration(cfg, result, logger)


def run_once(client, cfg: Config, state: State, logger) -> None:
    now = make_now(cfg)
    values = client.read_range(_full_range(cfg))
    venues = parse_table(values, cfg, now)

    # 新场地检测(仅用于日志/事件；报名候选另按 dedupe 判定)
    for v in venues:
        if not state.is_known(v.venue_id):
            logger.info(f"New venue detected: {v.date} {v.start}-{v.end} {v.field}")
            logger.info(f"Available slots: {len(v.empty_slots())}")

    # 只考虑未来场地
    future = [v for v in venues if v.is_future(now)]
    groups = group_by_dedupe(future)

    for key, vs in groups.items():
        secured = state.dedupe_secured(key)
        if secured and secured.status == "complete":
            continue  # 该时间段两人都已报到，忽略其他场地
        if secured and secured.status == "partial":
            # 已占到场但缺一人：只回到同一场地补报，绝不再占用别的场地
            target = next((v for v in vs if v.venue_id == secured.venue_id), None)
            if target is not None:
                _attempt(client, cfg, state, logger, target, now)
            continue
        # 尚未占到场：在同时间段的多个场地里挑一个
        chosen = select_one(vs, needed=len(cfg.register_names))
        _attempt(client, cfg, state, logger, chosen, now)

    # 扫描结束后更新 known_venues（旧场地被删不影响，重启后不会全部误判为新）
    now_iso = now.isoformat()
    for v in venues:
        state.mark_known(v.venue_id, now_iso)


def run_forever(client, cfg: Config, state: State, logger) -> None:
    _install_signal_handlers(logger)
    logger.info(f"Agent started. poll={cfg.poll_interval_seconds}s "
                f"jitter={cfg.poll_jitter_seconds}s dry_run={cfg.dry_run} "
                f"names={cfg.register_names}")
    while not _stop:
        try:
            run_once(client, cfg, state, logger)
        except Exception as e:  # 单次异常绝不拖垮长期运行；下个周期重试
            logger.error(f"Cycle error (will retry next cycle): {e!r}")
        if _stop:
            break
        sleep = cfg.poll_interval_seconds + random.uniform(0, cfg.poll_jitter_seconds)
        time.sleep(sleep)
    logger.info("Agent stopped cleanly.")
