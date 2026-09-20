"""Action dispatch -- single entry point for executing JARVIS actions.

Every action (search, draft, send, research, etc.) goes through here.
Both the CLI chat handler and the menu dispatcher call this.

This eliminates the 3-way duplication between:
  - jarvis.py menu items [4]-[9]
  - chat_handler.py if/elif chain
  - web/server.py WebSocket handler
"""
from typing import Optional

from agents.config import get_sender_name, get_business_profile
from agents.chatbot import ActionType


def dispatch(action_type: ActionType, params: dict, session) -> dict:
    """Execute an action and return a result dict.

    Returns:
        {
            "success": bool,
            "message": str,        # human-readable result
            "data": dict,          # structured result data
            "live_events": list,   # live update events to display
        }
    """
    sender = get_sender_name()

    # The registry owns the ack line; handlers own the behavior. The ack
    # here is the CLI-visible fallback — the web layer uses its own ack
    # from action.response (which chatbot.py builds from the same table).
    from agents.action_registry import ack_for
    handlers = {
        ActionType.SEARCH: lambda: _handle_search(params, session, sender),
        ActionType.DRAFT: lambda: _handle_draft(params, session, sender),
        ActionType.SEND: lambda: _handle_send(params, session, sender),
        ActionType.RESEARCH: lambda: _handle_research(params, session),
        ActionType.REVIEW: lambda: _handle_review(session),
        ActionType.SYNC: lambda: _handle_sync(params, session),
        ActionType.SCRAPE: lambda: _handle_scrape(params, session),
        ActionType.ENRICH: lambda: _handle_enrich(params, session),
        ActionType.STATUS: lambda: _handle_status(session),
        ActionType.DASHBOARD: lambda: _handle_dashboard(),
        ActionType.BRAINSTORM: lambda: _handle_brainstorm(),
        ActionType.CHECKIN: lambda: _handle_checkin(),
        ActionType.ASK_AGENT: lambda: _handle_ask_agent(params, session),
        ActionType.TEAM_ACT: lambda: _handle_team_act(session),
        ActionType.CAMPAIGN: lambda: _handle_campaign(params, session, sender),
    }

    handler = handlers.get(action_type)
    if handler:
        result = handler()
        # One registry rule: a dispatched action with no ack of its own
        # falls back to the table's ack line.
        if isinstance(result, dict) and not result.get("message"):
            table_ack = ack_for(action_type)
            if table_ack:
                result = {**result, "message": table_ack}
        return result

    return {
        "success": False,
        "message": f"Unknown action: {action_type.value}",
        "data": {},
        "live_events": [],
    }


