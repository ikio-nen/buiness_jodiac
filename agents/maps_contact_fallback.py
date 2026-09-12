"""Stage: best-effort contact extraction from Google search / Maps when Hunter.io is unavailable.

Reuses scrapling.Fetcher (same stack as business_enricher.py).
For each business, does a Google web search for the business name + area and
extracts whatever phone / contact email / rating it can find. Results are
BEST-EFFORT — Google is JS-heavy and will often return nothing; businesses
that come back empty are reported so the caller knows.

Populates (best-effort) on each business dict:
    phone          — first plausible phone found (or kept as-is)
    email          — first plausible contact email found (or kept as-is)
    maps_phone     — phone found via this stage (source-labeled)
    maps_email     — email found via this stage (source-labeled)
    maps_rating    — rating found via this stage
    maps_reviews   — review count found via this stage
    maps_searched  — bool: whether we actually ran the search
    maps_phone_found / maps_email_found — bool flags for the caller
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scrapling.fetchers import Fetcher

# ── patterns ──────────────────────────────────────────────────────────

PHONE_RE = re.compile(
    r"(?:(?:\+|00)[1-9]\d{0,2}[\s\-.\)]*)?"
    r"(?:\(?\d{2,4}\)?[\s\-.]*)?"
    r"\d[\d\s\-.]{5,}\d"
)
# Keep only candidates that look like real phones after stripping non-digits.
def _looks_like_phone(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw)
    return 7 <= len(digits) <= 15 and digits.startswith(("91", "97", "98", "6", "7", "8")) or len(digits) >= 10

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

RATING_RE = re.compile(r"(\d(?:\.\d)?)\s*[\/5s][-– ]?(?:\(?\d[\d,]*\"?\s*)?(?:reviews?|ratings?|ratings? reviews?)", re.I)
SHORT_RATING_RE = re.compile(r"(?<!\d)(\d(?:\.\d)?)\s*(?:/|out of)\s*5\b", re.I)

SKIP_EMAILS = {"example@", "test@", "noreply@", "no-reply@", "support@", "info@", "contact@"}
SKIP_PHONE_CTX = ("call", "whatsapp", "booking", "appointment", "emergency", "helpline", "toll")


def _first_phone(text: str) -> str:
    cands = []
    for m in PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        if not _looks_like_phone(raw):
            continue
        low = raw.lower()
        if any(s in low for s in SKIP_PHONE_CTX):
            continue
        cands.append(raw)
    return cands[0] if cands else ""


def _first_email(text: str) -> str:
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).strip().lower()
        if any(s in e for s in SKIP_EMAILS):
            continue
        return e
    return ""


def _rating_from_text(text: str) -> tuple:
    """Return (rating: float|None, reviews: int|None)."""
    m = RATING_RE.search(text)
    if m:
        try:
            rating = float(m.group(1))
            rest = text[m.end():m.end()+60]
            rcount = re.search(r"\(?\s*(\d[\d,]*)\s*\)?", rest)
            reviews = int(rcount.group(1).replace(",", "")) if rcount else None
            return rating, reviews
        except (ValueError, IndexError):
            pass
    m2 = SHORT_RATING_RE.search(text)
    if m2:
        try:
            return float(m2.group(1)), None
        except ValueError:
            pass
    return None, None


def _search_google(business_name: str, area: str = "", timeout: int = 12) -> str:
    """Best-effort: fetch a Google web-search results page text for the business."""
    query = f"{business_name}"
    if area:
        query += f" {area}"
    query += " contact phone"
    url = f"https://www.google.com/search?q={_quote(query)}&num=10"

    try:
        page = Fetcher.get(url, timeout=timeout)
    except Exception:
        return ""

    if not page:
        return ""

    try:
        body_el = page.css("body")
        text = body_el[0].get_all_text() if body_el else ""
    except Exception:
        text = ""

    # Also grab visible link texts (often contact info shows up as link text)
    try:
        linktexts = " ".join(
            (link.attrib.get("text", "") or "").strip()
            for link in page.css("a[href]")
            if link.attrib.get("text")
        )
        text = f"{text} {linktexts}"
    except Exception:
        pass

    return text


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def extract_contact_from_maps(business: dict, timeout: int = 12) -> dict:
    """Run a best-effort Google search for one business and extract contact info.

    Returns a dict of the fields we attempted to populate, with source flags.
    The caller merges these onto the business dict.
    """
    name = business.get("name", "")
    area = business.get("address", "") or business.get("city", "")
    if not name:
        return {}

    text = _search_google(name, area, timeout=timeout)
    phone = _first_phone(text)
    email = _first_email(text)
    rating, reviews = _rating_from_text(text)

    out: dict[str, Any] = {
        "maps_searched": bool(text),
        "maps_phone": phone,
        "maps_email": email,
        "maps_rating": rating,
        "maps_reviews": reviews,
        "maps_phone_found": bool(phone),
        "maps_email_found": bool(email),
    }

    # Merge policy: prefer what the business already had unless the maps value
    # is clearly better. We never clobber an already-present email/phone with a
    # weaker guess — but we DO record the maps value alongside so the caller can
    # decide. Concretely:
    if not business.get("phone") and phone:
        out["phone"] = phone
    if not business.get("email") and email:
        out["email"] = email
    if rating is not None:
        out.setdefault("rating", rating)
    if reviews is not None:
        out.setdefault("review_count", reviews)

    return out


def enrich_with_maps_contacts(businesses: list[dict], timeout: int = 12) -> dict:
    """Run best-effort Maps/Google contact extraction across a list of businesses.

    Returns:
        {
            "businesses": list[dict]   # same objects, updated in place + returned
            "searched": int,           # how many we actually queried
            "phone_found": int,        # businesses where we got a phone
            "email_found": int,        # businesses where we got an email
            "rating_found": int,       # businesses where we got a rating
            "empty": list[str],        # names that came back with no contact info
        }
    """
    searched = 0
    phone_found = 0
    email_found = 0
    rating_found = 0
    empty: list[str] = []

    for biz in businesses:
        name = biz.get("name", "?")
        delta = extract_contact_from_maps(biz, timeout=timeout)
        for k, v in delta.items():
            if k in ("maps_searched",):
                continue
            biz[k] = v
        if delta.get("maps_searched"):
            searched += 1
        if delta.get("maps_phone_found"):
            phone_found += 1
        if delta.get("maps_email_found"):
            email_found += 1
        if delta.get("maps_rating") is not None:
            rating_found += 1
        if not (delta.get("maps_phone_found") or delta.get("maps_email_found")):
            empty.append(name)

    return {
        "businesses": businesses,
        "searched": searched,
        "phone_found": phone_found,
        "email_found": email_found,
        "rating_found": rating_found,
        "empty": empty,
    }
