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
    }

    handler = handlers.get(action_type)
    if handler:
        return handler()

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

    if not location:
        return {"success": False, "message": "No location provided", "data": {},
                "live_events": []}

    report = run_outreach_pipeline(
        location, radius,
        session.id if session.active else "",
        session.name if session.active else "",
        sender, category=category,
    )

    # Save to session
    if session.active:
        session.save_data({
            "location": location, "radius": radius,
            "businesses": report.get("businesses", []),
            "no_website": report.get("no_site", []),
        }, "search_results.json")

    no_site = report.get("no_site", [])
    total = report.get("search", {}).get("total", 0)

    if report.get("errors"):
        errors = "; ".join(e.get("error", "") for e in report["errors"])
        return {"success": False, "message": f"Search error: {errors}",
                "data": report, "live_events": []}

    message = f"Found {total} businesses, {len(no_site)} without website"
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

    if not selected:
        return {"success": False, "message": "No businesses selected.",
                "data": {}, "live_events": []}

    # Research first
    research_data = research_workflow(selected)
    if session.active:
        session.save_research(research_data)

    # Draft
    result = draft_and_pdf_workflow(selected, sender, research_data)
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

    sent = len(result.get("sent", []))
    errors = len(result.get("errors", []))

    return {
        "success": sent > 0,
        "message": f"Sent {sent} emails, {errors} errors",
        "data": result,
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
    from agents.agent_team import ask_agent, AGENTS

    key = (params.get("agent") or "").lower()
    if key not in AGENTS:
        roster = ", ".join(sorted(AGENTS))
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
