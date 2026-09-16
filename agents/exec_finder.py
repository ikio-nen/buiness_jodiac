"""Decision-maker (CEO/founder/owner) email finder.

A scraped info@domain tells you where to send; it doesn't tell you who
reads it. With a Hunter.io key configured, this module looks up people at
the business's domain and separates:

    biz["exec_email"]   the person's direct address ('' if none found)
    biz["exec_name"]    e.g. "Anil Sharma"
    biz["exec_title"]   e.g. "Founder & Director"
    biz["exec_source"]  "hunter" | "apollo"

and — ONLY when no business address exists at all — routes the person's
email into biz["enrichment"]["email"] (and their name into
"first_name") so drafts address a human instead of a box. The generic
address always wins the to: line otherwise; it is the reliable channel.

Apollo is the optional fallback when Hunter misses or is unconfigured.

No keys → find_executives returns {"searched": 0} and costs nothing.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from agents.config import get_hunter_key, get_apollo_key

UA = "JARVIS-Outreach/1.0 (business contact finder)"
HUNTER_BASE = "https://api.hunter.io/v2"
APOLLO_BASE = "https://api.apollo.io/v1"

# Titles that mean "this person can sign a purchase order".
EXEC_TITLE = re.compile(
    r"\b(ceo|c\.e\.o|chief\s+executive|founder|co-?founder|owner|proprietor"
    r"|managing\s+director|director|principal|chairman|president"
    r"|head\s+of|director\s+principal|secretary|correspondent)\b",
    re.IGNORECASE,
)

PER_DOMAIN_SECONDS = 2.0  # be polite to the free-tier API


def find_executives(businesses: list[dict], max_seconds: float = 90.0) -> dict:
    """Attach decision-maker contacts to businesses that have a domain.

    Returns {searched, found, results: [{name, exec_email, exec_name,
    exec_title, exec_source}]}. Never raises.
    """
    out = {"searched": 0, "found": 0, "results": []}
    try:
        hunter_key = get_hunter_key()
        apollo_key = get_apollo_key()
    except Exception:
        return out
    if not hunter_key and not apollo_key:
        return out

    deadline = time.monotonic() + max_seconds
    for biz in businesses:
        if time.monotonic() >= deadline:
            break
        website = biz.get("website") or ""
        if not website:
            continue
        domain = website.replace("https://", "").replace("http://", "").split("/")[0]
        if not domain or biz.get("exec_email"):
            continue

        out["searched"] += 1
        person = None
        if hunter_key:
            person = _hunter_person(domain, hunter_key)
        if not person and apollo_key:
            person = _apollo_person(biz.get("name", ""), domain, apollo_key)

        if not person or not person.get("email"):
            time.sleep(0.3)
            continue

        biz["exec_email"] = person["email"]
        biz["exec_name"] = person.get("name", "")
        biz["exec_title"] = person.get("title", "")
        biz["exec_source"] = person.get("source", "")

        # No generic address exists → the person becomes the contact.
        if not (biz.get("email") or biz.get("maps_email")):
            enrichment = biz.get("enrichment") or {}
            enrichment.setdefault("email", person["email"])
            first = (person.get("name", "").split() or [""])[0]
            enrichment.setdefault("first_name", first)
            if person.get("title"):
                enrichment.setdefault("title", person["title"])
            biz["enrichment"] = enrichment

        out["found"] += 1
        out["results"].append({
            "name": biz.get("name", "?"),
            "exec_email": person["email"],
            "exec_name": person.get("name", ""),
            "exec_title": person.get("title", ""),
            "exec_source": person.get("source", ""),
        })
        time.sleep(PER_DOMAIN_SECONDS)

    return out


def _hunter_person(domain: str, key: str) -> dict | None:
    """Best decision-maker from Hunter domain-search, or None."""
    try:
        url = (f"{HUNTER_BASE}/domain-search?domain={urllib.parse.quote(domain)}"
               f"&limit=20&api_key={urllib.parse.quote(key)}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {}) or {}
    except Exception:
        return None

    candidates = []
    for e in data.get("emails", []) or []:
        email = (e.get("value") or "").strip()
        if not email or "@" not in email:
            continue
        if e.get("type") == "generic":
            continue  # info@/contact@ — exactly what we're trying to improve on
        title = " ".join(filter(None, [e.get("position"), e.get("seniority")]))
        first = (e.get("first_name") or "").strip()
        last = (e.get("last_name") or "").strip()
        candidates.append({
            "email": email,
            "name": f"{first} {last}".strip(),
            "title": title,
            "score": _person_score(e.get("position"), e.get("seniority")),
        })
    # Hunter also surfaces the likely owner at the top level.
    owner_first = (data.get("first_name") or "").strip()
    if owner_first:
        pass  # no email attached to it; the emails list is the real source

    if not candidates:
        return None
    candidates.sort(key=lambda c: -c["score"])
    best = candidates[0]
    if best["score"] <= 0:
        return None  # nobody executive-looking; don't send to a random intern
    return {**best, "source": "hunter"}


def _person_score(position: str, seniority: str) -> int:
    text = f"{position or ''} {seniority or ''}"
    if EXEC_TITLE.search(text):
        return 2
    if seniority and "executive" in seniority.lower():
        return 1
    return 0


def _apollo_person(company_name: str, domain: str, key: str) -> dict | None:
    """Optional Apollo fallback: org search by domain, then people by title."""
    try:
        # 1) find the organization id
        req = urllib.request.Request(
            f"{APOLLO_BASE}/mixed_companies/search",
            data=json.dumps({
                "api_key": key,
                "q_organization_domain_url": domain,
                "page": 1, "per_page": 1,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": UA},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            orgs = json.loads(resp.read().decode("utf-8"))
        org = ((orgs.get("organizations") or {}).get("accounts")
               or orgs.get("organizations") or [])
        if isinstance(org, dict):
            org = [org]
        if not org:
            return None
        org_id = org[0].get("id")
        if not org_id:
            return None

        # 2) people at that org with decision-maker titles
        req = urllib.request.Request(
            f"{APOLLO_BASE}/mixed_people/search",
            data=json.dumps({
                "api_key": key,
                "organization_ids": [org_id],
                "person_titles": ["CEO", "Founder", "Owner", "Director",
                                  "Managing Director", "Principal"],
                "page": 1, "per_page": 5,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": UA},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            people = json.loads(resp.read().decode("utf-8"))
        people = people.get("people") or []
        for p in people:
            email = p.get("email") or ""
            if not email or "@" not in email:
                continue
            name = " ".join(filter(None, [p.get("first_name"), p.get("last_name")]))
            return {"email": email, "name": name,
                    "title": p.get("title", ""), "source": "apollo"}
    except Exception:
        return None
    return None
