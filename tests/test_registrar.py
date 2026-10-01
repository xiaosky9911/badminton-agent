"""registrar 的正确性与并发安全测试。

最重要的三个断言目标(与需求优先级一致):
  1. 不覆盖别人  -> test_never_overwrites_* / test_conflict_then_retry_no_overwrite
  2. 不重复报名  -> test_idempotent
  3. 尽量两人都报 + 并发下最终一致 -> test_concurrent_cooperating_agents
"""
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from src.parser import build_venue
from src.registrar import register_venue
from conftest import FakeSheetsClient, make_config, seed_venue_row, _parse_a1

TZ = ZoneInfo("Europe/Brussels")
NOW = datetime(2026, 8, 15, 10, 0, tzinfo=TZ)


def make_venue(client, cfg, row_index=5, occupied=None, field="TSH1"):
    seed_venue_row(client, row_index, "Tuesday", "18/8", "18-20", field, occupied or [])
    row = client.read_range(f"'Sheet1'!A{row_index}:AB{row_index}")[0]
    return build_venue(row, row_index, cfg, NOW)


def row_names(client, row_index=5, cfg=None):
    cfg = cfg or make_config()
    vals = client.row_values(row_index, cfg.player_first_col, cfg.player_count)
    return [v for v in vals if v.strip()]


# ---------- 基本功能 ----------

def test_basic_registration(cfg, client, logger):
    v = make_venue(client, cfg)
    res = register_venue(client, v, cfg, logger, now=NOW)
    assert res.status == "complete"
    names = row_names(client, cfg=cfg)
    assert sorted(names) == ["alice", "bob"]
    assert client.intent_overwrites == []


def test_only_one_slot_left_prioritises_alice(cfg, client, logger):
    v = make_venue(client, cfg, occupied=["x"] * 23)  # 只剩 1 个空位
    res = register_venue(client, v, cfg, logger, now=NOW)
    assert res.status == "partial"
    assert res.name_status["alice"] == "registered"
    assert res.name_status["bob"] == "no_slot"
    names = row_names(client, cfg=cfg)
    assert "alice" in names
    assert "bob" not in names
    assert client.intent_overwrites == []


def test_no_slot_left(cfg, client, logger):
    v = make_venue(client, cfg, occupied=["x"] * 24)
    res = register_venue(client, v, cfg, logger, now=NOW)
    assert res.status == "failed"
    assert client.intent_overwrites == []
    assert len(row_names(client, cfg=cfg)) == 24  # 原有内容一字未动


# ---------- 幂等 ----------

def test_idempotent(cfg, client, logger):
    v = make_venue(client, cfg, occupied=["alice", "bob"])
    res1 = register_venue(client, v, cfg, logger, now=NOW)
    res2 = register_venue(client, v, cfg, logger, now=NOW)
    assert res1.status == "complete"
    assert res2.status == "complete"
    names = row_names(client, cfg=cfg)
    assert names.count("alice") == 1
    assert names.count("bob") == 1
    assert client.intent_overwrites == []


# ---------- 不覆盖别人 ----------

def test_never_overwrites_existing(cfg, client, logger):
    occupied = ["a", "b", "c", "d", "e"]
    v = make_venue(client, cfg, occupied=occupied)
    register_venue(client, v, cfg, logger, now=NOW)
    names = row_names(client, cfg=cfg)
    for existing in occupied:
        assert names.count(existing) == 1  # 原名字都还在，且没被复制/覆盖
    assert "alice" in names and "bob" in names
    assert client.intent_overwrites == []


class _RaceOnceClient(FakeSheetsClient):
    """在写前的“再读目标格”那一刻，让别人抢先占住目标格，逼出 conflict 分支。"""
    def __init__(self):
        super().__init__()
        self._injected = False

    def batch_get(self, ranges):
        if not self._injected:
            self._injected = True
            with self._lock:
                for a1 in ranges:
                    sc, sr, _, _ = _parse_a1(a1)
                    self.grid[(sr, sc)] = "intruder"
        return super().batch_get(ranges)


def test_conflict_then_retry_no_overwrite(cfg, logger):
    client = _RaceOnceClient()
    v = make_venue(client, cfg)
    res = register_venue(client, v, cfg, logger, now=NOW)
    assert res.status == "complete"
    names = row_names(client, cfg=cfg)
    assert "alice" in names and "bob" in names
    assert names.count("intruder") >= 1      # 抢先者仍在
    assert client.intent_overwrites == []    # 我们从未写到非空格


# ---------- 并发最终一致 ----------

def test_concurrent_cooperating_agents(logger):
    """8 个协作 Agent 各抢一个不同名字，写进同一场地行。
    验证：全部名字最终都在、无重复、无永久丢失(即使发生了瞬时覆盖，也能靠回读重试自愈)。"""
    cfg = make_config(max_retries=15, write_retry_jitter_ms_min=1, write_retry_jitter_ms_max=8)
    client = FakeSheetsClient(write_latency=0.01, read_latency=0.002)
    v = make_venue(client, cfg)

    people = [f"p{i}" for i in range(8)]
    errors = []

    def worker(name):
        try:
            register_venue(client, v, cfg, logger, names=[name], now=NOW)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(p,)) for p in people]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    names = row_names(client, cfg=cfg)
    for p in people:
        assert names.count(p) == 1, f"{p} lost or duplicated: {names}"
    assert len(names) == len(people)


def test_names_written_adjacent(cfg, client, logger):
    """空场地报名时，两人应被写进相邻的两个位置，且 alice 在前。"""
    v = make_venue(client, cfg)
    register_venue(client, v, cfg, logger, now=NOW)
    vals = client.row_values(5, cfg.player_first_col, cfg.player_count)
    filled = [(i, x) for i, x in enumerate(vals) if x.strip()]
    assert len(filled) == 2
    assert filled[1][0] - filled[0][0] == 1          # 相邻
    assert filled[0][1] == "alice" and filled[1][1] == "bob"


def test_names_adjacent_with_gaps(cfg, client, logger):
    """位置零碎时也尽量挨着：只留 slot5,6 相邻空位(其余占满)，应正好填进这一对。"""
    occupied = ["x"] * 24
    occupied[4] = ""   # player 5 空
    occupied[5] = ""   # player 6 空(与 5 相邻)
    v = make_venue(client, cfg, occupied=occupied)
    register_venue(client, v, cfg, logger, now=NOW)
    vals = client.row_values(5, cfg.player_first_col, cfg.player_count)
    assert vals[4] == "alice" and vals[5] == "bob"
    assert client.intent_overwrites == []
