"""SQLite database seam — one file, zero new dependencies (stdlib sqlite3).

``jodiac.db`` lives under ``OUTPUT_DIR`` (so ``JODIAC_HOME`` moves it too).
WAL mode for concurrent CLI + WebSocket access — the same pattern as
``chat_memory.py``. Every public function opens its own short-lived
connection: no shared-connection threading hazards, no connection healing.

Tables: ``businesses`` (the directory), ``contacts`` (every channel known
for a business), ``emails`` (drafts + sent outreach), ``sessions``
(registry), ``usage`` (per AI call, including which provider served it —
the grading feed for the provider cascade).

Migrations are idempotent and versioned in ``schema_migrations``. The DB is
best-effort infrastructure: every writer wraps it so a DB failure degrades,
never blocks the pipeline.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
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
# Each entry: (version, sql-or-callable). Applied in order, once each.
# Callables receive the open connection, for steps that need PRAGMA checks
# (SQLite has no ALTER TABLE ... ADD COLUMN IF NOT EXISTS).

_MIGRATIONS: list[tuple[int, str | Callable]] = [
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


def _migration_2(conn: sqlite3.Connection) -> None:
    """The directory: one row per business, every channel we know for it,
    and the outreach that went with it.

    v1 was a per-session log. This adds the normalised keys and the contacts
    table a directory needs, so the same business found twice is one row and
    an email is attached to the business instead of floating alone.
    """
    # Contacts first: emails.contact_id references it.
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
        email TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        whatsapp TEXT NOT NULL DEFAULT '',
        domain TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        verified INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(email, domain)
    );
    CREATE INDEX IF NOT EXISTS idx_contacts_business ON contacts(business_id);
    CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
    CREATE INDEX IF NOT EXISTS idx_contacts_domain ON contacts(domain);
    """)

    def add(table: str, columns: list[tuple[str, str]]) -> None:
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    add("businesses", [
        ("name_norm", "TEXT NOT NULL DEFAULT ''"),
        ("domain", "TEXT NOT NULL DEFAULT ''"),
        ("goal", "TEXT NOT NULL DEFAULT ''"),
        ("times_seen", "INTEGER NOT NULL DEFAULT 1"),
        ("first_seen", "TEXT NOT NULL DEFAULT ''"),
        ("last_seen", "TEXT NOT NULL DEFAULT ''"),
    ])
    add("emails", [
        ("contact_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL"),
        ("business_name", "TEXT NOT NULL DEFAULT ''"),
        ("approved_at", "TEXT NOT NULL DEFAULT ''"),
        ("error", "TEXT NOT NULL DEFAULT ''"),
        ("message_id", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ])

    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_businesses_norm ON businesses(name_norm);
    CREATE INDEX IF NOT EXISTS idx_businesses_domain ON businesses(domain);
    CREATE INDEX IF NOT EXISTS idx_businesses_email ON businesses(email);
    CREATE INDEX IF NOT EXISTS idx_businesses_score ON businesses(fit_score);
    CREATE INDEX IF NOT EXISTS idx_emails_to ON emails(to_email);
    CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);
    CREATE INDEX IF NOT EXISTS idx_emails_business ON emails(business_id);
    -- Backfill the normalised keys on rows that predate this migration.
    UPDATE businesses SET name_norm = lower(trim(name)) WHERE name_norm = '';
    UPDATE businesses SET first_seen = created_at WHERE first_seen = '';
    UPDATE businesses SET last_seen = updated_at WHERE last_seen = '';
    """)


_MIGRATIONS.append((2, _migration_2))


def migrate() -> int:
    """Apply pending migrations. Returns the current schema version."""
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {r[0] for r in
                   conn.execute("SELECT version FROM schema_migrations")}
        for version, step in sorted(_MIGRATIONS, key=lambda item: item[0]):
            if version in applied:
                continue
            if callable(step):
                step(conn)
            else:
                conn.executescript(step)
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
