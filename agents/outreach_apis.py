"""Free-tier outreach APIs behind thin stdlib clients (urllib, zero new deps).

Every function returns a dict and NEVER raises — failures come back as
{"error": "..."} so the pipeline degrades instead of crashing. Keys live in
env vars only (never in code, never in git), mirroring the provider-key rule:

  RESEND_API_KEY / BREVO_API_KEY      email sending (Resend 3k/mo free,
                                      Brevo 300/day free — no card either)
  OUTREACH_FROM_EMAIL                 sender address for both
  TAVILY_API_KEY                      AI-optimized search + extract
                                      (1k credits/mo recurring, no card)
  GEOAPIFY_API_KEY                    geocoding + Places with phone/website
                                      fields (3k credits/day, no card)
  REACHER_URL                         self-hosted Reacher email verifier
                                      (default http://localhost:8080, truly $0)

research_search() is the preferred entry for new code: Tavily when keyed,
keyless ddgs otherwise — so research works with zero signup and upgrades
itself the moment a Tavily key appears.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

_TIMEOUT_S = 30
_UA = {"User-Agent": "jodiac-agent/1.0"}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    """POST JSON, return parsed JSON. Raises on HTTP/transport failure."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", **_UA, **(headers or {})},
        method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={**_UA, **(headers or {})},
                                 method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fail(fn_name: str, e: Exception) -> dict:
    return {"error": f"{fn_name}: {type(e).__name__}: {str(e)[:160]}"}


# ── Email sending ────────────────────────────────────────────────────

def _from_addr() -> str:
    return _env("OUTREACH_FROM_EMAIL")


def resend_send(to_email: str, subject: str, body: str,
               from_email: str = "") -> dict:
    """Send via Resend (3k/mo free, no card). Returns {"status": "sent",
    "id": ...} or {"error": ...}."""
    key = _env("RESEND_API_KEY")
    if not key:
        return {"error": "RESEND_API_KEY not set"}
    sender = from_email or _from_addr()
    if not sender:
        return {"error": "OUTREACH_FROM_EMAIL not set"}
    try:
        r = _post("https://api.resend.com/emails",
                  {"from": sender, "to": [to_email],
                   "subject": subject, "text": body},
                  headers={"Authorization": f"Bearer {key}"})
        return {"status": "sent", "id": r.get("id", ""), "to": to_email,
                "via": "resend"}
    except Exception as e:
        return _fail("resend_send", e)


def brevo_send(to_email: str, subject: str, body: str,
               from_email: str = "") -> dict:
    """Send via Brevo (300/day free, no card) — the volume backup sender."""
    key = _env("BREVO_API_KEY")
    if not key:
        return {"error": "BREVO_API_KEY not set"}
    sender = from_email or _from_addr()
    if not sender:
        return {"error": "OUTREACH_FROM_EMAIL not set"}
    try:
        r = _post("https://api.brevo.com/v3/smtp/email",
                  {"sender": {"email": sender},
                   "to": [{"email": to_email}],
                   "subject": subject, "textContent": body},
                  headers={"api-key": key})
        return {"status": "sent", "id": r.get("messageId", ""), "to": to_email,
                "via": "brevo"}
    except Exception as e:
        return _fail("brevo_send", e)


# ── Research: search + extract ───────────────────────────────────────

def tavily_search(query: str, max_results: int = 5) -> dict:
    """Tavily search (1k credits/mo recurring, no card, agent-friendly ToS).

    Returns {"results": [{title, url, content}]} or {"error": ...}."""
    key = _env("TAVILY_API_KEY")
    if not key:
        return {"error": "TAVILY_API_KEY not set"}
    try:
        r = _post("https://api.tavily.com/search",
                  {"query": query, "max_results": max_results,
                   "include_answer": False},
                  headers={"Authorization": f"Bearer {key}"})
        return {"results": [
            {"title": it.get("title", ""), "url": it.get("url", ""),
             "content": (it.get("content", "") or "")[:2000]}
            for it in r.get("results", [])]}
    except Exception as e:
        return _fail("tavily_search", e)


def tavily_extract(urls: list[str], query: str = "") -> dict:
    """Tavily extract: clean page text for URLs. Returns
    {"results": [{url, text}]} or {"error": ...}."""
    key = _env("TAVILY_API_KEY")
    if not key:
        return {"error": "TAVILY_API_KEY not set"}
    try:
        payload: dict = {"urls": urls}
        if query:
            payload["query"] = query
        r = _post("https://api.tavily.com/extract", payload,
                  headers={"Authorization": f"Bearer {key}"})
        return {"results": [
            {"url": it.get("url", ""),
             "text": (it.get("raw_content", "") or "")[:8000]}
            for it in r.get("results", [])]}
    except Exception as e:
        return _fail("tavily_extract", e)