def _handle_search(params: dict, session, sender: str) -> dict:
    """Handle search action."""
    from agents.workflows import run_outreach_pipeline

    location = params.get("location", "")
    radius = params.get("radius", 2000)
    category = params.get("category", "")
    goal = params.get("goal", "")

    if not location:
        return {"success": False, "message": "No location provided", "data": {},
                "live_events": []}

    report = run_outreach_pipeline(
        location, radius,
        session.id if session.active else "",
        session.name if session.active else "",
        sender, category=category, goal=goal,
    )

    # Save to session, including which goal this batch was judged against so
    # the draft leg pitches the same thing the search targeted.
    if session.active:
        session.save_data({
            "location": location, "radius": radius,
            "businesses": report.get("businesses", []),
            "no_website": report.get("no_site", []),
            "goal": report.get("search", {}).get("goal", ""),
        }, "search_results.json")

    no_site = report.get("no_site", [])
    total = report.get("search", {}).get("total", 0)

    if report.get("errors"):
        errors = "; ".join(e.get("error", "") for e in report["errors"])
        return {"success": False, "message": f"Search error: {errors}",
                "data": report, "live_events": []}

    message = f"Found {total} businesses, {len(no_site)} without website"
    filter_report = report.get("search", {}).get("filter_report", "")
    if filter_report:
        message += f"\n  [filter] {filter_report}"
    phones_csv = report.get("phones_csv", "")
    enrich = report.get("enrich", {})
    if enrich.get("method") == "maps_fallback":
        emails_found = enrich.get("enriched", 0)
        phones_found = enrich.get("phone_found", 0)
        message += (f". Maps fallback found emails for {emails_found} "
                    f"and phones for {phones_found}")
        if emails_found == 0 and phones_found == 0:
            message += (" — nothing usable this time (Google did not surface "
                        "contact info; WhatsApp messaging will need another source)")
    if phones_csv:
        message += f". Phone/WhatsApp list saved: {phones_csv}"

    # Proactive: what did we learn from THIS search worth telling the user?
    from agents.proactive import proactive_notes, render_notes
    from agents.agent_team import team_act, team_proactive_notes
    notes = proactive_notes() + team_proactive_notes()

    # Layer 1: the team acts on the fresh batch unprompted. Scout researches
    # the top prospects, Strategist pre-writes hooks, Analyst debriefs.
    # Best-effort -- pipeline results are never blocked by team failures.
    team_res = None
    team_note = ""
    try:
        batch = no_site or report.get("search", {}).get("no_site", [])
        if batch:
            team_res = team_act(batch, session=session)
            if team_res.get("researched") or team_res.get("analyst_reply"):
                lines = [f"  Scout on {r['name']}: {r['scout_reply'][:140]}"
                         + (f" | Hook: {r['hook']}" if r["hook"] else "")
                         for r in team_res["researched"]]
                if team_res.get("analyst_reply"):
                    lines.append(f"  Analyst: {team_res['analyst_reply'][:180]}")
                team_note = "[AGENT TEAM]" + "\n" + "\n".join(lines)
    except Exception:
        team_res, team_note = None, ""

    notes_block = render_notes(notes)

    return {
        "success": True,
        "message": message
                   + (f"\n{team_note}" if team_note else "")
                   + (f"\n{notes_block}" if notes_block else ""),
        "data": {
            "total": total, "no_site": len(no_site),
            "with_site": report.get("search", {}).get("with_site", 0),
            "icp": report.get("search", {}).get("icp", {}),
            "businesses": no_site,
            "phones_csv": phones_csv,
            "proactive_notes": notes,
            "team_result": team_res,
        },
        "live_events": [],
    }


def _handle_draft(params: dict, session, sender: str) -> dict:
    """Handle draft action."""
    from agents.workflows import (
        select_businesses_workflow, complete_outreach,
        draft_and_pdf_workflow, research_workflow,
    )

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to draft for. Search first.",
                "data": {}, "live_events": []}

    selection = params.get("selection", "all")
    selected = select_businesses_workflow(businesses, selection)
    # Same goal the search was judged against, so the pitch matches the target.
    goal = params.get("goal") or data.get("goal", "")

    if not selected:
        return {"success": False, "message": "No businesses selected.",
                "data": {}, "live_events": []}

    # Research first
    research_data = research_workflow(selected)
    if session.active:
        session.save_research(research_data)

    # Draft
    result = draft_and_pdf_workflow(selected, sender, research_data, goal=goal)
    drafts = result.get("drafts", [])

    if session.active and drafts:
        from agents.workflows import trim_draft_for_storage
        session.save_data({"drafts": [trim_draft_for_storage(d) for d in drafts]},
                          "email_drafts.json")

    return {
        "success": bool(drafts),
        "message": f"Drafted {len(drafts)} emails" if drafts else "No drafts created",
        "data": result,
        "live_events": [],
    }


