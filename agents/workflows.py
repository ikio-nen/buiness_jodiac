"""Pure workflow logic. No UI calls. Each function takes explicit params, returns results."""
from pathlib import Path
from agents.map_search import geocode, search_businesses, filter_no_website, verify_no_site_businesses
from agents.pdf_gen import generate_proposal_pdf
from agents.mailer import send_email
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
)
from agents import Orchestrator
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
    """
    from agents.business_research import research_batch
    return research_batch(businesses)


def search_businesses_workflow(location: str, radius: int,
                              category: str = "") -> dict:
    """Search for businesses. Returns {geo_display, businesses, no_site, with_site} or error."""
    if not location:
        return {"error": "No location provided"}

    geo = geocode(location)
    if not geo:
        return {"error": "Could not find that location"}

    # Always search ALL categories for comprehensive results
    businesses = search_businesses(geo["lat"], geo["lon"], radius)

    # Filter by category if specified
    if category:
        from agents.category_filter import filter_by_category
        businesses = filter_by_category(businesses, category)
    no_site = filter_no_website(businesses)
    with_site = [b for b in businesses if b.get("website")]

    # Verify no-site businesses via web search to catch OSM-missing websites
    verified_businesses = verify_no_site_businesses(businesses, location)
    verified_no_site = filter_no_website(verified_businesses)
    verified_with_site = [b for b in verified_businesses if b.get("website")]

    # Learn from this search
    learn_from_search(verified_businesses, location)

    return {
        "geo_display": geo["display"],
        "businesses": verified_businesses,
        "no_site": verified_no_site,
        "with_site": verified_with_site,
    }


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
    """Enrich businesses with Hunter.io. Returns {enriched, enriched_count}."""
    if not hunter_key:
        return {"enriched": businesses, "enriched_count": 0, "skipped": True}

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
            results.append({"name": biz["name"], "email": result.output["email"],
                           "position": result.output.get("position", "N/A"), "found": True})
        else:
            results.append({"name": biz["name"], "email": None, "found": False})

    return {"enriched": businesses, "enriched_count": enriched_count, "results": results}


def select_businesses_workflow(businesses: list[dict], choice: str) -> list[dict]:
    """Parse user selection. Returns selected businesses."""
    choice = choice.strip().lower()
    if choice == "all":
        return list(businesses)
    if choice == "top5":
        return list(businesses[:5])

    selected = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(businesses):
                selected.append(businesses[idx])
    return selected


def draft_and_pdf_workflow(businesses: list[dict], sender_name: str,
                           research_data: list[dict] = None) -> dict:
    """Draft emails, generate PDFs, and create websites for no-site businesses.

    Args:
        businesses: List of business dicts to process.
        sender_name: Name to use in email signature.
        research_data: Optional list of research dicts (from research_workflow).
            Each dict should have 'name', 'strengths', 'gaps', 'email_hook',
            'improvement_suggestion'. If provided, emails are personalized.

    Returns {drafts, errors, ai_used}.
    """
    from agents import ai_engine
    from agents.business_research import format_research_for_email, get_research_for_business
    use_ai = ai_engine.is_available()
    drafts = []
    errors = []
    ai_count = 0

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

        # Combine learning + research context
        combined_ctx = learning_ctx
        if research_ctx:
            combined_ctx = f"{learning_ctx}\n\n--- Research on this specific business ---\n{research_ctx}" if learning_ctx else research_ctx

        email_task = "ai_draft_email" if use_ai else "draft_email"
        email_result = orch.run(email_task, {
            "business_name": biz["name"],
            "contact_name": contact_name,
            "email": email,
            "category": category,
            "learning_context": combined_ctx,
        }, context={"sender_name": sender_name})

        if not email_result.success and use_ai:
            email_result = orch.run("draft_email", {
                "business_name": biz["name"],
                "contact_name": contact_name,
                "email": email,
                "category": category,
                "learning_context": combined_ctx,
            }, context={"sender_name": sender_name})

        # PDF
        pdf_path = ""
        try:
            pdf_path = generate_proposal_pdf(biz, sender_name)
        except Exception as e:
            errors.append({"name": biz["name"], "type": "pdf", "error": str(e)})

        # Website — only for businesses without one
        website_path = ""
        if not biz.get("website"):
            site_task = "ai_generate_website" if use_ai else "generate_website"
            try:
                site_result = orch.run(site_task, {
                    "name": biz["name"],
                    "category": biz.get("category", ""),
                    "address": biz.get("address", ""),
                    "phone": biz.get("phone", ""),
                    "email": email,
                    "opening_hours": biz.get("opening_hours", ""),
                    "tags": biz.get("tags", {}),
                })
                if not site_result.success and use_ai:
                    site_result = orch.run("generate_website", {
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
            if email_result.output.get("ai_powered"):
                ai_count += 1
            # Learn from this draft
            learn_from_draft(category, draft.get("subject", ""), draft.get("body", ""))
            drafts.append(draft)
        else:
            errors.append({"name": biz["name"], "type": "email", "error": email_result.error})

    return {"drafts": drafts, "errors": errors, "ai_used": ai_count}


def parse_send_selection(drafts: list[dict], choice: str) -> list[dict]:
    choice = choice.strip().upper()
    if choice == "A":
        return list(drafts)
    if choice == "S":
        return []
    return []


def parse_send_numbers(drafts: list[dict], nums_str: str) -> list[dict]:
    selected = []
    for n in nums_str.split(","):
        n = n.strip()
        if n.isdigit() and 0 < int(n) <= len(drafts):
            selected.append(drafts[int(n) - 1])
    return selected


def review_and_send_workflow(drafts: list[dict], sender_name: str) -> dict:
    """Review emails one-by-one, then send approved ones.

    Shows each email, lets user edit/attach/approve/skip,
    then sends only the approved ones.

    Returns {sent, skipped, attached, errors}.
    """
    from agents.email_review import review_and_edit_workflow, get_approved_with_attachments

    # Interactive review
    review_result = review_and_edit_workflow(drafts)
    approved = review_result.get("approved", [])

    if not approved:
        return {"sent": [], "skipped": len(drafts), "attached": 0, "errors": []}

    # Prepare approved drafts for sending (with attachments)
    send_list = get_approved_with_attachments(approved)

    # Send
    sent = []
    errors = []
    attached_count = sum(1 for d in send_list if d.get("attachment_path"))

    for draft in send_list:
        if not draft.get("to"):
            continue
        result = send_email(
            to=draft["to"],
            subject=draft["subject"],
            body=draft["body"],
            pdf_path=draft.get("pdf_path", ""),
            sender_name=sender_name,
            attachment_path=draft.get("attachment_path", ""),
        )
        if result["success"]:
            sent.append(draft)
            biz = draft.get("business", {})
            if biz.get("name"):
                mark_contact_approached(biz["name"])
                learn_from_send(
                    biz.get("category", ""),
                    draft.get("subject", ""),
                    draft.get("body", ""),
                    success=True,
                )
        else:
            errors.append({"name": draft.get("business", {}).get("name", "?"),
                          "error": result.get("error", "Unknown")})

    return {
        "sent": sent,
        "skipped": len(drafts) - len(sent),
        "attached": attached_count,
        "errors": errors,
    }


def send_emails_workflow(drafts: list[dict], sender_name: str) -> dict:
    """Send emails. Filters empty 'to'. Returns {sent, skipped, errors}."""
    skipped = [d for d in drafts if not d.get("to")]
    to_send = [d for d in drafts if d.get("to")]

    sent = []
    errors = []

    for draft in to_send:
        result = send_email(
            to=draft["to"],
            subject=draft["subject"],
            body=draft["body"],
            pdf_path=draft.get("pdf_path", ""),
            sender_name=sender_name,
            attachment_path=draft.get("attachment_path", ""),
        )
        if result["success"]:
            sent.append(draft)
            biz = draft.get("business", {})
            if biz.get("name"):
                mark_contact_approached(biz["name"])
            # Learn from successful send
            learn_from_send(
                biz.get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=True,
            )
        else:
            errors.append({"name": draft.get("business", {}).get("name", "?"),
                          "error": result.get("error", "Unknown")})
            # Learn from failed send (likely bounce)
            learn_from_send(
                draft.get("business", {}).get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=False,
            )

    return {"sent": sent, "skipped": skipped, "errors": errors}


def obsidian_sync_workflow(businesses: list[dict], session_id: str,
                          project_name: str, approached: list[dict] = None) -> dict:
    """Sync everything to Obsidian — all 7 note types with cross-links."""
    paths = []

    # 1. Project note
    path = create_project_note(session_id, project_name, businesses)
    paths.append(path)

    # 2. Contact notes + industry grouping
    by_cat: dict[str, list] = {}
    for biz in businesses:
        p = create_contact_note(biz, biz.get("enrichment"), session_id, project_name)
        paths.append(p)
        cat = biz.get("category", "other")
        by_cat.setdefault(cat, []).append(biz)

    # 3. Industry notes
    for cat, cat_biz in by_cat.items():
        p = create_industry_note(cat, cat_biz)
        paths.append(p)

    # 4. Research note
    p = create_research_note(session_id, project_name, businesses, businesses)
    paths.append(p)

    # 5. Competitor notes (top businesses)
    for biz in businesses[:5]:
        p = create_competitor_note(biz, session_id)
        paths.append(p)

    # 6. Follow-up notes
    for biz in (approached or []):
        p = create_followup_note(biz, session_id)
        paths.append(p)

    # 7. Insight note
    insights = {
        "Total businesses": len(businesses),
        "Without website": len([b for b in businesses if not b.get("website")]),
        "Industries": ", ".join(sorted(by_cat.keys())),
    }
    p = create_insight_note(session_id, project_name, businesses, insights)
    paths.append(p)

    # 8. Outreach form
    if approached:
        p = create_outreach_form(session_id, approached, project_name)
        paths.append(p)

    # 9. Per-business research notes (from session research data)
    try:
        from agents.session import Session as _S
        _tmp = _S()
        _tmp.id = session_id
        research_data = _tmp.load_research()
        if research_data:
            for biz in businesses:
                for r in research_data:
                    if r.get("name") == biz.get("name") and not r.get("error"):
                        p = create_business_research_note(biz, r, session_id)
                        paths.append(p)
                        break
    except Exception:
        pass

    # 10. Update vault index
    idx = update_vault_index()
    paths.append(idx)

    # 11. Dashboard, timeline, tags, graph config, brain map
    try:
        from agents.obsidian_upgrade import run_all_upgrades
        upgraded = run_all_upgrades()
        paths.extend(upgraded)
    except Exception:
        pass

    # 12. Brain map
    try:
        bm = create_brain_map()
        paths.append(bm)
    except Exception:
        pass

    return {"paths": paths, "vault": str(OBSIDIAN_VAULT)}


def run_outreach_pipeline(location: str, radius: int, session_id: str,
                           project_name: str, sender_name: str,
                           auto_select: str = "", category: str = "") -> dict:
    """One-shot outreach pipeline. Runs the full workflow end-to-end.
    
    Returns a report dict with all results. The caller handles UI.
    User interacts at two points: selecting businesses, confirming send.
    """
    report = {
        "location": location, "radius": radius,
        "search": {}, "enrich": {}, "draft": {}, "send": {}, "sync": {},
        "errors": [],
    }

    # 1. SEARCH
    search = search_businesses_workflow(location, radius, category=category)
    if "error" in search:
        report["errors"].append({"step": "search", "error": search["error"]})
        return report
    report["search"] = {
        "total": len(search["businesses"]),
        "no_site": len(search["no_site"]),
        "with_site": len(search["with_site"]),
    }

    # 2. SCRAPE (Scrapling — get contact details from websites)
    businesses_with_site = search["with_site"]
    if businesses_with_site:
        scraped = scrape_businesses_workflow(businesses_with_site[:20])
        # Merge scraped data back
        scraped_map = {b["name"]: b for b in scraped}
        for i, b in enumerate(search["no_site"]):
            pass  # no-site businesses don't have sites to scrape
        for i, b in enumerate(search["businesses"]):
            if b["name"] in scraped_map:
                search["businesses"][i].update(scraped_map[b["name"]])

    # 3. ENRICH (Hunter.io — find emails for businesses WITH websites)
    hunter_key = get_hunter_key()
    if hunter_key and businesses_with_site:
        enrich_result = enrich_workflow(businesses_with_site[:20], hunter_key)
        report["enrich"] = {
            "enriched": enrich_result["enriched_count"],
            "total": len(businesses_with_site),
        }
        # Merge enrichment data back into no_site list
        enrich_map = {r["name"]: r for r in enrich_result["results"]}
        for b in search["no_site"]:
            if b["name"] in enrich_map and enrich_map[b["name"]].get("found"):
                b["email"] = enrich_map[b["name"]]["email"]

    # Return here — caller handles selection + send + sync
    report["businesses"] = search["businesses"]
    report["no_site"] = search["no_site"]
    report["with_site"] = search["with_site"]
    return report


def complete_outreach(selected: list[dict], session_id: str,
                      project_name: str, sender_name: str) -> dict:
    """Complete the outreach: draft, PDF, website, Obsidian sync.
    
    Called after user selects businesses. Returns full results.
    """
    result = {
        "drafts": [], "errors": [], "sync": {},
    }

    # Draft emails + PDFs + websites
    draft_result = draft_and_pdf_workflow(selected, sender_name)
    result["drafts"] = draft_result["drafts"]
    result["errors"] = draft_result["errors"]
    result["ai_used"] = draft_result.get("ai_used", 0)

    # Sync to Obsidian
    sync_result = obsidian_sync_workflow(
        selected, session_id, project_name, selected)
    result["sync"] = sync_result

    return result


def setup_hunter_key(key: str) -> dict:
    if key:
        set_hunter_key(key)
        return {"success": True}
    return {"success": False}
