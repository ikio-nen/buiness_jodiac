"""Business enricher — scrapes websites to extract business details.

Uses Scrapling's adaptive parser to handle website changes gracefully.
Extracts: social media links, business hours, descriptions, contact info,
Google Maps reviews, and more.
"""
import re
from urllib.parse import urljoin, urlparse

from scrapling.fetchers import Fetcher

from .config import DATA_DIR


# ── Social media patterns ────────────────────────────────────────────
SOCIAL_PATTERNS = {
    "facebook": re.compile(r"(facebook\.com/[\w.\-]+)", re.I),
    "instagram": re.compile(r"(instagram\.com/[\w.\-]+)", re.I),
    "twitter": re.compile(r"(twitter\.com/[\w.\-]+|x\.com/[\w.\-]+)", re.I),
    "linkedin": re.compile(r"(linkedin\.com/(?:company|in)/[\w.\-]+)", re.I),
    "tiktok": re.compile(r"(tiktok\.com/@[\w.\-]+)", re.I),
    "youtube": re.compile(r"(youtube\.com/(?:c/|channel/|@)[\w.\-]+)", re.I),
    "yelp": re.compile(r"(yelp\.com/biz/[\w.\-]+)", re.I),
}

# ── Contact patterns ────────────────────────────────────────────────
PHONE_RE = re.compile(r"(?:\+?[\d\s\-\(\)]{7,15})")
EMAIL_RE = re.compile(r"[\w.\-]+@[\w.\-]+\.[a-zA-Z]{2,}")


def scrape_business(business: dict) -> dict:
    """Scrape a business website and return enriched data.
    
    Input: business dict with at least 'name' and optionally 'website'.
    Output: dict with scraped social links, description, hours, etc.
    """
    result = {
        "social_links": {},
        "description": "",
        "hours": "",
        "emails_found": [],
        "phones_found": [],
        "images": [],
        "scraped_successfully": False,
    }

    url = business.get("website", "")
    if not url:
        return result

    # Ensure URL has protocol
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        page = Fetcher.get(url, timeout=15)
    except Exception as e:
        print(f"  [SCRAPER] Failed to fetch {url}: {e}")
        return result

    if not page:
        return result

    # Get page text for pattern matching
    try:
        html = page.html_content if hasattr(page, "html_content") else ""
        body_el = page.css("body")
        body_text = body_el[0].get_all_text() if body_el else ""
    except Exception:
        body_text = ""
        html = ""

    # ── Extract social links ──────────────────────────────────────────
    all_links = page.css("a[href]")
    for link in all_links:
        href = link.attrib.get("href", "")
        full_url = urljoin(url, href)
        for platform, pattern in SOCIAL_PATTERNS.items():
            if pattern.search(full_url):
                result["social_links"][platform] = full_url

    # Also check page HTML for social links
    for platform, pattern in SOCIAL_PATTERNS.items():
        if platform not in result["social_links"]:
            match = pattern.search(html or body_text)
            if match:
                result["social_links"][platform] = (
                    match.group(1) if match.group(1).startswith("http")
                    else "https://" + match.group(1)
                )

    # ── Extract description ───────────────────────────────────────────
    # Try meta description first
    meta_desc = page.css('meta[name="description"]')
    if meta_desc:
        desc = meta_desc[0].attrib.get("content", "")
        if desc:
            result["description"] = desc[:500]

    # Fallback: first meaningful paragraph
    if not result["description"]:
        paragraphs = page.css("p")
        for p in paragraphs:
            text = p.get_all_text().strip()
            if len(text) > 50 and not text.lower().startswith(("cookie", "copyright", "©")):
                result["description"] = text[:500]
                break

    # ── Extract hours ─────────────────────────────────────────────────
    hours_patterns = [
        re.compile(r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)[\s:]+[\d:]+(?:\s*(?:am|pm))?\s*[-–to]+\s*[\d:]+(?:\s*(?:am|pm))?", re.I),
        re.compile(r"(?:open|hours|trading)[\s:]+[\w\s:\-–toampm]+", re.I),
    ]
    for pattern in hours_patterns:
        match = pattern.search(body_text)
        if match:
            result["hours"] = match.group(0).strip()[:200]
            break

    # ── Extract emails ────────────────────────────────────────────────
    emails = set(EMAIL_RE.findall(html or body_text))
    # Filter out common non-contact emails
    skip = {"example@", "test@", "noreply@", "no-reply@", "support@"}
    result["emails_found"] = [
        e for e in emails
        if not any(s in e.lower() for s in skip)
    ][:5]

    # ── Extract phones ────────────────────────────────────────────────
    phones = set(PHONE_RE.findall(body_text))
    # Filter likely phone numbers (at least 7 digits)
    result["phones_found"] = [
        p.strip() for p in phones
        if len(re.sub(r"\D", "", p)) >= 7
    ][:3]

    # ── Extract images ────────────────────────────────────────────────
    imgs = page.css("img[src]")
    for img in imgs[:5]:
        src = img.attrib.get("src", "")
        if src:
            result["images"].append(urljoin(url, src))

    result["scraped_successfully"] = True
    return result


