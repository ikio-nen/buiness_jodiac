"""HTTP surface of the office: the document, session stats, history, uploads,
the brain, the roster, the agent lifecycle, the event log and the skills
library.

Every route here is a thin read or a hand-off to a module that owns the rules
(``hiring`` owns who may be hired, ``skills`` owns the library, ``event_bus``
owns the log). Nothing in this file decides anything on its own, which is why
it can be read top to bottom as the API's table of contents.
"""

import json
import logging
import re
import secrets
from pathlib import Path

from fastapi import (APIRouter, File, HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse

from agents.web.web_session import resume_latest

logger = logging.getLogger("jarvis.api")


def _sanitize_error(e: Exception, context: str = "operation") -> dict:
    """Log full traceback server-side only and return a sanitized error with correlation ID."""
    err_id = secrets.token_hex(4)
    logger.exception(f"Internal error during {context} [error_id={err_id}]: {e}")
    return {
        "error": f"An internal error occurred while processing {context}.",
        "error_id": err_id,
    }

# Strict identifier regex to prevent path traversal, IDOR probing, and SQL/command injection
ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
ALLOWED_VAULT_KEYS = {
    "gemini_api_key",
    "ai_provider_key",
    "gmail_app_password",
    "gmail_user",
}


def _safe_report_path(raw_path: str, default_pattern: str) -> Path:
    """Safely validate that a report file path resolves strictly within the reports directory."""
    from agents.config import OUTPUT_DIR
    reports_dir = (OUTPUT_DIR / "reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    if raw_path:
        try:
            candidate = Path(raw_path).resolve()
            # Path must exist, be a file, end in .pdf, and be strictly located within reports_dir
            if (
                candidate.is_file()
                and candidate.suffix.lower() == ".pdf"
                and str(candidate).startswith(str(reports_dir))
            ):
                return candidate
        except Exception:
            pass

    # Safe fallback to the newest matching report strictly within reports_dir
    candidates = sorted(reports_dir.glob(default_pattern))
    if candidates:
        return candidates[-1].resolve()
    raise HTTPException(status_code=404, detail="Report not found")


def _provider_status() -> dict:
    """Which AI provider is serving the org (for the status panel)."""
    try:
        from agents.ai import providers
        return providers.status()
    except Exception:
        return {"provider": "gemini", "active": False}

STATIC_DIR = Path(__file__).parent / "static"

router = APIRouter()


# Served in place of the app when the browser has no launch cookie. It says
# where the launch URL comes from and contains no secret of its own.
_LAUNCH_REQUIRED = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>J.A.R.V.I.S — locked</title>
  <meta name="color-scheme" content="light">
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: #f1e6d0; color: #2c271f;
           font: 17px/1.5 "Courier New", monospace; }
    main { max-width: 34rem; margin: 1rem; padding: 2rem;
           border: 2px solid #2c271f; border-radius: 2px; background: #faf3e3; }
    h1 { font-size: 1rem; letter-spacing: .14em; margin: 0 0 1.2rem; }
    code { background: #e5d7ba; padding: 1px 4px; }
  </style>
</head>
<body>
  <main>
    <h1>J.A.R.V.I.S — LOCKED</h1>
    <p>This office opens only from its launch URL. The terminal that started
       the server printed it; it looks like:</p>
    <p><code>http://127.0.0.1:8765/?token=…</code></p>
    <p>Opening it once stores a session cookie in this browser. If you no
       longer have it, restart the server to mint a fresh one.</p>
  </main>
</body>
</html>
"""


# ── The document ───────────────────────────────────────────────────────

@router.get("/")
@router.get("/index.html")
async def index(request: Request):
    """Serve the app document, never from cache — to the launch cookie only.

    The document used to carry the per-launch token in a <meta> tag, so any
    script, extension or local process that could read the page held full API
    authority. The token now arrives once, in the launch URL, and leaves as an
    HttpOnly cookie the page cannot read back.
    """
    from fastapi.responses import HTMLResponse
    from agents.web.auth import SESSION_COOKIE, verify_auth_token

    if not verify_auth_token(request.cookies.get(SESSION_COOKIE, "")):
        return HTMLResponse(content=_LAUNCH_REQUIRED, status_code=200,
                            headers={"Cache-Control": "no-store"})

    from agents.config import is_dry_run
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    dry_badge = '<span class="dry-run-badge" id="dryRunBadge" title="DRY RUN active — email sending and paid APIs are mocked">DRY RUN</span>' if is_dry_run() else ''
    html = html.replace('<!-- DRY_RUN_BADGE -->', dry_badge)
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/favicon.ico")
async def favicon_ico():
    """Serve retro SVG favicon for standard browser icon requests."""
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


# ── Session and conversation ───────────────────────────────────────────

@router.get("/api/status")
async def api_status():
    """Return current session stats."""
    try:
        from agents.config import get_business_profile
        from agents import ai_engine
        s = resume_latest()
        profile = get_business_profile()
        data = s.load_data("search_results.json") if s.active else {}
        drafts = s.load_data("email_drafts.json").get("drafts", []) if s.active else []
        return {
            "session_id": s.id if s.active else None,
            "session_name": s.name if s.active else None,
            "profile": profile,
            "businesses_found": len(data.get("businesses", [])),
            "businesses_no_site": len(data.get("no_website", [])),
            "drafts_count": len(drafts),
            "ai_configured": ai_engine.is_available(),
            "ai_provider": _provider_status(),
        }
    except Exception as e:
        err = _sanitize_error(e, "status check")
        return {"error": err["error"], "error_id": err["error_id"]}


@router.get("/api/geocode")
def api_reverse_geocode(lat: float, lon: float):
    """Name a map pin. Server-side on purpose: the browser's CSP keeps it off
    Nominatim, and naming the pin from the point itself is what makes a map
    selection mean something -- snapping every pin to "Kolkata" would make
    two pins in different suburbs search the same place."""
    try:
        import urllib.parse
        import urllib.request
        url = ("https://nominatim.openstreetmap.org/reverse?format=json&zoom=15"
               f"&lat={lat}&lon={lon}")
        req = urllib.request.Request(
            url, headers={"User-Agent": "JARVIS-AgentOffice/1.0 (local)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        a = data.get("address") or {}
        label = next((a.get(k) for k in (
            "suburb", "neighbourhood", "town", "village", "city",
            "city_district", "county") if a.get(k)), "")
        return {"label": label, "display": data.get("display_name", "")}
    except Exception as e:
        err = _sanitize_error(e, "reverse geocode")
        return {"label": "", "display": "", **err}


@router.post("/api/map/search")
def api_map_search(body: dict):
    """One map-pin search at an explicit radius.

    The chat path derives its radius from the goal, which is exactly why the
    map cannot grow a circle through it. This route takes the radius the pin
    shows. It is a plain ``def`` so the blocking discovery work (Overpass,
    web discovery, ICP) runs in the threadpool instead of stalling the loop.
    """
    location = str(body.get("location") or "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="location required")
    try:
        radius = max(500, min(int(body.get("radius") or 2500), 15000))
    except Exception:
        radius = 2500
    category = str(body.get("category") or "").strip()
    try:
        from agents.workflows import search_businesses_workflow
        res = search_businesses_workflow(location, radius, category=category)
        if res.get("error"):
            return {"error": res["error"], "location": location,
                    "radius": radius, "rows": []}
        rows = []
        for b in (res.get("businesses") or [])[:60]:
            v = b.get("icp") or {}
            rows.append({
                "name": b.get("name", ""),
                "fit": v.get("fit", ""),
                "score": v.get("fit_score", 0),
                "type": v.get("institution_type", ""),
                "email": b.get("email") or b.get("maps_email") or "",
                # The web discovery source attaches an address only when the
                # page it came from is confidently THIS business; a hunt result
                # is separate and may be flagged unverified. Both are returned
                # so the panel can show what is already known before hunting.
                "email_guess": b.get("contact_finder_email") or "",
                "has_site": bool(b.get("website")),
                "phone": b.get("phone") or "",
                "website": b.get("website") or "",
            })
        return {
            "location": location, "radius": radius,
            "raw": res.get("found_raw", 0), "kept": len(rows),
            "web_added": res.get("web_added", 0),
            "report": (res.get("filter_report") or "")[:280],
            "rows": rows,
        }
    except Exception as e:
        err = _sanitize_error(e, "map search")
        return {"error": err["error"], "error_id": err["error_id"], "rows": []}


@router.post("/api/map/contacts")
def api_map_contacts(body: dict):
    """Hunt emails for one pin's leads, without going through the chat pipeline.

    The map route stops at discovery + ICP on purpose, so a pin's rows arrive
    with whatever address the web source could attribute and nothing more.
    This route hands only those rows to the existing contact finder — the same
    one the chat pipeline uses — so a pin can be worked in isolation. Plain
    ``def``: the scrapes block, and they belong in the threadpool.

    Only a VERIFIED address is promoted by the finder itself; a guess is
    returned flagged, never silently queued as a recipient.
    """
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="rows required")
    try:
        budget = max(15, min(int(body.get("budget") or 60), 180))
    except Exception:
        budget = 60

    clean = []
    for r in rows[:40]:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()[:120]
        if not name:
            continue
        clean.append({
            "name": name,
            "email": str(r.get("email") or "").strip()[:120],
            "website": str(r.get("website") or "").strip()[:300],
            "phone": str(r.get("phone") or "").strip()[:40],
        })
    if not clean:
        raise HTTPException(status_code=400, detail="no usable rows")

    try:
        from agents.contact_finder import find_contacts
        res = find_contacts(clean, budget=float(budget), log=lambda *_: None)
        return {
            "searched": res.get("searched", 0),
            "found": res.get("found", 0),
            "empty": res.get("empty", []),
            "results": [
                {
                    "name": r.get("name", ""),
                    "email": r.get("email", ""),
                    "verified": bool(r.get("verified")),
                    "domain": r.get("domain", ""),
                    "source": r.get("source", ""),
                }
                for r in (res.get("results") or [])
            ],
        }
    except Exception as e:
        err = _sanitize_error(e, "map contacts")
        return {"error": err["error"], "error_id": err["error_id"], "results": []}


 #: What the panel's drafter may treat as fact. A map row carries a name and a
 #: type, nothing else — and without this the model invents a locality (the
 #: first live draft placed a Kolkata institute in Begambagh, Uttar Pradesh).
_MAP_DRAFT_FACTS = (
    "BUSINESS FACTS KNOWN: the name and the course type only. No street "
    "address, city, locality, rating, review count, staff or website content "
    "has been verified for this lead. Do not state or imply any address, "
    "locality or city, and invent no other specific detail about them. The "
    "promotional flyer IS attached to this email, so the flyer line stays. "
    "Open on the shared risk of a training centre with unlicensed seats "
    "instead of claiming you looked anything up — never write a sentence "
    "about having reviewed their site, address or details."
)


# The drafter is told it knows only a name and a course type, and it still
# wrote "I looked at the Justdial reviews ... over 1,200 ratings" for a lead we
# hold no research for. An instruction cannot be trusted with a fact that must
# never appear, so the body is checked for evidence claims after generation and
# replaced with the house template when it invents any.
_INVENTED_EVIDENCE = re.compile(
    r"(justdial|google reviews?|tripadvisor|trustpilot|yelp|glassdoor"
    r"|\d[\d,]*\s*\+?\s*(?:ratings?|reviews?)|star[- ]rated|review count)",
    re.IGNORECASE,
)

# "your Sholinganallur location" / "our centre in Kolkata": the row carries no
# locality, so a place next to their premises is always made up. Case-sensitive
# on purpose -- a capitalised place name is the tell, and the house template
# ("I looked at {biz}'s training setup") must not trip it.
_INVENTED_PLACE = re.compile(
    r"\byour\s+[A-Z][a-z]+\s+(?:location|branch|campus)"
    r"|\b(?:centre|center|institute|office|branch)\s+(?:in|at)\s+[A-Z][a-z]+"
)


def _invented_evidence(text: str) -> str:
    """The first fabricated claim in a body, or "" when it is clean."""
    for pattern in (_INVENTED_EVIDENCE, _INVENTED_PLACE):
        hit = pattern.search(text or "")
        if hit:
            return hit.group(0)
    return ""

# Mailboxes that say nothing about which branch owns them.
_PLAIN_MAILBOX = {
    "info", "contact", "enquiry", "enquiries", "inquiry", "admin", "office",
    "support", "sales", "hello", "mail", "reach", "care", "team", "help",
    "admissions", "admission", "hr", "marketing", "course", "courses",
}


def _foreign_branch(row: dict) -> str:
    """A branch-qualified mailbox that belongs to a different branch.

    Franchise brands publish every branch on one domain: the Kolkata page of
    caddcentre.com yielded ``tn.mylapore@caddcentre.com`` -- Tamil Nadu's
    Mylapore centre. The address is real, deliverable and entirely the wrong
    recipient, which is exactly the failure a "verified" flag is supposed to
    rule out. Flagged only for location pages, so ordinary company mailboxes
    on a normal site are untouched.
    """
    url = str(row.get("website") or "").lower()
    email_addr = str(row.get("email") or "").lower()
    if not url or "@" not in email_addr:
        return ""
    if "/location" not in url and "/centre" not in url and "/center" not in url:
        return ""
    local = email_addr.split("@")[0]
    tokens = [t for t in re.split(r"[^a-z0-9]+", local) if len(t) >= 2]
    context = set(re.split(r"[^a-z0-9]+", url + " " + str(row.get("name") or "").lower()))
    strays = [t for t in tokens if t not in _PLAIN_MAILBOX and t not in context]
    return strays[0] if strays else ""


def _map_template_draft(biz: dict, sender: str) -> tuple[str, str]:
    """The deterministic house draft: no claim the row cannot support."""
    from agents import email_copy
    issue = email_copy.issue_line(biz["name"], biz.get("category", ""))
    body = email_copy.compose_body(
        issue, greeting=email_copy.greeting_for("", biz["name"]), sender=sender)
    return f"Licensed AutoCAD seats for {biz['name']}", body


@router.post("/api/map/draft")
def api_map_draft(body: dict):
    """Draft outreach for one pin's sendable leads, with no chat turn involved.

    It runs the same generator the chat pipeline runs (``ai_draft_email``,
    which falls back to the template agent on its own), but deliberately does
    NOT touch the session: no PDF, no session draft file, no review state
    machine. A pin's batch must not rewrite the session the chat is working
    in, and a draft is cheap to regenerate.

    An address the contact hunt flagged unverified is refused here. That is
    the one rule the finder exists to enforce, and a route that skipped it
    would make the flag decorative.
    """
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="rows required")

    clean, seen, refused = [], set(), []
    for r in rows[:20]:
        if not isinstance(r, dict):
            continue
        to = str(r.get("email") or "").strip()[:160]
        name = str(r.get("name") or "").strip()[:160]
        if not to or not name:
            continue
        if r.get("email_verified") is False:
            refused.append(name)
            continue
        stray = _foreign_branch({"website": r.get("website"), "email": to, "name": name})
        if stray:
            refused.append(f"{name} ({to} looks like another branch: '{stray}')")
            continue
        if to.lower() in seen:
            continue
        seen.add(to.lower())
        clean.append({
            "name": name,
            "email": to,
            "website": str(r.get("website") or "")[:300],
            "phone": str(r.get("phone") or "")[:40],
            "category": str(r.get("type") or r.get("category") or "")[:80],
        })
    if not clean:
        raise HTTPException(status_code=400,
                            detail="no sendable rows (needs a name and a verified address)")

    try:
        from agents.config import get_sender_name
        from agents.icp import resolve_goal
        from agents.workflows import orch

        goal = resolve_goal()
        sender = get_sender_name()
        drafts, errors, notes = [], [], []
        for biz in clean:
            # The copy promises the flyer, so attach the same proposal PDF the
            # chat path attaches. A missing PDF must not block the draft.
            pdf_path = ""
            try:
                from agents.pdf_gen import generate_proposal_pdf
                pdf_path = generate_proposal_pdf(
                    {"name": biz["name"], "category": biz["category"],
                     "phone": biz["phone"], "website": biz["website"]},
                    sender, goal=goal)
            except Exception:
                pdf_path = ""
            try:
                result = orch.run("ai_draft_email", {
                    "business_name": biz["name"],
                    "contact_name": "",
                    "email": biz["email"],
                    "category": biz["category"],
                    "goal": goal["key"],
                    "learning_context": _MAP_DRAFT_FACTS,
                }, context={"sender_name": sender})
            except Exception as e:
                errors.append({"name": biz["name"], "error": str(e)[:160]})
                continue
            out = getattr(result, "output", None)
            if not getattr(result, "success", False) or not isinstance(out, dict):
                errors.append({"name": biz["name"], "error": "draft failed"})
                continue
            if not out.get("subject") or not out.get("body"):
                errors.append({"name": biz["name"], "error": "empty draft"})
                continue
            subject, text = out.get("subject", ""), out.get("body", "")
            ai_powered = bool(out.get("ai_powered"))
            claim = _invented_evidence(text)
            if claim:
                # Keep the mail, drop the fabrication: the template says the
                # same thing without pretending to have looked anything up.
                subject, text = _map_template_draft(biz, sender)
                ai_powered = False
                notes.append({"name": biz["name"],
                              "note": f"invented evidence '{claim}' — template copy used"})
            drafts.append({
                "to": out.get("to") or biz["email"],
                "name": biz["name"],
                "subject": subject,
                "body": text,
                "ai_powered": ai_powered,
                "pdf_path": pdf_path,
                # Carried through the panel so the send leg can re-run the
                # branch check on its own copy of the row.
                "website": biz["website"],
            })
        return {"drafts": drafts, "errors": errors, "notes": notes, "refused": refused}
    except Exception as e:
        err = _sanitize_error(e, "map draft")
        return {"error": err["error"], "error_id": err["error_id"], "drafts": []}


def _sent_ledger() -> Path:
    """The append-only record of what actually left the building."""
    from agents import config
    return Path(config.OUTPUT_DIR) / "emails" / "sent_ledger.jsonl"


def _bounced_addresses() -> dict:
    """Addresses the mailbox has reported undeliverable, address -> reason.

    Gmail accepts a message even when the recipient server will refuse it, so
    the ledger records "sent" for mail that bounced an hour later. The bounce
    store is the only place that knows, and it is checked before the ledger.
    """
    try:
        from agents import bounce_scan
        return {k: (v.get("reason") or "") for k, v in bounce_scan.known_bounces().items()}
    except Exception:
        return {}


def _ledger_addresses() -> set:
    """Addresses already sent to, from every route that sends."""
    path = _sent_ledger()
    out = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("success") and entry.get("to"):
                out.add(entry["to"].strip().lower())
    except Exception:
        pass
    return out


@router.post("/api/map/send")
def api_map_send(body: dict):
    """Send drafts the panel just produced, one pin at a time.

    Uses the app's own send leg (``send_emails_workflow``: mailer, receipt
    PDF, brain memory, contacted CSV), so a send from the panel is
    indistinguishable downstream from one started in the chat.

    Two guards: an address the ledger says we already mailed is skipped
    (a panel is easy to double-click), and every send is appended to that
    ledger, which is what makes the guard work next time.
    """
    drafts_in = body.get("drafts")
    if not isinstance(drafts_in, list) or not drafts_in:
        raise HTTPException(status_code=400, detail="drafts required")

    already = _ledger_addresses()
    bounced = _bounced_addresses()
    prepared, duplicates, invalid, dead = [], [], [], []
    for d in drafts_in[:20]:
        if not isinstance(d, dict):
            continue
        to = str(d.get("to") or "").strip()[:160]
        subject = str(d.get("subject") or "").strip()[:200]
        text = str(d.get("body") or "").strip()
        name = str(d.get("name") or d.get("to") or "")[:160]
        if not to or not subject or not text:
            invalid.append(name or "(unnamed)")
            continue
        stray = _foreign_branch({"website": d.get("website"), "email": to, "name": name})
        if stray:
            invalid.append(f"{name} ({to} looks like another branch: '{stray}')")
            continue
        if to.lower() in bounced:
            # Known dead inbox: sending again just earns another bounce, and
            # reporting it as "duplicate" would hide why nothing arrived.
            dead.append({"to": to, "name": name, "reason": bounced[to.lower()]})
            continue
        if to.lower() in already:
            duplicates.append(to)
            continue
        already.add(to.lower())
        prepared.append({
            "to": to,
            "subject": subject,
            "body": text,
            "pdf_path": str(d.get("pdf_path") or "") if Path(str(d.get("pdf_path") or "")).exists() else "",
            "business": {"name": name, "category": str(d.get("category") or "")[:80]},
        })

    if not prepared:
        return {"sent": [], "duplicates": duplicates, "invalid": invalid,
                "bounced": dead, "errors": []}

    try:
        from agents.config import get_sender_name
        from agents.outreach_send import send_emails_workflow

        result = send_emails_workflow(prepared, get_sender_name())
        stamp = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        path = _sent_ledger()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for draft in result.get("sent") or []:
                fh.write(json.dumps({
                    "to": draft.get("to", ""),
                    "name": (draft.get("business") or {}).get("name", ""),
                    "subject": draft.get("subject", ""),
                    "sent_at": stamp,
                    "success": True,
                    "source": "map-panel",
                    "flyer": bool(draft.get("pdf_path")),
                }, ensure_ascii=True) + "\n")
        return {
            "sent": [{"to": d.get("to"), "name": (d.get("business") or {}).get("name", "")}
                     for d in (result.get("sent") or [])],
            "errors": result.get("errors") or [],
            "duplicates": duplicates,
            "invalid": invalid,
            "bounced": dead,
        }
    except Exception as e:
        err = _sanitize_error(e, "map send")
        return {"error": err["error"], "error_id": err["error_id"], "sent": []}


@router.get("/api/map/bounces")
def api_map_bounces():
    """Addresses that bounced, so a pin can label a dead inbox."""
    found = _bounced_addresses()
    return {"count": len(found), "addresses": found}


@router.post("/api/map/bounces/scan")
def api_map_bounces_scan(body: dict):
    """Read the sending inbox for delivery failures and record new ones."""
    raw_days = (body or {}).get("days")
    try:
        days = min(max(int(raw_days), 1), 60)
    except (TypeError, ValueError):
        days = 14
    try:
        from agents import bounce_scan
        return bounce_scan.scan(days=days)
    except Exception as e:
        err = _sanitize_error(e, "bounce scan")
        return {"error": err["error"], "error_id": err["error_id"],
                "checked": 0, "bounces": [], "new": []}


@router.get("/api/goals")
async def api_goals():
    """The goal catalog + which goal is pinned (the goal chip's data)."""
    try:
        from agents.config import get_active_goal
        from agents import icp
        active = get_active_goal()
        # A pinned custom goal is a phrase, not a catalog key.
        label = active if (active and not icp.known_goal_key(active)) \
            else (icp.goal_of(active)["label"] if active else "")
        return {
            "active": active,
            "label": label or "Auto (infer per search)",
            "is_auto": not active,
            "goals": [{"key": g["key"], "label": g["label"]}
                      for g in icp.GOALS.values() if g["key"] != "custom"],
        }
    except Exception as e:
        err = _sanitize_error(e, "goals retrieval")
        return {"error": err["error"], "error_id": err["error_id"], "active": "", "is_auto": True, "goals": []}


@router.post("/api/goals")
async def api_set_goal(body: dict):
    """Pin/clear the active goal — same path as the chat 'i sell X' intent."""
    from agents.action_dispatch import handle_goal
    result = handle_goal({"goal": (body or {}).get("goal", "")})
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Could not set goal"))
    return result


@router.get("/api/history")
async def api_history():
    """Return recent conversations."""
    try:
        from agents.chat_memory import ChatMemory
        mem = ChatMemory()
        convos = mem.get_recent_conversations(20)
        mem.close()
        return {"conversations": convos}
    except Exception as e:
        err = _sanitize_error(e, "history retrieval")
        return {"conversations": [], "error": err["error"], "error_id": err["error_id"]}


@router.get("/api/conversation/{conv_id}")
async def api_conversation(conv_id: int):
    """Return messages for a specific conversation.

    404s when the id is unknown. Returning 200 with an empty list made a
    deleted conversation look like an empty one, so a client could never
    tell whether a delete had actually landed.
    """
    if conv_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    from agents.chat_memory import ChatMemory
    mem = ChatMemory(conversation_id=conv_id)
    try:
        if not mem.conversation_exists(conv_id):
            raise HTTPException(status_code=404, detail="No such conversation")
        return {"messages": mem.get_context(100)}
    finally:
        mem.close()


@router.delete("/api/conversation/{conv_id}")
async def api_delete_conversation(conv_id: int):
    """Delete a conversation and all its messages."""
    if conv_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    try:
        from agents.chat_memory import ChatMemory
        mem = ChatMemory()
        deleted = mem.delete_conversation(conv_id)
        mem.close()
        return {"ok": deleted,
                "error": None if deleted else f"Conversation {conv_id} not found."}
    except Exception as e:
        err = _sanitize_error(e, "conversation deletion")
        return {"ok": False, "error": err["error"], "error_id": err["error_id"]}


# File upload restrictions: 10 MB maximum, document and image formats only
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".doc", ".docx"
}


@router.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Save a user-uploaded attachment (brochure, catalog) for an email."""
    import uuid
    import re
    try:
        from agents.config import OUTPUT_DIR
        up_dir = (OUTPUT_DIR / "uploads").resolve()
        up_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = file.filename or "upload.bin"
        # Sanitize filename: extract basename, strip directory traversal characters
        safe_name = Path(raw_filename).name.strip()
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', safe_name)
        if not safe_name or safe_name.startswith('.'):
            safe_name = f"upload_{uuid.uuid4().hex[:6]}.bin"

        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Disallowed file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
            )

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds maximum size limit of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
            )

        # Secure unique destination inside uploads dir
        unique_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
        dest = (up_dir / unique_name).resolve()
        # Verify destination path stays strictly within up_dir
        if not str(dest).startswith(str(up_dir)):
            raise HTTPException(status_code=400, detail="Invalid destination path")

        dest.write_bytes(content)
        return {"ok": True, "path": str(dest), "name": safe_name, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("jarvis.upload").error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process upload")


# ── Brain, roster and the floor's telemetry ────────────────────────────

@router.get("/api/campaign")
async def api_campaign():
    """Current campaign gate state, so a fresh tab can re-render the
    interactive checklist instead of the flow silently waiting on a
    card that died with the old page."""
    session = resume_latest()
    if not session.active:
        return {"phase": "none"}
    state = session.load_data("campaign_state.json")
    phase = state.get("phase", "none")
    out = {"phase": phase}
    if phase == "awaiting_selection":
        out["checklist"] = {
            "location": state.get("location", ""),
            "goal": state.get("goal", ""),
            "businesses": state.get("curated", []),
            "selected": state.get("selected", []),
        }
    elif phase == "interview":
        from agents.campaign import current_question
        out["question"] = current_question(state)
    return out


# ── Campaign report downloads ─────────────────────────────────────

@router.get("/api/report/initial")
async def api_report_initial():
    """Download the current campaign's initial PDF (approved targets)."""
    from fastapi.responses import FileResponse as _FR
    session = resume_latest()
    raw_path = ""
    if session.active:
        raw_path = session.load_data("campaign_state.json").get("initial_pdf", "")
    safe_path = _safe_report_path(raw_path, "campaign_initial_*.pdf")
    return _FR(str(safe_path), filename=safe_path.name,
               headers={"Cache-Control": "no-cache"})


@router.get("/api/report/final")
async def api_report_final():
    """Download the most recent final campaign report PDF."""
    from fastapi.responses import FileResponse as _FR
    session = resume_latest()
    raw_path = ""
    if session.active:
        raw_path = session.load_data("campaign_final.json").get("final_pdf", "")
    safe_path = _safe_report_path(raw_path, "campaign_final_*.pdf")
    return _FR(str(safe_path), filename=safe_path.name,
               headers={"Cache-Control": "no-cache"})


@router.get("/api/brain")
async def api_brain():
    """Everything the brain knows -- powers the Agent Ops floor + status panel."""
    try:
        from agents.brain import get_brain
        from agents.config import OUTPUT_DIR
        brain = get_brain()
        stats = brain.get_stats()
        industries = []
        for name in brain.list_industries()[:12]:
            d = brain.get_industry(name)
            industries.append({
                "name": name,
                "encounters": d.get("times_encountered", 0),
                "pain_points": len(d.get("pain_points", [])),
                "hooks": len(d.get("hooks", [])),
            })
        # Recent businesses the brain has intel on
        biz_list = []
        for rec in brain.list_businesses()[:12]:
            inters = rec.get("interactions", [])
            biz_list.append({
                "name": rec.get("name", "?"),
                "category": rec.get("category", ""),
                "rating": rec.get("rating"),
                "gaps": len(rec.get("gaps", [])),
                "last": (inters[-1].get("type", "?") if inters else ""),
            })
        # Specialist agent memories (agent_brains/*.json)
        agents_out = []
        for f in sorted((OUTPUT_DIR / "agent_brains").glob("*.json")):
            if f.stem.startswith("_"):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                agents_out.append({
                    "key": f.stem,
                    "facts": sum(len(v) for v in d.get("facts", {}).values()),
                    "chats": d.get("chat_count", 0),
                    "updated": d.get("updated_at", "")[:19],
                })
            except Exception:
                continue
        return {
            "stats": stats,
            "industries": industries,
            "businesses": biz_list,
            "agents": agents_out,
        }
    except Exception as e:
        err = _sanitize_error(e, "brain state retrieval")
        return {"error": err["error"], "error_id": err["error_id"]}


@router.get("/api/agents")
async def api_agents():
    """The roster: one record shape for built-ins and hires alike.

    `look` and `home_station` are served for EVERY agent. They used to be
    sent only for hires, because the client hardcoded the built-ins' look and
    desk — which meant an agent's identity lived in this module, in
    agent_team.py and in two JS maps, and those could drift silently. The
    roster (agent_team) owns the identity; this endpoint just publishes it;
    the client renders whatever it is handed.
    """
    try:
        from agents.agent_team import AGENTS, get_agent, all_agent_keys, _memory_count
        agents = []
        for k in all_agent_keys():
            v = get_agent(k) or {}
            agents.append({
                "key": k,
                "name": v.get("name", k),
                "role": v.get("role", ""),
                "memory": _memory_count(k),
                "hired": k not in AGENTS,
                "look": v.get("look"),
                "home_station": v.get("station") or "station-brain",
            })
        return {"agents": agents}
    except Exception as e:
        err = _sanitize_error(e, "roster retrieval")
        return {"error": err["error"], "error_id": err["error_id"]}


@router.post("/api/agents/hire")
async def api_hire_agent(payload: dict):
    """ADD AGENT — create a specialist at runtime (hiring.py owns the rules)."""
    from agents.hiring import hire as do_hire
    from agents.event_bus import emit
    rec, err = do_hire(payload)
    if err:
        return {"ok": False, "error": err}
    emit("bot", bot=rec["id"], status="done",
         task=f"{rec['name']} joins the floor — {rec['role']}")
    return {"ok": True, "agent": rec}


@router.post("/api/agents/{agent_id}/deactivate")
async def api_deactivate_agent(agent_id: str):
    """Part the ways — soft delete; desk frees, memory stays."""
    if not ID_REGEX.match(agent_id):
        raise HTTPException(status_code=400, detail="Invalid agent identifier")
    from agents.hiring import deactivate
    from agents.event_bus import emit
    if not deactivate(agent_id):
        return {"ok": False, "error": f"No active hire named '{agent_id}'."}
    emit("bot", bot=agent_id, status="done", task="departs the floor")
    return {"ok": True}


@router.get("/api/events")
async def api_events():
    """Recent bus events (for the ops floor when a client reconnects)."""
    from agents.event_bus import recent
    return {"events": recent(60)}


# ── Skills library ─────────────────────────────────────────────────────

@router.get("/api/skills")
async def api_skills(agent: str = None):
    """The skills library, optionally filtered to one agent."""
    try:
        if agent and not ID_REGEX.match(agent) and agent != "*":
            raise HTTPException(status_code=400, detail="Invalid agent filter")
        from agents.skills import list_skills, stats
        return {"skills": list_skills(agent=agent), "stats": stats()}
    except HTTPException:
        raise
    except Exception as e:
        err = _sanitize_error(e, "skills retrieval")
        return {"skills": [], "error": err["error"], "error_id": err["error_id"]}


@router.post("/api/skills")
async def api_skills_add(body: dict = None):
    """Add a skill: {name, description, steps[], agents[]}."""
    try:
        from agents.skills import add_skill
        body = body or {}
        skill = add_skill(body.get("name", ""), body.get("description", ""),
                          body.get("steps") or [], body.get("agents"))
        return {"ok": True, "skill": skill}
    except Exception as e:
        err = _sanitize_error(e, "adding skill")
        return {"ok": False, "error": err["error"], "error_id": err["error_id"]}


@router.delete("/api/skills/{skill_id}")
async def api_skills_delete(skill_id: str):
    if not ID_REGEX.match(skill_id):
        raise HTTPException(status_code=400, detail="Invalid skill identifier")
    try:
        from agents.skills import remove_skill
        return {"ok": remove_skill(skill_id)}
    except Exception as e:
        err = _sanitize_error(e, "removing skill")
        return {"ok": False, "error": err["error"], "error_id": err["error_id"]}


@router.post("/api/skills/{skill_id}/toggle")
async def api_skills_toggle(skill_id: str):
    if not ID_REGEX.match(skill_id):
        raise HTTPException(status_code=400, detail="Invalid skill identifier")
    try:
        from agents.skills import toggle_skill
        s = toggle_skill(skill_id)
        return {"ok": s is not None, "skill": s}
    except Exception as e:
        err = _sanitize_error(e, "toggling skill")
        return {"ok": False, "error": err["error"], "error_id": err["error_id"]}


@router.patch("/api/skills/{skill_id}/assign")
async def api_skills_assign(skill_id: str, body: dict = None):
    """Assign/unassign a skill to an agent: {agent, add}."""
    if not ID_REGEX.match(skill_id):
        raise HTTPException(status_code=400, detail="Invalid skill identifier")
    body = body or {}
    agent_target = body.get("agent", "")
    if agent_target and not ID_REGEX.match(str(agent_target)) and agent_target != "*":
        raise HTTPException(status_code=400, detail="Invalid agent identifier")
    try:
        from agents.skills import assign_skill
        s = assign_skill(skill_id, agent_target,
                         bool(body.get("add", True)))
        return {"ok": s is not None, "skill": s}
    except Exception as e:
        err = _sanitize_error(e, "assigning skill")
        return {"ok": False, "error": err["error"], "error_id": err["error_id"]}


# ── Personal key vault ──────────────────────────────────────────────────
#
# Every route is a thin guard over agents/web/vault.py, which owns the
# code hash, the lockout and the token sessions. The invariant: no route
# below returns secret material without a valid `token` from /unlock,
# and /reveal is the only place a full secret ever crosses the wire.

@router.get("/api/vault/status")
async def vault_status():
    from agents.web import vault
    return {"has_code": vault.has_code(), **vault.locked_info()}


@router.post("/api/vault/set-code")
async def vault_set_code(body: dict = None):
    """First-time setup, or a code change with the current code: {code, current?}."""
    from agents.web import vault
    body = body or {}
    res = vault.set_code(str(body.get("code") or ""),
                         current=body.get("current"))
    if res is True:
        return {"ok": True}
    if res == "exists":
        raise HTTPException(status_code=403, detail="Wrong current code")
    raise HTTPException(status_code=400, detail="Code must be 4-128 characters")


@router.post("/api/vault/unlock")
async def vault_unlock(body: dict = None):
    """Exchange the access code for a session token: {code} -> {token, ttl}."""
    from agents.web import vault
    body = body or {}
    token = vault.verify(str(body.get("code") or ""))
    if not token:
        info = vault.locked_info()
        raise HTTPException(status_code=401, detail={
            "message": "Wrong code" if not info["locked"] else "Vault locked",
            **info})
    return {"ok": True, "token": token, "ttl": vault.ttl(token)}


@router.post("/api/vault/lock")
async def vault_lock(body: dict = None):
    from agents.web import vault
    vault.lock(str((body or {}).get("token") or ""))
    return {"ok": True}


@router.get("/api/vault/keys")
async def vault_keys(token: str = ""):
    """Masked key inventory — requires a session token from /unlock."""
    from agents.web import vault
    if not vault.check(token):
        raise HTTPException(status_code=401, detail="Vault is locked")
    return {"ok": True, "entries": vault.entries(), "ttl": vault.ttl(token)}


@router.get("/api/vault/activity")
async def vault_activity(token: str = ""):
    """Vault event log (newest first) — token-gated like the keys."""
    from agents.web import vault
    if not vault.check(token):
        raise HTTPException(status_code=401, detail="Vault is locked")
    return {"ok": True, "events": vault.activity(), "ttl": vault.ttl(token)}


@router.get("/api/vault/reveal/{entry_id}")
async def vault_reveal(entry_id: str, token: str = ""):
    """The one route a full secret ever crosses — token-gated, logged by touch."""
    if entry_id not in ALLOWED_VAULT_KEYS or not ID_REGEX.match(entry_id):
        raise HTTPException(status_code=404, detail="Unknown vault entry")
    from agents.web import vault
    if not vault.check(token):
        raise HTTPException(status_code=401, detail="Vault is locked")
    secret = vault.reveal(entry_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="Unknown vault entry")
    return {"ok": True, "id": entry_id, "secret": secret, "ttl": vault.ttl(token)}