def _handle_send(params: dict, session, sender: str) -> dict:
    """Handle send action."""
    from agents.workflows import send_emails_workflow

    data = session.load_data("email_drafts.json") if session.active else {}
    drafts_all = data.get("drafts", [])

    if not drafts_all:
        return {"success": False, "message": "No drafts to send. Draft first.",
                "data": {}, "live_events": []}

    # If drafts were reviewed, only the approved ones may be sent.
    reviewed = any("approved" in d for d in drafts_all)
    if reviewed:
        approved = [d for d in drafts_all if d.get("approved") is True]
        if not approved:
            return {"success": False,
                    "message": "No approved emails to send. Say 'review emails' to approve drafts.",
                    "data": {}, "live_events": []}
        drafts = approved
    else:
        drafts = drafts_all

    has_email = [d for d in drafts if d.get("to")]
    if not has_email:
        return {"success": False, "message": "No businesses with email addresses.",
                "data": {}, "live_events": []}

    result = send_emails_workflow(has_email, sender)

    if session.active:
        session.save_data({"sent": result.get("sent", [])}, "sent_emails.json")

    # Final PDF report + campaign bookkeeping. Best-effort: a reporting
    # failure must not turn an executed send into a reported failure.
    final_pdf = ""
    try:
        from agents.campaign import final_report_pdf, get_state, mark_sent
        final_pdf = final_report_pdf(
            result.get("sent_records", []),
            result.get("errors", []),
            len(result.get("skipped", [])),
            session.name or "",
        )
        if get_state(session.id).get("phase"):
            mark_sent(session.id)
        if session.active:
            session.save_data({"final_pdf": final_pdf}, "campaign_final.json")
    except Exception as e:
        print(f"  [CAMPAIGN] final report failed: {e}")

    sent = len(result.get("sent", []))
    errors_n = len(result.get("errors", []))
    msg = f"Sent {sent} emails, {errors_n} errors"
    if final_pdf:
        msg += f"\n  Final report ready: {final_pdf}"

    return {
        "success": sent > 0,
        "message": msg,
        "data": {**result, "final_pdf": final_pdf},
        "live_events": [],
    }


def _handle_research(params: dict, session) -> dict:
    """Handle research action."""
    from agents.workflows import research_workflow

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to research. Search first.",
                "data": {}, "live_events": []}

    results = research_workflow(businesses)
    if session.active:
        session.save_research(results)

    researched = [r for r in results if not r.get("error")]
    return {
        "success": bool(researched),
        "message": f"Researched {len(researched)} businesses",
        "data": {"results": results},
        "live_events": [],
    }


def _handle_sync(params: dict, session) -> dict:
    """Handle Obsidian sync action."""
    from agents.workflows import obsidian_sync_workflow

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to sync. Search first.",
                "data": {}, "live_events": []}

    result = obsidian_sync_workflow(
        businesses,
        session.id if session.active else "",
        session.name if session.active else "",
    )

    return {
        "success": True,
        "message": f"Synced {len(result.get('paths', []))} files to Obsidian",
        "data": result,
        "live_events": [],
    }


def _handle_scrape(params: dict, session) -> dict:
    """Handle scrape action."""
    from agents.workflows import scrape_businesses_workflow

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to scrape. Search first.",
                "data": {}, "live_events": []}

    scraped = scrape_businesses_workflow(businesses)
    return {
        "success": True,
        "message": f"Scraped {len(scraped)} businesses",
        "data": {"scraped": scraped},
        "live_events": [],
    }


