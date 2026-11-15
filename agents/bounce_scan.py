"""Read delivery failures (bounces) from the sending Gmail inbox over IMAP.

Gmail accepts every message at SMTP time, so ``send_email`` reports success
even when the receiving server later rejects the recipient. Those rejections
come back as Delivery Status Notifications from ``mailer-daemon`` an hour or
a day later -- invisible to anything in the send path.

This module reads the inbox with the same app password already used for
sending, extracts which addresses failed and why, and keeps them in
``agent_output/emails/bounces.jsonl`` so the panel can show a bounced address
instead of pretending it was contacted.
"""
import email
import imaplib
import json
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from pathlib import Path

from . import config
from .config import get_gmail_app_password, get_gmail_user


def bounces_path() -> Path:
    """Same folder as the send ledger, so one directory holds all mail state."""
    p = Path(config.OUTPUT_DIR) / "emails" / "bounces.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def known_bounces() -> dict[str, dict]:
    """Failed recipient -> its bounce record. Lower-cased addresses as keys."""
    out: dict[str, dict] = {}
    for rec in _read_jsonl(bounces_path()):
        addr = (rec.get("to") or "").strip().lower()
        if addr:
            out[addr] = rec
    return out


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _failed_recipients(msg) -> list[tuple[str, str]]:
    """(address, reason) pairs from one delivery-status notification."""
    found: list[tuple[str, str]] = []
    body_chunks: list[str] = []

    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("message/delivery-status", "text/rfc822-headers"):
            try:
                raw = part.as_string()
            except Exception:
                raw = ""
            current_addr = ""
            for line in raw.splitlines():
                low = line.lower()
                if low.startswith("final-recipient:") or low.startswith("original-recipient:"):
                    addr = line.split(";")[-1].strip()
                    if "@" in addr:
                        current_addr = addr
                elif low.startswith("diagnostic-code:") and current_addr:
                    reason = line.split(":", 1)[-1].strip()
                    found.append((current_addr, reason))
                    current_addr = ""
            if current_addr:
                found.append((current_addr, ""))
        elif ctype in ("text/plain", "text/html"):
            try:
                body_chunks.append(part.get_payload(decode=True).decode("utf-8", "replace"))
            except Exception:
                continue

    if not found:
        # Some senders omit the machine-readable part; fall back to the
        # prose, which still names the address after "couldn't be delivered".
        text = "\n".join(body_chunks)
        for addr in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
            if addr.lower().startswith("mailer-daemon"):
                continue
            reason = ""
            m = re.search(r"(\d{3}[- ]\d(?:\.\d+)+\s*[^\n]*)", text)
            if m:
                reason = m.group(1).strip()
            found.append((addr, reason))
    return found


def scan(days: int = 14, sender_email: str = "") -> dict:
    """Look for delivery failures in the inbox and record new ones.

    Returns ``{"checked": n, "bounces": [...], "new": [...], "error": ""}``.
    A bounce already in the store is not appended twice.
    """
    user = get_gmail_user() or sender_email
    password = get_gmail_app_password()
    if not user or not password:
        return {"checked": 0, "bounces": [], "new": [], "error": "Gmail not configured"}

    since = (datetime.now() - timedelta(days=max(1, days))).strftime("%d-%b-%Y")
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
            imap.login(user, password)
            imap.select("INBOX", readonly=True)
            # Bounces come from mailer-daemon at Google, and some clients file
            # them under "Delivery Status Notification (Failure)".
            typ, data = imap.search(None, f'(SINCE {since} FROM "mailer-daemon")')
            ids = data[0].split() if typ == "OK" and data and data[0] else []
            existing = known_bounces()
            fresh: list[dict] = []
            seen: list[dict] = []

            for msg_id in ids:
                typ, raw = imap.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])
                subject = _decode(msg.get("Subject", ""))
                when = _decode(msg.get("Date", ""))
                for addr, reason in _failed_recipients(msg):
                    key = addr.strip().lower()
                    rec = {"to": addr.strip(), "reason": reason,
                           "subject": subject, "detected_at": datetime.now().isoformat()}
                    seen.append(rec)
                    if key not in existing:
                        fresh.append(rec)
                        existing[key] = rec

            if fresh:
                with open(bounces_path(), "a", encoding="utf-8") as fh:
                    for rec in fresh:
                        fh.write(json.dumps(rec) + "\n")
            return {"checked": len(ids), "bounces": seen, "new": fresh, "error": ""}
    except imaplib.IMAP4.error as exc:
        return {"checked": 0, "bounces": [], "new": [],
                "error": f"Gmail mailbox refused IMAP access: {exc}"}
    except Exception as exc:
        return {"checked": 0, "bounces": [], "new": [], "error": str(exc)}


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    result = scan(days=days)
    if result["error"]:
        print("error:", result["error"])
        raise SystemExit(1)
    print(f"checked {result['checked']} delivery notices over {days} day(s)")
    for rec in result["bounces"]:
        print(f"  BOUNCED  {rec['to']:38s} {rec['reason'][:70]}")
    print(f"new this scan: {len(result['new'])}")
