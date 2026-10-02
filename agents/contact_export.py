"""Contact export for later WhatsApp messaging.

Writes a CSV of every business we have a phone number or email for, so the
user can message them later from whatever WhatsApp tool they use.

Columns: name, category, address, phone, phone_source, email, email_source, website
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .config import REPORTS_DIR


def _phone_source(biz: dict) -> str:
    if biz.get("phone"):
        if biz.get("maps_phone") and biz.get("phone") != biz.get("maps_phone"):
            return "osm+maps"
        return "osm"
    if biz.get("maps_phone"):
        return "maps"
    return ""


def _email_source(biz: dict) -> str:
    if biz.get("email"):
        if biz.get("maps_email") and biz.get("email") != biz.get("maps_email"):
            return "osm+maps"
        return "osm"
    if biz.get("maps_email"):
        return "maps"
    if biz.get("enrichment", {}).get("email"):
        return "hunter"
    return ""


def contact_rows(businesses: list[dict]) -> list[dict[str, str]]:
    """One row per business that has a phone or an email."""
    rows: list[dict[str, str]] = []
    for b in businesses:
        name = b.get("name", "")
        phone = b.get("phone", "") or b.get("maps_phone", "")
        email = (
            b.get("email", "") or b.get("maps_email", "")
            or b.get("enrichment", {}).get("email", "")
        )
        if not phone and not email:
            continue
        v2 = b.get("enrichment_v2") or {}
        rows.append({
            "name": name,
            "category": b.get("category", ""),
            "address": b.get("address", "") or b.get("city", ""),
            "phone": phone,
            "phone_source": _phone_source(b),
            "email": email,
            "email_source": _email_source(b),
            "website": b.get("website", ""),
            # WhatsApp-ready mobile (validated MOBILE via libphonenumber) and
            # the email's MX deliverability, from enrichment v2.
            "whatsapp": v2.get("whatsapp", "") or b.get("whatsapp_link", ""),
            "email_status": ("deliverable" if (v2.get("candidates") and
                              any(c.get("status") == "deliverable"
                                  for c in v2["candidates"])) else ""),
        })
    return rows


def write_phones_csv(
    businesses: list[dict],
    out_dir: Path | None = None,
    filename: str | None = None,
) -> str:
    """Write the phones/emails CSV. Returns the file path."""
    d = out_dir or REPORTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = filename or f"phones_for_whatsapp_{ts}.csv"
    path = d / name

    rows = contact_rows(businesses)
    if not rows and not path.exists():
        path.write_text("", encoding="utf-8")
        return str(path)

    fieldnames = [
        "name", "category", "address", "phone", "phone_source",
        "email", "email_source", "website", "whatsapp", "email_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)
