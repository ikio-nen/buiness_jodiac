"""Typed data access over agents/db.py — the one place business, outreach,
session-registry, and usage rows are read and written.

All functions take and return plain dicts (the codebase's lingua franca),
open their own short-lived connection via db.connect(), and never raise for
telemetry-grade writes: a DB failure degrades, never blocks the pipeline.

The directory convention: ``session_id=""`` means "the shared directory" —
every business the office has ever met, one row each, keyed by a normalised
name. A session id keeps the per-session view for tests and replays.
"""
from __future__ import annotations

import json
import re

from agents import db as _db

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


def norm_name(name: str) -> str:
    """The dedupe key for a business: case, spacing and punctuation removed."""
    text = (name or "").lower().strip()
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def domain_of(value: str) -> str:
    """Host for a website or email — the join key between the two tables."""
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "@" in text:
        return text.rsplit("@", 1)[1].strip(".")
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0]
    text = text.split(":", 1)[0]
    return text[4:] if text.startswith("www.") else text


# ── Businesses ───────────────────────────────────────────────────────

_BUSINESS_TEXT = (
    "name", "category", "location", "website", "phone", "email", "source",
    "fit_verdict", "fit_rationale", "icp_veto", "name_norm", "domain", "goal",
    "snippets_json",
)
_BUSINESS_NUM = ("rating", "review_count", "lat", "lon", "fit_score")
_BUSINESS_FIELDS = ("session_id", "ext_id") + _BUSINESS_TEXT + _BUSINESS_NUM
# Columns whose empty value must never wipe a known one on update.
_PRESERVE_EMPTY = {"name", "category", "location", "website", "phone", "email",
                   "domain", "goal", "fit_verdict", "fit_rationale"}


def _business_params(session_id: str, data: dict) -> dict:
    snippets = data.get("snippets") or []
    name = str(data.get("name", ""))
    fit = data.get("fit") if isinstance(data.get("fit"), dict) else {}
    website = str(data.get("website", "") or "")
    email = str(data.get("email", "") or "")
    normalized = norm_name(name)
    params = {
        "session_id": session_id,
        # A directory write has no provider id: the normalised name is the
        # stable identity, so meeting the same business twice updates one row.
        "ext_id": str(data.get("id") or normalized or name or ""),
        "name": name,
        "category": str(data.get("category", "")),
        "location": str(data.get("location", "")),
        "website": website,
        "phone": str(data.get("phone", "") or ""),
        "email": email,
        "rating": data.get("rating"),
        "review_count": data.get("review_count"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "source": str(data.get("source", "")),
        "snippets_json": json.dumps(snippets, ensure_ascii=True),
        "fit_score": fit.get("score") if fit else data.get("fit_score"),
        "fit_verdict": fit.get("fit", "") if fit else str(data.get("fit_verdict", "")),
        "fit_rationale": fit.get("rationale", "") if fit else str(data.get("fit_rationale", "")),
        "icp_veto": str(data.get("icp_veto", "")),
        "name_norm": normalized,
        "domain": domain_of(website) or domain_of(email),
        "goal": str(data.get("goal", "") or ""),
        "times_seen": int(data.get("times_seen") or 1),
    }
    return params


def upsert_business(session_id: str, data: dict) -> int:
    """Insert or update a business (deduped on session_id + ext_id).

    Text fields only overwrite when the incoming value is non-empty, so a
    later thin record cannot erase a phone number or website we already had.
    Returns the row id. Never raises.
    """
    try:
        _db.migrate()
        p = _business_params(session_id, data)
        cols = ", ".join(_BUSINESS_FIELDS)
        placeholders = ", ".join(f":{c}" for c in _BUSINESS_FIELDS)
        now = _db._now()
        updates = []
        for c in _BUSINESS_FIELDS:
            if c in ("session_id", "ext_id"):
                continue
            if c in _PRESERVE_EMPTY or c == "snippets_json":
                blank = "'[]'" if c == "snippets_json" else "''"
                updates.append(
                    f"{c} = COALESCE(NULLIF(excluded.{c}, {blank}), businesses.{c})")
            elif c in _BUSINESS_NUM:
                updates.append(f"{c} = COALESCE(excluded.{c}, businesses.{c})")
            else:
                updates.append(f"{c} = excluded.{c}")
        updates += [
            # Monotone and idempotent: replays of the same history are free.
            "times_seen = MAX(businesses.times_seen, excluded.times_seen)",
            "last_seen = excluded.last_seen",
            "updated_at = excluded.updated_at",
        ]
        with _db.connect() as conn:
            conn.execute(
                f"INSERT INTO businesses ({cols}, times_seen, first_seen,"
                f" last_seen, created_at, updated_at)"
                f" VALUES ({placeholders}, :times_seen, :now, :now, :now, :now)"
                f" ON CONFLICT(session_id, ext_id) DO UPDATE SET"
                f" {', '.join(updates)}",
                {**p, "now": now},
            )
            row = conn.execute(
                "SELECT id FROM businesses WHERE session_id = ? AND ext_id = ?",
                (session_id, p["ext_id"])).fetchone()
            row_id = row["id"] if row else 0
        return row_id
    except Exception:
        return 0


def list_businesses(session_id: str, verdict: str = "",
                    limit: int = 0) -> list[dict]:
    """Businesses for a session (or the whole directory when id is "")."""
    try:
        _db.migrate()
        sql = "SELECT * FROM businesses"
        args: list = []
        where = []
        if session_id:
            where.append("session_id = ?")
            args.append(session_id)
        if verdict:
            where.append("fit_verdict = ?")
            args.append(verdict)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY fit_score DESC NULLS LAST, name"
        if limit:
            sql += " LIMIT ?"
            args.append(int(limit))
        with _db.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(sql, args)]
    except Exception:
        return []


