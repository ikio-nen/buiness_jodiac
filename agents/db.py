"""SQLite database seam — one file, zero new dependencies (stdlib sqlite3).

``jodiac.db`` lives under ``OUTPUT_DIR`` (so ``JODIAC_HOME`` moves it too).
WAL mode for concurrent CLI + WebSocket access — the same pattern as
``chat_memory.py``. Every public function opens its own short-lived
connection: no shared-connection threading hazards, no connection healing.

Tables (v1): ``businesses`` (discovered + scored businesses per session),
``emails`` (drafts + sent outreach), ``sessions`` (registry), ``usage``
(per AI call, including which provider served it — the grading feed for the
provider cascade).

Migrations are idempotent and versioned in ``schema_migrations``. The DB is
best-effort infrastructure: every writer wraps it so a DB failure degrades,
never blocks the pipeline.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agents.config import OUTPUT_DIR

DB_PATH = OUTPUT_DIR / "jodiac.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect():
    """One short-lived connection: WAL, row dicts, FK enforcement."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Migrations ───────────────────────────────────────────────────────
# Each entry: (version, sql). Applied in order, once each.

_MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL DEFAULT '',
        ext_id TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        category TEXT DEFAULT '',
        location TEXT DEFAULT '',
        website TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        rating REAL,
        review_count INTEGER,
        lat REAL,
        lon REAL,
        source TEXT DEFAULT '',
        snippets_json TEXT DEFAULT '[]',
        fit_score INTEGER,
        fit_verdict TEXT DEFAULT '',
        fit_rationale TEXT DEFAULT '',
        icp_veto TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(session_id, ext_id)
    );
    CREATE INDEX IF NOT EXISTS idx_businesses_session ON businesses(session_id);
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL DEFAULT '',
        business_id INTEGER REFERENCES businesses(id),
        kind TEXT NOT NULL DEFAULT 'draft',
        to_email TEXT DEFAULT '',
        subject TEXT DEFAULT '',
        body TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        provider TEXT DEFAULT '',
        sent_at TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_emails_session ON emails(session_id);
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        name TEXT DEFAULT '',
        product TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        capability TEXT NOT NULL,
        prompt_version TEXT DEFAULT '',
        business_id TEXT DEFAULT '',
        ok INTEGER NOT NULL DEFAULT 1,
        used_gemini INTEGER NOT NULL DEFAULT 0,
        provider TEXT DEFAULT '',
        notes TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_usage_cap ON usage(capability);
    CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage(provider);
    """),
]


def migrate() -> int:
    """Apply pending migrations. Returns the current schema version."""
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {r[0] for r in
                   conn.execute("SELECT version FROM schema_migrations")}
        for version, sql in sorted(_MIGRATIONS):
            if version in applied:
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at)"
                " VALUES (?, ?)", (version, _now()))
    return current_version()


def current_version() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_migrations").fetchone()
        return row[0] or 0


def journal_mode() -> str:
    with connect() as conn:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]


def status() -> dict:
    """{path, version, journal_mode, tables} for dashboards/debugging."""
    with connect() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"path": str(DB_PATH), "version": current_version(),
            "journal_mode": journal_mode(),
            "tables": [t for t in tables if t != "sqlite_sequence"]}
