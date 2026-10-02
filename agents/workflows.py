"""Pure workflow logic. No UI calls. Each function takes explicit params, returns results."""
from datetime import datetime
from pathlib import Path
from agents.map_search import geocode, search_businesses, filter_no_website, verify_no_site_businesses
from agents.pdf_gen import generate_proposal_pdf
from agents.mailer import send_email
from agents.sent_email_pdf import send_receipt_pdf, sent_dir
from agents.maps_contact_fallback import enrich_with_maps_contacts
from agents.contact_export import write_phones_csv
from agents.obsidian_sync import (
    create_project_note, create_contact_note, create_outreach_form,
    create_industry_note, create_research_note, create_competitor_note,
    create_followup_note, create_insight_note,
    create_business_research_note, create_brain_map,
    mark_contact_approached, update_vault_index,
)
from agents.config import (
    get_sender_name, get_hunter_key, set_hunter_key,
    get_gmail_user, OBSIDIAN_VAULT,
    save_session_data,
)
from agents import Orchestrator
from agents.icp import delivers_websites
from agents.learn import (
    learn_from_search, learn_from_draft, learn_from_send,
    learn_from_rejection, record_draft_feedback, get_learning_context,
)

orch = Orchestrator()


def research_workflow(businesses: list[dict]) -> list[dict]:
    """Research a batch of businesses using web scraping + AI analysis.

    Returns list of research dicts, one per business.
    Each dict has: name, rating, review_count, strengths, gaps,
    email_hook, improvement_suggestion.

    Every successful research result is also stored in the brain as
    per-business knowledge (agents/businesses/<name>.json).
    """
    from agents.event_bus import emit
    from agents.business_research import research_batch
    emit("bot", bot="analyst", status="thinking",
         task=f"Researching {len(businesses)} business(es)", source="workflow")
    results = research_batch(businesses)
    for r in results:
        emit("bot", bot="analyst",
             status="done" if not r.get("error") else "error",
             task=f"{r.get('name', '?')}: rating={r.get('rating', '?')}, "
                  f"gaps={len(r.get('gaps', []))}", source="workflow")
        emit("packet", from_="analyst", to="brain",
             label=str(r.get('name', '?'))[:26])

    # Feed the brain: one knowledge file per business
    try:
        from agents.brain import get_brain
        brain = get_brain()
        for biz, r in zip(businesses, results):
            if r.get("error"):
                continue
            brain.learn_business(
                r.get("name") or biz.get("name", "?"),
                category=r.get("category") or biz.get("category", ""),
                facts={
                    "rating": r.get("rating"),
                    "review_count": r.get("review_count"),
                    "strengths": r.get("strengths", []),
                    "gaps": r.get("gaps", []),
                    "email_hook": r.get("email_hook", ""),
                    "improvement_suggestion": r.get("improvement_suggestion", ""),
                },
                interaction={"type": "researched", "detail": f"rating={r.get('rating', 0)}"},
                source="research",
            )
    except Exception:
        pass  # learning must never break research

    return results