def search_businesses(query: str, limit: int = 50) -> list[dict]:
    """Name / domain / email / category / location contains (case-insensitive)."""
    needle = f"%{(query or '').strip().lower()}%"
    try:
        _db.migrate()
        with _db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM businesses"
                " WHERE lower(name) LIKE ? OR name_norm LIKE ?"
                " OR lower(domain) LIKE ? OR lower(email) LIKE ?"
                " OR lower(category) LIKE ? OR lower(location) LIKE ?"
                " ORDER BY fit_score DESC NULLS LAST, name LIMIT ?",
                (needle, needle, needle, needle, needle, needle, int(limit)))
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


# ── Contacts (every channel known for one business) ──────────────────

def upsert_contact(business_id: int = 0, email: str = "", phone: str = "",
                   whatsapp: str = "", domain: str = "", source: str = "",
                   verified: bool = False, status: str = "",
                   detail: str = "") -> int:
    """Insert or update one channel. Deduped on (email, domain). Never raises."""
    email = (email or "").strip().lower()
    domain = (domain or domain_of(email)).strip().lower()
    if not (email or phone or whatsapp):
        return 0
    if not domain:
        # The unique key is (email, domain); two phone-only contacts would
        # both be ('', '') and merge into one row. Give the number its own key.
        digits = re.sub(r"\D", "", phone or whatsapp)
        domain = f"phone:{digits[-10:]}" if digits else ""
    try:
        _db.migrate()
        now = _db._now()
        with _db.connect() as conn:
            conn.execute(
                "INSERT INTO contacts (business_id, email, phone, whatsapp,"
                " domain, source, verified, status, detail, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(email, domain) DO UPDATE SET"
                " business_id = CASE WHEN excluded.business_id > 0 THEN excluded.business_id"
                " ELSE contacts.business_id END,"
                " phone = COALESCE(NULLIF(excluded.phone, ''), contacts.phone),"
                " whatsapp = COALESCE(NULLIF(excluded.whatsapp, ''), contacts.whatsapp),"
                " source = COALESCE(NULLIF(excluded.source, ''), contacts.source),"
                " verified = MAX(excluded.verified, contacts.verified),"
                " status = COALESCE(NULLIF(excluded.status, ''), contacts.status),"
                " detail = COALESCE(NULLIF(excluded.detail, ''), contacts.detail),"
                " updated_at = excluded.updated_at",
                # NULL, not 0: an orphan is unlinkable, and 0 is not a
                # business id the foreign key will accept.
                (int(business_id) if business_id else None,
                 email, phone or "", whatsapp or "",
                 domain, source or "", int(bool(verified)), status or "",
                 (detail or "")[:400], now, now),
            )
            row = conn.execute(
                "SELECT id FROM contacts WHERE email = ? AND domain = ?",
                (email, domain)).fetchone()
            return row["id"] if row else 0
    except Exception:
        return 0


