"""状态持久化 (SQLite)。用于:
  - known_venues : 已见过的 venue_id(区分“新场地”)
  - registrations: 报名记录(幂等 + 同时间段去重 + 断电恢复)
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RegRecord:
    venue_id: str
    dedupe_key: str
    date: str
    start: str
    end: str
    field: str
    status: str            # complete | partial | no_slot | failed
    name_status: Dict[str, str]  # {名字: registered|already|no_slot|failed}
    detected_at: str
    registered_at: str


class State:
    def __init__(self, db_path: str = "./data/state.db"):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS known_venues (
                venue_id   TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS registrations (
                venue_id        TEXT PRIMARY KEY,
                dedupe_key      TEXT NOT NULL,
                date            TEXT,
                start           TEXT,
                end             TEXT,
                field           TEXT,
                status          TEXT NOT NULL,
                name_status     TEXT,
                detected_at     TEXT,
                registered_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reg_dedupe ON registrations(dedupe_key);
            """
        )
        # 兼容旧版数据库(只有两列固定名字的状态)：缺列则补上
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(registrations)")}
        if "name_status" not in cols:
            self.conn.execute("ALTER TABLE registrations ADD COLUMN name_status TEXT")
        self.conn.commit()

    # ---- known_venues ----
    def is_known(self, venue_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM known_venues WHERE venue_id=?", (venue_id,))
        return cur.fetchone() is not None

    def mark_known(self, venue_id: str, now: str) -> None:
        self.conn.execute(
            """INSERT INTO known_venues(venue_id, first_seen, last_seen) VALUES(?,?,?)
               ON CONFLICT(venue_id) DO UPDATE SET last_seen=excluded.last_seen""",
            (venue_id, now, now),
        )
        self.conn.commit()

    # ---- registrations ----
    def get_by_venue(self, venue_id: str) -> Optional[RegRecord]:
        cur = self.conn.execute("SELECT * FROM registrations WHERE venue_id=?", (venue_id,))
        row = cur.fetchone()
        return self._to_record(row) if row else None

    def get_by_dedupe(self, dedupe_key: str) -> List[RegRecord]:
        cur = self.conn.execute("SELECT * FROM registrations WHERE dedupe_key=?", (dedupe_key,))
        return [self._to_record(r) for r in cur.fetchall()]

    def dedupe_secured(self, dedupe_key: str) -> Optional[RegRecord]:
        """该时间段是否已经占到过场(complete/partial)。返回那条记录。"""
        for r in self.get_by_dedupe(dedupe_key):
            if r.status in ("complete", "partial"):
                return r
        return None

    def upsert_registration(self, rec: RegRecord) -> None:
        self.conn.execute(
            """INSERT INTO registrations
               (venue_id, dedupe_key, date, start, end, field, status,
                name_status, detected_at, registered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(venue_id) DO UPDATE SET
                 status=excluded.status,
                 name_status=excluded.name_status,
                 registered_at=excluded.registered_at""",
            (rec.venue_id, rec.dedupe_key, rec.date, rec.start, rec.end, rec.field,
             rec.status, json.dumps(rec.name_status, ensure_ascii=False, sort_keys=True), rec.detected_at, rec.registered_at),
        )
        self.conn.commit()

    def _to_record(self, row: sqlite3.Row) -> RegRecord:
        return RegRecord(
            venue_id=row["venue_id"], dedupe_key=row["dedupe_key"], date=row["date"],
            start=row["start"], end=row["end"], field=row["field"], status=row["status"],
            name_status=json.loads(row["name_status"]) if row["name_status"] else {},
            detected_at=row["detected_at"], registered_at=row["registered_at"],
        )

    def close(self) -> None:
        self.conn.close()
