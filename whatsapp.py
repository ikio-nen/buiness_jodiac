#!/usr/bin/env python3
"""Stage 5: WhatsApp message outreach.

This module sends WhatsApp messages via the Hermes gateway WhatsApp adapter
or via the WhatsApp Business API directly.

Usage:
    python whatsapp.py                    # send to all businesses with phone numbers
    python whatsapp.py --limit 5          # send to first 5
    python whatsapp.py --dry-run          # preview without sending
"""

import json
import os
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent
BUSINESSES_FILE = DATA_DIR / "businesses.json"

DEFAULT_MESSAGE = """Hi {first_name}! I noticed {business_name} doesn't have a website. I help local businesses get online with professional, mobile-friendly sites. Would you be interested in a quick chat?"""


def load_businesses():
    if not BUSINESSES_FILE.exists():
        return []
    return json.loads(BUSINESSES_FILE.read_text())


def save_businesses(businesses):
    BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))


def format_message(biz):
    enrichment = biz.get("enrichment", {})
    first_name = enrichment.get("first_name") or "there"
    return DEFAULT_MESSAGE.format(
        first_name=first_name,
        business_name=biz.get("name", "your business"),
    )


def send_via_hermes(phone, message):
    """Send via Hermes WhatsApp gateway."""
    result = subprocess.run(
        ["hermes", "send", "--platform", "whatsapp", "--to", phone, "--message", message],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode == 0:
        return {"status": "sent"}
    return {"error": result.stderr.strip() or "hermes send failed"}


def send_whatsapp(businesses=None, limit=None, dry_run=False):
    """Send WhatsApp messages to businesses with phone numbers."""
    if businesses is None:
        businesses = load_businesses()

    sent_count = 0
    for biz in businesses:
        if limit and sent_count >= limit:
            break

        phone = biz.get("phone", "")
        if not phone:
            continue

        if biz.get("whatsapp_outreach", {}).get("status") == "sent":
            continue

        message = format_message(biz)

        if dry_run:
            print(f"[DRY RUN] Would send to {phone}:")
            print(f"  Business: {biz.get('name')}")
            print(f"  Message: {message[:100]}...")
            sent_count += 1
            continue

        result = send_via_hermes(phone, message)
        biz["whatsapp_outreach"] = {
            "status": result.get("status", "failed"),
            "phone": phone,
            "result": result,
        }
        if result.get("status") == "sent":
            sent_count += 1
            print(f"[{sent_count}] Sent WhatsApp to {phone} ({biz.get('name')})")
        else:
            print(f"Failed WhatsApp for {phone}: {result.get('error')}")

    save_businesses(businesses)
    print(f"\nDone. Sent {sent_count} WhatsApp messages.")
    return sent_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Send WhatsApp outreach messages")
    parser.add_argument("--limit", type=int, help="Max messages to send")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()
    send_whatsapp(limit=args.limit, dry_run=args.dry_run)
