#!/usr/bin/env python3
"""Stage 3: Send personalized cold emails to businesses.

Uses SMTP (configurable) or SendGrid API.

Usage:
    python outreach.py                    # send to all businesses with emails
    python outreach.py --limit 5          # send to first 5
    python outreach.py --dry-run          # preview without sending

Requires SMTP credentials or SENDGRID_API_KEY in environment or .env file.
"""

import json
import os
import smtplib
import subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

DATA_DIR = Path(__file__).parent
BUSINESSES_FILE = DATA_DIR / "businesses.json"
TEMPLATE_FILE = DATA_DIR / "email_template.txt"

# SMTP config from environment
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", SMTP_USER)
SENDER_NAME = os.environ.get("SENDER_NAME", "BizFinder")

DEFAULT_TEMPLATE = """Hi {first_name},

I noticed {business_name} ({category}) at {address} doesn't have a website yet. I help local businesses get online with a professional, mobile-friendly site — no tech skills needed.

Would you be interested in a quick chat about getting your business online?

Best regards,
{sender_name}
"""


def load_template():
    """Load email template from file or use default."""
    if TEMPLATE_FILE.exists():
        return TEMPLATE_FILE.read_text()
    return DEFAULT_TEMPLATE


def load_businesses():
    """Load businesses from JSON file."""
    if not BUSINESSES_FILE.exists():
        return []
    return json.loads(BUSINESSES_FILE.read_text())


def save_businesses(businesses):
    """Save businesses to JSON file."""
    BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))


def format_email(biz, template):
    """Format an email template for a business."""
    enrichment = biz.get("enrichment", {})
    first_name = enrichment.get("first_name") or "there"

    return template.format(
        first_name=first_name,
        business_name=biz.get("name", "your business"),
        category=biz.get("category", ""),
        address=biz.get("address", ""),
        sender_name=SENDER_NAME,
    )


def send_smtp(to_email, subject, body):
    """Send email via SMTP."""
    if not SMTP_USER or not SMTP_PASS:
        return {"error": "SMTP credentials not configured"}

    msg = MIMEMultipart()
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return {"status": "sent", "to": to_email}
    except Exception as e:
        return {"error": str(e)}


def send_resend(to_email, subject, body):
    """Send email via Resend API (3k/mo free, no card)."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        return {"error": "RESEND_API_KEY not set"}

    payload = json.dumps({
        "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "text": body,
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.resend.com/emails",
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "-d", payload],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=15)

    if result.returncode == 0:
        try:
            resp = json.loads(result.stdout or "{}")
        except Exception:
            resp = {}
        return {"status": "sent", "to": to_email, "id": resp.get("id", ""),
                "via": "resend"}
    return {"error": result.stderr}


def send_sendgrid(to_email, subject, body):
    """Send email via SendGrid API."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        return {"error": "SENDGRID_API_KEY not set"}

    payload = json.dumps({
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.sendgrid.com/v3/mail/send",
         "-H", f"Authorization: Bearer {api_key}",
         "-H", "Content-Type: application/json",
         "-d", payload],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=15)

    if result.returncode == 0:
        return {"status": "sent", "to": to_email}
    return {"error": result.stderr}


def send_outreach(businesses=None, limit=None, dry_run=False, subject="Get Your Business Online"):
    """Send outreach emails to businesses with emails."""
    if businesses is None:
        businesses = load_businesses()

    template = load_template()
    sent_count = 0

    for i, biz in enumerate(businesses):
        if limit and sent_count >= limit:
            break

        # Get email
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        if not email:
            continue

        # Skip if already contacted
        if biz.get("outreach", {}).get("status") == "sent":
            continue

        body = format_email(biz, template)

        if dry_run:
            print(f"[DRY RUN] Would send to {email}:")
            print(f"  Business: {biz.get('name')}")
            print(f"  Body preview: {body[:100]}...")
            print()
            sent_count += 1
            continue

        result = send_smtp(email, subject, body)
        if result.get("error"):
            # Try Resend (free tier) before SendGrid (trial-only)
            result = send_resend(email, subject, body)
        if result.get("error"):
            # Try SendGrid as final fallback
            result = send_sendgrid(email, subject, body)

        biz["outreach"] = {
            "status": "sent" if result.get("status") == "sent" else "failed",
            "email": email,
            "result": result,
        }

        if result.get("status") == "sent":
            sent_count += 1
            print(f"[{sent_count}] Sent to {email} ({biz.get('name')})")
        else:
            print(f"Failed for {email}: {result.get('error')}")

    save_businesses(businesses)
    print(f"\nDone. Sent {sent_count} emails.")
    return sent_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Send outreach emails")
    parser.add_argument("--limit", type=int, help="Max emails to send")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--subject", default="Get Your Business Online", help="Email subject")
    args = parser.parse_args()

    send_outreach(limit=args.limit, dry_run=args.dry_run, subject=args.subject)
