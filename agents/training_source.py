"""Web discovery of private training institutes.

Why this exists: OSM and Geoapify map *institutions of record* -- schools,
colleges, universities. The businesses that actually charge a fee to teach
AutoCAD (CADD Centre franchises, "CAD Academy", drafting classes, computer
institutes that added a CAD course) are almost never in OSM: they are single
shops on the second floor of a market, not civic amenities. A geo-only search
therefore returns exactly the audience a per-seat licence pitch is NOT for --
colleges and schools -- while missing every coaching centre in the city.

This source asks the open web instead. It is deliberately dumb: it produces
candidate names (plus any email/phone/website the result itself carries) and
leaves judging to the ICP and the category filter.

Name rule: a capitalised run that ends in a business noun (institute, academy,
centre, classes, solutions...). Ending position matters -- "AutoCAD Civil" and
"Architectural CADD" are COURSES on an institute's page, not institutes, and a
name whose last word is not a business noun is dropped. Locality words from the
query ("Salt Lake") are trimmed off the tail so "CADD Centre Salt Lake" becomes
"CADD Centre".

Contact attribution is strict: an email or URL is attached only when the page
names exactly one institute. Directory pages list a dozen, and handing page A's
address to name B is how a playtest reports emails that belong to nobody.

Nothing here raises: a failed search returns [] and the caller keeps whatever
the geo sources found.
"""
from __future__ import annotations

import re

# A name is only worth carrying forward when it says what the business IS...
_INSTITUTION_WORDS = (
    "institute", "institution", "centre", "center", "academy", "classes",
    "coaching", "solutions", "technologies", "technology", "studio", "school",
    "training", "computer", "cad", "cadd", "autocad", "design", "drafting",
    "draughting", "multimedia", "animation",
)
# ...and it must END in one of these, or it is a course/section heading.
_BUSINESS_TAILS = (
    "institute", "institution", "centre", "center", "academy", "classes",
    "coaching", "solutions", "technologies", "technology", "studio", "school",
    "lab", "labs",
)
_CAD_WORDS = ("cad", "cadd", "autocad", "auto cad", "drafting", "draughting",
              "draughtsman", "revit", "bim", "3ds", "sketchup", "interior design",
              "architectural", "mep", "hvac", "piping", "cam", "cnc", "cad-cam",
              "tool design")

# Hosts that are listings ABOUT institutes, never an institute's own site.
_DIRECTORY_HOSTS = (
    "justdial", "urbanpro", "sulekha", "indiamart", "quikr", "olx", "facebook",
    "linkedin", "youtube", "instagram", "twitter", "x.com", "google.", "goo.gl",
    "yelp", "wikipedia", "infoisinfo", "quickdials", "asklaila", "tripadvisor",
    "maps.app", "whatsapp", "pinterest", "reddit", "quora", "blogspot",
    "wordpress", "medium.com", "glassdoor", "naukri", "shiksha", "collegedunia",
    "careers360", "99acres", "magicbricks", "exa.ai", "tavily", "bing.", "duckduckgo",
)

# Words that start a snippet, not a business name ("Best CAD Institute ...").
_LEAD_STOPWORDS = {
    "the", "best", "top", "top10", "list", "find", "contact", "address",
    "phone", "email", "home", "about", "read", "more", "view", "call", "book",
    "join", "get", "new", "our", "your", "we", "at", "in", "near", "for",
    "with", "and", "or", "a", "an", "this", "these", "all", "leading",
    "top-rated", "verified", "popular", "famous", "trusted", "no",
    "details", "review", "reviews", "rating", "fees", "course", "courses",
    "online", "offline", "introduction", "location", "map", "directory",
    "also", "through", "since", "established", "welcome", "official",
}
# A trailing fragment of an address is not part of the name.
_ADDRESS_TAILS = {
    "road", "rd", "street", "st", "lane", "ln", "nagar", "colony", "sector",
    "block", "floor", "building", "complex", "market", "bazar", "bazaar",
    "more", "para", "pally", "bagan", "tala", "hat", "station", "metro",
    "india", "bengal", "district", "near", "opposite", "opp", "beside",
}
_CONNECTORS = {"of", "and", "for", "the", "&", "de", "at", "in", "on", "to"}

_CAD_QUERY = (
    '"{cad}" training institute {loc} contact email phone',
    '"CADD centre" {loc} address phone email',
    'AutoCAD coaching classes {loc} fees contact number',
    'drafting design training institute {loc} admission contact',
    'computer institute {loc} autocad course contact email',
    # Segments that teach AutoCAD without naming it: the Autodesk Authorized
    # Training Centre network (every ATC must hold licensed seats), BIM/Revit,
    # MEP/HVAC drafting, CNC/CAM, quantity surveying and interior design courses.
    # These are the "training ideas" the segment research surfaced -- all private, all fee-paying.
    'Autodesk authorized training centre {loc} contact email',
    '"Revit" "BIM" training institute {loc} contact email',
    'MEP HVAC drafting training institute {loc} contact email',
    'CNC CAM cad training centre {loc} contact phone',
    'quantity surveying estimation course institute {loc} contact',
    'interior design drafting institute {loc} contact email',
    'structural drafting piping design training institute {loc} contact',
)

