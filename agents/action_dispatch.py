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
        ActionType.SYNC: lambda: _handle_sync(params, session),
        ActionType.SCRAPE: lambda: _handle_scrape(params, session),
        ActionType.ENRICH: lambda: _handle_enrich(params, session),
        ActionType.STATUS: lambda: _handle_status(session),
        ActionType.DASHBOARD: lambda: _handle_dashboard(),
        ActionType.BRAINSTORM: lambda: _handle_brainstorm(),
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

    return {
        "success": True,
        "message": f"Found {total} businesses, {len(no_site)} without website",
        "data": {
            "total": total, "no_site": len(no_site),
            "with_site": report.get("search", {}).get("with_site", 0),
            "businesses": no_site,
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
        session.save_data({"drafts": [{k: v for k, v in d.items() if k != "business"}
                                       for d in drafts]}, "email_drafts.json")

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
    drafts = data.get("drafts", [])

    if not drafts:
        return {"success": False, "message": "No drafts to send. Draft first.",
                "data": {}, "live_events": []}

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
    """Handle Hunter.io enrichment action."""
    from agents.workflows import enrich_workflow
    from agents.config import get_hunter_key

    hunter_key = get_hunter_key()
    if not hunter_key:
        return {"success": False, "message": "Hunter.io API key not set.",
                "data": {}, "live_events": []}

    data = session.load_data("search_results.json") if session.active else {}
    businesses = data.get("no_website", data.get("businesses", []))

    if not businesses:
        return {"success": False, "message": "No businesses to enrich. Search first.",
                "data": {}, "live_events": []}

    result = enrich_workflow(businesses, hunter_key)
    return {
        "success": True,
        "message": f"Enriched {result['enriched_count']}/{len(businesses)} businesses",
        "data": result,
        "live_events": [],
    }


def _handle_status(session) -> dict:
    """Handle status action."""
    data = session.load_data("search_results.json") if session.active else {}
    drafts = session.load_data("email_drafts.json").get("drafts", []) if session.active else []

    return {
        "success": True,
        "message": f"Session: {session.name or 'None'}",
        "data": {
            "businesses": len(data.get("businesses", [])),
            "no_site": len(data.get("no_website", [])),
            "drafts": len(drafts),
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


def _handle_brainstorm() -> dict:
    """Handle brainstorm action."""
    return {
        "success": True,
        "message": "Let's set up your business profile!",
        "data": {},
        "live_events": [],
    }
