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
    save_session_data, load_session_data,
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

    Every successful research result is also stored in the brain as
    per-business knowledge (agents/businesses/<name>.json).
    """
    from agents.business_research import research_batch
    results = research_batch(businesses)

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
    """Enrich businesses with Hunter.io when the key is set, otherwise run a
    best-effort Maps/Google contact fallback for phone + email.

    Returns {enriched, enriched_count, method, results}."""
    if not hunter_key:
        maps = enrich_with_maps_contacts(businesses)
        return {
            "enriched": businesses,
            "enriched_count": maps["email_found"],
            "skipped": False,
            "method": "maps_fallback",
            "phone_found": maps["phone_found"],
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

        # Per-business brain memory: rating, gaps, past interactions.
        # Guarded like every other learning hook — a brain failure must
        # never break drafting.
        brain_ctx = ""
        try:
            from agents.brain import get_brain
            brain_ctx = get_brain().get_business_context(biz["name"])
        except Exception:
            brain_ctx = ""

        # Combine: industry learning + business research + brain memory
        combined_ctx = learning_ctx
        if research_ctx:
            combined_ctx = f"{learning_ctx}\n\n--- Research on this specific business ---\n{research_ctx}" if learning_ctx else research_ctx
        if brain_ctx:
            combined_ctx = f"{combined_ctx}\n\n--- Brain memory of this business ---\n{brain_ctx}" if combined_ctx else brain_ctx

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

        email_task = "ai_draft_email" if use_ai else "draft_email"
        # AI first; the orchestrator owns the ai_* -> template fallback and
        # the agent layer owns raising-vs-falling, so the workflow just runs
        # one task and reports honestly. (ai_design now raises on failure, so
        # an ai_ task failing here really does mean both layers failed.)
        email_result = orch.run(email_task, {
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
                # Same single-task policy as email: orchestrator handles the
                # ai_* -> template fallback, agent layer raises on failure.
                site_result = orch.run(site_task, {
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
        return {"sent": [], "skipped": len(drafts), "attached": 0, "errors": [],
                "sent_pdf_dir": str(sent_dir()), "contacted_csv": ""}

    # Prepare approved drafts for sending (with attachments)
    send_list = get_approved_with_attachments(approved)

    # Send
    sent = []
    errors = []
    attached_count = 0
    sent_records = []

    for draft in send_list:
        if not draft.get("to"):
            continue
        biz = draft.get("business", {})
        pdf_path = draft.get("pdf_path", "")
        # Only attach a proposal PDF that actually exists on disk
        real_pdf = pdf_path if pdf_path and Path(pdf_path).exists() else ""
        if real_pdf:
            attached_count += 1
        result = send_email(
            to=draft["to"],
            subject=draft["subject"],
            body=draft["body"],
            pdf_path=real_pdf,
            sender_name=sender_name,
            attachment_path=draft.get("attachment_path", ""),
        )
        if result["success"]:
            # Write the sent-email receipt PDF
            attached_name = Path(real_pdf).name if real_pdf else None
            rec_path = send_receipt_pdf(
                business_name=biz.get("name", "Business"),
                to=draft["to"],
                subject=draft["subject"],
                body=draft["body"],
                sender_name=sender_name,
                attached_pdf_name=attached_name,
            )
            record = {
                "business": biz,
                "to": draft["to"],
                "subject": draft["subject"],
                "body": draft["body"],
                "pdf_path": real_pdf,
                "receipt_pdf": rec_path,
                "timestamp": datetime.now().isoformat(),
            }
            sent.append(draft)
            sent_records.append(record)
            if biz.get("name"):
                mark_contact_approached(biz["name"])
                learn_from_send(
                    biz.get("category", ""),
                    draft.get("subject", ""),
                    draft.get("body", ""),
                    success=True,
                )
        else:
            errors.append({"name": biz.get("name", "?") if biz else "?",
                          "error": result.get("error", "Unknown")})

    # Phone/email export of the businesses we actually contacted, for later
    # WhatsApp messaging. (A broader export is also written in
    # run_outreach_pipeline from the full enriched business list.)
    contacted_csv = ""
    if sent_records:
        try:
            contacted_csv = write_phones_csv(
                [r["business"] for r in sent_records],
                out_dir=sent_dir(),
                filename="phones_contacted_{}.csv".format(
                    datetime.now().strftime("%Y%m%d_%H%M%S")),
            )
        except Exception:
            contacted_csv = ""

    return {
        "sent": sent,
        "skipped": len(drafts) - len(sent),
        "attached": attached_count,
        "errors": errors,
        "sent_records": sent_records,
        "sent_pdf_dir": str(sent_dir()),
        "contacted_csv": contacted_csv,
    }


def send_emails_workflow(drafts: list[dict], sender_name: str) -> dict:
    """Send emails. Filters empty 'to'. Returns {sent, skipped, errors}."""
    skipped = [d for d in drafts if not d.get("to")]
    to_send = [d for d in drafts if d.get("to")]

    sent = []
    errors = []
    attached_count = 0
    sent_records = []

    for draft in to_send:
        if not draft.get("to"):
            continue
        biz = draft.get("business", {})
        pdf_path = draft.get("pdf_path", "")
        real_pdf = pdf_path if pdf_path and Path(pdf_path).exists() else ""
        if real_pdf:
            attached_count += 1
        result = send_email(
            to=draft["to"],
            subject=draft["subject"],
            body=draft["body"],
            pdf_path=real_pdf,
            sender_name=sender_name,
            attachment_path=draft.get("attachment_path", ""),
        )
        if result["success"]:
            attached_name = Path(real_pdf).name if real_pdf else None
            rec_path = send_receipt_pdf(
                business_name=biz.get("name", "Business"),
                to=draft["to"],
                subject=draft["subject"],
                body=draft["body"],
                sender_name=sender_name,
                attached_pdf_name=attached_name,
            )
            record = {
                "business": biz,
                "to": draft["to"],
                "subject": draft["subject"],
                "body": draft["body"],
                "pdf_path": real_pdf,
                "receipt_pdf": rec_path,
                "timestamp": datetime.now().isoformat(),
            }
            sent.append(draft)
            sent_records.append(record)
            if biz.get("name"):
                mark_contact_approached(biz["name"])
            learn_from_send(
                biz.get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=True,
            )
            # Per-business brain memory of the send
            try:
                from agents.brain import get_brain
                get_brain().learn_business(
                    biz.get("name", "?"),
                    category=biz.get("category", ""),
                    facts={"phone": biz.get("phone", ""), "email": draft.get("to", "")},
                    interaction={"type": "emailed", "detail": draft.get("subject", "")[:80]},
                    source="send",
                )
            except Exception:
                pass
        else:
            errors.append({"name": biz.get("name", "?") if biz else "?",
                          "error": result.get("error", "Unknown")})
            learn_from_send(
                draft.get("business", {}).get("category", "unknown"),
                draft.get("subject", ""),
                draft.get("body", ""),
                success=False,
            )

    contacted_csv = ""
    if sent_records:
        try:
            contacted_csv = write_phones_csv(
                [r["business"] for r in sent_records],
                out_dir=sent_dir(),
                filename="phones_contacted_{}.csv".format(
                    datetime.now().strftime("%Y%m%d_%H%M%S")),
            )
        except Exception:
            contacted_csv = ""

    return {
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "sent_records": sent_records,
        "attached": attached_count,
        "sent_pdf_dir": str(sent_dir()),
        "contacted_csv": contacted_csv,
    }


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

    # 3. ENRICH
    #    - With Hunter key: find emails for businesses that HAVE a website (Hunter
    #      needs a domain). Merge any results back into no_site by name.
    #    - Without Hunter key: run the best-effort Maps/Google contact fallback on
    #      the no-site outreach targets (the businesses we'll actually email), plus
    #      the with-site businesses, so we get phone + email for both.
    hunter_key = get_hunter_key()
    if hunter_key and businesses_with_site:
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

    # Return here — caller handles selection + send + sync
    report["businesses"] = search["businesses"]
    report["no_site"] = search["no_site"]
    report["with_site"] = search["with_site"]
    report["phones_csv"] = phones_csv
    return report


def complete_outreach(selected: list[dict], session_id: str,
                      project_name: str, sender_name: str,
                      research_data: list[dict] = None) -> dict:
    """Complete the outreach: draft, PDF, website, Obsidian sync.

    Called after user selects businesses. Returns full results.

    research_data: results from research_workflow. If omitted, the research
    already persisted for this session is used — drafting never ignores
    research the pipeline just spent minutes gathering.
    Drafts are saved to the session so review/send finds them afterwards.
    """
    result = {
        "drafts": [], "errors": [], "sync": {},
    }

    if research_data is None and session_id:
        research_data = load_session_data(
            session_id, "research.json").get("research", [])

    # Draft emails + PDFs + websites
    draft_result = draft_and_pdf_workflow(selected, sender_name, research_data)
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