def scrape_google_maps_reviews(business_name: str, location: str = "") -> dict:
    """Search Google Maps for reviews/ratings of a business.
    
    Returns: {"rating": float, "review_count": int, "reviews": list}
    """
    result = {"rating": 0, "review_count": 0, "reviews": []}

    query = f"{business_name} {location} reviews".strip()
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"

    try:
        page = Fetcher.get(search_url, timeout=10)
    except Exception:
        return result

    if not page:
        return result

    body_el = page.css("body")
    body = body_el[0].get_all_text() if body_el else ""

    # Try to find rating pattern like "4.5 (123 reviews)"
    rating_match = re.search(r"(\d\.\d)\s*\((\d[\d,]*)\s*review", body)
    if rating_match:
        result["rating"] = float(rating_match.group(1))
        result["review_count"] = int(rating_match.group(2).replace(",", ""))

    return result


def enrich_businesses(businesses: list[dict], scrape_reviews: bool = True) -> list[dict]:
    """Enrich a list of businesses by scraping their websites.
    
    Returns the same list with enriched data added to each business dict.

    Each business runs under a watchdog: a site whose fetch stalls past
    _SCRAPER_TIMEOUT_S (DNS lookups and some TLS handshakes can ignore the
    HTTP client's own timeout) is skipped, so one bad site can no longer
    hang the whole scrape leg with the UI stuck on "Scraping N websites".
    """
    import threading

    _SCRAPER_TIMEOUT_S = 30

    def _scrape_one(biz: dict, out: dict) -> None:
        d = scrape_business(biz)
        if scrape_reviews and not biz.get("rating"):
            d.update(scrape_google_maps_reviews(
                biz.get("name", ""),
                biz.get("address", ""),
            ))
        out.update(d)

    enriched = []
    for biz in businesses:
        print(f"  [SCRAPER] Scraping {biz.get('name', 'Unknown')}...")
        data: dict = {}
        worker = threading.Thread(target=_scrape_one, args=(biz, data), daemon=True)
        worker.start()
        # daemon+join(timeout): a site whose fetch stalls past the limit is
        # abandoned in place (its thread dies with the process); the
        # concurrent.futures result(timeout) proved unreliable on this box.
        worker.join(_SCRAPER_TIMEOUT_S)
        if worker.is_alive():
            print(f"  [SCRAPER] Timed out on {biz.get('name', '?')} "
                  f"after {_SCRAPER_TIMEOUT_S}s -- skipped")
        biz.update(data)
        enriched.append(biz)
    return enriched


def save_enrichment(businesses: list[dict], session_id: str):
    """Save enriched data to session storage."""
    from .config import save_session_data
    save_session_data(session_id, businesses, "enriched_businesses.json")
