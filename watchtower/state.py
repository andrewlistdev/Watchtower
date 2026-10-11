"""SQLite state: which Arctic Wolf ticket maps to which SDP request, and what has been done."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    aw_id            INTEGER PRIMARY KEY,
    sdp_id           TEXT,
    state            TEXT NOT NULL,      -- creating | open | aw_closed | failed_create
    aw_title         TEXT,
    assigned_email   TEXT,
    assigned_pd_id   TEXT,
    assign_reason    TEXT,
    created_at       TEXT NOT NULL,
    aw_closed_at     TEXT,
    closed_by        TEXT,               -- sdp | arcticwolf
    last_error       TEXT,
    owner_name       TEXT,               -- current SDP technician, refreshed every check
    owner_email      TEXT,
    sdp_status       TEXT,               -- current SDP status name, refreshed every check
    refreshed_at     TEXT,
    refresh_error    TEXT                -- set when the last refresh from SDP failed
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (       -- routing history
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    aw_id    INTEGER,
    kind     TEXT NOT NULL,
    message  TEXT NOT NULL,
    actor    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_ticket ON events(aw_id, id);
"""

# Columns added after 1.0.0; existing databases get them on start-up.
ADDED_COLUMNS = {
    "owner_name": "TEXT", "owner_email": "TEXT", "sdp_status": "TEXT",
    "refreshed_at": "TEXT", "refresh_error": "TEXT",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class State:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")  # GUI reads while the worker writes
        self._migrate()
        self.db.executescript(SCHEMA)
        self.db.commit()

    def _migrate(self) -> None:
        existing = {r["name"] for r in self.db.execute("PRAGMA table_info(tickets)")}
        if not existing:
            return  # fresh database; SCHEMA creates everything
        for column, kind in ADDED_COLUMNS.items():
            if column not in existing:
                self.db.execute(f"ALTER TABLE tickets ADD COLUMN {column} {kind}")

    # meta
    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.commit()

    # tickets
    def get(self, aw_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM tickets WHERE aw_id = ?", (aw_id,)).fetchone()

    def begin_create(self, aw_id: int, title: str) -> None:
        """Record intent before calling SDP so a crash mid-create can't cause a duplicate."""
        self.db.execute(
            "INSERT INTO tickets(aw_id, state, aw_title, created_at) VALUES(?, 'creating', ?, ?)",
            (aw_id, title, utcnow()),
        )
        self.db.commit()

    def finish_create(
        self, aw_id: int, sdp_id: str, email: str | None, pd_id: str | None, reason: str,
        name: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE tickets SET sdp_id = ?, state = 'open', assigned_email = ?, "
            "assigned_pd_id = ?, assign_reason = ?, last_error = NULL, "
            "owner_email = ?, owner_name = ? WHERE aw_id = ?",
            (sdp_id, email, pd_id, reason, email, name or email, aw_id),
        )
        self.db.commit()

    def fail_create(self, aw_id: int, error: str) -> None:
        self.db.execute(
            "UPDATE tickets SET state = 'failed_create', last_error = ? WHERE aw_id = ?",
            (error[:2000], aw_id),
        )
        self.db.commit()

    def retryable_failed_creates(self) -> list[int]:
        rows = self.db.execute("SELECT aw_id FROM tickets WHERE state = 'failed_create'").fetchall()
        return [r["aw_id"] for r in rows]

    def clear_failed(self, aw_id: int) -> None:
        self.db.execute("DELETE FROM tickets WHERE aw_id = ? AND state = 'failed_create'", (aw_id,))
        self.db.commit()

    def stuck_creating(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tickets WHERE state = 'creating'").fetchall()

    def open_mappings(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM tickets WHERE state = 'open' AND sdp_id IS NOT NULL"
        ).fetchall()

    def mark_aw_closed(self, aw_id: int, closed_by: str) -> None:
        self.db.execute(
            "UPDATE tickets SET state = 'aw_closed', aw_closed_at = ?, closed_by = ?, "
            "last_error = NULL, refresh_error = NULL WHERE aw_id = ?",
            (utcnow(), closed_by, aw_id),
        )
        self.db.commit()

    def resolve_stuck(self, aw_id: int, sdp_id: str | None) -> bool:
        """Operator fix for a 'creating' row: link the SDP request found, or drop it to recreate."""
        if sdp_id:
            cur = self.db.execute(
                "UPDATE tickets SET sdp_id = ?, state = 'open', last_error = NULL "
                "WHERE aw_id = ? AND state = 'creating'",
                (sdp_id, aw_id),
            )
            message = f"An admin linked this ticket to ServiceDesk Plus request #{sdp_id}."
        else:
            cur = self.db.execute(
                "DELETE FROM tickets WHERE aw_id = ? AND state = 'creating'", (aw_id,)
            )
            message = "An admin confirmed no SDP request exists. It will be created on the next check."
        self.db.commit()
        if cur.rowcount:
            self.record_event(aw_id, "admin", message, actor="Admin (command line)")
        return cur.rowcount > 0

    def all_rows(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()

    def update_refresh(self, aw_id: int, owner_name: str | None, owner_email: str | None,
                       sdp_status: str | None) -> None:
        self.db.execute(
            "UPDATE tickets SET owner_name = ?, owner_email = ?, sdp_status = ?, refreshed_at = ?, "
            "refresh_error = NULL WHERE aw_id = ?",
            (owner_name, owner_email, sdp_status, utcnow(), aw_id),
        )
        self.db.commit()

    def set_refresh_error(self, aw_id: int, error: str) -> None:
        self.db.execute("UPDATE tickets SET refresh_error = ? WHERE aw_id = ?", (error[:2000], aw_id))
        self.db.commit()

    def clear_error(self, aw_id: int) -> None:
        self.db.execute("UPDATE tickets SET last_error = NULL WHERE aw_id = ?", (aw_id,))
        self.db.commit()

    # routing history
    def record_event(self, aw_id: int | None, kind: str, message: str, actor: str = "Watchtower",
                     dedupe: bool = False) -> None:
        """Append to the routing history. With dedupe, skip if it repeats this ticket's last event."""
        if dedupe and aw_id is not None:
            last = self.db.execute(
                "SELECT kind, message FROM events WHERE aw_id = ? ORDER BY id DESC LIMIT 1", (aw_id,)
            ).fetchone()
            if last and last["kind"] == kind and last["message"] == message:
                return
        self.db.execute(
            "INSERT INTO events(at, aw_id, kind, message, actor) VALUES(?, ?, ?, ?, ?)",
            (utcnow(), aw_id, kind, message[:2000], actor),
        )
        self.db.commit()

    def events(self, aw_id: int | None = None, limit: int = 200) -> list[sqlite3.Row]:
        if aw_id is None:
            return self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return self.db.execute(
            "SELECT * FROM events WHERE aw_id = ? ORDER BY id DESC LIMIT ?", (aw_id, limit)
        ).fetchall()

    def set_error(self, aw_id: int, error: str) -> None:
        self.db.execute(
            "UPDATE tickets SET last_error = ? WHERE aw_id = ?", (error[:2000], aw_id)
        )
        self.db.commit()
