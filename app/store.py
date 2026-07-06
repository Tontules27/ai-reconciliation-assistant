"""Manual review decisions + append-only audit trail (SQLite, stdlib only).

Deliberately the ONLY persistence in the system: reconciliation is recomputed
from the source files on every run, so the database never stores derived
matching state — just human decisions and their history.

Two tables with different jobs:
- audit_log      append-only, never updated or deleted — the source of truth
                 for who did what and when.
- review_decisions  one row per record with the CURRENT decision — a
                 convenience projection kept in sync by the write functions.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("review.db")

DECISIONS = ("approved", "rejected", "marked_duplicate", "resolved")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_decisions (
    record_id  TEXT PRIMARY KEY,
    decision   TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    action    TEXT NOT NULL,
    reviewer  TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    at        TEXT NOT NULL
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_decision(record_id: str, decision: str, reviewer: str,
                    note: str = "", db_path: Path = DB_PATH) -> None:
    """Set the current decision for a record (upsert) and append to the audit."""
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}; expected one of {DECISIONS}")
    now = _utcnow()
    # closing() releases the file handle; sqlite3's own context manager only
    # commits/rolls back, it never closes the connection.
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """INSERT INTO review_decisions (record_id, decision, reviewer, note, decided_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(record_id) DO UPDATE SET
                 decision=excluded.decision, reviewer=excluded.reviewer,
                 note=excluded.note, decided_at=excluded.decided_at""",
            (record_id, decision, reviewer, note, now),
        )
        conn.execute(
            "INSERT INTO audit_log (record_id, action, reviewer, note, at) VALUES (?, ?, ?, ?, ?)",
            (record_id, decision, reviewer, note, now),
        )


def clear_decision(record_id: str, reviewer: str, db_path: Path = DB_PATH) -> None:
    """Remove the current decision; the audit keeps the full history."""
    with closing(_connect(db_path)) as conn, conn:
        removed = conn.execute(
            "DELETE FROM review_decisions WHERE record_id = ?", (record_id,)
        ).rowcount
        if removed:
            conn.execute(
                "INSERT INTO audit_log (record_id, action, reviewer, note, at) "
                "VALUES (?, 'cleared', ?, '', ?)",
                (record_id, reviewer, _utcnow()),
            )


def get_decisions(db_path: Path = DB_PATH) -> dict[str, dict]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute("SELECT * FROM review_decisions").fetchall()
    return {row["record_id"]: dict(row) for row in rows}


def get_audit_log(db_path: Path = DB_PATH, limit: int = 200) -> list[dict]:
    """Newest first — the operator reads recent activity at the top."""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
