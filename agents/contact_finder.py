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


def _fetch(url: str, timeout: int = 8):
    """Fetch a page. Returns the scrapling response or None. Never raises."""
    try:
        return Fetcher.get(url, timeout=timeout)
    except Exception:
        return None


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


def _probe_domain(domain: str, tokens: list[str]) -> str | None:
    """Return the working base URL if the domain hosts the business, else None."""
    for scheme in ("https://", "http://"):
        page = _fetch(scheme + domain, timeout=6)
        if page is not None:
            text = _page_text(page)
            if _looks_official(text, tokens):
                return scheme + domain
            return None  # resolves but wrong site -- don't keep the domain
    return None


def _official_site_from_search(name: str) -> str:
    """Bing search for the official site; first non-aggregator hit wins."""
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
                            max_fetches: int = 12) -> dict:
    """Hunt one business's email. Returns {email, domain, source, verified}.

    Order: existing website -> Bing-found site -> probed name domains.

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

    # Candidate homepages, each with whether it is known to be this business:
    # its own listed site and a search-verified site are; a probed domain is not.
    homepages: list[tuple[str, bool]] = []
    if biz.get("website"):
        homepages.append((biz["website"] if biz["website"].startswith("http")
                          else "https://" + biz["website"], True))

    if budget_left():
        fetches += 1
        site = _official_site_from_search(name)
        if site and site not in [h for h, _ in homepages]:
            homepages.append((site, True))

    if budget_left():
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
        emails = _extract_emails(_page_text(page)) or _extract_emails(
            getattr(page, "html_content", "") or "")
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
            emails = _extract_emails(_page_text(c_page)) or _extract_emails(
                getattr(c_page, "html_content", "") or "")
            if emails:
                found_email = emails[0]
                found_domain = re.sub(r"^https?://", "", hp).split("/")[0]
                source = "contact_page"
                verified = is_verified
                break
        if found_email:
            break

    return {"email": found_email, "domain": found_domain, "source": source,
            "verified": verified}


def find_contacts(businesses: list[dict], sleep_between: float = 0.4,
                  log=print, budget: float = 120.0) -> dict:
    """Hunt emails for every business that lacks one. Mutates in place.

    Runs inside a total time budget. Each business gets an equal share of what
    is left, so a batch of misses is bounded instead of costing 45s x N, and no
    single hunt can eat the whole batch.

    Returns {searched, found, empty, guessed, results:[{name, email, domain,
    source, verified}]}.
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
                        "verified": hit.get("verified", False)})
        time.sleep(sleep_between)

    return {"searched": searched, "found": found, "empty": empty,
            "guessed": guessed, "results": results}
