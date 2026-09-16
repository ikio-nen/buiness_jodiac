"""Google Maps discovery source — Apify and Outscraper adapters.

Overpass/OSM is free but blind to many Indian institutions and small firms.
When an Apify token or Outscraper key is configured, a search that comes up
empty on Overpass fails over to Google Maps for that area, using whichever
provider is configured (Apify preferred, Outscraper second).

Every provider row is converted into the SAME dict shape as map_search:
    name, lat, lon, website, phone, email, address, opening_hours,
    category, tags, source ("gmaps:apify"/"gmaps:outscraper")

No keys configured → `available()` is False and the search path never
touches this module.
"""
import json
import subprocess
import time
import urllib.parse
import urllib.request

from agents.config import get_apify_token, get_outscraper_key

UA = "JARVIS-Outreach/1.0 (business contact finder)"
CURL_TIMEOUT = 90.0


def available() -> bool:
    """True when at least one Google Maps provider key is configured."""
    try:
        return bool(get_apify_token() or get_outscraper_key())
    except Exception:
        return False


def _category_terms(category: str, goal: dict = None) -> list[str]:
    """Search terms for the Maps query — category first, then goal hints.

    The ICP still judges every result afterwards; this only decides what we
    type into the Maps search box.
    """
    terms = []
    if category:
        terms.append(category.strip())
    if goal:
        for kw in goal.get("map_keywords", []) or []:
            if kw and kw not in terms:
                terms.append(kw)
    return terms or ["business"]


def search_gmaps(lat: float, lon: float, radius_m: int,
                 category: str = "", goal: dict = None) -> list[dict]:
    """Search Google Maps around lat/lon. Returns pipeline-shaped dicts.

    Tries Apify first, then Outscraper. Returns [] on total failure — the
    caller decides what an empty result means.
    """
    terms = _category_terms(category, goal)
    errors = []
    if get_apify_token():
        try:
            rows = _via_apify(lat, lon, radius_m, terms)
            if rows:
                return [_convert(r, source="gmaps:apify") for r in rows]
            errors.append("apify: no results")
        except Exception as e:
            errors.append(f"apify: {e}")
    if get_outscraper_key():
        try:
            rows = _via_outscraper(lat, lon, radius_m, terms)
            if rows:
                return [_convert(r, source="gmaps:outscraper") for r in rows]
            errors.append("outscraper: no results")
        except Exception as e:
            errors.append(f"outscraper: {e}")
    if errors:
        print(f"  [GMAPS] {'; '.join(errors)}")
    return []


# ── Apify ──────────────────────────────────────────────────────────────
# Runs thelukasz-wiecek/google-maps-plus-scraper actor (grid search):
# POST a run, poll until SUCCEEDED, pull the default dataset.
APIFY_ACTOR = "thelukasz-wiecek~google-maps-plus-scraper"