def search_businesses_workflow(location: str, radius: int,
                              category: str = "", goal: str = "") -> dict:
    """Search for businesses. Returns {geo_display, businesses, no_site, with_site,
    filter_report, icp, goal} or error.

    ``goal`` is what we are selling on this search (see agents/icp.py); it is
    resolved from the user's own phrasing when not given explicitly, because the
    target changes from search to search.
    """
    if not location:
        return {"error": "No location provided"}

    # The goal decides what we sell on THIS search and drives both the ICP
    # ranking and the Google Maps failover query, so resolve it first.
    from agents.icp import rank as icp_rank, learn as icp_learn, resolve_goal
    goal_obj = resolve_goal(request=category, explicit=goal)
    # Say WHERE the goal came from (pinned / inferred / profile) so a wrong
    # match is diagnosable from the report line alone.
    source = goal_obj.get("_source", "")
    source_tag = f" [goal: {source}]" if source else ""

    geo = geocode(location)
    if not geo:
        return {"error": "Could not find that location"}

    # Always search ALL categories, then let the ICP decide who is actually a
    # customer. Searching everything and filtering afterwards is deliberate:
    # pre-filtering by OSM tag misses the institutions whose tags are wrong.
    overpass_error = ""
    try:
        businesses = search_businesses(geo["lat"], geo["lon"], radius)
    except Exception as e:
        # Overpass is a free public service and fails often under load
        # (rate limits, invalid JSON, timeouts). An error means exactly what an
        # empty result means — we have no OSM data for this area — so it must
        # reach the same failover instead of ending the search before the other
        # source is ever tried.
        businesses = []
        overpass_error = f"{type(e).__name__}: {e}"
        print(f"  [SEARCH] Overpass failed ({str(e)[:90]}) — trying Google Maps")

    maps_source = ""
    maps_tried = False
    if not businesses:
        # No OSM data: Overpass was rate-limited, errored, or genuinely has
        # nothing here. With a Google Maps provider key set, fail over instead
        # of reporting a dead end.
        try:
            from agents.gmaps_source import available, search_gmaps
            from agents.event_bus import emit
            if available():
                maps_tried = True
                emit("bot", bot="scout", status="thinking",
                     task=("Overpass failed — switching to Google Maps" if overpass_error
                           else "Overpass empty — switching to Google Maps"),
                     source="workflow")
                businesses = search_gmaps(geo["lat"], geo["lon"], radius,
                                          category=category, goal=goal_obj)
                maps_source = "gmaps" if businesses else ""
        except Exception as e:
            print(f"  [SEARCH] Google Maps failover failed: {e}")

    if overpass_error and not businesses:
        # Nothing from either source: report the real reason rather than a
        # misleading "found 0 businesses", which reads as "this town is empty".
        return {"error": f"Overpass failed ({overpass_error[:100]}) — "
                         + ("Google Maps found nothing here either." if maps_tried
                            else "no Google Maps fallback is configured.")}

    # Stage 1: fit against the goal of THIS search. Deterministic, always on.
    kept, dropped, filter_report, icp_summary = icp_rank(businesses, goal=goal_obj)
    # learns from rejects as well as fits, kept separate per goal
    icp_learn(kept + dropped, goal=goal_obj)

    # Stage 1b: AI rationale on the top kept fits — the verdict itself stays
    # deterministic (one judge), Gemini only adds the "why" for the user.
    # Best-effort: never blocks or slows the search meaningfully.
    try:
        from agents.ai import service as ai_service
        from agents.ai.scrape_adapter import to_business
        for b in [x for x in kept if x["icp"]["fit"] == "fits"][:5]:
            fit = ai_service.score_fit(to_business(b))
            if fit.rationale:
                b["icp"]["ai_rationale"] = fit.rationale
    except Exception:
        pass

    # Stage 2: the user's own phrasing, when they gave one, narrows it further.
    if category:
        from agents.category_filter import filter_by_category
        kept, intent_report = filter_by_category(kept, category, goal=goal_obj)
        filter_report = f"{filter_report} {intent_report}"
    if source_tag:
        filter_report = f"{filter_report}{source_tag}" if filter_report else source_tag.strip()

    # Verify no-site businesses via web search to catch OSM-missing websites
    verified_businesses = verify_no_site_businesses(kept, location)
    verified_no_site = filter_no_website(verified_businesses)
    verified_with_site = [b for b in verified_businesses if b.get("website")]

    # Learn from this search
    learn_from_search(verified_businesses, location)
    _remember_fit(kept, goal_obj)
    try:
        from agents.event_bus import emit
        emit("packet", from_="search", to="brain", label=location[:26])
        emit("bot", bot="scout", status="done",
             task=f"Found {len(verified_no_site)} no-site businesses in {location}",
             source="workflow")
        emit("bot", bot="analyst", status="done",
             task=f"ICP [{goal_obj['label']}]: {icp_summary['fits']} direct fits, "
                  f"{icp_summary['plausible']} plausible, "
                  f"{icp_summary['dropped']} ruled out",
             source="workflow")
        emit("packet", from_="analyst", to="brain", label=f"ICP: {goal_obj['label']}"[:26])
    except Exception:
        pass

    return {
        "geo_display": geo["display"],
        "businesses": verified_businesses,
        "no_site": verified_no_site,
        "with_site": verified_with_site,
        "filter_report": filter_report,
        "icp": icp_summary,
        "dropped": dropped,
        "goal": goal_obj["key"],
        "goal_label": goal_obj["label"],
        "goal_source": goal_obj.get("_source", ""),
        "source": maps_source or "osm",
    }