_NAME_RUN = re.compile(
    r"[A-Z][A-Za-z0-9&.'\u2019\-]*"
    r"(?:\s+(?:of|and|&|for|the|de|[A-Z][A-Za-z0-9&.'\u2019\-]*)){0,6}"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?91[\s\-]?)?([6-9]\d{9})\b")


def available() -> bool:
    """True when some web search backend is usable (keyed or keyless)."""
    try:
        from agents import outreach_apis
        st = outreach_apis.status()
        if st.get("tavily") or st.get("exa"):
            return True
    except Exception:
        pass
    try:
        import ddgs  # noqa: F401
        return True
    except Exception:
        try:
            import duckduckgo_search  # noqa: F401
            return True
        except Exception:
            return False


def _is_directory(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _DIRECTORY_HOSTS)


def _key(name: str) -> str:
    """Dedupe key: spelling variants of the same institute collapse together."""
    k = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    k = re.sub(r"\bcentre\b", "center", k)
    k = re.sub(r"\binstitution\b", "institute", k)
    k = re.sub(r"\bach?ademy\b", "academy", k)
    return re.sub(r"\s+", " ", k)


def _loc_words(location: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (location or "").lower())
            if len(w) > 2}


def _tidy(name: str, loc: set[str]) -> str:
    """Trim snippet fluff off both ends of a candidate name."""
    words = [w for w in re.split(r"\s+", name.strip(" .,;:|-\u2013\u2014")) if w]
    while words and len(words[0]) <= 1:
        words.pop(0)
    while words:
        w = words[0].lower().strip(".")
        if w in _LEAD_STOPWORDS or w in _CONNECTORS or re.fullmatch(r"\d+", w):
            words.pop(0)
        else:
            break
    # A leading tail-word ("Classes CADD Centre") is a listing caption, not part
    # of the name -- but only strip it when a real name survives ("CB Classes"
    # keeps its head because nothing else is left).
    if len(words) >= 3 and words[0].lower() in _BUSINESS_TAILS:
        words.pop(0)
    # "AutoCAD Institute AutoCAD Institute" is one name captured twice.
    half = len(words) // 2
    if half and words[:half] == words[half:half * 2]:
        words = words[:half]
    # Locality + address fragments come off the tail; so do dangling joiners.
    while words:
        w = words[-1].lower().strip(".")
        if w in _ADDRESS_TAILS or w in loc or w in _CONNECTORS:
            words.pop()
        else:
            break
    out = " ".join(words).strip(" .,;:|-\u2013\u2014")
    return out if 2 <= len(out) <= 64 else ""


def _accept(name: str) -> bool:
    """A name is a business only when it ENDS in a business noun.

    Bare "Academy" / "CAD Institute" are section headings and franchise
    categories, not a name -- except a single coined word containing CAD
    (CADPOINT, CADDESK), which is exactly how several chains brand themselves.
    """
    words = name.split()
    if not 1 <= len(words) <= 7:
        return False
    last = words[-1].lower().strip(".")
    if last not in _BUSINESS_TAILS:
        return False
    if len(words) == 1:
        low = words[0].lower()
        return len(low) >= 5 and ("cad" in low or "cadd" in low)
    return True


def _segment(parts: list[str]) -> str:
    """Joined words, used on '.'-split fragments of one capitalised run."""
    return " ".join(parts)


def _names_in(text: str, loc: set[str] | None = None) -> list[str]:
    """Candidate institute names in a block of title/snippet text."""
    loc = loc or set()
    out: list[str] = []
    for m in _NAME_RUN.finditer(text or ""):
        raw = m.group(0)
        if raw.count(" ") > 6:
            continue
        # "AskLaila. CADD Centre" and "X CAD INSTITUTE. X CAD INSTITUTE" are
        # one regex run whose useful name is the LAST dotted fragment.
        frags = [f for f in raw.split(".") if f.strip()]
        name = ""
        for frag in reversed(frags):
            cand = _tidy(frag, loc)
            if cand and _accept(cand):
                name = cand
                break
        if not name:
            continue
        low = name.lower()
        words = set(re.findall(r"[a-z]+", low))
        if not words & set(_INSTITUTION_WORDS):
            continue
        if not any(w in low for w in _CAD_WORDS) and not (
                words & {"institute", "academy", "centre", "center", "classes"}):
            # "Computer Academy" is plausible but generic; keep only CAD-named
            # or clearly-institute-named runs, not bare "Training".
            if not words & {"coaching", "solutions", "technology", "technologies"}:
                continue
        if "@" in name or "http" in name or "|" in name:
            continue
        if not re.search(r"[A-Za-z]{3,}", name):
            continue
        out.append(name)
    return out