def contacts_for(business_id: int) -> list[dict]:
    try:
        _db.migrate()
        with _db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE business_id = ?"
                " ORDER BY verified DESC, id", (int(business_id),))
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def link_contact_domains() -> int:
    """Attach orphan contacts to the business that owns their domain."""
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "UPDATE contacts SET business_id = ("
                "  SELECT b.id FROM businesses b"
                "   WHERE b.domain <> '' AND b.domain = contacts.domain"
                "   ORDER BY b.fit_score DESC NULLS LAST, b.id LIMIT 1)"
                " WHERE (business_id IS NULL OR business_id = 0) AND domain <> ''"
                "   AND EXISTS (SELECT 1 FROM businesses b"
                "                WHERE b.domain <> '' AND b.domain = contacts.domain)")
            return cur.rowcount or 0
    except Exception:
        return 0


def link_contacts_by_name() -> int:
    """Second pass: attach a contact whose domain spells the business name.

    Only for names long enough to be unambiguous (12+ letters squashed), so
    "city centre" cannot swallow citycentre.com by accident.
    """
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "UPDATE contacts SET business_id = ("
                "  SELECT b.id FROM businesses b"
                "   WHERE length(replace(b.name_norm, ' ', '')) >= 12"
                "     AND instr(lower(replace(c.domain, '-', '')),"
                "               replace(b.name_norm, ' ', '')) > 0"
                "   ORDER BY length(replace(b.name_norm, ' ', '')) DESC, b.id LIMIT 1)"
                " WHERE (business_id IS NULL OR business_id = 0) AND domain <> ''"
                "   AND EXISTS (SELECT 1 FROM businesses b"
                "                WHERE length(replace(b.name_norm, ' ', '')) >= 12"
                "                  AND instr(lower(replace(contacts.domain, '-', '')),"
                "                            replace(b.name_norm, ' ', '')) > 0)")
            return cur.rowcount or 0
    except Exception:
        return 0


def breakdown() -> dict:
    """The slices the directory dashboard charts: fit, category, email state."""
    out = {"fit": [], "categories": [], "email_status": [], "top": []}
    try:
        _db.migrate()
        with _db.connect() as conn:
            for r in conn.execute(
                    "SELECT CASE WHEN fit_verdict = '' THEN 'unjudged'"
                    "             ELSE fit_verdict END AS label, COUNT(*) c"
                    " FROM businesses GROUP BY label ORDER BY c DESC"):
                out["fit"].append({"label": r["label"], "value": r["c"]})
            for r in conn.execute(
                    "SELECT CASE WHEN category = '' THEN 'uncategorised'"
                    "             ELSE replace(category, '_', ' ') END AS label,"
                    "       COUNT(*) c"
                    " FROM businesses GROUP BY label ORDER BY c DESC LIMIT 6"):
                out["categories"].append({"label": r["label"], "value": r["c"]})
            for r in conn.execute(
                    "SELECT status AS label, COUNT(*) c FROM emails"
                    " GROUP BY status ORDER BY c DESC"):
                out["email_status"].append({"label": r["label"] or "unknown",
                                            "value": r["c"]})
            for r in conn.execute(
                    "SELECT b.name, b.fit_score, b.category,"
                    " COALESCE(NULLIF((SELECT c.email FROM contacts c"
                    "   WHERE c.business_id = b.id AND c.email <> ''"
                    "   ORDER BY c.verified DESC, c.id LIMIT 1), ''),"
                    "          b.email) AS best_email"
                    " FROM businesses b WHERE b.email <> ''"
                    "    OR EXISTS (SELECT 1 FROM contacts c WHERE c.business_id = b.id"
                    "                AND c.email <> '')"
                    " ORDER BY b.fit_score DESC NULLS LAST, b.name LIMIT 8"):
                out["top"].append(dict(r))
    except Exception:
        pass
    return out


