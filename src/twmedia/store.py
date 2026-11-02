"""Local storage: append-only JSONL per source per day, plus a SQLite index of seen items.

Raw data stays on this machine (data/ is git-ignored). Only derived data is ever published.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pseudonymize(value: str | None) -> str | None:
    """One-way hash for user handles on discussion platforms (個資保護)."""
    if not value:
        return None
    return hashlib.sha256(("twmedia:" + value).encode()).hexdigest()[:16]


class Store:
    def __init__(self, root: Path = DATA_DIR):
        self.root = root
        (root / "raw").mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(root / "state.sqlite", check_same_thread=False, timeout=30)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " source TEXT, item_id TEXT, first_seen TEXT,"
            " PRIMARY KEY (source, item_id))"
        )
        self._db.commit()
        self._lock = threading.Lock()

    def is_seen(self, source: str, item_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM seen WHERE source = ? AND item_id = ?", (source, item_id)
            ).fetchone()
        return row is not None

    def save(self, source: str, item_id: str, record: dict) -> bool:
        """Write a record once. Returns False if it was already stored."""
        record = {"source": source, "id": item_id, "collected_at": now_utc(), **record}
        day = record["collected_at"][:10]
        path = self.root / "raw" / source / f"{day}.jsonl"
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO seen VALUES (?, ?, ?)",
                (source, item_id, record["collected_at"]),
            )
            if cur.rowcount == 0:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._db.commit()
        return True

    def counts(self) -> list[tuple[str, int, str]]:
        with self._lock:
            return self._db.execute(
                "SELECT source, COUNT(*), MAX(first_seen) FROM seen GROUP BY source ORDER BY source"
            ).fetchall()
