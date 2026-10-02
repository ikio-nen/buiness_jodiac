"""Contact finder -- hunt official websites for businesses the map search
returned without one, and scrape their contact pages for email addresses.

Why: enrich's Maps/Google fallback often finds nothing for colleges (Google
does not surface contact emails for them), so drafts end up with no `to:`.
Most Indian colleges DO have a website (usually *.ac.in / *.edu.in / *.org)
with a contact or admissions page listing an email.

Strategy per business:
1. Find the official site: Bing search for "<name> official website" and take
   the first result that is not a social/aggregator domain.
2. If no site found, probe candidate domains built from the name
   (token-join + acronym, common Indian academic TLDs).
3. On the homepage, follow up to 2 contact-ish links (contact / about /
   admissions / "reach us") and extract emails.
4. Rank extracted emails: contact/admission/admin-style local parts first;
   skip junk (noreply, sentry, example, support-desk artifacts).

Everything is best-effort and bounded: per-business time budget and fetch cap,
politeness sleep between fetches. A failure never raises to the caller.

Populates on each business dict:
    email                  — filled if it was empty (source-labeled below)
    contact_finder_email   — email found by this module ('' if none)
    contact_finder_domain  — domain the email came from ('' if none)
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote, urljoin

from scrapling.fetchers import Fetcher

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Local parts worth preferring when several emails share a page.
PREFERRED_LOCAL = (
    "contact", "info", "admission", "admin", "office", "principal",
    "registrar", "secretary", "enquiry", "inquiry", "helpdesk", "hello",
)
SKIP_LOCAL = ("noreply", "no-reply", "donotreply", "example", "test",
              "sentry", "wixpress", "u003", "cloudflare", "abuse", "postmaster",
              "support", "webmaster", "privacy", "gdpr")

# Placeholder / template addresses that HTML boilerplate ships with. These
# come from page templates (a site built from a stock theme), not real
# contacts -- sending outreach to them silently fails.
SKIP_EMAILS = ("user@domain.com", "your@email.com", "youremail@email.com",
               "email@example.com", "name@example.com", "email@domain.com",
               "username@domain.com", "info@example.com", "contact@example.com")
SKIP_DOMAINS = ("example.com", "example.org", "domain.com", "domain.org",
                "email.com", "yoursite.com", "sentry.io", "wixpress.com")

# Domains that appear in SERPs but are never the official site.
NOT_OFFICIAL = ("bing.com", "microsoft", "google.", "youtube.", "facebook.",
                "instagram.", "twitter.", "x.com", "linkedin.", "wikipedia.",
                "yelp.", "justdial.", "sulekha.", "indiamart.", " Collegedunia",
                "collegedunia.", "shiksha.", "careers360.", "quickcompany.",
                "zaubacorp.", "indiafilings.", "falconebiz.", "thecompanycheck.")

STOP_TOKENS = {"the", "of", "and", "a", "an", "in", "at", "campus", "building"}

CONTACT_LINK_RE = re.compile(
    r"contact|about\s+us|admission|reach\s+us|directory|get\s+in\s+touch|email\s+us",
    re.I,
)

# Phone harvesting (LeadHunter/website-contact-scraper strategy): tel: links
# first (cleanest signal), then Indian-format numbers from page text.
PHONE_TEXT_RE = re.compile(
    r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")
SOCIAL_DOMAINS = {
    "facebook": "facebook.com", "instagram": "instagram.com",
    "linkedin": "linkedin.com", "twitter": "twitter.com", "x": "x.com",
    "youtube": "youtube.com", "whatsapp": "wa.me", "telegram": "t.me",
}

# Tech-stack fingerprints for a pitch angle ("your site runs on X"): naive
# generator meta tags + script srcs, deliberately cheap — no wappalyzer.
TECH_SIGNATURES = (
    ("wordpress", ("wp-content", "wp-includes", "/wp-json")),
    ("shopify", ("cdn.shopify.com", "shopify.theme")),
    ("wix", ("static.wixstatic.com", "wix.com")),
    ("squarespace", ("static1.squarespace.com",)),
    ("google sites", ("sites.google.com",)),
    ("blogger", ("blogger.com", "blogspot.")),
    ("jquery (dated)", ("jquery-1.", "jquery-2.")),
)


def _extract_phones(text: str) -> list[str]:
    """Plausible Indian phone numbers from page text, deduped."""
    seen: list[str] = []
    for m in PHONE_TEXT_RE.finditer(text or ""):
        num = re.sub(r"[\s-]", "", m.group(0))
        if len(num) < 10:
            continue
        if num not in seen:
            seen.append(num)
    return seen[:4]


def _decode_cfemails(html: str) -> list[str]:
    """XOR-decode Cloudflare-protected emails (LeadHunter strategy).

    Sites obfuscate addresses as data-cfemail="<hex>" — first byte is the
    key, each following pair XORs back to a character. Many institutional
    sites hide their real contact email this way; without decoding, the
    hunter sees an empty page.
    """
    out: list[str] = []
    for m in re.finditer(r'data-cfemail="([0-9a-fA-F]+)"', html or ""):
        hx = m.group(1)
        try:
            key = int(hx[:2], 16)
            decoded = "".join(
                chr(int(hx[i:i + 2], 16) ^ key) for i in range(2, len(hx), 2))
        except ValueError:
            continue
        if EMAIL_RE.fullmatch(decoded) and decoded.lower() not in out:
            out.append(decoded.lower())
    return out


def _extract_schema_contacts(page) -> tuple[list[str], list[str]]:
    """(emails, phones) from schema.org JSON-LD structured data.

    Organization/LocalBusiness blocks carry clean "email"/"telephone"
    fields — higher signal than any regex on rendered text.
    """
    import json as _json
    emails: list[str] = []
    phones: list[str] = []
    try:
        html = getattr(page, "html_content", "") or ""
        for m in re.finditer(
                r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                html, re.S | re.I):
            try:
                data = _json.loads(m.group(1).strip())
            except Exception:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if not isinstance(node, dict):
                    continue
                e = node.get("email")
                p = node.get("telephone")
                if isinstance(e, str):
                    e = e.strip().lower().removeprefix("mailto:")
                    if EMAIL_RE.fullmatch(e) and e not in emails:
                        emails.append(e)
                if isinstance(p, str) and len(re.sub(r"\D", "", p)) >= 10:
                    pn = re.sub(r"[^0-9+]", "", p)
                    if pn not in phones:
                        phones.append(pn)
    except Exception:
        pass
    return emails, phones


def _extract_tel_links(page) -> list[str]:
    """Numbers from tel: hrefs — the cleanest signal a contact page gives."""
    seen: list[str] = []
    try:
        for a in page.css("a[href^='tel:'], a[href^=\"tel:\"]")[:20]:
            raw = (a.attrib.get("href", "") or "")[4:]
            num = re.sub(r"[^0-9+]", "", raw)
            if len(re.sub(r"\D", "", num)) >= 10 and num not in seen:
                seen.append(num)
    except Exception:
        pass
    return seen


def _extract_socials(page) -> dict[str, str]:
    """Social profile links on a page: {platform: url} (first hit wins)."""
    out: dict[str, str] = {}
    try:
        for a in page.css("a[href]")[:120]:
            href = (a.attrib.get("href", "") or "").lower()
            if not href.startswith("http"):
                continue
            for plat, dom in SOCIAL_DOMAINS.items():
                if dom in href and plat not in out:
                    out[plat] = href
    except Exception:
        pass
    return out


def _detect_tech(page) -> list[str]:
    """Cheap tech-stack hints from generator meta + script/link srcs."""
    try:
        html = (getattr(page, "html_content", "") or "").lower()
    except Exception:
        return []
    return [name for name, sigs in TECH_SIGNATURES if any(s in html for s in sigs)][:3]


def _decode_sucuri_cookie(html: str) -> tuple[str, str] | None:
    """Solve a Sucuri CloudProxy JS challenge -> (cookie_name, cookie_value).

    The gate page builds the value in a variable (o='3'+'e'+fromCharCode(99)+...)
    then does document.cookie='s'+'u'+...+"=" + o + ';path=/;...'; reload().
    Both are pure string concatenations, so they evaluate in Python: render
    each quoted/fromCharCode term, resolve variable references, then split
    name=value at the first '='. No JS runtime needed.
    """
    m = re.search(r"S='([A-Za-z0-9+/=]+)'", html or "")
    if not m:
        return None
    import base64
    try:
        script = base64.b64decode(m.group(1)).decode("utf-8", "ignore")
    except Exception:
        return None

    _TERM = re.compile(
        r"String\.fromCharCode\((\d+)\)|'([^']*)'|\"([^\"]*)\"|(\b[a-zA-Z_]\w*\b)")

    def render(expr: str, vars: dict[str, str]) -> str:
        out = []
        for code, sq, dq, ident in _TERM.findall(expr):
            if code:
                out.append(chr(int(code)))
            elif sq or dq:
                out.append(sq or dq)
            elif ident in vars:
                out.append(vars[ident])
        return "".join(out)

    vars: dict[str, str] = {}
    # Value assignments first: o='3' + 'e' + ... + '';
    for assign in re.finditer(r"\b([a-zA-Z_]\w*)\s*=\s*([^;]+);", script):
        var, expr = assign.group(1), assign.group(2)
        if "fromCharCode" in expr or "'" in expr or '"' in expr:
            vars[var] = render(expr, {k: v for k, v in vars.items() if k != var})

    cookie = re.search(r"document\.cookie\s*=\s*(.+?);\s*location\.reload", script, re.S)
    if not cookie:
        cookie = re.search(r"document\.cookie\s*=\s*(.+?);", script, re.S)
    if not cookie:
        return None
    rendered = render(cookie.group(1), vars)
    if "=" not in rendered:
        return None
    name, _, value = rendered.partition("=")
    value = value.split(";")[0].strip()
    if name and value:
        return name, value
    return None


def _fetch(url: str, timeout: int = 8):
    """Fetch a page. Returns the scrapling response or None. Never raises.

    Anti-bot aware: a Sucuri CloudProxy JS-gate stub (rare on ordinary pages,
    common on Indian institutional sites) is solved in-process — the cookie
    is computed and the fetch retried with it, no headless browser needed.
    """
    page = None
    try:
        page = Fetcher.get(url, timeout=timeout)
    except Exception:
        return None
    html = (getattr(page, "html_content", "") or "") if page is not None else ""
    if page is not None and "sucuri_cloudproxy" in html and len(html) < 4000:
        solved = _decode_sucuri_cookie(html)
        if solved:
            import time as _t
            from urllib.parse import urlsplit
            host = urlsplit(url).netloc
            try:
                Fetcher.get(url, timeout=timeout,
                            headers={"Cookie": f"{solved[0]}={solved[1]}"})
                page = Fetcher.get(url, timeout=timeout,
                                   headers={"Cookie": f"{solved[0]}={solved[1]}"})
            except Exception:
                pass
    return page


def _page_text(page) -> str:
    try:
        bodies = page.css("body")
        return bodies[0].get_all_text() if bodies else ""
    except Exception:
        return ""


def _extract_emails(text: str) -> list[str]:
    """All plausible emails on a page, junk removed, best-ranked first."""
    seen: list[str] = []
    for m in EMAIL_RE.finditer(text or ""):
        e = m.group(0).strip().lower().strip(".")
        local = e.split("@")[0]
        domain = e.split("@", 1)[1]
        if any(s in local for s in SKIP_LOCAL):
            continue
        if e in SKIP_EMAILS or any(domain == d or domain.endswith("." + d)
                                   for d in SKIP_DOMAINS):
            continue
        if any(e.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
            continue
        if e not in seen:
            seen.append(e)
    seen.sort(key=lambda e: 0 if any(p in e.split("@")[0] for p in PREFERRED_LOCAL) else 1)
    return seen


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in STOP_TOKENS and len(t) > 1]


def _looks_official(text: str, tokens: list[str]) -> bool:
    """A fetched homepage counts if it mentions at least one distinctive token."""
    low = (text or "").lower()
    distinctive = [t for t in tokens if len(t) >= 5]
    return any(t in low for t in (distinctive or tokens))


def _candidate_domains(name: str) -> list[str]:
    tokens = _name_tokens(name)
    if not tokens:
        return []
    joined = "".join(tokens)[:40]
    acronym = "".join(t[0] for t in tokens)
    short = "".join(tokens[:2])[:40]
    bases = []
    for b in (joined, short, acronym):
        if len(b) >= 4 and b not in bases:
            bases.append(b)
    tlds = (".ac.in", ".edu.in", ".in", ".org", ".com")
    return [b + t for b in bases for t in tlds][:9]


def _dns_resolves(domain: str) -> bool:
    """True when the domain name exists at all (NXDOMAIN kills 9 candidate
    domains for ~3s of retries each -- resolve check first, fetch only if
    the name is real). Never raises; an unreachable resolver says True so
    the fetch path still gets its chance."""
    try:
        import dns.resolver
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
        r.timeout = 1.5
        r.lifetime = 3
        r.resolve(domain, "A")
        return True
    except dns.resolver.NXDOMAIN:
        return False
    except Exception:
        return True  # resolver trouble -- let the HTTP fetch decide


def _probe_domain(domain: str, tokens: list[str]) -> str | None:
    """Return the working base URL if the domain hosts the business, else None."""
    if not _dns_resolves(domain):
        return None
    for scheme in ("https://", "http://"):
        page = _fetch(scheme + domain, timeout=6)
        if page is not None:
            text = _page_text(page)
            if _looks_official(text, tokens):
                return scheme + domain
            return None  # resolves but wrong site -- don't keep the domain
    return None


def _official_site_from_search(name: str, extra_search=None) -> str:
    """Search for the official site; first non-aggregator hit wins.

    `extra_search` (contact_enricher.discover_website) is the production
    discovery engine: a keyless multi-backend metasearch that fails over
    across engines. The inline Bing scrape is the fallback when it is not
    provided -- one engine's HTML layout is a single point of failure.
    """
    if extra_search is not None:
        try:
            hits = extra_search(name)
            return hits[0] if hits else ""
        except Exception:
            pass
    try:
        url = f"https://www.bing.com/search?q={quote(name + ' official website')}"
        page = _fetch(url, timeout=10)
        if page is None:
            return ""
        for li in page.css("li.b_algo")[:6]:
            links = li.css("a[href]")
            href = links[0].attrib.get("href", "") if links else ""
            if not href.startswith("http"):
                continue
            if any(bad in href.lower() for bad in NOT_OFFICIAL):
                continue
            return href
    except Exception:
        pass
    return ""


def _contact_page_urls(homepage: str, page) -> list[str]:
    """Contact-ish links on the homepage, in page order."""
    out = []
    try:
        for a in page.css("a[href]")[:80]:
            href = a.attrib.get("href", "") or ""
            text = (a.get_all_text() or "").strip() if hasattr(a, "get_all_text") else ""
            if not href.startswith(("http", "/", "./")) or href.startswith(("mailto:", "tel:", "#")):
                continue
            if CONTACT_LINK_RE.search(href) or CONTACT_LINK_RE.search(text):
                full = urljoin(homepage, href)
                if full not in out and full.rstrip("/") != homepage.rstrip("/"):
                    out.append(full)
    except Exception:
        pass
    return out[:2]


def find_email_for_business(biz: dict, max_seconds: float = 45.0,
                            max_fetches: int = 12, extra_search=None) -> dict:
    """Hunt one business's contact info on the web.

    Returns {email, domain, source, verified, phones, socials, tech}.

    Order: existing website -> Bing-found site -> probed name domains.
    Every fetched page is also mined for phones (tel: + text), social links
    and tech-stack hints, so one hunt enriches even when no email exists.

    `verified` says whether the page an address came off is confirmed to be
    THIS business: its own listed site, or a site a search engine returned for
    its name. A domain *probed from the name* is a guess, and names are not
    unique — "Don Bosco School" in Bandel probed its way to a Don Bosco school
    in Kattappana, Kerala, and harvested that school's address. Guesses are
    still returned (they are the only lead for a business with no web presence
    at all) but flagged, and callers must not treat them as a verified contact.
    """
    started = time.monotonic()
    fetches = 0

    def budget_left() -> bool:
        return (time.monotonic() - started < max_seconds) and fetches < max_fetches

    name = biz.get("name", "")
    tokens = _name_tokens(name)
    found_email, found_domain, source = "", "", ""
    verified = False
    phones: list[str] = []
    socials: dict[str, str] = {}
    tech: list[str] = []
    extra_emails: list[str] = []  # Cloudflare-decoded + schema.org addresses

    def mine(page) -> None:
        """Harvest contacts/socials/tech off any fetched page (no extra fetch)."""
        nonlocal socials, tech
        for p in _extract_tel_links(page) + _extract_phones(_page_text(page)):
            if p not in phones:
                phones.append(p)
        for k, v in _extract_socials(page).items():
            socials.setdefault(k, v)
        for t in _detect_tech(page):
            if t not in tech:
                tech.append(t)
        html = getattr(page, "html_content", "") or ""
        for e in _decode_cfemails(html) + _extract_schema_contacts(page)[0]:
            if e not in extra_emails:
                extra_emails.append(e)
        for p in _extract_schema_contacts(page)[1]:
            if p not in phones:
                phones.append(p)

    # Candidate homepages, each with whether it is known to be this business:
    # its own listed site and a search-verified site are; a probed domain is not.
    homepages: list[tuple[str, bool]] = []
    if biz.get("website"):
        homepages.append((biz["website"] if biz["website"].startswith("http")
                          else "https://" + biz["website"], True))

    if budget_left():
        fetches += 1
        site = _official_site_from_search(name, extra_search=extra_search)
        if site and site not in [h for h, _ in homepages]:
            homepages.append((site, True))

    # Probing name-guessed domains is the LAST resort: it burns a fetch
    # credit per candidate and harvests namesakes. Only when search found
    # nothing at all is a guess better than an empty result.
    if not homepages and budget_left():
        for d in _candidate_domains(name):
            if not budget_left():
                break
            fetches += 1
            base = _probe_domain(d, tokens)
            if base:
                homepages.append((base, False))
                break

    for hp, is_verified in homepages:
        if not budget_left():
            break
        page = _fetch(hp, timeout=8)
        fetches += 1
        if page is None:
            continue
        mine(page)
        emails = (_extract_emails(_page_text(page))
                  or _extract_emails(getattr(page, "html_content", "") or "")
                  or extra_emails)
        if emails:
            found_email, found_domain, source = emails[0], re.sub(r"^https?://", "", hp).split("/")[0], "homepage"
            verified = is_verified
            break
        for c_url in _contact_page_urls(hp, page):
            if not budget_left():
                break
            c_page = _fetch(c_url, timeout=8)
            fetches += 1
            if c_page is None:
                continue
            mine(c_page)
            emails = (_extract_emails(_page_text(c_page))
                      or _extract_emails(getattr(c_page, "html_content", "") or "")
                      or extra_emails)
            if emails:
                found_email = emails[0]
                found_domain = re.sub(r"^https?://", "", hp).split("/")[0]
                source = "contact_page"
                verified = is_verified
                break
        if found_email:
            break

    return {"email": found_email, "domain": found_domain, "source": source,
            "verified": verified, "phones": phones, "socials": socials,
            "tech": tech}


def find_contacts(businesses: list[dict], sleep_between: float = 0.4,
                  log=print, budget: float = 120.0) -> dict:
    """Hunt emails for every business that lacks one. Mutates in place.

    Runs inside a total time budget. Each business gets an equal share of what
    is left, so a batch of misses is bounded instead of costing 45s x N, and no
    single hunt can eat the whole batch.

    Returns {searched, found, empty, guessed, results:[{name, email, domain,
    source, verified, phones, socials, tech}]}.
    """
    searched = found = 0
    empty: list[str] = []
    guessed: list[str] = []
    results: list[dict] = []

    pending = [b for b in businesses
               if not (b.get("email") or b.get("maps_email"))]
    deadline = time.monotonic() + budget

    for idx, biz in enumerate(pending):
        remaining = deadline - time.monotonic()
        if remaining <= 3:
            log(f"  [CONTACT] budget spent, {len(pending) - idx} left unsearched")
            break
        share = max(6.0, min(45.0, remaining / max(1, len(pending) - idx)))
        searched += 1
        name = biz.get("name", "?")
        log(f"  [CONTACT] hunting email for {name}...")
        hit = find_email_for_business(biz, max_seconds=share)
        biz["contact_finder_email"] = hit["email"]
        biz["contact_finder_domain"] = hit["domain"]
        # Contact enrichment beyond the inbox (LeadHunter-style): phones,
        # socials and tech hints ride the same hunt. Only a VERIFIED source
        # may fill the primary `phone` field (same rule as `email`) — a
        # guessed domain's number is kept visible but not promoted.
        biz["contact_finder_phones"] = hit.get("phones", [])
        biz["contact_finder_socials"] = hit.get("socials", {})
        biz["contact_finder_tech"] = hit.get("tech", [])
        if hit.get("phones") and hit.get("verified") and not biz.get("phone"):
            biz["phone"] = hit["phones"][0]
        # Only a VERIFIED address is promoted to `email`, because that is the
        # field the draft/send steps use as the recipient. An address harvested
        # from a guessed domain stays visible in contact_finder_email to be
        # checked by hand, instead of being queued up to a stranger.
        if hit["email"] and hit.get("verified") and not biz.get("email"):
            biz["email"] = hit["email"]
        elif hit["email"]:
            guessed.append(hit["email"])
        if hit["email"]:
            found += 1
            how = "" if hit.get("verified") else "  [unverified — domain guessed from the name, not promoted to a recipient]"
            log(f"  [CONTACT] found {hit['email']} via {hit['domain']} ({hit['source']}){how}")
        else:
            empty.append(name)
            log(f"  [CONTACT] nothing for {name}")
        results.append({"name": name, "email": hit["email"],
                        "domain": hit["domain"], "source": hit["source"],
                        "verified": hit.get("verified", False),
                        "phones": hit.get("phones", []),
                        "socials": sorted(hit.get("socials", {})),
                        "tech": hit.get("tech", [])})
        time.sleep(sleep_between)

    return {"searched": searched, "found": found, "empty": empty,
            "guessed": guessed, "results": results}
