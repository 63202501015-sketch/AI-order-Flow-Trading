"""Persistent request de-duplication (SQLite). A request_id is decided at most once,
across bridge restarts; the AI is never called twice for the same bar."""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional


class DedupStore:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS requests ("
            " request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, status TEXT NOT NULL,"
            " response_json TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS spend (day TEXT PRIMARY KEY, cost REAL NOT NULL, calls INTEGER NOT NULL)")

    def begin(self, request_id: str, payload_hash: str) -> tuple[str, Optional[str], Optional[str]]:
        """Atomically claim a request id.
        Returns ("new", None, None) | ("exists", status, response_json) | ("conflict", None, None)."""
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?)",
                (request_id, payload_hash, "pending", None, now, now))
            if cur.rowcount == 1:
                return "new", None, None
            row = self._db.execute(
                "SELECT payload_hash, status, response_json FROM requests WHERE request_id=?",
                (request_id,)).fetchone()
        if row[0] != payload_hash:
            return "conflict", None, None
        return "exists", row[1], row[2]

    def finish(self, request_id: str, response_json: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE requests SET status='final', response_json=?, updated_at=? "
                "WHERE request_id=? AND status='pending'", (response_json, time.time(), request_id))

    def get(self, request_id: str) -> Optional[tuple[str, Optional[str]]]:
        with self._lock:
            row = self._db.execute(
                "SELECT status, response_json FROM requests WHERE request_id=?", (request_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def pending_ids(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT request_id FROM requests WHERE status='pending'")]

    def purge_older_than(self, seconds: float) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM requests WHERE status='final' AND updated_at < ?",
                                   (time.time() - seconds,))
            return cur.rowcount

    def add_spend(self, day: str, cost: float, calls: int) -> None:
        """Persisted, so the daily budget survives a bridge restart."""
        with self._lock:
            self._db.execute(
                "INSERT INTO spend VALUES (?,?,?) ON CONFLICT(day) DO UPDATE SET "
                "cost = cost + excluded.cost, calls = calls + excluded.calls", (day, cost, calls))

    def spend(self, day: str) -> float:
        with self._lock:
            row = self._db.execute("SELECT cost FROM spend WHERE day=?", (day,)).fetchone()
        return float(row[0]) if row else 0.0

    def calls(self, day: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT calls FROM spend WHERE day=?", (day,)).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._db.close()
