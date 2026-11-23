"""Import the JSON stores into jodiac.db — idempotent, safe to re-run.

Sources of truth that predate the database:

    brain/businesses/*.json   -> businesses (one row per business, ever)
    contact_cache.json        -> contacts  (emails/phones the finder verified)
    emails/sent_ledger.jsonl  -> emails    (status 'sent')
    emails/bounces.jsonl      -> emails    (status 'failed', reason kept)

Usage:
    python -m agents.db_backfill          # import and print what changed
    python -m agents.db_backfill --stats  # just print the current counts
    python -m agents.db_backfill --export # write business_emails.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agents import db, store
from agents.config import OUTPUT_DIR

BRAIN_BIZ = Path(OUTPUT_DIR) / "brain" / "businesses"
CONTACT_CACHE = Path(OUTPUT_DIR) / "contact_cache.json"
SENT_LEDGER = Path(OUTPUT_DIR) / "emails" / "sent_ledger.jsonl"
BOUNCES = Path(OUTPUT_DIR) / "emails" / "bounces.jsonl"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return rows


def _domain_from_source(sources: dict) -> str:
    raw = str((sources or {}).get("email") or "")
    raw = raw.split(" (", 1)[0].strip()
    return store.domain_of(raw)


def backfill_businesses() -> int:
    """brain/businesses/*.json -> businesses. Returns rows touched."""
    if not BRAIN_BIZ.is_dir():
        return 0
    touched = 0
    for path in sorted(BRAIN_BIZ.glob("*.json")):
        rec = _read_json(path)
        if not rec.get("name"):
            continue
        if store.upsert_business("", {
            "name": rec.get("name", ""),
            "category": rec.get("category", ""),
            "location": rec.get("location", ""),
            "website": rec.get("website", ""),
            "phone": rec.get("phone", ""),
            "email": rec.get("email", ""),
            "goal": rec.get("goal", ""),
            "fit_score": rec.get("fit_score"),
            "fit_verdict": rec.get("fit", ""),
            "fit_rationale": rec.get("why_fit", ""),
            "times_seen": rec.get("times_seen", 1),
            "source": "brain",
        }):
            touched += 1
    return touched


def backfill_contacts() -> int:
    """contact_cache.json -> contacts, then attach them to businesses."""
    cache = _read_json(CONTACT_CACHE)
    touched = 0
    for entry in cache.values():
        if not isinstance(entry, dict):
            continue
        email = str(entry.get("email", "") or "").strip().lower()
        phone = str(entry.get("phone", "") or "")
        whatsapp = str(entry.get("whatsapp", "") or "")
        if not (email or phone or whatsapp):
            continue
        sources = entry.get("sources") if isinstance(entry.get("sources"), dict) else {}
        candidates = entry.get("candidates") if isinstance(entry.get("candidates"), list) else []
        best = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        if store.upsert_contact(
            business_id=0,
            email=email,
            phone=phone,
            whatsapp=whatsapp,
            domain=_domain_from_source(sources),
            source=str(sources.get("email", "") or "contact_cache")[:200],
            verified=bool(sources.get("email_verified")),
            status=str(best.get("status", "")),
            detail=str(best.get("detail", "")),
        ):
            touched += 1
    store.link_contact_domains()
    store.link_contacts_by_name()
    return touched


def _email_id_for(to_email: str, subject: str, sent_at: str) -> int:
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM emails WHERE to_email = ? AND subject = ?"
                " AND (sent_at = ? OR status = 'sent') ORDER BY id DESC LIMIT 1",
                (to_email, subject, sent_at)).fetchone()
            return row["id"] if row else 0
    except Exception:
        return 0


def backfill_sent() -> int:
    """sent_ledger.jsonl -> emails (sent / failed). Returns rows added."""
    added = 0
    for rec in _read_jsonl(SENT_LEDGER):
        to_email = str(rec.get("to", "") or "")
        subject = str(rec.get("subject", "") or "")
        if not to_email:
            continue
        sent_at = str(rec.get("sent_at", "") or "")
        if _email_id_for(to_email, subject, sent_at):
            continue
        ok = bool(rec.get("success"))
        business_id = store.upsert_business("", {
            "name": str(rec.get("name", "") or ""),
            "email": to_email,
            "source": "sent_ledger",
        }) if rec.get("name") else 0
        if store.save_email(
            session_id="",
            to_email=to_email,
            subject=subject,
            body="",
            business_id=business_id,
            kind="sent" if ok else "failed",
            status="sent" if ok else "failed",
            provider="ledger",
            business_name=str(rec.get("name", "") or ""),
            error=str(rec.get("error", "") or ""),
            sent_at=sent_at,
        ):
            added += 1
    return added


def backfill_bounces() -> int:
    """bounces.jsonl -> fail the matching sent email, reason kept."""
    marked = 0
    for rec in _read_jsonl(BOUNCES):
        to_email = str(rec.get("to", "") or "")
        if not to_email:
            continue
        subject = str(rec.get("subject", "") or "")
        reason = str(rec.get("reason", "") or "")
        email_id = _email_id_for(to_email, subject, "")
        if email_id and store.mark_email_failed(email_id, reason):
            marked += 1
    return marked


def run() -> dict:
    """Import everything, then return the resulting counts."""
    touched = {
        "businesses": backfill_businesses(),
        "contacts": backfill_contacts(),
        "sent": backfill_sent(),
        "bounced": backfill_bounces(),
    }
    return {**touched, "db": store.stats()}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    db.migrate()
    if "--stats" in args:
        print(json.dumps(store.stats(), indent=2))
        return 0
    if "--export" in args:
        out = Path(OUTPUT_DIR) / "business_emails.csv"
        count = store.export_csv(out)
        print(json.dumps({"file": str(out), "rows": count}, indent=2))
        return 0
    result = run()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