def _ddgs_search(query: str, max_results: int = 5) -> dict:
    """Keyless ddgs fallback (zero signup). Never raises."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # legacy package name
        out = []
        with DDGS() as ddgs:
            for it in ddgs.text(query, max_results=max_results,
                                region="in-en"):
                out.append({"title": it.get("title", ""),
                            "url": it.get("href", ""),
                            "content": (it.get("body", "") or "")[:2000]})
        return {"results": out, "via": "ddgs"}
    except Exception as e:
        return _fail("ddgs_search", e)


def research_search(query: str, max_results: int = 5) -> dict:
    """Preferred search entry: Tavily when keyed, keyless ddgs otherwise."""
    if _env("TAVILY_API_KEY"):
        r = tavily_search(query, max_results=max_results)
        if "error" not in r:
            r["via"] = "tavily"
            return r
    return _ddgs_search(query, max_results=max_results)


# ── Geoapify: geocoding + Places (zero-card Google Places substitute) ─

def geoapify_geocode(text: str) -> dict:
    """Forward geocode. Returns {"results": [{lat, lon, label}]}."""
    key = _env("GEOAPIFY_API_KEY")
    if not key:
        return {"error": "GEOAPIFY_API_KEY not set"}
    try:
        url = ("https://api.geoapify.com/v1/geocode/search?text="
               + urllib.parse.quote(text)
               + f"&limit=5&apiKey={urllib.parse.quote(key)}")
        r = _get(url)
        return {"results": [
            {"lat": f["properties"].get("lat"),
             "lon": f["properties"].get("lon"),
             "label": f["properties"].get("formatted", "")}
            for f in r.get("features", [])]}
    except Exception as e:
        return _fail("geoapify_geocode", e)


def geoapify_places(lat: float, lon: float, categories: str,
                    radius_m: int = 5000, limit: int = 50) -> dict:
    """Places search with phone/website fields (caching allowed).
    categories e.g. "education.school,commercial". Returns
    {"results": [{name, categories, phone, website, lat, lon, address}]}."""
    key = _env("GEOAPIFY_API_KEY")
    if not key:
        return {"error": "GEOAPIFY_API_KEY not set"}
    try:
        url = ("https://api.geoapify.com/v2/places?categories="
               + urllib.parse.quote(categories)
               + f"&filter=circle:{lon},{lat},{radius_m}"
               + f"&limit={limit}&apiKey={urllib.parse.quote(key)}")
        r = _get(url)
        out = []
        for f in r.get("features", []):
            p = f.get("properties", {})
            out.append({"name": p.get("name", ""),
                        "categories": p.get("categories", []),
                        "phone": p.get("contact:phone", "") or p.get("phone", ""),
                        "website": p.get("website", ""),
                        "lat": p.get("lat"), "lon": p.get("lon"),
                        "address": p.get("formatted", ""),
                        "source": "geoapify"})
        return {"results": out}
    except Exception as e:
        return _fail("geoapify_places", e)


# ── Reacher: self-hosted email verification (truly $0, unlimited) ────

def reacher_verify(email: str) -> dict:
    """Verify one address against a self-hosted Reacher instance.

    REACHER_URL env (default http://localhost:8080). Returns
    {"reachable": "safe"|"risky"|"invalid"|"unknown", "detail": {...}}."""
    base = _env("REACHER_URL") or "http://localhost:8080"
    try:
        r = _post(base.rstrip("/") + "/v0/check_email",
                  {"to_email": email})
        return {"reachable": r.get("is_reachable", "unknown"),
                "detail": {k: v for k, v in r.items()
                           if k in ("is_reachable", "is_valid_syntax",
                                    "is_disposable", "is_role_account",
                                    "mx", "smtp")}}
    except Exception as e:
        return _fail("reacher_verify", e)


# ── Introspection ────────────────────────────────────────────────────

def status() -> dict:
    """Which outreach APIs are keyed and ready. Values are booleans only —
    never key material."""
    return {
        "resend": bool(_env("RESEND_API_KEY")),
        "brevo": bool(_env("BREVO_API_KEY")),
        "tavily": bool(_env("TAVILY_API_KEY")),
        "geoapify": bool(_env("GEOAPIFY_API_KEY")),
        "reacher_url": _env("REACHER_URL") or "http://localhost:8080",
        "from_email_set": bool(_from_addr()),
    }
