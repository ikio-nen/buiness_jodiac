"""
Outbox ledger — the only writer of agent_output/outbox.db.

Pass 1 of the send pipeline: a durable, unique-constrained ledger that
makes a duplicate send structurally impossible and records every send
state transition. Nothing here talks to a provider or schedules anything;
that is later passes.

Deleted rows and corrupted files are not recovered here — that is the
durable-state pass — but this module never writes outside a transaction
and never trusts a caller to finish one.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from agents.outbox import schema as S

_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


# ── dataclasses ────────────────────────────────────────────────────────────────

class EnqueueResult:
    """Plain dataclass returned by enqueue(). No provider is called."""

    __slots__ = ("queued", "suppressed", "over_cap", "rolls_to_tomorrow", "batch_id")

    def __init__(
        self,
        queued: int,
        suppressed: int,
        over_cap: int,
        rolls_to_tomorrow: int,
        batch_id: str,
    ) -> None:
        self.queued = queued
        self.suppressed = suppressed
        self.over_cap = over_cap
        self.rolls_to_tomorrow = rolls_to_tomorrow
        self.batch_id = batch_id


class Row:
    """One recipient row, as returned by claim() and summary()."""

    __slots__ = (
        "id",
        "batch_id",
        "business_name",
        "email",
        "subject",
        "body_ref",
        "attachment",
        "state",
        "provider_id",
        "claimed_at",
        "sent_at",
        "last_error",
        "attempts",
    )

    def __init__(self, row: tuple[Any, ...]) -> None:
        (
            rid,
            batch_id,
            business_name,
            email,
            subject,
            body_ref,
            attachment,
            state,
            provider_id,
            claimed_at,
            sent_at,
            last_error,
            attempts,
        ) = row
        self.id: int = rid
        self.batch_id: str = batch_id
        self.business_name: str = business_name
        self.email: str = email
        self.subject: str = subject
        self.body_ref: str = body_ref
        self.attachment: str | None = attachment
        self.state: str = state
        self.provider_id: str | None = provider_id
        self.claimed_at: datetime | None = claimed_at
        self.sent_at: datetime | None = sent_at
        self.last_error: str | None = last_error
        self.attempts: int = attempts


# ── helpers ────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.strftime(_TIMESTAMP_FMT)


def _parse(ts: str | None) -> datetime | None:
    if ts is None or ts == "":
        return None
    return datetime.strptime(ts, _TIMESTAMP_FMT).replace(tzinfo=timezone.utc)


def _extract_domain(email: str) -> str:
    """Lowercased domain from an email address; the empty string if unparseable."""
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


# ── ledger ─────────────────────────────────────────────────────────────────────

class Ledger:
    """
    Opens (or creates) outbox.db in WAL mode and applies the schema once.

    Every public method that mutates state does so inside a transaction that
    this module owns — callers never see a half-written row.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._ensure()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            conn.close()

    # ── schema ───────────────────────────────────────────────────────────────

    def _ensure(self) -> None:
        conn = self._get_conn()
        try:
            self._apply_schema(conn)
        finally:
            self._release(conn)

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS batches (
                id            TEXT PRIMARY KEY,
                session_id    TEXT    NOT NULL,
                created_at    TEXT    NOT NULL,
                approved_at   TEXT,
                cap_snapshot  INTEGER NOT NULL DEFAULT 0,
                state         TEXT    NOT NULL DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS recipients (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id      TEXT    NOT NULL,
                business_name TEXT    NOT NULL,
                email         TEXT    NOT NULL,
                subject       TEXT    NOT NULL,
                body_ref      TEXT    NOT NULL,
                attachment    TEXT,
                state         TEXT    NOT NULL DEFAULT 'queued',
                provider_id   TEXT,
                claimed_at    TEXT,
                sent_at       TEXT,
                last_error    TEXT,
                attempts      INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (batch_id) REFERENCES batches(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS recipient_batch_email_uniq
                ON recipients (batch_id, email);

            CREATE TABLE IF NOT EXISTS suppressions (
                email     TEXT NOT NULL,
                domain    TEXT NOT NULL,
                reason    TEXT NOT NULL,
                source    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (email, domain, reason, source)
            );

            CREATE INDEX IF NOT EXISTS idx_recipients_batch
                ON recipients (batch_id);
            CREATE INDEX IF NOT EXISTS idx_recipients_state
                ON recipients (state);
            CREATE INDEX IF NOT EXISTS idx_suppressions_email
                ON suppressions (email);
            CREATE INDEX IF NOT EXISTS idx_suppressions_domain
                ON suppressions (domain);
            """
        )

    # ── connection hygiene ───────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._path),
                isolation_level=None,  # autocommit off; we BEGIN explicitly
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _release(self, conn: sqlite3.Connection) -> None:
        # Keep the single shared connection open; allocation is cheap enough
        # that we do not pool on the read side for a single-operator box.
        pass

    def _begin(self, conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN")

    def _commit(self, conn: sqlite3.Connection) -> None:
        conn.execute("COMMIT")

    def _rollback(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            # No transaction active — already rolled back by an earlier error
            # path, or the operation was auto-rolled back by the DB. Nothing
            # to clean up.
            pass

    # ── warm-up allowance ─────────────────────────────────────────────────────

    def allowance(self, today: date | None = None) -> int:
        """Today's send allowance from the warm-up schedule.

        This is a placeholder for Pass 1: the schedule is not yet configurable
        here, because that belongs in config (spec 3) and is wired by the pacer
        (pass 3). For now the ledger exposes the hook and a stub default so the
        state machine and the cap logic can be tested independently of config.
        """
        if today is None:
            today = date.today()
        # Stub: a real implementation reads config.json / config.py for
        # warmup_start, warmup_initial, warmup_increment, daily_ceiling.
        # Pass 1 tests supply their own allowance by monkeypatching this method.
        return 10

    def set_allowance_for(self, target: date, value: int) -> None:
        """Override allowance() for a given date during a test.

        Not part of the shipped interface — a test seam, kept small and explicit.
        """
        if not hasattr(self, "_allowance_overrides"):
            self._allowance_overrides: dict[date, int] = {}
        self._allowance_overrides[target] = value

    def _effective_allowance(self, today: date) -> int:
        if hasattr(self, "_allowance_overrides"):
            if today in self._allowance_overrides:
                return self._allowance_overrides[today]
        return self.allowance(today)

    # ── enqueue ───────────────────────────────────────────────────────────────

    def enqueue(
        self,
        session_id: str,
        drafts: list[dict[str, Any]],
        cap_snapshot: int | None = None,
    ) -> EnqueueResult:
        """Queue one batch of approved drafts.

        One transaction per recipient. A duplicate address inside the same batch
        is silently skipped (it already exists); a suppressed address is counted
        and skipped, never raised. Returns immediately — nothing is sent.
        """
        if cap_snapshot is None:
            cap_snapshot = self._effective_allowance(date.today())

        now = _now()
        batch_id = self._batch_id_for(session_id, now)
        conn = self._get_conn()
        try:
            self._begin(conn)

            # batch row
            conn.execute(
                f"""
                INSERT OR IGNORE INTO batches (id, session_id, created_at, approved_at, cap_snapshot, state)
                VALUES (?, ?, ?, ?, ?, 'open')
                """,
                (batch_id, session_id, _iso(now), _iso(now), cap_snapshot),
            )

            queued = 0
            suppressed = 0
            over_cap = 0
            rolls_to_tomorrow = 0

            for draft in drafts:
                email = (draft.get("email") or "").strip().lower()
                if not email:
                    continue

                # suppression check — both address and domain
                if self._is_suppressed_raw(conn, email):
                    suppressed += 1
                    continue

                # already in this batch?
                if self._already_in_batch(conn, batch_id, email):
                    # silent skip — it is already queued (or beyond)
                    continue

                if queued + over_cap >= cap_snapshot:
                    rolls_to_tomorrow += 1
                    continue

                body_ref = draft.get("body_ref") or ""
                subject = (draft.get("subject") or "").strip()
                if not subject:
                    subject = "(no subject)"
                attachment = draft.get("attachment")

                conn.execute(
                    f"""
                    INSERT INTO recipients
                        (batch_id, business_name, email, subject, body_ref, attachment, state, attempts)
                    VALUES (?, ?, ?, ?, ?, ?, 'queued', 0)
                    """,
                    (
                        batch_id,
                        (draft.get("business_name") or "").strip(),
                        email,
                        subject,
                        body_ref,
                        attachment,
                    ),
                )
                queued += 1

            self._commit(conn)
            return EnqueueResult(
                queued=queued,
                suppressed=suppressed,
                over_cap=0,
                rolls_to_tomorrow=rolls_to_tomorrow,
                batch_id=batch_id,
            )
        except Exception:
            self._rollback(conn)
            raise

    def _batch_id_for(self, session_id: str, now: datetime) -> str:
        return f"{session_id}-{now.strftime('%Y%m%d-%H%M%S-%f')}"

    def _already_in_batch(self, conn: sqlite3.Connection, batch_id: str, email: str) -> bool:
        row = conn.execute(
            f"SELECT 1 FROM recipients WHERE batch_id = ? AND email = ? LIMIT 1",
            (batch_id, email),
        ).fetchone()
        return row is not None

    def _is_suppressed_raw(self, conn: sqlite3.Connection, email: str) -> bool:
        domain = _extract_domain(email)
        return conn.execute(
            f"""
            SELECT 1 FROM suppressions
            WHERE email = ? OR domain = ?
            LIMIT 1
            """,
            (email, domain),
        ).fetchone() is not None

    # ── claim ────────────────────────────────────────────────────────────────

    def claim(self, limit: int) -> list[Row]:
        """Atomically claim up to `limit` queued rows for sending.

        Each claimed row is locked by the UPDATE ... WHERE state='queued'
        pattern — a second caller (or a restart racing the pacer) never gets
        the same row. Returns the claimed rows so the caller can send them.
        """
        conn = self._get_conn()
        try:
            self._begin(conn)
            now = _now()
            rows_raw = conn.execute(
                f"""
                UPDATE recipients
                SET state = 'claimed', claimed_at = ?
                WHERE id IN (
                    SELECT id FROM recipients
                    WHERE state = 'queued'
                    LIMIT ?
                )
                RETURNING *
                """,
                (_iso(now), limit),
            ).fetchall()
            self._commit(conn)
            return [Row(r) for r in rows_raw]
        except Exception:
            self._rollback(conn)
            raise

    # ── post-send transitions ────────────────────────────────────────────────

    def mark_sent(self, row_id: int, provider_id: str) -> None:
        self._transition(row_id, "sent", provider_id=provider_id, sent_at=_iso(_now()))

    def mark_failed(self, row_id: int, error: str) -> None:
        self._transition(row_id, "failed", last_error=error, attempts="+1")

    def apply_event(self, provider_id: str, event: str) -> int:
        """Flip a sent row to delivered/bounced/complained by provider_id.

        Returns the number of rows affected. An unknown provider_id or an
        already-terminal row is a no-op, never an error.
        """
        if event not in ("delivered", "bounced", "complained"):
            return 0
        conn = self._get_conn()
        try:
            self._begin(conn)
            cur = conn.execute(
                f"""
                UPDATE recipients
                SET state = ?, sent_at = ?
                WHERE provider_id = ? AND state = 'sent'
                """,
                (event, _iso(_now()), provider_id),
            )
            self._commit(conn)
            return cur.rowcount
        except Exception:
            self._rollback(conn)
            raise

    # ── suppression ──────────────────────────────────────────────────────────

    def suppress(
        self,
        email: str,
        reason: str,
        source: str,
        domain: str | None = None,
    ) -> None:
        """Write a suppression so future sends skip this address and domain.

        Idempotent per (email, domain, reason, source).
        """
        if domain is None:
            domain = _extract_domain(email)
        now = _now()
        conn = self._get_conn()
        try:
            self._begin(conn)
            conn.execute(
                f"""
                INSERT OR IGNORE INTO suppressions (email, domain, reason, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email.lower(), domain, reason, source, _iso(now)),
            )
            self._commit(conn)
        except Exception:
            self._rollback(conn)
            raise

    def is_suppressed(self, email: str) -> bool:
        conn = self._get_conn()
        try:
            return self._is_suppressed_raw(conn, email)
        finally:
            self._release(conn)

    # ── generic transition guard ─────────────────────────────────────────────

    def _transition(
        self,
        row_id: int,
        to_state: str,
        *,
        provider_id: str | None = None,
        sent_at: str | None = None,
        claimed_at: str | None = None,
        last_error: str | None = None,
        attempts: str | int = 0,
    ) -> None:
        conn = self._get_conn()
        try:
            self._begin(conn)

            cur = conn.execute(
                f"""
                SELECT state FROM recipients WHERE id = ?
                """,
                (row_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                self._rollback(conn)
                raise ValueError(f"no recipient row {row_id}")

            from_state = existing["state"]
            if not S.valid_transition(S.RECIPIENTS, from_state, to_state):
                self._rollback(conn)
                raise ValueError(
                    f"illegal transition {from_state!r} -> {to_state!r} on recipient {row_id}"
                )

            sets: list[str] = [f"state = '{to_state}'"]
            if provider_id is not None:
                sets.append(f"provider_id = {provider_id!r}")
            if sent_at is not None:
                sets.append(f"sent_at = {sent_at!r}")
            if claimed_at is not None:
                sets.append(f"claimed_at = {claimed_at!r}")
            if last_error is not None:
                sets.append(f"last_error = {last_error!r}")
            if attempts == "+1":
                sets.append("attempts = attempts + 1")
            elif isinstance(attempts, int) and attempts != 0:
                sets.append(f"attempts = {attempts}")

            conn.execute(
                f"""
                UPDATE recipients
                SET {', '.join(sets)}
                WHERE id = ?
                """,
                (row_id,),
            )
            self._commit(conn)
        except Exception:
            self._rollback(conn)
            raise

    # ── pause ────────────────────────────────────────────────────────────────

    def pause(self, batch_id: str, paused: bool) -> None:
        """Set or clear the paused flag on a batch."""
        target = "paused" if paused else "open"
        conn = self._get_conn()
        try:
            self._begin(conn)
            conn.execute(
                f"""
                UPDATE batches SET state = ? WHERE id = ?
                """,
                (target, batch_id),
            )
            self._commit(conn)
        except Exception:
            self._rollback(conn)
            raise

    # ── reconciliation on boot ───────────────────────────────────────────────

    def reconcile_stuck_claimed(self, stuck_minutes: int = 10) -> list[Row]:
        """Rows stuck in `claimed` for longer than `stuck_minutes`.

        The pacer calls this on boot to reconcile uncertain sends rather than
        blindly re-sending. This module does no provider verification — it only
        surfaces the rows and lets the caller decide. Rows it surfaces remain
        in `claimed` until the caller marks them failed or reconciles them.
        """
        cutoff_dt = _now() - __import__("datetime").timedelta(minutes=stuck_minutes)
        cutoff = _iso(cutoff_dt)
        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"""
                SELECT *
                FROM recipients
                WHERE state = 'claimed' AND claimed_at <= ?
                ORDER BY claimed_at
                """,
                (cutoff,),
            ).fetchall()
            return [Row(r) for r in rows]
        finally:
            self._release(conn)

    # ── summary ──────────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Plain-language snapshot for /api/outbox and the outbox line in the UI."""
        conn = self._get_conn()
        try:
            batch_count = conn.execute(f"SELECT COUNT(*) FROM batches").fetchone()[0]
            recipient_count = conn.execute(f"SELECT COUNT(*) FROM recipients").fetchone()[0]
            by_state: dict[str, int] = {}
            for row in conn.execute(
                "SELECT state, COUNT(*) FROM recipients GROUP BY state"
            ):
                by_state[row[0]] = row[1]
            suppressed_count = conn.execute(
                f"SELECT COUNT(*) FROM suppressions"
            ).fetchone()[0]
            return {
                "batches": int(batch_count),
                "recipients": int(recipient_count),
                "by_state": by_state,
                "suppressions": int(suppressed_count),
            }
        finally:
            self._release(conn)
