from datetime import datetime
from zoneinfo import ZoneInfo

from src.dedupe import select_one, group_by_dedupe
from src.parser import build_venue
from conftest import make_config

TZ = ZoneInfo("Europe/Brussels")
NOW = datetime(2026, 8, 15, 10, 0, tzinfo=TZ)


def _venue(cfg, row_index, field, occupied):
    row = ["Wednesday", "19/8", "19-20", field] + occupied + [""] * (24 - len(occupied))
    return build_venue(row, row_index, cfg, NOW)


def test_prefers_court_with_two_free():
    cfg = make_config()
    # court1 只剩 1 空位, court2 剩很多, court3 也剩很多但行号更大
    court1 = _venue(cfg, 5, "Court1", ["a"] * 23)
    court2 = _venue(cfg, 6, "Court2", ["a"] * 5)
    court3 = _venue(cfg, 7, "Court3", ["a"] * 5)
    chosen = select_one([court1, court2, court3], needed=2)
    assert chosen.field == "Court2"  # 能放下两人且行号最小


def test_tie_breaks_on_row_index():
    cfg = make_config()
    a = _venue(cfg, 8, "A", [])
    b = _venue(cfg, 6, "B", [])
    chosen = select_one([a, b], needed=2)
    assert chosen.field == "B"  # 同为全空，选先出现的(行号6)


def test_group_by_dedupe():
    cfg = make_config()
    a = _venue(cfg, 5, "Court1", [])
    b = _venue(cfg, 6, "Court2", [])
    groups = group_by_dedupe([a, b])
    assert len(groups) == 1
    assert list(groups.values())[0] == [a, b]
