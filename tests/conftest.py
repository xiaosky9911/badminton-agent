"""测试夹具：内存版 FakeSheetsClient，模拟 Google Sheets 的
“单次请求原子、跨请求可交错、最后写入者获胜(LWW)”语义。

关键点：读和写是两次独立的 API 调用，之间可以被别的线程插入 ->
这正是真实并发覆盖风险的来源，用来验证 registrar 的读-校验-写-再校验。
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.a1 import a1_to_col, col_to_a1  # noqa: E402
from src.config import Config  # noqa: E402

_CELL = re.compile(r"([A-Za-z]+)(\d+)")


def _split_cell(token: str):
    m = _CELL.match(token.strip())
    return a1_to_col(m.group(1)), int(m.group(2))


def _parse_a1(a1: str):
    rng = a1.split("!", 1)[1] if "!" in a1 else a1
    rng = rng.replace("'", "")
    if ":" in rng:
        start, end = rng.split(":", 1)
    else:
        start = end = rng
    sc, sr = _split_cell(start)
    ec, er = _split_cell(end)
    return sc, sr, ec, er


class FakeSheetsClient:
    def __init__(self, write_latency: float = 0.0, read_latency: float = 0.0):
        self.grid = {}  # (row, col) -> str
        self._lock = threading.Lock()
        self.write_latency = write_latency
        self.read_latency = read_latency
        # 记录“意图覆盖”事件：写入落在一个当时非空且非本次写入值的格子
        self.intent_overwrites = []  # list of (row, col, old, new)

    # ---- 测试辅助 ----
    def set_cell(self, row: int, col_letter: str, value: str):
        self.grid[(row, a1_to_col(col_letter))] = value

    def get_cell(self, row: int, col_letter: str) -> str:
        return self.grid.get((row, a1_to_col(col_letter)), "")

    def row_values(self, row: int, first_col: str, count: int):
        c0 = a1_to_col(first_col)
        return [self.grid.get((row, c0 + i), "") for i in range(count)]

    def _read_rect(self, a1: str):
        sc, sr, ec, er = _parse_a1(a1)
        out = []
        for r in range(sr, er + 1):
            row = [str(self.grid.get((r, c), "")) for c in range(sc, ec + 1)]
            out.append(row)
        return out

    # ---- 与 GoogleSheetsClient 相同的接口 ----
    def read_range(self, a1: str):
        if self.read_latency:
            time.sleep(self.read_latency)
        with self._lock:
            return self._read_rect(a1)

    def batch_get(self, ranges):
        if self.read_latency:
            time.sleep(self.read_latency)
        with self._lock:
            return [self._read_rect(a1) for a1 in ranges]

    def batch_update(self, updates):
        if self.write_latency:
            time.sleep(self.write_latency)  # 放大盲区窗口，逼出竞态
        with self._lock:
            for u in updates:
                sc, sr, _, _ = _parse_a1(u["range"])
                new = str(u["values"][0][0])
                old = str(self.grid.get((sr, sc), ""))
                if old != "" and old != new:
                    self.intent_overwrites.append((sr, sc, old, new))
                self.grid[(sr, sc)] = new  # LWW


def make_config(**overrides) -> Config:
    cfg = Config(
        spreadsheet_id="test",
        sheet_name="Sheet1",
        player_first_col="E",
        player_count=24,
        header_row=2,
        data_start_row=3,
        max_data_rows=50,
        register_names=["alice", "bob"],
        timezone="Europe/Brussels",
        default_year=None,
        max_retries=6,
        write_retry_jitter_ms_min=1,
        write_retry_jitter_ms_max=5,
        dry_run=False,
        email_enabled=False,
    )
    cfg.player_first_col_index = a1_to_col(cfg.player_first_col)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


@pytest.fixture
def cfg():
    return make_config()


@pytest.fixture
def client():
    return FakeSheetsClient()


@pytest.fixture
def logger():
    lg = logging.getLogger("test")
    lg.setLevel(logging.CRITICAL)  # 测试时静默
    return lg


def seed_venue_row(client: FakeSheetsClient, row: int, day: str, date: str, tm: str, field: str,
                   players=None):
    """在指定行写入一个场地(A..D + 若干 player)。players 为已占用名字列表。"""
    client.grid[(row, a1_to_col("A"))] = day
    client.grid[(row, a1_to_col("B"))] = date
    client.grid[(row, a1_to_col("C"))] = tm
    client.grid[(row, a1_to_col("D"))] = field
    players = players or []
    for i, name in enumerate(players):
        client.grid[(row, a1_to_col("E") + i)] = name
