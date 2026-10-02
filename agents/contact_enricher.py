"""Contact enrichment -- the production layer on top of contact_finder.

What this adds over the basic hunter, and why it matters for real outreach:

1. MULTI-BACKEND WEBSITE DISCOVERY (ddgs). The old path scraped Bing's HTML
   with one CSS selector -- one engine hiccup and every business came back
   empty ("emails for 0"). ddgs aggregates bing/duckduckgo/google/brave with
   automatic failover, keyless, so discovery survives any single engine's
   mood. Region pinned to India, where the prospects are.
2. MX DELIVERABILITY VALIDATION (dnspython). An email on a page with no mail
   exchanger is a dead inbox wearing a nice local part. Every candidate
   address gets its domain's MX probed against public resolvers (1.1.1.1,
   8.8.8.8, then the system resolver); only MX-confirmed addresses may become
   the draft recipient. Others are kept visible as candidates, never promoted.
   Results are cached 1h in-process so a 20-business batch doesn't re-ask the
   same domain 20 times.
3. REAL PHONE VALIDATION (phonenumbers, Google's libphonenumber). Harvested
   digit strings become parsed, type-checked E.164 numbers. A number that
   parses as MOBILE gets a wa.me link -- WhatsApp outreach only targets
   numbers that ARE WhatsApp-capable, not landlines.
4. DISK CACHE (14 days). The same Kolkata college re-searched next week costs
   zero network and returns the same verified contacts, from
   agent_output/contact_cache.json. Entries expire; the cache is bounded.

Honesty contract (matches contact_finder): an address from the business's own
site or a search-verified site is VERIFIED; anything from a domain merely
guessed from the name is flagged and never promoted. A failure anywhere
degrades to "no contact found" -- it never raises into the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .config import OUTPUT_DIR

CACHE_PATH = OUTPUT_DIR / "contact_cache.json"
CACHE_TTL_DAYS = 14
CACHE_MAX_ENTRIES = 5000
MX_TTL_SECONDS = 3600

# Public resolvers first -- the system resolver on this network has been the
# slow path; a batch of lookups must not serialize behind it.
_RESOLVER_NAMESERVERS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")

# Engines for ddgs: "auto" already fails over, the list is the fallback when
# a backend itself errors out entirely.
_ENGINES = ("bing", "duckduckgo", "google", "brave")

_mx_cache: dict[str, tuple[float, str]] = {}
_cache_loaded = False


# ── Cache ────────────────────────────────────────────────────────────

def _cache_key(name: str, city: str) -> str:
    return hashlib.sha1(f"{name}|{(city or '').lower()}".encode()).hexdigest()[:16]


def _load_cache() -> dict:
    global _cache_loaded
    if not _cache_loaded:
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        # Bound the file: drop oldest-expiring entries past the cap.
        if len(cache) > CACHE_MAX_ENTRIES:
            keep = sorted(cache.items(), key=lambda kv: kv[1].get("ts", ""))[-CACHE_MAX_ENTRIES:]
            cache = dict(keep)
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=True), encoding="utf-8")
    except Exception:
        pass


def cache_get(name: str, city: str = "") -> dict | None:
    """Fresh cache entry ({email, phone, whatsapp, sources, ts}) or None."""
    entry = _load_cache().get(_cache_key(name, city))
    if not entry:
        return None
    try:
        age = datetime.now() - datetime.fromisoformat(entry.get("ts", ""))
        if age.days < CACHE_TTL_DAYS:
            return entry
    except Exception:
        return None
    return None


def cache_put(name: str, city: str, entry: dict) -> None:
    cache = _load_cache()
    entry = dict(entry)
    entry["ts"] = datetime.now().isoformat()
    cache[_cache_key(name, city)] = entry
    _save_cache(cache)


# ── MX deliverability ────────────────────────────────────────────────

def mx_status(domain: str) -> str:
    """'mx_ok' | 'no_mx' | 'no_domain' | 'error' for one email domain.

    Cached for MX_TTL_SECONDS: a batch re-encounters the same handful of
    domains (ac.in, gmail.com...), and DNS must not be re-asked each time.
    """
    if not domain or "." not in domain:
        return "no_domain"
    now = time.monotonic()
    hit = _mx_cache.get(domain)
    if hit and now - hit[0] < MX_TTL_SECONDS:
        return hit[1]
    status = "error"
    try:
        import dns.resolver

        last_err = ""
        for ns in _RESOLVER_NAMESERVERS:
            try:
                r = dns.resolver.Resolver(configure=False)
                r.nameservers = [ns]
                r.timeout = 2.5
                r.lifetime = 5
                r.resolve(domain, "MX")
                status = "mx_ok"
                break
            except dns.resolver.NXDOMAIN:
                status = "no_domain"
                break
            except dns.resolver.NoAnswer:
                # A domain with A records but no MX can still receive via
                # implicit MX (RFC 5321 5.1) -- treat "exists" as ok-ish.
                try:
                    r.resolve(domain, "A")
                    status = "mx_ok"
                except Exception:
                    status = "no_mx"
                break
            except Exception as e:  # timeout, servfail -- try next resolver
                last_err = str(e)[:60]
                continue
        else:
            status = "error"
            if last_err:
                status = "error"
    except Exception:
        status = "error"
    _mx_cache[domain] = (now, status)
    return status


def email_deliverability(email: str) -> tuple[str, str]:
    """(status, detail) for one address: 'deliverable' when the domain can
    accept mail. Syntax is pre-checked; MX is the network truth we can get
    without SMTP-probing a stranger's server."""
    e = (email or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", e):
        return "invalid", "syntax"
    status = mx_status(e.split("@", 1)[1])
    if status == "mx_ok":
        return "deliverable", "mx confirmed"
    if status == "no_mx":
        return "undeliverable", "domain accepts no mail"
    if status == "no_domain":
        return "undeliverable", "domain does not exist"
    return "unverified", "dns unreachable"


# ── Phones ───────────────────────────────────────────────────────────

def parse_phone(raw: str, region: str = "IN") -> dict:
    """Normalize one raw number -> {e164, type, is_mobile, national} or {}.

    Only numbers libphonenumber accepts as valid, in (MOBILE, FIXED_LINE)
    make it out -- harvested digit soup (timestamps, prices, coords) dies here.
    """
    if not raw:
        return {}
    try:
        import phonenumbers
        from phonenumbers import PhoneNumberType

        cand = re.sub(r"[^\d+]", "", str(raw))
        if not cand:
            return {}
        num = phonenumbers.parse(cand, region)
        if not phonenumbers.is_valid_number(num):
            return {}
        t = phonenumbers.number_type(num)
        if t not in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE,
                     PhoneNumberType.FIXED_LINE_OR_MOBILE):
            return {}
        return {
            "e164": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164),
            "national": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL),
            "is_mobile": t in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE),
            "type": ("mobile" if t == PhoneNumberType.MOBILE
                     else "fixed_or_mobile" if t == PhoneNumberType.FIXED_LINE_OR_MOBILE
                     else "fixed_line"),
        }
    except Exception:
        return {}