# ── Emails (drafts + sent outreach) ──────────────────────────────────

def save_email(session_id: str, to_email: str, subject: str, body: str,
               business_id: int = 0, kind: str = "draft",
               status: str = "draft", provider: str = "",
               business_name: str = "", error: str = "",
               sent_at: str = "") -> int:
    """Persist an outreach email. Returns the row id, 0 on failure."""
    try:
        _db.migrate()
        now = _db._now()
        with _db.connect() as conn:
            if not business_id and business_name:
                row = conn.execute(
                    "SELECT id FROM businesses WHERE name_norm = ? LIMIT 1",
                    (norm_name(business_name),)).fetchone()
                business_id = row["id"] if row else 0
            # A send or failure is the next state of an existing draft, not a
            # second email. Reuse that row so one outreach is one row.
            if status != "draft" and to_email:
                row = conn.execute(
                    "SELECT id FROM emails WHERE to_email = ? AND subject = ?"
                    " AND status IN ('draft', 'failed')"
                    " ORDER BY id DESC LIMIT 1",
                    (to_email, subject)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE emails SET business_id = COALESCE(?, business_id),"
                        " business_name = COALESCE(NULLIF(?, ''), business_name),"
                        " body = ?, kind = ?, status = ?,"
                        " provider = COALESCE(NULLIF(?, ''), provider),"
                        " sent_at = ?, error = ?, updated_at = ? WHERE id = ?",
                        (business_id or None, business_name or "", body,
                         kind, status, provider,
                         sent_at or (now if status == "sent" else ""),
                         (error or "")[:400], now, row["id"]))
                    return row["id"]
            cur = conn.execute(
                "INSERT INTO emails (session_id, business_id, business_name,"
                " kind, to_email, subject, body, status, provider, sent_at,"
                " error, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, business_id or None, business_name or "",
                 kind, to_email, subject, body, status, provider,
                 sent_at or (now if status == "sent" else ""), (error or "")[:400],
                 now, now),
            )
            return cur.lastrowid or 0
    except Exception:
        return 0


def mark_email_sent(email_id: int, provider: str = "",
                    message_id: str = "") -> bool:
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "UPDATE emails SET kind = 'sent', status = 'sent',"
                " provider = ?, message_id = COALESCE(NULLIF(?, ''), message_id),"
                " sent_at = ?, updated_at = ? WHERE id = ?",
                (provider, message_id or "", _db._now(), _db._now(),
                 int(email_id)),
            )
            return cur.rowcount > 0
    except Exception:
        return False


def mark_email_failed(email_id: int, error: str = "") -> bool:
    try:
        _db.migrate()
        with _db.connect() as conn:
            cur = conn.execute(
                "UPDATE emails SET status = 'failed', error = ?,"
                " updated_at = ? WHERE id = ?",
                ((error or "")[:400], _db._now(), int(email_id)),
            )
            return cur.rowcount > 0
    except Exception:
        return False


def list_emails(session_id: str, kind: str = "") -> list[dict]:
    try:
        _db.migrate()
        sql = "SELECT * FROM emails"
        where, args = [], []
        if session_id:
            where.append("session_id = ?")
            args.append(session_id)
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        with _db.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(sql, args)]
    except Exception:
        return []