def _remember_fit(businesses: list[dict], goal: dict = None) -> None:
    """Store each kept business's fit verdict in the brain. Never raises."""
    try:
        from agents.brain import get_brain
        brain = get_brain()
        goal_label = (goal or {}).get("label", "")
        for biz in businesses:
            verdict = biz.get("icp") or {}
            if verdict.get("fit") == "unlikely":
                continue
            brain.learn_business(
                biz.get("name", "?"),
                category=biz.get("category", ""),
                facts={
                    "fit": verdict.get("fit"),
                    "fit_score": verdict.get("fit_score"),
                    "institution_type": verdict.get("institution_type"),
                    "why_fit": "; ".join(verdict.get("fit_reasons", [])[:3]),
                    "goal": goal_label or verdict.get("goal", ""),
                    **({"email": biz["email"]} if biz.get("email") else {}),
                    **({"phone": biz["phone"]} if biz.get("phone") else {}),
                },
                source="search",
            )
    except Exception:
        pass


def scrape_businesses_workflow(businesses: list[dict]) -> list[dict]:
    """Scrape business websites using Scrapling. Returns enriched businesses."""
    try:
        from agents.business_enricher import enrich_businesses
        return enrich_businesses(businesses, scrape_reviews=True)
    except ImportError:
        return businesses
    except Exception as e:
        print(f"  [SCRAPER] Scrape failed: {e}")
        return businesses


def enrich_workflow(businesses: list[dict], hunter_key: str) -> dict:
    """Enrich businesses with Hunter.io when the key is set, otherwise run a
    best-effort Maps/Google contact fallback for phone + email.

    Returns {enriched, enriched_count, method, results}."""
    if not hunter_key:
        maps = enrich_with_maps_contacts(businesses)

        # College-style businesses often have no Maps-surfaced email but DO
        # have an official site with a contact page. Hunt those before
        # giving up, so drafts get a `to:` address.
        contact_result = None
        missing = [b for b in businesses
                   if not (b.get("email") or b.get("maps_email"))]
        if missing:
            try:
                from agents.contact_finder import find_contacts
                contact_result = find_contacts(missing)
            except Exception as e:
                print(f"  [ENRICH] contact finder failed: {e}")

        contact_found = (contact_result or {}).get("found", 0)

        # Production enrichment pass (ddgs discovery + MX deliverability +
        # libphonenumber WhatsApp links + 14-day cache). Runs after the
        # basic hunter; promotes only verified+deliverable contacts.
        try:
            from agents.contact_enricher import enrich_businesses
            enrich2 = enrich_businesses(missing)
        except Exception as e:
            print(f"  [ENRICH] v2 enrichment failed: {e}")
            enrich2 = None

        # Decision-maker pass (CEO/founder/owner), same contract as the
        # Hunter branch above: separate the person from the inbox, promote
        # only when no business address exists at all.
        exec_result = _run_exec_finder(businesses)

        return {
            "enriched": businesses,
            "enriched_count": maps["email_found"] + contact_found,
            "skipped": False,
            "method": "maps_fallback",
            "phone_found": maps["phone_found"],
            "contact_finder": contact_result,
            "enrich_v2": enrich2,
            "exec_finder": exec_result,
            "maps_results": maps,
            "results": [
                {
                    "name": b["name"],
                    "email": b.get("email") or b.get("maps_email", ""),
                    "phone": b.get("phone") or b.get("maps_phone", ""),
                    "found": bool(
                        b.get("email") or b.get("maps_email", "")
                        or b.get("phone") or b.get("maps_phone", "")
                    ),
                }
                for b in businesses
            ],
        }

    enriched_count = 0
    results = []

    for biz in businesses:
        website = biz.get("website", "")
        if not website:
            results.append({"name": biz["name"], "email": None, "found": False})
            continue

        domain = website.replace("https://", "").replace("http://", "").split("/")[0]
        result = orch.run("enrich_with_hunter", {"domain": domain})

        if result.success and result.output.get("email"):
            biz["enrichment"] = result.output
            enriched_count += 1
            results.append({
                "name": biz["name"],
                "email": result.output["email"],
                "position": result.output.get("position", "N/A"),
                "found": True,
            })
        else:
            results.append({"name": biz["name"], "email": None, "found": False})

    # Decision-maker pass: whoever this business's buyer is (CEO/founder/
    # owner) — separated from the generic inbox, promoted to contact only
    # when no business address exists at all.
    exec_result = _run_exec_finder(businesses)

    return {"enriched": businesses, "enriched_count": enriched_count,
            "exec_finder": exec_result, "results": results}