def _via_apify(lat: float, lon: float, radius_m: int, terms: list[str]) -> list[dict]:
    token = get_apify_token()
    base = f"https://api.apify.com/v2"

    search_string = ", ".join(terms) if terms else "business"
    run_input = {
        "searchStringsArray": [search_string],
        "maxCrawledPlaces": 60,
        "locationQuery": f"location:{lat},{lon} (radius {radius_m} m)",
        "language": "en",
        "maxReviews": 0,
        "scrapeContacts": True,
        "scrapeWebsiteEmails": True,
        "deeperWebsiteScrape": False,
    }
    # Start the actor run (synchronous body, async execution).
    req = urllib.request.Request(
        f"{base}/acts/{APIFY_ACTOR.replace('~', '/')}/runs?token={urllib.parse.quote(token)}",
        data=json.dumps(run_input).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        run = json.loads(resp.read().decode("utf-8")).get("data", {})

    run_id = run.get("id", "")
    if not run_id:
        raise RuntimeError(f"apify did not return a run id ({run.get('status', '?')})")

    # Poll until the run finishes (actors take 1-5 minutes for a small grid).
    body = run
    deadline = time.monotonic() + 420.0
    status = run.get("status", "READY")
    while status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT") and time.monotonic() < deadline:
        time.sleep(6)
        req = urllib.request.Request(
            f"{base}/acts/{APIFY_ACTOR.replace('~', '/')}/runs/{run_id}?token={urllib.parse.quote(token)}",
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8")).get("data", {})
        status = body.get("status", "UNKNOWN")

    if status != "SUCCEEDED":
        raise RuntimeError(f"apify run {status}")

    # Default dataset holds the places (announced on the run object).
    dataset_id = body.get("defaultDatasetId") or run.get("defaultDatasetId") or ""
    if not dataset_id:
        raise RuntimeError("apify run produced no dataset")
    rows, offset = [], 0
    while True:
        req = urllib.request.Request(
            f"{base}/datasets/{dataset_id}/items?token={urllib.parse.quote(token)}"
            f"&clean=true&offset={offset}&limit=200",
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            page = json.loads(resp.read().decode("utf-8"))
        rows.extend(page)
        if len(page) < 200 or len(rows) > 500:
            break
        offset += 200
    return rows


# ── Outscraper ─────────────────────────────────────────────────────────
def _via_outscraper(lat: float, lon: float, radius_m: int, terms: list[str]) -> list[dict]:
    key = get_outscraper_key()
    # Outscraper GET endpoint: coords-based search with zoom + square size.
    latlng = f"{lat},{lon}"
    params = {
        "query": ", ".join(terms) if terms else "business",
        "limit": 60,
        "latlng": latlng,
        "zoom": _zoom_for_radius(radius_m),
        "async": "false",
        "language": "en",
        "region": "IN",
    }
    url = ("https://api.outscraper.cloud/maps/search-v3?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"X-API-KEY": key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=CURL_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # Non-async returns {"status": "OK", "data": [[rows...]]}
    rows = (data.get("data") or [[]])[0]
    return rows


def _zoom_for_radius(radius_m: int) -> int:
    """Rough zoom that keeps the square ≈ radius. Maps API convention."""
    r = max(int(radius_m), 500)
    for z, meters in ((15, 1600), (14, 3200), (13, 6400), (12, 13000), (11, 26000)):
        if r <= meters:
            return z
    return 10


# ── Row conversion ─────────────────────────────────────────────────────
# Provider rows are flat dicts with overlapping-but-different field names;
# both are handled here so the pipeline sees one shape.

def _first(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return default


def _convert(row: dict, source: str) -> dict:
    website = _first(row, "website", "site", "webPages", default="")
    category = _first(row, "category", "type", "categories", default="")
    if isinstance(category, list):
        category = ", ".join(str(c) for c in category[:3])
    address = _first(row, "address", "location", "fullAddress", default="")
    if isinstance(address, dict):  # Outscraper nested address
        address = address.get("freeform", "") or str(address)
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    emails = _extract_emails_from_row(row)
    return {
        "name": _first(row, "title", "name", "productName", default="?"),
        "lat": row.get("latitude") or loc.get("lat"),
        "lon": row.get("longitude") or loc.get("lng"),
        "website": website if str(website).startswith("http") else "",
        "phone": _first(row, "phone", "phoneUnformatted", "phoneNumber", default=""),
        "email": "; ".join(emails[:3]),
        "address": address,
        "opening_hours": _first(row, "openingHours", default=""),
        "category": category or "other",
        "tags": {"source": source},
        "source": source,
    }


def _extract_emails_from_row(row: dict) -> list[str]:
    """Emails may arrive as a list (Apify scrapeWebsiteEmails) or a string."""
    emails = row.get("emails")
    if isinstance(emails, list):
        return [e for e in emails if isinstance(e, str) and "@" in e]
    if isinstance(emails, str) and "@" in emails:
        return [emails]
    return []