def emails_for(business_id: int) -> list[dict]:
    """Every email ever drafted/sent to one business."""
    try:
        _db.migrate()
        with _db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM emails WHERE business_id = ? ORDER BY id DESC",
                (int(business_id),))
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


# ── Directory reads ──────────────────────────────────────────────────

def directory(limit: int = 0, where: str = "") -> list[dict]:
    """Businesses with their best contact and outreach count, for export."""
    try:
        _db.migrate()
        sql = ("SELECT b.id, b.name, b.category, b.location, b.website,"
               " b.phone, b.email, b.domain, b.fit_score, b.fit_verdict,"
               " b.goal, b.times_seen, b.first_seen, b.last_seen,"
               " COALESCE(c.email, b.email) AS best_email,"
               " c.verified AS email_verified, c.source AS email_source,"
               " (SELECT COUNT(*) FROM emails e WHERE e.business_id = b.id"
               "   AND e.status = 'sent') AS sent_count"
               " FROM businesses b"
               " LEFT JOIN ("
               "   SELECT business_id, email, verified, source,"
               "          ROW_NUMBER() OVER (PARTITION BY business_id"
               "            ORDER BY verified DESC, id) AS rn"
               "   FROM contacts WHERE email <> ''"
               " ) c ON c.business_id = b.id AND c.rn = 1")
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY b.fit_score DESC NULLS LAST, b.name"
        if limit:
            sql += " LIMIT ?"
        with _db.connect() as conn:
            args = [int(limit)] if limit else []
            return [_row_to_dict(r) for r in conn.execute(sql, args)]
    except Exception:
        return []


def export_csv(path) -> int:
    """Write one row per business that has a reachable email. Returns rows.

    Columns: name, category, location, email, verified, source, fit_score.
    The file is the human-readable copy of the directory; SQLite stays the
    source of truth.
    """
    import csv
    rows = directory(limit=0)
    written = 0
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["name", "category", "location", "email",
                             "verified", "source", "fit_score"])
            for r in rows:
                if not r.get("best_email"):
                    continue
                writer.writerow([r.get("name", ""), r.get("category", ""),
                                 r.get("location", ""), r["best_email"],
                                 "yes" if r.get("email_verified") else "no",
                                 r.get("email_source", ""),
                                 r.get("fit_score") or ""])
                written += 1
    except Exception:
        return 0
    return written


def stats() -> dict:
    """Counts for the dashboard: what the directory actually holds."""
    out = {"businesses": 0, "with_email": 0, "with_website": 0,
           "contacts": 0, "verified_contacts": 0,
           "emails": 0, "drafts": 0, "sent": 0, "failed": 0,
           "sessions": 0, "usage": 0}
    try:
        _db.migrate()
        with _db.connect() as conn:
            row = conn.execute(
                "SELECT"
                " (SELECT COUNT(*) FROM businesses) AS businesses,"
                " (SELECT COUNT(*) FROM businesses WHERE email <> '') AS with_email,"
                " (SELECT COUNT(*) FROM businesses WHERE website <> '') AS with_website,"
                " (SELECT COUNT(*) FROM contacts) AS contacts,"
                " (SELECT COUNT(*) FROM contacts WHERE verified = 1) AS verified_contacts,"
                " (SELECT COUNT(*) FROM emails) AS emails,"
                " (SELECT COUNT(*) FROM emails WHERE status = 'draft') AS drafts,"
                " (SELECT COUNT(*) FROM emails WHERE status = 'sent') AS sent,"
                " (SELECT COUNT(*) FROM emails WHERE status = 'failed') AS failed,"
                " (SELECT COUNT(*) FROM sessions) AS sessions,"
                " (SELECT COUNT(*) FROM usage) AS usage").fetchone()
            out.update({k: (row[k] or 0) for k in out})
    except Exception:
        pass
    return out


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