def _handle_enrich(params: dict, session) -> dict:
    """Handle enrichment action.

    With a Hunter key: domain-search emails for businesses that have one.
    Without a key: best-effort Maps/Google contact fallback for phone + email
    (the no-API-key path). Either way, enriched businesses are saved back to
    the session so draft/send see them.
    """
    from agents.workflows import enrich_workflow
    from agents.config import get_hunter_key

    hunter_key = get_hunter_key()

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to enrich. Search first.",
                "data": {}, "live_events": []}

    result = enrich_workflow(businesses, hunter_key)
    method = result.get("method", "hunter")

    # Save enriched businesses back so the draft/send steps see phone/email
    if session.active:
        data["no_website"] = businesses
        session.save_data(data, "search_results.json")

    if method == "maps_fallback":
        phone_found = result.get("phone_found", 0)
        email_found = result.get("enriched_count", 0)
        empty = result.get("maps_results", {}).get("empty", [])
        msg = (f"Maps fallback: found emails for {email_found}/{len(businesses)}, "
               f"phones for {phone_found}/{len(businesses)}")
        if empty and len(empty) == len(businesses):
            msg += " — nothing found (Google did not surface contact info for any of them)"
        contact = result.get("contact_finder") or {}
        execs = result.get("exec_finder") or {}
        if execs.get("found"):
            hits = ", ".join(
                f"{r['name']} → {r['exec_name'] or r['exec_email']}"
                + (f" ({r['exec_title']})" if r.get('exec_title') else "")
                for r in execs["results"])[:400]
            msg += f"\n  [exec] decision-makers found for {execs['found']}/{len(businesses)}: {hits}"
        if contact.get("searched"):
            if contact.get("found"):
                hits = ", ".join(
                    f"{r['name']} → {r['email']}" for r in contact["results"] if r.get("email"))
                msg += f"\n  [contact] domain hunt found emails for {contact['found']}/{contact['searched']}: {hits}"
            else:
                msg += (f"\n  [contact] domain hunt found no emails for "
                        f"{contact['searched']} businesses — drafts will need manual addresses")
            unverified = [r for r in contact["results"]
                          if r.get("email") and not r.get("verified")]
            if unverified:
                # Say it out loud: these were found on a domain guessed from the
                # business name, and a name is not an identity. They are NOT set
                # as the recipient, so the batch will not silently mail a
                # same-named institution in another state.
                msg += ("\n  [contact] " + str(len(unverified)) + " address(es) came from a "
                        "domain guessed from the name and are NOT set as recipients "
                        "(check them by hand): "
                        + ", ".join(f"{r['name']} → {r['email']}" for r in unverified)[:300])
        return {"success": True, "message": msg, "data": result, "live_events": []}

    return {
        "success": True,
        "message": f"Enriched {result['enriched_count']}/{len(businesses)} businesses",
        "data": result,
        "live_events": [],
    }


def _handle_team_act(session=None) -> dict:
    """Put the whole specialist team on the current prospect batch."""
    data = session.load_data("search_results.json") if (session and session.active) else {}
    batch = data.get("no_website", data.get("businesses", []))
    if not batch:
        from agents.agent_team import _latest_pending_batch
        batch = _latest_pending_batch()
    if not batch:
        return {"success": False,
                "message": "Nothing for the team to work on -- search for businesses first.",
                "data": {}, "live_events": []}

    from agents.agent_team import team_act
    try:
        res = team_act(batch, session=session)
    except Exception as e:
        return {"success": False, "message": f"Team run failed: {type(e).__name__}: {e}",
                "data": {}, "live_events": []}

    lines = [f"Team worked {len(res['researched'])} prospect(s):"]
    for r in res["researched"]:
        lines.append(f"- {r['name']}: {r['scout_reply'][:160]}"
                     + (f" | Hook: {r['hook']}" if r["hook"] else ""))
    if res.get("analyst_reply"):
        lines.append(f"Analyst: {res['analyst_reply'][:250]}")
    if res.get("vault_note"):
        lines.append(f"Debrief note: {res['vault_note']}")
    if res.get("errors"):
        lines.append(f"(issues: {'; '.join(res['errors'][:3])})")
    message = "\n".join(lines)
    if res["researched"]:
        message += "\n\nHooks are wired into drafting -- say 'draft emails' and Strategist's openings go in automatically."
    return {"success": bool(res["researched"] or res.get("analyst_reply")),
            "message": message, "data": res, "live_events": []}


