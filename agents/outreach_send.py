"""The send leg — review, send, and receipt for outreach emails.

Owns everything that happens after a draft is approved: sending via the
mailer, receipt PDFs, contact marking, learning, the contacted-phones
export, and the selection parsers (interface grammar that used to live
inside workflows.py). workflows.py re-exports these names so existing
consumers keep working — new code should import from here.
"""

from datetime import datetime
from pathlib import Path

from agents.mailer import send_email
from agents.sent_email_pdf import send_receipt_pdf, sent_dir
from agents.contact_export import write_phones_csv
from agents.obsidian_sync import mark_contact_approached
from agents.learn import learn_from_send


# ── Selection parsers (interface grammar) ────────────────────────────

def parse_send_selection(drafts: list[dict], choice: str) -> list[dict]:
    """'A' = all, 'S'/'skip' = none, '1,3-5' style numbers = picked drafts."""
    choice = (choice or "").strip().upper()
    if choice in ("A", "ALL"):
        return list(drafts)
    if choice in ("S", "SKIP"):
        return []
    if choice.isdigit() and 0 < int(choice) <= len(drafts):
        return [drafts[int(choice) - 1]]
    # ranges and lists: 1,3-5
    picked = []
    try:
        for part in choice.split(","):
            part = part.strip()
            if "-" in part:
                a, _, b = part.partition("-")
                lo, hi = int(a), int(b)
                for n in range(lo, hi + 1):
                    if 1 <= n <= len(drafts):
                        picked.append(drafts[n - 1])
            elif part.isdigit() and 0 < int(part) <= len(drafts):
                picked.append(drafts[int(part) - 1])
    except ValueError:
        return []
    return picked


def parse_send_numbers(drafts: list[dict], nums_str: str) -> list[dict]:
    """Plain comma-separated one-based draft numbers."""
    selected = []
    for n in (nums_str or "").split(","):
        n = n.strip()
        if n.isdigit() and 0 < int(n) <= len(drafts):
            selected.append(drafts[int(n) - 1])
    return selected


# ── Shared send internals ────────────────────────────────────────────

def _send_one(draft: dict, sender_name: str) -> tuple[dict, dict | None, str]:
    """Send one draft. Returns (send_result, sent_record|None, real_pdf_path)."""
    biz = draft.get("business", {})
    pdf_path = draft.get("pdf_path", "")
    real_pdf = pdf_path if pdf_path and Path(pdf_path).exists() else ""
    result = send_email(
        to=draft["to"],
        subject=draft["subject"],
        body=draft["body"],
        pdf_path=real_pdf,
        sender_name=sender_name,
        attachment_path=draft.get("attachment_path", ""),
    )
    if not result.get("success"):
        return result, None, real_pdf

    attached_name = Path(real_pdf).name if real_pdf else None
    rec_path = send_receipt_pdf(
        business_name=biz.get("name", "Business"),
        to=draft["to"],
        subject=draft["subject"],
        body=draft["body"],
        sender_name=sender_name,
        attached_pdf_name=attached_name,
    )
    record = {
        "business": biz,
        "to": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "pdf_path": real_pdf,
        "receipt_pdf": rec_path,
        "timestamp": datetime.now().isoformat(),
    }
    if biz.get("name"):
        mark_contact_approached(biz["name"])
    return result, record, real_pdf


def _contacted_csv(sent_records: list[dict]) -> str:
    if not sent_records:
        return ""
    try:
        return write_phones_csv(
            [r["business"] for r in sent_records],
            out_dir=sent_dir(),
            filename="phones_contacted_{}.csv".format(
                datetime.now().strftime("%Y%m%d_%H%M%S")),
        )
    except Exception:
        return ""


# ── The two send workflows ───────────────────────────────────────────

def review_and_send_workflow(drafts: list[dict], sender_name: str) -> dict:
    """Review emails one-by-one, then send approved ones.

    Shows each email, lets user edit/attach/approve/skip,
    then sends only the approved ones.

    Returns {sent, skipped, attached, errors}.
    """
    from agents.email_review import review_and_edit_workflow, get_approved_with_attachments

    review_result = review_and_edit_workflow(drafts)
    approved = review_result.get("approved", [])

    if not approved:
        return {"sent": [], "skipped": len(drafts), "attached": 0, "errors": [],
                "sent_pdf_dir": str(sent_dir()), "contacted_csv": ""}

    send_list = get_approved_with_attachments(approved)

    sent = []
    errors = []
    attached_count = 0
    sent_records = []

    for draft in send_list:
        if not draft.get("to"):
            continue
        biz = draft.get("business", {})
        if draft.get("pdf_path") and Path(draft["pdf_path"]).exists():
            attached_count += 1
        result, record, _ = _send_one(draft, sender_name)
        if record:
            sent.append(draft)
            sent_records.append(record)
            learn_from_send(
                biz.get("category", ""),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=True,
            )
        else:
            errors.append({"name": biz.get("name", "?") if biz else "?",
                           "error": result.get("error", "Unknown")})

    return {
        "sent": sent,
        "skipped": len(drafts) - len(sent),
        "attached": attached_count,
        "errors": errors,
        "sent_records": sent_records,
        "sent_pdf_dir": str(sent_dir()),
        "contacted_csv": _contacted_csv(sent_records),
    }


def send_emails_workflow(drafts: list[dict], sender_name: str) -> dict:
    """Send emails. Filters empty 'to'. Returns {sent, skipped, errors}."""
    from agents.event_bus import emit
    skipped = [d for d in drafts if not d.get("to")]
    to_send = [d for d in drafts if d.get("to")]

    sent = []
    errors = []
    attached_count = 0
    sent_records = []

    for draft in to_send:
        if not draft.get("to"):
            continue
        biz = draft.get("business", {})
        if draft.get("pdf_path") and Path(draft["pdf_path"]).exists():
            attached_count += 1
        result, record, real_pdf = _send_one(draft, sender_name)
        if record:
            emit("bot", bot="mailer", status="done",
                 task=f"Sent to {draft['to']}", source="workflow")
            emit("packet", from_="mailer", to="sent",
                 label=str(biz.get("name", "?"))[:26])
            sent.append(draft)
            sent_records.append(record)
            learn_from_send(
                biz.get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=True,
            )
            # Per-business brain memory of the send
            try:
                from agents.brain import get_brain
                get_brain().learn_business(
                    biz.get("name", "?"),
                    category=biz.get("category", ""),
                    facts={"phone": biz.get("phone", ""), "email": draft.get("to", "")},
                    interaction={"type": "emailed", "detail": draft.get("subject", "")[:80]},
                    source="send",
                )
            except Exception:
                pass
        else:
            errors.append({"name": biz.get("name", "?") if biz else "?",
                           "error": result.get("error", "Unknown")})
            emit("bot", bot="mailer", status="error",
                 task=f"Failed: {biz.get('name', '?')}", source="workflow")
            learn_from_send(
                draft.get("business", {}).get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=False,
            )

    return {
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "sent_records": sent_records,
        "attached": attached_count,
        "sent_pdf_dir": str(sent_dir()),
        "contacted_csv": _contacted_csv(sent_records),
    }