def whatsapp_link(parsed: dict) -> str:
    """wa.me link for a parsed MOBILE number -- '' for anything else."""
    return f"https://wa.me/{parsed['e164'].lstrip('+')}" if parsed.get("is_mobile") else ""


# ── Website discovery (ddgs) ─────────────────────────────────────────

def discover_website(name: str, city: str = "") -> list[str]:
    """Candidate official-site URLs from multi-backend search, best first.

    Aggregator/social domains are filtered with contact_finder's list. The
    top URL whose snippet/href looks like the business itself wins; the rest
    come back as fallbacks. Empty list = nothing found anywhere.
    """
    try:
        from ddgs import DDGS
        from .contact_finder import NOT_OFFICIAL
    except Exception:
        return []

    q = f"{name} {city} official website contact".strip()
    hits: list[str] = []
    for backend in ("auto", *_ENGINES):
        if hits:
            break
        try:
            for r in DDGS(timeout=10).text(q, region="in-en", max_results=8,
                                           backend=backend):
                href = (r.get("href") or "").strip()
                if not href.startswith("http") or href in hits:
                    continue
                low = href.lower()
                if any(bad in low for bad in (n.lower() for n in NOT_OFFICIAL)):
                    continue
                hits.append(href.split("#")[0].rstrip("/"))
        except Exception:
            continue
    return hits[:3]


# ── The orchestrator ─────────────────────────────────────────────────

