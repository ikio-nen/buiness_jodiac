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
        from agents.pipeline_handler import run_step_search
        run_step_search(session)

    elif choice == "5":
        from agents.pipeline_handler import run_step_enrich
        run_step_enrich(session)

    elif choice == "6":
        from agents.pipeline_handler import run_step_select
        run_step_select(session)

    elif choice == "7":
        from agents.pipeline_handler import run_step_draft
        run_step_draft(session)

    elif choice == "8":
        from agents.pipeline_handler import run_step_review_send
        run_step_review_send(session)

    elif choice == "9":
        from agents.pipeline_handler import run_step_sync
        run_step_sync(session)

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
