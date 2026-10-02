"""Typed data access over agents/db.py — the one place business, outreach,
session-registry, and usage rows are read and written.

All functions take and return plain dicts (the codebase's lingua franca),
open their own short-lived connection via db.connect(), and never raise for
telemetry-grade writes: a DB failure degrades, never blocks the pipeline.
"""
from __future__ import annotations

import json

from agents import db as _db


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


# ── Businesses ───────────────────────────────────────────────────────

_BUSINESS_FIELDS = (
    "session_id", "ext_id", "name", "category", "location", "website",
    "phone", "email", "rating", "review_count", "lat", "lon", "source",
    "snippets_json", "fit_score", "fit_verdict", "fit_rationale", "icp_veto",
)


def _business_params(session_id: str, data: dict) -> dict:
    snippets = data.get("snippets") or []
    params = {
        "session_id": session_id,
        "ext_id": str(data.get("id") or data.get("name") or ""),
        "name": str(data.get("name", "")),
        "category": str(data.get("category", "")),
        "location": str(data.get("location", "")),
        "website": str(data.get("website", "")),
        "phone": str(data.get("phone", "")),
        "email": str(data.get("email", "")),
        "rating": data.get("rating"),
        "review_count": data.get("review_count"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "source": str(data.get("source", "")),
        "snippets_json": json.dumps(snippets, ensure_ascii=True),
        "fit_score": (data.get("fit") or {}).get("score")
        if isinstance(data.get("fit"), dict) else data.get("fit_score"),
        "fit_verdict": (data.get("fit") or {}).get("fit", "")
        if isinstance(data.get("fit"), dict) else str(data.get("fit_verdict", "")),
        "fit_rationale": (data.get("fit") or {}).get("rationale", "")
        if isinstance(data.get("fit"), dict) else str(data.get("fit_rationale", "")),
        "icp_veto": str(data.get("icp_veto", "")),
    }
    return params


def upsert_business(session_id: str, data: dict) -> int:
    """Insert or update a business (deduped on session_id + ext_id).

    Returns the row id. Never raises."""
    try:
        _db.migrate()
        p = _business_params(session_id, data)
        cols = ", ".join(_BUSINESS_FIELDS)
        placeholders = ", ".join(f":{c}" for c in _BUSINESS_FIELDS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _BUSINESS_FIELDS
                            if c not in ("session_id", "ext_id"))
        with _db.connect() as conn:
            conn.execute(
                f"INSERT INTO businesses ({cols}, created_at, updated_at)"
                f" VALUES ({placeholders}, :now, :now)"
                f" ON CONFLICT(session_id, ext_id) DO UPDATE SET {updates},"
                f" updated_at = excluded.updated_at",
                {**p, "now": _db._now()},
            )
            row = conn.execute(
                "SELECT id FROM businesses WHERE session_id = ? AND ext_id = ?",
                (session_id, p["ext_id"])).fetchone()
            return row["id"] if row else 0
    except Exception:
        return 0


def list_businesses(session_id: str, verdict: str = "") -> list[dict]:
    """Businesses for a session, optionally filtered by fit verdict."""
    try:
        _db.migrate()
        with _db.connect() as conn:
            if verdict:
                rows = conn.execute(
                    "SELECT * FROM businesses WHERE session_id = ?"
                    " AND fit_verdict = ? ORDER BY fit_score DESC NULLS LAST, name",
                    (session_id, verdict)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM businesses WHERE session_id = ?"
                    " ORDER BY fit_score DESC NULLS LAST, name",
                    (session_id,)).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def count_businesses(session_id: str = "") -> int:
    try:
        _db.migrate()
        with _db.connect() as conn:
            if session_id:
                row = conn.execute(
                    "SELECT COUNT(*) FROM businesses WHERE session_id = ?",
                    (session_id,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()
            return row[0] or 0
    except Exception:
        return 0


# ── Emails (drafts + sent outreach) ──────────────────────────────────

def save_email(session_id: str, to_email: str, subject: str, body: str,
               business_id: int = 0, kind: str = "draft",
               status: str = "draft", provider: str = "") -> int:
    """Persist an outreach email. Returns the row id, 0 on failure."""
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO emails (session_id, business_id, kind, to_email,"
                " subject, body, status, provider, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, business_id or None, kind, to_email, subject,
                 body, status, provider, _db._now()),
            )
            return cur.lastrowid or 0
    except Exception:
        return 0


def mark_email_sent(email_id: int, provider: str = "") -> bool:
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "UPDATE emails SET kind = 'sent', status = 'sent',"
                " provider = ?, sent_at = ? WHERE id = ?",
                (provider, _db._now(), email_id),
            )
            return cur.rowcount > 0
    except Exception:
        return False


def list_emails(session_id: str, kind: str = "") -> list[dict]:
    try:
        _db.migrate()
        with _db.connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM emails WHERE session_id = ? AND kind = ?"
                    " ORDER BY id", (session_id, kind)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM emails WHERE session_id = ? ORDER BY id",
                    (session_id,)).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


# ── Session registry ─────────────────────────────────────────────────

def register_session(session_id: str, name: str = "",
                     product: str = "") -> bool:
    try:
        _db.migrate()
        with _db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, name, product, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET name = excluded.name,"
                " product = excluded.product",
                (session_id, name, product, _db._now()),
            )
            return True
    except Exception:
        return False


def get_session(session_id: str) -> dict:
    try:
        _db.migrate()
        with _db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return _row_to_dict(row)
    except Exception:
        return {}


# ── Usage (per AI call — the provider grading feed) ───────────────────

def log_usage(ts: str, capability: str, prompt_version: str = "",
              business_id: str = "", ok: bool = True,
              used_gemini: bool = False, provider: str = "",
              notes: str = "") -> bool:
    """Append one usage record. Never raises."""
    try:
        _db.migrate()
        with _db.connect() as conn:
            conn.execute(
                "INSERT INTO usage (ts, capability, prompt_version, business_id,"
                " ok, used_gemini, provider, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, capability, prompt_version, business_id, int(ok),
                 int(used_gemini), provider, notes[:160]),
            )
            return True
    except Exception:
        return False


def usage_stats() -> dict:
    """Per-capability totals (mirrors usage_log.stats shape). Never raises."""
    out: dict[str, dict] = {}
    try:
        _db.migrate()
        with _db.connect() as conn:
            for r in conn.execute(
                    "SELECT capability, COUNT(*) c,"
                    " SUM(used_gemini) g, SUM(1 - ok) f"
                    " FROM usage GROUP BY capability"):
                out[r["capability"]] = {
                    "calls": r["c"], "gemini": r["g"] or 0,
                    "fallbacks": (r["c"] or 0) - (r["g"] or 0),
                    "errors": r["f"] or 0,
                }
    except Exception:
        pass
    return out


def provider_stats() -> dict:
    """Per-provider totals: calls, ok-rate — the cascade grading feed."""
    out: dict[str, dict] = {}
    try:
        _db.migrate()
        with _db.connect() as conn:
            for r in conn.execute(
                    "SELECT provider, COUNT(*) c, SUM(ok) okc"
                    " FROM usage GROUP BY provider"):
                name = r["provider"] or "(unknown)"
                c = r["c"] or 0
                out[name] = {"calls": c,
                             "ok_rate": round((r["okc"] or 0) / c, 3) if c else 0}
    except Exception:
        pass
    return out