def _run_exec_finder(businesses: list[dict]) -> dict:
    """Decision-maker lookup. Never raises; free (no keys) is a no-op."""
    try:
        from agents.exec_finder import find_executives
        return find_executives(businesses)
    except Exception as e:
        print(f"  [ENRICH] exec finder failed: {e}")
        return {"searched": 0, "found": 0, "results": []}


def select_businesses_workflow(businesses: list[dict], choice: str) -> list[dict]:
    """Parse user selection. Returns selected businesses.

    Understands "all", "top5" (with the spacing variants the parser passes
    through), 1-based indices, and business names — "draft for Ankuran"
    arrives here with the NAME as the choice, which used to select nothing
    and answer "No businesses selected."
    """
    choice = (choice or "").strip().lower()
    if not choice or choice == "all":
        return list(businesses)
    if choice in ("top5", "top-5", "top 5"):
        return list(businesses[:5])

    selected = []
    for part in choice.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(businesses):
                selected.append(businesses[idx])
        else:
            for b in businesses:
                if part in (b.get("name") or "").lower() and b not in selected:
                    selected.append(b)
    return selected


def draft_and_pdf_workflow(businesses: list[dict], sender_name: str,
                           research_data: list[dict] = None,
                           goal: str = "", angles: dict = None) -> dict:
    """Draft emails, generate PDFs, and (only if the goal sells them) websites.

    Args:
        businesses: List of business dicts to process.
        sender_name: Name to use in email signature.
        research_data: Optional list of research dicts (from research_workflow).
            Each dict should have 'name', 'strengths', 'gaps', 'email_hook',
            'improvement_suggestion'. If provided, emails are personalized.
        goal: What this outreach sells (agents/icp.py). Decides the pitch, the
            PDF headline and whether the website leg runs at all.
        angles: Optional {business_name: user's angle note} from the campaign
            interview. The user's instruction is the most specific context the
            drafter gets, so it rides above research and brain memory.

    Returns {drafts, errors, ai_used}.
    """
    from agents.icp import resolve_goal
    goal_obj = resolve_goal(explicit=goal)
    from agents.business_research import format_research_for_email, get_research_for_business
    from agents.event_bus import emit
    drafts = []
    errors = []
    ai_count = 0

    # A file attached in the composer/CLI is stored on the session; put it on
    # every draft that doesn't already carry one, so "attach the brochure"
    # reaches the emails instead of stopping at the upload.
    session_attachment = ""
    try:
        from agents.session import get_active_session
        session_attachment = get_active_session().load_attachments().get("__default__", "")
    except Exception:
        session_attachment = ""

    emit("bot", bot="strategist", status="thinking",
         task=f"Drafting {len(businesses)} email(s)", source="workflow")

    for biz in businesses:
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        contact_name = biz.get("enrichment", {}).get("first_name", "")

        # Email — AI first, template fallback
        # Include learning context so AI improves with each session
        category = biz.get("category", "")
        learning_ctx = get_learning_context(category)

        # Build research context for this business
        research_ctx = ""
        if research_data:
            research = get_research_for_business(biz, research_data)
            if research and not research.get("error"):
                research_ctx = format_research_for_email(research)

        # Per-business brain memory: rating, gaps, past interactions.
        # Guarded like every other learning hook — a brain failure must
        # never break drafting.
        brain_ctx = ""
        try:
            from agents.brain import get_brain
            brain_ctx = get_brain().get_business_context(biz["name"])
        except Exception:
            brain_ctx = ""

        # Combine: user's angle (campaign interview) > industry learning >
        # business research > brain memory. The angle is the one instruction
        # the drafter must follow, so it leads the context.
        angle_note = (angles or {}).get(biz["name"], "")
        ctx_parts = []
        if angle_note:
            ctx_parts.append(f"USER'S ANGLE FOR THIS EMAIL: {angle_note}")
        if learning_ctx:
            ctx_parts.append(learning_ctx)
        if research_ctx:
            ctx_parts.append(f"--- Research on this specific business ---\n{research_ctx}")
        if brain_ctx:
            ctx_parts.append(f"--- Brain memory of this business ---\n{brain_ctx}")
        combined_ctx = "\n\n".join(ctx_parts)

        # Layer 2: Strategist's pre-written hook (from the agent team) rides
        # the existing "Suggested opening:" channel -- the template path
        # already scans for it and the AI path gets it as prompt context.
        try:
            from agents.agent_team import get_hook_for
            team_hook = get_hook_for(biz["name"])
            if team_hook:
                team_line = f"Suggested opening: {team_hook}"
                combined_ctx = f"{team_line}\n{combined_ctx}" if combined_ctx else team_line
        except Exception:
            pass

        # AI profile hook — one summary per business, cached across drafts
        # and searches. Grounded in scraped snippets; "unknown" stays unknown.
        try:
            from agents.ai import service as ai_service
            from agents.ai.scrape_adapter import to_business
            prof = ai_service.summarize_profile(to_business(biz))
            if prof.hook and prof.hook != "unknown":
                hook_line = f"AI profile hook: {prof.hook} (industry: {prof.industry})"
                combined_ctx = f"{hook_line}\n{combined_ctx}" if combined_ctx else hook_line
            if prof.pain_point and prof.pain_point != "unknown":
                combined_ctx = (combined_ctx + f"\nLikely pain point: {prof.pain_point}").strip()
        except Exception:
            pass

        # Always the AI task: the orchestrator owns ai_* -> template fallback
        # and the agent layer raises on failure, so one call site covers
        # AI-up, AI-down, and AI-error identically.
        email_result = orch.run("ai_draft_email", {
            "business_name": biz["name"],
            "contact_name": contact_name,
            "email": email,
            "category": category,
            "goal": goal_obj["key"],
            "learning_context": combined_ctx,
        }, context={"sender_name": sender_name})

        # PDF
        emit("bot", bot="strategist", status="writing-pdf",
             task=str(biz["name"])[:60], source="workflow")
        pdf_path = ""
        try:
            pdf_path = generate_proposal_pdf(biz, sender_name, goal=goal_obj)
        except Exception as e:
            errors.append({"name": biz["name"], "type": "pdf", "error": str(e)})

        # Website — only when our profile says we deliver websites, and only for
        # businesses that don't have one. A licensing product should not be
        # building prospects a website they never asked for.
        website_path = ""
        if not biz.get("website") and delivers_websites(goal_obj):
            emit("packet", from_="strategist", to="builder",
                 label=str(biz["name"])[:26])
            try:
                site_result = orch.run("ai_generate_website", {
                    "name": biz["name"],
                    "category": biz.get("category", ""),
                    "address": biz.get("address", ""),
                    "phone": biz.get("phone", ""),
                    "email": email,
                    "opening_hours": biz.get("opening_hours", ""),
                    "tags": biz.get("tags", {}),
                })
                if site_result.success:
                    website_path = site_result.output.get("path", "")
                    if site_result.output.get("ai_powered"):
                        ai_count += 1
            except Exception as e:
                errors.append({"name": biz["name"], "type": "website", "error": str(e)})

        if email_result.success:
            draft = email_result.output
            draft["pdf_path"] = pdf_path
            draft["website_path"] = website_path
            draft["business"] = biz
            if session_attachment and not draft.get("attachment"):
                draft["attachment"] = session_attachment
            if email_result.output.get("ai_powered"):
                ai_count += 1
            emit("bot", bot="strategist", status="done",
                 task=f"Draft for {biz['name']}: {draft.get('subject', '')[:50]}",
                 source="workflow")
            emit("packet", from_="strategist", to="drafts",
                 label=str(biz["name"])[:26])
            # Learn from this draft
            learn_from_draft(category, draft.get("subject", ""), draft.get("body", ""))
            # Day-one brain memory: capture the draft itself, not just sends,
            # so future sessions know we've been in touch.
            try:
                from agents.brain import get_brain
                get_brain().learn_business(
                    biz["name"],
                    category=category,
                    facts={"email": draft.get("to", "")},
                    interaction={"type": "drafted", "detail": draft.get("subject", "")[:80]},
                    source="draft",
                )
            except Exception:
                pass
            drafts.append(draft)
        else:
            errors.append({"name": biz["name"], "type": "email", "error": email_result.error})

    return {"drafts": drafts, "errors": errors, "ai_used": ai_count}