def _handle_ask_agent(params: dict, session=None) -> dict:
    """Route a question to a specialist agent (their own brain + tools)."""
    from agents.agent_team import ask_agent, get_agent, all_agent_keys

    key = (params.get("agent") or "").lower()
    if not get_agent(key):
        roster = ", ".join(sorted(all_agent_keys()))
        return {"success": False, "message": f"No specialist named '{key}'. The team: {roster}.",
                "data": {}, "live_events": []}

    message = params.get("message", "")
    try:
        out = ask_agent(key, message, session=session)
    except Exception as e:
        return {"success": False, "message": f"{key.capitalize()} hit an error: {type(e).__name__}: {e}",
                "data": {}, "live_events": []}

    prefix = ""
    if out.get("drafts_saved"):
        n = out["drafts_saved"]
        prefix += (f"{out['agent']} wrote {n} email{'s' if n != 1 else ''} into your draft "
                   f"queue -- say 'review emails' to check {'them' if n != 1 else 'it'} before sending.\n\n")
    tag = " (searched the web)" if out.get("used_web") else ""
    tools_used = out.get("tools_used", [])
    if tools_used and not out.get("used_web"):
        tag = f" (used: {', '.join(tools_used)})"
    elif len(tools_used) > 1:
        tag = f" (used: {', '.join(tools_used)})"
    mem = out.get("memory_count", 0)
    message = f"{out['agent']} ({out['role']}){tag}:\n\n{out['reply']}"
    if mem:
        message += f"\n\n[{out['agent']} remembers {mem} thing{'s' if mem != 1 else ''} about you]"
    return {"success": True, "message": prefix + message,
            "data": {"agent": out["agent"], "reply": out["reply"],
                     "used_web": out["used_web"], "learned": out["learned"],
                     "tools_used": tools_used,
                     "drafts_saved": out.get("drafts_saved", 0)},
            "live_events": []}


def _handle_review(session) -> dict:
    """Handle review action (fallback summary; chat/web run the interactive flow)."""
    data = session.load_data("email_drafts.json") if session.active else {}
    drafts = data.get("drafts", [])
    if not drafts:
        return {"success": False, "message": "No drafts to review. Draft emails first.",
                "data": {}, "live_events": []}

    approved = len([d for d in drafts if d.get("approved") is True])
    pending = len(drafts) - approved
    return {
        "success": True,
        "message": f"{len(drafts)} draft(s) available, {approved} approved, "
                   f"{pending} still pending review.",
        "data": {"total": len(drafts), "approved": approved, "pending": pending},
        "live_events": [],
    }