def _emails(text: str) -> list[str]:
    seen, out = set(), []
    junk_patterns = ("example.", "domain.", "email.com", "exa.ai", "tavily.", "google.",
                     "bing.", "duckduckgo.", "sentry.io", "wixpress.")
    for e in _EMAIL_RE.findall(text or ""):
        e = e.strip(".,;:)(").lower()
        if e in seen or any(x in e for x in junk_patterns):
            continue
        seen.add(e)
        out.append(e)
    return out


def _phones(text: str) -> list[str]:
    seen, out = set(), []
    for p in _PHONE_RE.findall(text or ""):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def search_training_institutes(location: str, goal: dict | None = None,
                               max_results: int = 24) -> list[dict]:
    """Find private training institutes in ``location`` via the open web.

    Returns pipeline-shaped dicts (name, category, website, email, phone,
    address, tags, source). Empty list on any failure.
    """
    if not location:
        return []
    try:
        from agents.outreach_apis import research_search
    except Exception:
        return []

    cad = "AutoCAD"
    if goal:
        kws = [str(k) for k in (goal.get("map_keywords") or [])]
        if kws and not any("cad" in k.lower() for k in kws):
            cad = kws[0]

    loc = _loc_words(location)
    queries = [q.format(loc=location, cad=cad) for q in _CAD_QUERY]
    found: dict[str, dict] = {}
    for q in queries:
        try:
            res = research_search(q, max_results=8)
        except Exception:
            continue
        for item in (res or {}).get("results") or []:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            content = str(item.get("content") or "")
            blob = f"{title}. {content}"
            names = _names_in(blob, loc)
            if not names:
                continue
            # Whose address is this? A page on the institute's own domain is
            # theirs -- even when it lists several COURSES as names (that is how
            # caddcentre.com reads). A directory listing is nobody's, so its
            # address is attached to no name at all rather than guessed.
            own_page = bool(url) and not _is_directory(url)
            if own_page:
                host = set(re.findall(r"[a-z]+", url.split("//")[-1].split("/")[0]))
                ranked = sorted(names, key=lambda n: -len(set(_key(n).split()) & host))
                best = ranked[0] if ranked and set(_key(ranked[0]).split()) & host else names[0]
                attach = {_key(best)}
            elif len(names) == 1:
                attach = {_key(names[0])}
            else:
                attach = set()
            emails = _emails(blob) if attach else []
            phones = _phones(blob) if attach else []
            site = url if (own_page and attach) else ""
            for name in names:
                k = _key(name)
                if not k:
                    continue
                rec = found.get(k)
                if rec is None:
                    mine = k in attach
                    found[k] = {
                        "name": name,
                        "lat": None, "lon": None,
                        "website": site if mine else "",
                        "phone": phones[0] if (phones and mine) else "",
                        "email": emails[0] if (emails and mine) else "",
                        "address": location,
                        "category": "training",
                        "tags": {"source": "web"},
                        "source": "web",
                    }
                    continue
                if k not in attach:
                    continue
                if not rec.get("website") and site:
                    rec["website"] = site
                if not rec.get("email") and emails:
                    rec["email"] = emails[0]
                if not rec.get("phone") and phones:
                    rec["phone"] = phones[0]

    # A truncated capture ("CADD Centre") and a fuller one ("CADD Centre
    # Computer Education & Training Centre") are the same institute; keep the
    # fuller name and merge whatever the shorter one knew.
    keys = list(found.keys())
    for a in keys:
        if a not in found:
            continue
        for b in keys:
            if b == a or b not in found or a not in found:
                continue
            if b.startswith(a + " ") or a.startswith(b + " "):
                short, long_ = (a, b) if len(a) < len(b) else (b, a)
                srec, lrec = found[short], found[long_]
                for f in ("website", "email", "phone"):
                    if not lrec.get(f) and srec.get(f):
                        lrec[f] = srec[f]
                found.pop(short, None)

    # Last gate before the ICP sees them: a one-word name must carry CAD/CADD
    # (CADPOINT, CADDESK) -- a bare "Academy" is a heading, not a customer.
    rows = [r for r in found.values()
            if len(r["name"].split()) >= 2 or "cad" in r["name"].lower()]
    # CAD-named institutes first: they are the customers, not the neighbours.
    rows.sort(key=lambda r: (0 if any(w in r["name"].lower() for w in ("cad", "draft"))
                             else 1, r["name"].lower()))
    return rows[:max_results]


def dedupe(rows: list[dict], existing: list[dict]) -> list[dict]:
    """Rows from ``rows`` whose name is not already in ``existing``."""
    seen = {_key(b.get("name") or "") for b in existing}
    return [r for r in rows if _key(r.get("name") or "") not in seen]
