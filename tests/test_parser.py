from datetime import datetime
from zoneinfo import ZoneInfo

from src.parser import parse_date, parse_time_range, parse_table, build_venue
from conftest import make_config, seed_venue_row, FakeSheetsClient

TZ = ZoneInfo("Europe/Brussels")
NOW = datetime(2026, 8, 15, 10, 0, tzinfo=TZ)


def test_parse_time_range_variants():
    assert parse_time_range("14-16") == ("14:00", "16:00")
    assert parse_time_range("15-17") == ("15:00", "17:00")
    assert parse_time_range("18:30-20:30") == ("18:30", "20:30")
    assert parse_time_range("19:00–20:00") == ("19:00", "20:00")  # en-dash
    assert parse_time_range("garbage") is None


def test_parse_date_dm():
    d = parse_date("16/8", NOW, None)
    assert (d.year, d.month, d.day) == (2026, 8, 16)


def test_parse_date_iso():
    d = parse_date("2026-08-18", NOW, None)
    assert (d.year, d.month, d.day) == (2026, 8, 18)


def test_parse_date_year_rollover():
    # 1月的日期在 8月看来应属于明年
    d = parse_date("5/1", NOW, None)
    assert d.year == 2027


def test_build_venue_ids():
    cfg = make_config()
    row = ["Tuesday", "18/8", "18-20", "TSH1"] + [""] * 24
    v = build_venue(row, 5, cfg, NOW)
    assert v is not None
    assert v.venue_id == "2026-08-18|18:00|20:00|TSH1"
    assert v.dedupe_key == "2026-08-18|18:00|20:00"
    assert len(v.slots) == 24
    assert v.slots[0].a1 == "'Sheet1'!E5"
    assert v.slots[-1].a1 == "'Sheet1'!AB5"


def test_build_venue_bad_row_returns_none():
    cfg = make_config()
    assert build_venue(["", "", "", ""], 5, cfg, NOW) is None


def test_parse_table_multiple_rows():
    cfg = make_config()
    client = FakeSheetsClient()
    seed_venue_row(client, 3, "Sunday", "16/8", "14-16", "TSH1", ["Yang L", "zongyuan"])
    seed_venue_row(client, 4, "Tuesday", "18/8", "18-20", "TSH1", [])
    values = client.read_range("'Sheet1'!A1:AB52")
    venues = parse_table(values, cfg, NOW)
    assert len(venues) == 2
    assert venues[0].field == "TSH1"
    assert venues[0].name_present("Yang L")
    assert len(venues[1].empty_slots()) == 24
