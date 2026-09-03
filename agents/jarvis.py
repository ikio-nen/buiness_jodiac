#!/usr/bin/env python3
"""J.A.R.V.I.S - Thin orchestrator. Menu loop + dispatch only.

All handler logic lives in:
  - pipeline_handler.py  (quick outreach, full pipeline)
  - chat_handler.py      (conversational mode)
  - setup_handler.py     (setup menu, business profile)
  - dashboard_handler.py (learning dashboard)
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import agents.heavy as heavy_mod
from agents.config import OUTPUT_DIR, SITES_DIR
from agents.ui import (
    C, clear, pause, p, success, error, info, warn,
    banner, boot_sequence, farewell,
    show_session, show_main_menu, show_sessions,
    prompt,
)
from agents.session import Session, list_sessions

heavy_mod.SITES_DIR = SITES_DIR
heavy_mod.REPORTS_DIR = OUTPUT_DIR / "reports"

session = Session()


def _ensure_session():
    """Create a new session with wizard if needed."""
    if session.active:
        return
    from agents.ui import show_wizard_step, show_wizard_summary
    from agents.config import get_business_profile, set_business_profile

    show_wizard_step(1, 4, "Project name")
    name = prompt("")
    if not name:
        name = f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    profile = get_business_profile()
    if profile.get("product"):
        session.create(name)
        success(f"Session started: {session.id}")
        return

    show_wizard_step(2, 4, "What are we selling?",
                     "e.g. AutoCAD product keys, web design services")
    product = prompt("")

    show_wizard_step(3, 4, "Who are we targeting?",
                     "e.g. educational centers, restaurants, pharmacies")
    target = prompt("")

    show_wizard_step(4, 4, "Email tone (professional/friendly/casual)",
                     "Press Enter for professional")
    tone = prompt("") or "professional"

    session.create_with_wizard(name, product, target, tone)

    if product:
        set_business_profile({
            **profile,
            "product": product,
            "target_customers": target or profile.get("target_customers", ""),
            "email_tone": tone,
        })

    show_wizard_summary(session.load_profile())
    success(f"Session started: {session.id}")


def handle_choice(choice: str):
    """Dispatch menu choice to the appropriate handler."""
    if choice == "Q":
        return False

    if choice == "C":
        from agents.chat_handler import run_chat_mode
        run_chat_mode(session)

    elif choice == "R":
        from agents.pipeline_handler import run_quick_outreach
        run_quick_outreach(session)

    elif choice == "1":
        _ensure_session()
        success(f"Session: {session.name}")

    elif choice == "2":
        sessions = list_sessions()
        if not sessions:
            warn("No existing sessions found.")
            p("  Start a new project with [1] to create your first session.", C.DIM)
            return True
        show_sessions(sessions)
        idx = prompt("Choose session number (Enter to cancel): ")
        if idx.isdigit() and 0 < int(idx) <= len(sessions):
            s = sessions[int(idx) - 1]
            session.load(s["id"], s)
            success(f"Resumed: {session.name}")

    elif choice == "V":
        sessions = list_sessions()
        if not sessions:
            warn("No sessions to view.")
            p("  Start a new project with [1] to create your first session.", C.DIM)
            return True
        show_sessions(sessions)
        idx = prompt("Choose session to view (Enter to cancel): ")
        if idx.isdigit() and 0 < int(idx) <= len(sessions):
            s = sessions[int(idx) - 1]
            _view_session(s)

    elif choice == "D":
        sessions = list_sessions()
        if not sessions:
            warn("No sessions to delete.")
            return True
        show_sessions(sessions)
        idx = prompt("Choose session to DELETE (Enter to cancel): ")
        if idx.isdigit() and 0 < int(idx) <= len(sessions):
            s = sessions[int(idx) - 1]
            if prompt_yes_no(f"Delete '{s.get('name', 'Unnamed')}' ({s['id']})?"):
                import shutil
                from agents.config import SESSIONS_DIR
                session_path = SESSIONS_DIR / s["id"]
                if session_path.exists():
                    shutil.rmtree(session_path)
                    success(f"Deleted session: {s.get('name', 'Unnamed')}")
                else:
                    error("Session directory not found")

    elif choice == "3":
        _ensure_session()
        from agents.pipeline_handler import run_full_pipeline
        run_full_pipeline(session)

    elif choice == "4":
        _ensure_session()
        from agents.ui import step_header, status_badge, spinner, show_search_results
        from agents.workflows import search_businesses_workflow
        step_header(1, 5, "Searching Businesses")
        location = prompt("Search location (city/address): ")
        radius_str = prompt("Search radius in meters [2000]: ")
        radius = int(radius_str) if radius_str.isdigit() else 2000
        status_badge("active", f"Geocoding '{location}'...")
        spinner(f"Querying Overpass API for '{location}'", 1.0)
        result = search_businesses_workflow(location, radius)
        if "error" in result:
            status_badge("error", result["error"])
            if "location" in result["error"].lower() or "find" in result["error"].lower():
                p("  Tip: Try a major city name like 'London' or 'Manchester'", C.DIM)
        else:
            status_badge("complete", f"Found {len(result['businesses'])} businesses, {len(result['no_site'])} without website")
            show_search_results(result["no_site"], result["with_site"])
            session.save_data({"location": location, "radius": radius,
                              "businesses": result["businesses"],
                              "no_website": result["no_site"]}, "search_results.json")

    elif choice == "5":
        _ensure_session()
        from agents.ui import step_header, status_badge, spinner
        from agents.workflows import enrich_workflow, setup_hunter_key
        from agents.config import get_hunter_key
        step_header(2, 5, "Finding Emails (Hunter.io)")
        data = session.load_data("search_results.json")
        businesses = data.get("no_website", data.get("businesses", []))
        hunter_key = get_hunter_key()
        if not hunter_key:
            warn("Hunter.io API key not set.")
            key = prompt("Paste your Hunter.io API key (or Enter to skip): ")
            if key:
                setup_hunter_key(key)
                hunter_key = key
                success("Hunter.io key saved!")
            else:
                warn("Skipping email enrichment.")
                return True
        spinner(f"Enriching {len(businesses)} businesses via Hunter.io", 1.2)
        result = enrich_workflow(businesses, hunter_key)
        for r in result["results"]:
            if r["found"]:
                status_badge("complete", f"{r['name']}: {r['email']} ({r.get('position', 'N/A')})")
            else:
                p(f"  {r['name']}: no email found", C.DIM)
        status_badge("complete", f"Enriched {result['enriched_count']}/{len(businesses)} businesses with emails")

    elif choice == "6":
        _ensure_session()
        from agents.ui import step_header, show_select_list
        from agents.workflows import select_businesses_workflow
        step_header(3, 5, "Selecting Businesses")
        data = session.load_data("search_results.json")
        businesses = data.get("no_website", data.get("enriched", []))
        if not businesses:
            warn("No businesses to select.")
            return True
        show_select_list(businesses)
        sel = prompt("Select businesses: ")
        selected = select_businesses_workflow(businesses, sel)
        if selected:
            success(f"Selected {len(selected)} businesses")
            session.save_data({"selected": selected}, "selected.json")

    elif choice == "7":
        _ensure_session()
        from agents.ui import step_header, status_badge, spinner, show_draft_summary
        from agents.workflows import draft_and_pdf_workflow, research_workflow
        from agents.config import get_sender_name
        step_header(4, 5, "Research + Drafting Emails + PDFs")
        data = session.load_data("selected.json")
        selected = data.get("selected", [])
        if not selected:
            data2 = session.load_data("search_results.json")
            selected = data2.get("no_website", [])
        if not selected:
            warn("No businesses to draft for.")
            return True
        sender = get_sender_name()

        spinner(f"Researching {len(selected)} businesses", 1.0)
        research_data = research_workflow(selected)
        session.save_research(research_data)
        researched = [r for r in research_data if not r.get("error")]
        if researched:
            status_badge("complete", f"Researched {len(researched)} businesses")

        spinner(f"Generating {len(selected)} emails + PDFs", 1.0)
        result = draft_and_pdf_workflow(selected, sender, research_data)
        show_draft_summary(result)
        session.save_data({"drafts": [{k: v for k, v in d.items() if k != "business"}
                                      for d in result["drafts"]]}, "email_drafts.json")

    elif choice == "8":
        from agents.ui import step_header
        from agents.workflows import review_and_send_workflow
        from agents.config import get_sender_name
        step_header(5, 5, "Review & Send Emails")
        data = session.load_data("email_drafts.json")
        drafts = data.get("drafts", [])
        if not drafts:
            warn("No drafts found. Run Step 7 first.")
            return True
        sender = get_sender_name()
        send_result = review_and_send_workflow(drafts, sender)
        if send_result.get("sent"):
            success(f"Sent {len(send_result['sent'])} emails")
        if send_result.get("attached", 0) > 0:
            status_badge("complete", f"{send_result['attached']} file(s) attached")
        if send_result.get("errors"):
            for e in send_result["errors"][:3]:
                error(f"{e.get('name', '?')}: {e.get('error', '')[:50]}")
        session.save_data({"sent": send_result.get("sent", [])}, "sent_emails.json")

    elif choice == "9":
        _ensure_session()
        from agents.ui import step_header, status_badge, spinner
        from agents.workflows import obsidian_sync_workflow
        step_header(5, 5, "Syncing to Obsidian")
        data = session.load_data("search_results.json")
        businesses = data.get("no_website", [])
        status_badge("syncing", "Writing to Obsidian vault...")
        spinner("Syncing project notes + contact cards", 0.8)
        result = obsidian_sync_workflow(businesses, session.id, session.name)
        status_badge("complete", f"Synced {len(result['paths'])} files to {result['vault']}")

    elif choice == "S":
        from agents.setup_handler import run_setup
        run_setup()

    elif choice == "L":
        from agents.dashboard_handler import run_learning_dashboard
        run_learning_dashboard()

    elif choice == "W":
        from agents.web.server import start_server
        start_server()

    return True


def _view_session(s: dict):
    """View a session's summary."""
    from agents.session import Session as S
    tmp = S()
    tmp.load(s["id"], s)
    print(f"\n  {C.BOLD}Session: {s.get('name', 'Unnamed')}{C.RESET}")
    p(f"  ID: {s['id']}")
    p(f"  Started: {s.get('started', 'unknown')[:19]}")
    businesses = tmp.load_data("search_results.json")
    no_site = businesses.get("no_website", [])
    drafts = tmp.load_data("email_drafts.json")
    draft_list = drafts.get("drafts", [])
    p(f"  Businesses found: {len(no_site)}")
    p(f"  Drafts created: {len(draft_list)}")
    if no_site:
        p(f"  Top 5:")
        for b in no_site[:5]:
            p(f"    - {b.get('name', '?')} ({b.get('category', '')})")


def prompt_yes_no(text: str) -> bool:
    """Prompt for yes/no confirmation."""
    answer = input(f"  {C.RED}{C.BOLD}{text}{C.RESET} {C.DIM}{C.DARK}(yes/no):{C.RESET} ").strip().lower()
    return answer in ("yes", "y")


def main():
    boot_sequence()
    running = True
    while running:
        show_session(session.id, session.name)
        show_main_menu(has_session=session.active)
        choice = prompt(">")
        try:
            running = handle_choice(choice.upper())
        except KeyboardInterrupt:
            print()
            info("Interrupted.")
        except Exception as e:
            error(f"{type(e).__name__}: {e}")
        if running:
            pause()
            clear()
            banner()
    farewell()


if __name__ == "__main__":
    main()