def _handle_campaign(params: dict, session, sender: str) -> dict:
    """Guided campaign: discover + curate the shortlist, then STOP.

    The result carries ``campaign_checklist`` data; the web layer turns it
    into the interactive checklist and does not run another stage until the
    user approves a selection. The CLI path just shows the curated list and
    tells the user to select.
    """
    from agents.campaign import (curate_workflow, start_selection,
                                 get_state, checklist_payload)

    location = params.get("location", "")
    radius = int(params.get("radius", 2000) or 2000)
    category = params.get("category", "")
    goal = params.get("goal", "")

    if not session.active:
        return {"success": False, "message": "No active session — start one first.",
                "data": {}, "live_events": []}

    # A paused gate resumes instead of restarting: bare "campaign" must not
    # silently run a new discovery and overwrite the saved shortlist/angles
    # (the pause message literally tells the user to do this). An EXPLICIT
    # new request — a location or category named — always starts fresh: the
    # user asking "campaign in X, training centers only" while a gate is
    # open wants the NEW intent, not the old shortlist replayed. This exact
    # swallow made a corrected "...and no schools" request return the old
    # school-filled checklist unchanged.
    state = get_state(session.id)
    explicit_restart = bool((params.get("location") or "").strip()
                            or (params.get("category") or "").strip())
    if (state.get("phase") in ("awaiting_selection", "interview")
            and not explicit_restart):
        payload = checklist_payload(state)
        if state["phase"] == "awaiting_selection" and payload.get("businesses"):
            lines = [f"Resuming campaign in {state.get('location') or 'your area'} — "
                     f"{len(payload['businesses'])} curated candidates are still waiting."]
            lines.append("Tick the ones you want and approve the checklist — "
                         "nothing was lost while it was paused.")
            return {"success": True, "message": "\n".join(lines),
                    "data": {"campaign_checklist": payload}, "live_events": []}
        if state["phase"] == "interview":
            from agents.campaign import current_question
            return {"success": True,
                    "message": "Resuming the tuning round. " + current_question(state),
                    "data": {"campaign_checklist": payload}, "live_events": []}

    location = params.get("location", "")
    radius = int(params.get("radius", 2000) or 2000)
    category = params.get("category", "")
    goal = params.get("goal", "")

    if not location:
        return {"success": False, "message": "No location provided for the campaign.",
                "data": {}, "live_events": []}

    result = curate_workflow(
        location, radius, category, goal, sender,
        session.id, session.name or "",
    )
    if result.get("error"):
        return {"success": False, "message": f"Campaign discovery failed: {result['error']}",
                "data": {}, "live_events": []}

    curated = result.get("curated", [])
    state = start_selection(session.id, location, radius, category, goal, curated)

    # Persist the full search exactly like _handle_search does, so every
    # downstream consumer (draft, send, enrich, status) sees this campaign's
    # data; the curated shortlist becomes the default 'no_website' batch.
    report = result.get("report", {})
    curated_full = result.get("curated", [])
    try:
        session.save_data({
            "location": location, "radius": radius,
            "businesses": report.get("businesses", []),
            "no_website": curated_full,
            "goal": report.get("search", {}).get("goal", ""),
        }, "search_results.json")
    except Exception:
        pass

    lines = [f"Found and curated {len(curated)} candidates in {location}:"]
    for i, b in enumerate(state.get("curated", []), 1):
        contact = b.get("email") or b.get("phone") or "no contact on file"
        lines.append(f"  {i}. {b.get('name', '?')} — {b.get('category', '') or 'n/a'} ({contact})")
    lines.append("")
    lines.append("Review, tick the ones you want, and approve the checklist "
                 "in the panel — I will not go further until you do.")

    return {
        "success": True,
        "message": "\n".join(lines),
        "data": {"campaign_checklist": {
            "location": state.get("location", ""),
            "goal": state.get("goal", ""),
            "businesses": state.get("curated", []),
            "selected": state.get("selected", []),
        }},
        "live_events": [],
    }


def _handle_status(session) -> dict:
    """Handle status action."""
    data = session.load_data("search_results.json") if session.active else {}
    drafts = session.load_data("email_drafts.json").get("drafts", []) if session.active else []
    sent = session.load_data("sent_emails.json").get("sent", []) if session.active else []

    businesses = len(data.get("businesses", []))
    no_site = len(data.get("no_website", []))
    draft_count = len(drafts)
    sent_count = len(sent)
    name = session.name or "None"

    msg = (f"Session '{name}': {businesses} businesses found "
           f"({no_site} without website), {draft_count} drafts, {sent_count} sent.")

    return {
        "success": True,
        "message": msg,
        "data": {
            "businesses": businesses,
            "no_site": no_site,
            "drafts": draft_count,
            "sent": sent_count,
        },
        "live_events": [],
    }


def _handle_dashboard() -> dict:
    """Handle dashboard action."""
    from agents.learn import get_learning_summary
    return {
        "success": True,
        "message": get_learning_summary(),
        "data": {},
        "live_events": [],
    }


def _handle_checkin() -> dict:
    """Agent check-in: scan brain, vault, KB and sessions for what matters."""
    from agents.proactive import check_in, format_briefing
    brief = check_in()
    return {
        "success": True,
        "message": format_briefing(brief),
        "data": brief,
        "live_events": [],
    }


def _handle_brainstorm() -> dict:
    """Handle brainstorm action."""
    return {
        "success": True,
        "message": "Let's set up your business profile!",
        "data": {},
        "live_events": [],
    }