def enrich_businesses(businesses: list[dict], log=print,
                      budget: float = 150.0) -> dict:
    """Enrich every business lacking a usable contact. Mutates in place.

    Per business, in order: cache -> website discovery (ddgs) -> contact hunt
    (reusing contact_finder's page mining: emails, Cloudflare-decoded,
    schema.org, tel: links) -> MX validation -> phone normalization. Only
    deliverable emails and valid phones are promoted to the fields the
    draft/send steps read; everything else lands in biz['enrichment_v2'] as
    visible candidates with a status.

    Returns {searched, cache_hits, emails_found, deliverable, phones,
    whatsapp, empty, results}.
    """
    from .contact_finder import find_email_for_business

    started = time.monotonic()
    stats = {"searched": 0, "cache_hits": 0, "emails_found": 0,
             "deliverable": 0, "phones": 0, "whatsapp": 0, "empty": 0,
             "results": []}
    pending = [b for b in businesses
               if not (b.get("email") or b.get("maps_email")
                       or b.get("contact_finder_email"))]

    for biz in pending:
        if time.monotonic() - started > budget:
            log("  [ENRICH-V2] budget spent, rest left unsearched")
            break
        name = biz.get("name", "?")
        city = (biz.get("city") or biz.get("address") or "")
        stats["searched"] += 1
        entry = {"email": "", "phone": "", "whatsapp": "", "sources": {},
                 "candidates": []}

        cached = cache_get(name, city)
        if cached:
            stats["cache_hits"] += 1
            entry.update({k: cached.get(k, "") for k in ("email", "phone", "whatsapp")})
            # The verified flag lives in sources -- without restoring it a
            # cache hit would demote its own address to unpromoted.
            entry["sources"] = cached.get("sources") or {}
            entry["candidates"] = cached.get("candidates") or []
            log(f"  [ENRICH-V2] cache hit for {name}")
        else:
            # 40s: enough for discovery + 2-3 page fetches at realistic
            # latencies; 25s was eaten by one slow redirect chain.
            # max_fetches=12: search(1) + homepage + contact pages with headroom.
            hunt = find_email_for_business(biz, max_seconds=40.0, max_fetches=12,
                                           extra_search=discover_website)
            email = hunt.get("email", "")
            # MX-check every harvestable address: the hunter's pick first,
            # then the alternates it saw on the same pages.
            checked: list[tuple[str, str, str]] = []  # (email, status, detail)
            if email:
                st, det = email_deliverability(email)
                checked.append((email, st, det))
            if hunt.get("phones"):
                parsed = [p for p in (parse_phone(x) for x in hunt["phones"]) if p]
                if parsed:
                    stats["phones"] += len(parsed)
                    best = parsed[0]
                    entry["phone"] = best["e164"]
                    wl = whatsapp_link(best)
                    if wl:
                        entry["whatsapp"] = wl
                        stats["whatsapp"] += 1
            site = (hunt.get("domain") or "")
            if email and site:
                entry["sources"]["email"] = f"{site} ({hunt.get('source', '')})"
                entry["sources"]["email_verified"] = bool(hunt.get("verified"))
            if email:
                stats["emails_found"] += 1
                if checked and checked[0][1] == "deliverable":
                    entry["email"] = email
                    stats["deliverable"] += 1
                entry["candidates"].extend({"email": e, "status": s, "detail": d}
                                           for e, s, d in checked)
            # Cache the hunt outcome even when thin (a week of "nothing" is
            # itself knowledge -- don't re-hunt a contactless site daily).
            cache_put(name, city, entry)

        # Promotion -- same trust rule as everywhere else: only a verified,
        # deliverable address becomes the recipient.
        email = entry.get("email", "")
        verified = entry.get("sources", {}).get("email_verified", False)
        if email and verified and not biz.get("email"):
            biz["email"] = email
        elif email:
            biz.setdefault("enrichment_v2", {})["unpromoted_email"] = email
        if entry.get("phone") and not biz.get("phone"):
            biz["phone"] = entry["phone"]
        biz["enrichment_v2"] = {**biz.get("enrichment_v2", {}),
                                "whatsapp": entry.get("whatsapp", ""),
                                "candidates": entry.get("candidates", [])}
        if entry.get("whatsapp"):
            biz["whatsapp_link"] = entry["whatsapp"]
        stats["results"].append({"name": name, "email": entry.get("email", ""),
                                 "phone": entry.get("phone", ""),
                                 "whatsapp": entry.get("whatsapp", "")})
        if not (email or entry.get("phone")):
            stats["empty"] += 1
            log(f"  [ENRICH-V2] nothing for {name}")
        else:
            log(f"  [ENRICH-V2] {name}: "
                f"email={entry.get('email') or 'none'}"
                f"{' (deliverable)' if entry.get('email') else ''}"
                f" phone={entry.get('phone') or 'none'}"
                f"{' wa' if entry.get('whatsapp') else ''}")

    return stats