# ── The send leg lives in its own module (agents/outreach_send.py) —
#    parsers + review/send + receipts. Re-exported here so existing
#    consumers keep their import path; new code imports from there.
from agents.outreach_send import (  # noqa: F401
    parse_send_selection, parse_send_numbers,
    review_and_send_workflow, send_emails_workflow,
)


def obsidian_sync_workflow(businesses: list[dict], session_id: str,
                          project_name: str, approached: list[dict] = None) -> dict:
    """Sync everything to Obsidian — all 7 note types with cross-links.

    Implementation lives in obsidian_sync.run_sync_workflow (its natural
    owner); this wrapper keeps the existing import path stable.
    """
    from agents.obsidian_sync import run_sync_workflow
    return run_sync_workflow(businesses, session_id, project_name, approached)


def run_outreach_pipeline(location: str, radius: int, session_id: str,
                           project_name: str, sender_name: str,
                           auto_select: str = "", category: str = "",
                           goal: str = "") -> dict:
    """One-shot outreach pipeline. Runs the full workflow end-to-end.
    
    Returns a report dict with all results. The caller handles UI.
    User interacts at two points: selecting businesses, confirming send.
    """
    report = {
        "location": location, "radius": radius,
        "search": {}, "enrich": {}, "draft": {}, "send": {}, "sync": {},
        "errors": [],
    }

    from agents.event_bus import emit

    # 1. SEARCH
    emit("step", phase="search", message=f"Hunting businesses in {location}...", done=False)
    search = search_businesses_workflow(location, radius, category=category, goal=goal)
    if "error" in search:
        emit("step", phase="search", message=f"Search failed: {search['error']}", done=True, failed=True)
        report["errors"].append({"step": "search", "error": search["error"]})
        return report
    emit("step", phase="search",
         message=f"Found {len(search['businesses'])} businesses "
                 f"({len(search['no_site'])} without website)", done=True)
    report["search"] = {
        "total": len(search["businesses"]),
        "no_site": len(search["no_site"]),
        "with_site": len(search["with_site"]),
        "filter_report": search.get("filter_report", ""),
        "icp": search.get("icp", {}),
        "goal": search.get("goal", ""),
        "goal_label": search.get("goal_label", ""),
    }

    # Persist the search leg NOW, before any later stage can fail or hang:
    # a discovery that took minutes of API work must survive a scrape crash,
    # a timeout, or the user walking away mid-run. (_handle_search re-saves
    # the same file with the enriched report afterwards — same key layout,
    # so a later stage overwriting this is harmless.)
    if session_id:
        try:
            save_session_data(session_id, {
                "location": location, "radius": radius,
                "businesses": search["businesses"],
                "no_website": search["no_site"],
                "goal": search.get("goal", ""),
            }, "search_results.json")
        except Exception:
            pass  # persistence failure must not break the run

    # 2. SCRAPE (Scrapling — get contact details from websites)
    businesses_with_site = search["with_site"]
    if businesses_with_site:
        emit("step", phase="scrape", message=f"Scraping {len(businesses_with_site[:20])} websites...", done=False)
        emit("packet", from_="search", to="scraper", label="with-site list")
        scraped = scrape_businesses_workflow(businesses_with_site[:20])
        # Merge scraped data back
        scraped_map = {b["name"]: b for b in scraped}
        for i, b in enumerate(search["no_site"]):
            pass  # no-site businesses don't have sites to scrape
        for i, b in enumerate(search["businesses"]):
            if b["name"] in scraped_map:
                search["businesses"][i].update(scraped_map[b["name"]])

    # 3. ENRICH
    #    - With Hunter key: find emails for businesses that HAVE a website (Hunter
    #      needs a domain). Merge any results back into no_site by name.
    #    - Without Hunter key: run the best-effort Maps/Google contact fallback on
    #      the no-site outreach targets (the businesses we'll actually email), plus
    #      the with-site businesses, so we get phone + email for both.
    hunter_key = get_hunter_key()
    if hunter_key and businesses_with_site:
        emit("step", phase="enrich", message="Looking up emails via Hunter...", done=False)
        emit("packet", from_="scraper", to="enricher", label="domains")
        enrich_result = enrich_workflow(businesses_with_site[:20], hunter_key)
        report["enrich"] = {
            "enriched": enrich_result["enriched_count"],
            "total": len(businesses_with_site),
            "method": "hunter",
        }
        enrich_map = {r["name"]: r for r in enrich_result["results"]}
        for b in search["no_site"]:
            if b["name"] in enrich_map and enrich_map[b["name"]].get("found"):
                b["email"] = enrich_map[b["name"]]["email"]
    else:
        maps_targets = list(search["no_site"])
        if businesses_with_site:
            maps_targets.extend(businesses_with_site[:20])
        if maps_targets:
            emit("step", phase="enrich", message="Maps/Google contact fallback...", done=False)
            emit("packet", from_="scraper", to="enricher", label="contact hunt")
            maps_result = enrich_workflow(maps_targets, "")
            report["enrich"] = {
                "enriched": maps_result["enriched_count"],
                "phone_found": maps_result.get("phone_found", 0),
                "total": len(maps_targets),
                "method": "maps_fallback",
            }

    # Phone/email export for later WhatsApp messaging — written from the
    # enriched business list so it's available as soon as enrichment completes.
    phones_csv = ""
    try:
        if search["businesses"]:
            phones_csv = write_phones_csv(search["businesses"])
    except Exception:
        phones_csv = ""
    emit("step", phase="enrich", message="Enrichment done", done=True)

    # Return here — caller handles selection + send + sync
    report["businesses"] = search["businesses"]
    report["no_site"] = search["no_site"]
    report["with_site"] = search["with_site"]
    report["phones_csv"] = phones_csv
    return report


