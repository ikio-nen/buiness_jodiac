"""Search businesses via Overpass API and filter those without websites.

Bug fix: Overpass data was not URL-encoded, causing silent failures.
Added: Web search verification to catch businesses with websites not tagged in OSM.
"""
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from .config import OVERPASS_URLS

CATEGORIES = [
    "shop", "amenity", "office", "craft",
    "healthcare", "leisure", "tourism",
]


def geocode(query: str) -> dict | None:
    """Geocode an address to lat/lon via Nominatim."""
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
    result = subprocess.run(
        ["curl", "-s", "-H", "User-Agent: AgentSystem/1.0", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", timeout=10,
    )
    data = json.loads(result.stdout)
    if not data:
        return None
    return {
        "lat": float(data[0]["lat"]),
        "lon": float(data[0]["lon"]),
        "display": data[0].get("display_name", ""),
    }


# Geoapify's place taxonomy has no 1:1 Overpass equivalent, so the fallback
# asks for the business-shaped buckets once and lets the pipeline's own
# category filter judge the names. Geoapify is the zero-card Google Places
# substitute named in AGENTS.md; using it here means a blocked Overpass (the
# mirrors are unreachable from some networks) degrades search instead of
# ending it.
# Verified against the live Places API: these six buckets return named POIs, and
# adding accommodation/entertainment/sport either drags in unnamed OSM building
# footprints (building.accommodation) or empties the whole response.
_GEOAPIFY_BUCKETS = "commercial,education,healthcare,catering,service,office"


# Overpass is asked for every business tag in the area and the ICP filters
# afterwards, which works because OSM has thousands of rows to choose from.
# Geoapify answers with a few dozen, so that same strategy handed back whichever
# 50 places happen to be densest -- "schools in Rajwada" came back as a street of
# pharmacies, and every search in an area returned an identical list. One
# keyword table keeps the fallback on the category the user asked for; anything
# unrecognised keeps the broad set.
_CATEGORY_HINTS = (
    (("school", "vidyalaya", "k-12"), "education.school"),
    (("college", "university", "institute", "polytechnic", "campus"),
     "education.college,education.university"),
    # Coaching centres and training institutes are tagged as schools in
    # Geoapify's taxonomy; education.language_school is the only "coaching"
    # bucket it accepts and it is empty across Indian cities.
    (("coaching", "tuition", "tutorial", "training", "academy"),
     "education.school"),
    (("cafe", "coffee"), "catering.cafe"),
    (("restaurant", "food", "dhaba"), "catering.restaurant"),
    (("pharmacy", "medical", "chemist"), "healthcare.pharmacy"),
    (("hospital", "clinic"), "healthcare.hospital,healthcare.clinic"),
    (("gym", "fitness"), "sport.fitness"),
    (("hotel", "lodge", "guest house"), "accommodation.hotel"),
    (("office", "company", "firm"), "office"),
)


def _hint_buckets(phrase: str | None) -> str:
    """Geoapify buckets for the user's category phrase, or "" if unrecognised."""
    q = (phrase or "").lower()
    for words, buckets in _CATEGORY_HINTS:
        if any(w in q for w in words):
            return buckets
    return ""


# Geoapify mixes the place's business taxonomy with unrelated facility tags
# ("internet_access.free", "highway.residential"), and the facility tag is
# often LAST — taking raw[-1] labelled a college "free" and a pharmacy
# "residential". Only roots that describe a business are considered, deepest
# path wins.
_BIZ_ROOTS = ("commercial", "education", "catering", "healthcare", "service",
              "office", "entertainment", "sport", "tourism", "shop",
              "leisure", "production", "rental", "childcare")


def _geoapify_category(raw: list[str]) -> str:
    """Most specific business category as a plain word (education.school)."""
    best = ""
    for c in raw or []:
        if not isinstance(c, str) or not c:
            continue
        if c.split(".", 1)[0] not in _BIZ_ROOTS:
            continue
        if c.count(".") > best.count("."):
            best = c
    leaf = best.rsplit(".", 1)[-1].replace("_", " ").strip() if best else ""
    return leaf or "other"


def _geoapify_rows(payload: dict) -> list[dict]:
    """Shape a Geoapify response into the Overpass row contract, dropping
    unnamed POIs and duplicate names (a place often appears twice)."""
    out: list[dict] = []
    seen: set[str] = set()
    for r in payload.get("results", []) or []:
        name = (r.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        cat = _geoapify_category(r.get("categories"))
        out.append({
            "name": name,
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "website": r.get("website", "") or "",
            "phone": r.get("phone", "") or "",
            "email": "",
            "address": r.get("address", "") or "",
            "opening_hours": "",
            "category": cat,
            "tags": {"source": "geoapify", "category": cat},
        })
    return out


def _from_geoapify(lat: float, lon: float, radius: int,
                   phrase: str | None = None) -> list[dict] | None:
    """Overpass-shaped results from Geoapify, or None when it can't help.

    Same dict contract as the Overpass branch so every downstream stage
    (no-website filter, category filter, ICP, evidence notes) keeps working.
    The user's category phrase narrows the request; if that bucket is empty
    here, the broad business set is tried before giving up."""
    try:
        from .outreach_apis import geoapify_places
    except Exception:
        return None
    hint = _hint_buckets(phrase)
    for buckets in ([hint, _GEOAPIFY_BUCKETS] if hint else [_GEOAPIFY_BUCKETS]):
        payload = geoapify_places(lat, lon, buckets,
                                  radius_m=max(radius, 1000), limit=50)
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        rows = _geoapify_rows(payload)
        if rows:
            return rows
    return None


def search_businesses(lat: float, lon: float, radius: int = 2000,
                      categories: list[str] | None = None,
                      phrase: str | None = None) -> list[dict]:
    """Search for businesses near lat/lon via Overpass API.

    ``phrase`` is the user's own category wording ("schools", "coaching
    centres"). Overpass ignores it -- it fetches every category and the ICP
    filters afterwards -- but the places fallback uses it, because it only
    returns a few dozen rows and picking them blind drops the query.
    """
    if categories is None:
        categories = CATEGORIES

    parts = []
    for c in categories:
        parts.append(f'node["{c}"](around:{radius},{lat},{lon});')
        parts.append(f'way["{c}"](around:{radius},{lat},{lon});')
        parts.append(f'relation["{c}"](around:{radius},{lat},{lon});')

    query = '[out:json][timeout:25];(' + "".join(parts) + ");out center;"

    # URL-encode and send, falling through primary -> mirrors.
    encoded_data = urllib.parse.quote(query)

    # The whole lookup runs inside one time budget: a slow mirror used to hang
    # the search for minutes, and an unhandled socket timeout on any endpoint
    # killed it outright instead of moving on to the next one. Each endpoint
    # gets its own slice of the budget so a hanging primary can never eat the
    # time its mirrors would need -- failover must actually be reachable.
    data = None            # first NON-EMPTY JSON payload wins
    empty_endpoints = set()  # endpoints that answered valid JSON but 0 elements
    failure = ""
    deadline = time.monotonic() + 100.0
    per_endpoint = 100.0 / max(len(OVERPASS_URLS), 1)

    for url in OVERPASS_URLS:  # primary first, then mirrors
        url_deadline = time.monotonic() + per_endpoint
        for attempt in range(2):
            budget = min(deadline, url_deadline) - time.monotonic()
            if budget <= 5:
                break
            try:
                result = subprocess.run(
                    ["curl", "-s", "-X", "POST", url,
                     "-H", "User-Agent: JARVIS-Outreach/1.0 (business contact finder)",
                     "-d", f"data={encoded_data}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    encoding="utf-8", errors="replace", timeout=min(40.0, budget),
                )
            except subprocess.TimeoutExpired:
                failure = f"{url} timed out"
            except OSError as e:
                failure = f"{url} unavailable ({e})"
            else:
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        payload = json.loads(result.stdout)
                    except json.JSONDecodeError:
                        failure = f"{url} returned invalid JSON"
                    else:
                        if payload.get("elements"):
                            data = payload
                            break
                        # A mirror that doesn't serve this region (or is
                        # degraded) answers VALID JSON with 0 elements. That
                        # used to be accepted as success, so a rate-limited
                        # primary followed by an empty mirror reported
                        # "Found 0" for a town that has 60+ businesses. An
                        # empty answer is only trustworthy if EVERY endpoint
                        # agrees -- remember it and keep trying.
                        empty_endpoints.add(url)
                        failure = f"{url} answered empty (0 elements)"
                else:
                    failure = f"{url} returned nothing (curl {result.returncode})"
            time.sleep(2 * (attempt + 1))  # backoff: 2s, 4s
        if data is not None or time.monotonic() >= min(deadline, url_deadline):
            break

    if data is None:
        if len(empty_endpoints) == len(OVERPASS_URLS):
            # Every endpoint answered with a real, empty dataset: genuinely
            # no OSM data here. That is an honest empty, not an error.
            data = {"elements": []}
        else:
            # Every mirror unreachable is a network condition, not an empty
            # region. Try the configured places provider before giving up.
            fallback = _from_geoapify(lat, lon, radius, phrase=phrase)
            if fallback:
                print(f"  [map] Overpass unreachable — Geoapify returned "
                      f"{len(fallback)} businesses")
                return fallback
            mirror_note = (f"; {len(empty_endpoints)} mirror(s) answered empty "
                           f"for this region") if empty_endpoints else ""
            raise RuntimeError(f"Overpass API failed on all {len(OVERPASS_URLS)} "
                               f"endpoints ({failure}{mirror_note}); no places "
                               f"fallback available (set GEOAPIFY_API_KEY)")
    businesses = []
    seen_names = set()

    # Tags that are NOT real businesses (parks, playgrounds, churches, govt)
    EXCLUDE_TAGS = {
        ("leisure", "park"), ("leisure", "playground"),
        ("leisure", "sports_centre"), ("leisure", "pitch"),
        ("amenity", "place_of_worship"), ("amenity", "townhall"),
        ("amenity", "public_building"), ("amenity", "community_centre"),
        ("amenity", "fountain"), ("amenity", "shelter"),
        ("tourism", "attraction"), ("tourism", "viewpoint"),
    }

    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name", tags.get("brand", ""))
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        # Skip non-business entries (parks, churches, playgrounds, govt)
        if any((k, tags.get(k)) in EXCLUDE_TAGS for k in tags):
            continue

        el_lat = el.get("lat") or el.get("center", {}).get("lat")
        el_lon = el.get("lon") or el.get("center", {}).get("lon")

        website = tags.get("website", tags.get("contact:website", ""))

        businesses.append({
            "name": name,
            "lat": el_lat,
            "lon": el_lon,
            "website": website,
            "phone": tags.get("phone", tags.get("contact:phone", "")),
            "email": tags.get("email", tags.get("contact:email", "")),
            "address": _format_address(tags),
            "opening_hours": tags.get("opening_hours", ""),
            "category": tags.get("shop") or tags.get("amenity") or tags.get("office") or "other",
            "tags": tags,
        })

    return businesses


def filter_no_website(businesses: list[dict]) -> list[dict]:
    """Return only businesses that have NO website in OSM data."""
    return [b for b in businesses if not b.get("website")]


def _find_website_wikidata(name: str, location: str = "") -> str:
    """Search Wikidata for a business and return its official website."""
    query = f"{name} {location}"
    url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={urllib.parse.quote(query)}&language=en&format=json&limit=5"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgentSystem/1.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        for item in data.get("search", []):
            entity_id = item.get("id", "")
            entity_url = f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={entity_id}&format=json&props=claims"
            req2 = urllib.request.Request(entity_url, headers={"User-Agent": "AgentSystem/1.0"})
            resp2 = urllib.request.urlopen(req2, timeout=10)
            entity = json.loads(resp2.read())
            claims = entity.get("entities", {}).get(entity_id, {}).get("claims", {})

            # P856 = official website
            if "P856" in claims:
                mainsnak = claims["P856"][0].get("mainsnak", {})
                value = mainsnak.get("datavalue", {}).get("value", "")
                if isinstance(value, str) and value.startswith("http"):
                    return value
    except Exception:
        pass
    return ""


def _find_website_dns(name: str, budget: float = 3.0) -> str:
    """Try common domain patterns for a business name, within a time budget.

    Guessed domains mostly do not exist, and each dead guess used to cost a
    full socket timeout - minutes across a search. A hard budget keeps the
    contact hunt fast. The process-wide default timeout is restored afterwards
    instead of being left mutated for every other socket call in the process.
    """
    import socket
    import time

    # Strip non-alphanumeric chars for valid DNS labels
    import re as _re
    clean_slug = _re.sub(r"[^a-z0-9\-]", "", name.lower().replace(" ", "-")).strip("-")
    clean_nospace = clean_slug.replace("-", "")

    raw_candidates = [
        f"www.{clean_nospace}.com", f"www.{clean_nospace}.in", f"www.{clean_nospace}.org",
        f"www.{clean_slug}.com", f"www.{clean_slug}.in", f"www.{clean_slug}.org",
        f"{clean_nospace}.com", f"{clean_nospace}.in",
    ]
    # RFC 1035: domain <= 253 chars, each label 1..63 chars
    candidates = [
        d for d in raw_candidates
        if 4 <= len(d) <= 253 and all(1 <= len(part) <= 63 for part in d.split("."))
    ]

    deadline = time.monotonic() + budget
    previous = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(1.5)
        for domain in candidates:
            if time.monotonic() >= deadline:
                break
            try:
                socket.gethostbyname(domain)
                return f"https://{domain}"
            except (socket.gaierror, socket.timeout, OSError, UnicodeError, ValueError):
                continue
    finally:
        socket.setdefaulttimeout(previous)
    return ""


def _generate_name_variations(name: str) -> list[str]:
    """Generate name variations for better search coverage."""
    variations = [name]
    # Common abbreviations
    abbrev_map = {
        "don bosco": ["dbb", "db"],
        "st. john": ["st john", "saint john"],
        "st. mary": ["st mary", "saint mary"],
    }
    lower = name.lower()
    for full, abbrs in abbrev_map.items():
        if full in lower:
            for abbr in abbrs:
                variations.append(name.lower().replace(full, abbr).title())
                variations.append(name.lower().replace(full, abbr))
    # Try without punctuation
    clean = name.replace(".", "").replace(",", "")
    if clean != name:
        variations.append(clean)
    return list(set(variations))


def verify_website(business_name: str, location: str = "") -> str:
    """Find a real website for a business using Wikidata + DNS.
    
    Returns the URL if found, empty string if not.
    """
    # Try name variations
    for name_var in _generate_name_variations(business_name):
        # Wikidata (most reliable)
        url = _find_website_wikidata(name_var, location)
        if url:
            return url

    # DNS lookup on original name
    url = _find_website_dns(business_name)
    if url:
        return url

    return ""


def verify_no_site_businesses(businesses: list[dict], location: str = "",
                              max_verify: int = 15, budget: float = 25.0) -> list[dict]:
    """For businesses marked as no-site, verify via Wikidata + DNS.

    Updates business['website'] if a real website is found.
    Bounded by both a count and a total time budget: one slow lookup must not
    stall the whole search, and unresolved names are not worth waiting on.
    """
    import time

    no_site = [b for b in businesses if not b.get("website")]
    checked = 0
    deadline = time.monotonic() + budget

    for biz in no_site:
        if checked >= max_verify or time.monotonic() >= deadline:
            break
        name = biz.get("name", "")
        if not name:
            continue

        checked += 1
        url = verify_website(name, location)
        if url:
            biz["website"] = url
            biz["website_source"] = "wikidata"

    return businesses


def _format_address(tags: dict) -> str:
    parts = []
    for key in ["housenumber", "street", "road", "suburb", "city", "town",
                 "village", "state", "postcode", "country"]:
        val = tags.get(f"addr:{key}", "")
        if val:
            parts.append(val)
    return ", ".join(parts) if parts else ""