def complete_outreach(selected: list[dict], session_id: str,
                      project_name: str, sender_name: str,
                      research_data: list[dict] = None,
                      goal: str = "", angles: dict = None) -> dict:
    """Complete the outreach: draft, PDF, website, Obsidian sync.

    Called after user selects businesses. Returns full results.

    research_data: results from research_workflow, if any. Drafts are
    saved to the session so review/send finds them afterwards.
    angles: {business_name: user's angle note} from the campaign interview.
    """
    result = {
        "drafts": [], "errors": [], "sync": {},
    }

    # Draft emails + PDFs + websites, pitched for this goal
    draft_result = draft_and_pdf_workflow(selected, sender_name, research_data,
                                          goal=goal, angles=angles)
    result["drafts"] = draft_result["drafts"]
    result["errors"] = draft_result["errors"]
    result["ai_used"] = draft_result.get("ai_used", 0)

    # Persist drafts so 'review emails' / 'send' work after quick outreach
    if session_id and result["drafts"]:
        try:
            save_session_data(session_id, {
                "drafts": [trim_draft_for_storage(d) for d in result["drafts"]],
            }, "email_drafts.json")
        except Exception:
            pass  # persistence failure must not break the run

    # Sync to Obsidian
    sync_result = obsidian_sync_workflow(
        selected, session_id, project_name, selected)
    result["sync"] = sync_result

    return result


def trim_draft_for_storage(draft: dict) -> dict:
    """Lighten a draft before saving it to session JSON.

    Keeps all email fields (to/subject/body/pdf_path/attachment/approved),
    but replaces the bulky full 'business' object with a slim subset so the
    email review UI can still show the target's name/category.
    """
    out = dict(draft)
    biz = draft.get("business")
    if isinstance(biz, dict):
        slim = {k: biz.get(k) for k in ("name", "category", "address") if biz.get(k)}
        out["business"] = slim
    return out


def setup_hunter_key(key: str) -> dict:
    if key:
        set_hunter_key(key)
        return {"success": True}
    return {"success": False}
