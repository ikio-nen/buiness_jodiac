"""Chat handler -- conversational mode for JARVIS (Gemini-powered)."""
import random as _rand

from agents.config import get_sender_name, get_business_profile
from agents.ui import (
    C, p, success, error, info, warn, clear, banner,
    typing_print, spinner, prompt, prompt_yes_no, show_sessions,
)
from agents.chatbot import parse_intent, ActionType, HELP_TEXT
from agents.workflows import (
    select_businesses_workflow, complete_outreach, send_emails_workflow,
    obsidian_sync_workflow, enrich_workflow, scrape_businesses_workflow,
    run_outreach_pipeline, research_workflow, draft_and_pdf_workflow,
)
from agents.chat_memory import get_memory
from agents.brain import get_brain
from agents.brainstorm import BrainstormSession
from agents.live_updates import live


def run_chat_mode(session):
    """Conversational mode -- talk to JARVIS naturally (Gemini-powered)."""
    _ensure_session(session)
    clear()
    banner()

    print(f"\n  {C.BOLD}{C.CYAN}JARVIS Chat Mode{C.RESET}")
    p("  Type naturally. I'll understand and execute.", C.DIM)
    p("  Type 'exit' to return to menu.", C.DIM)
    print()
    typing_print("Online. What would you like to do?", C.CYAN, delay=0.04)
    print()

    memory = get_memory(session_id=session.id if session.active else "")
    profile = get_business_profile()

    while True:
        try:
            user_input = input(f"  {C.WHITE}You: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "back", "menu", "q"):
            p("\n  Returning to main menu...", C.DIM)
            break

        # Save user message to memory
        memory.add_message("user", user_input)

        # Get conversation context for Gemini
        context = memory.get_context(10)
        profile = get_business_profile()

        # Get session state so Gemini knows what's been done
        session_state = session.get_session_state() if session.active else ""

        # Parse intent with Gemini + context + state
        action = parse_intent(user_input, context=context, business_profile=profile,
                             session_state=session_state)

        # Save JARVIS response to memory
        if action.response:
            memory.add_message("jarvis", action.response,
                             action={"type": action.type.value, "params": action.params})

        if action.type == ActionType.HELP:
            print(HELP_TEXT)
            continue

        if action.type == ActionType.GREETING:
            typing_print(f"JARVIS: {action.response}", C.RED, delay=0.03)
            print()
            continue

        if action.type not in (ActionType.UNKNOWN,):
            thinking_msgs = ["Analyzing your request", "Processing", "Thinking", "Working on it"]
            msg = _rand.choice(thinking_msgs)
            spinner(f"{msg}...", 0.5)

        if action.response:
            typing_print(f"JARVIS: {action.response}", C.RED, delay=0.03)
            print()

        try:
            if action.type == ActionType.SEARCH:
                location = action.params.get("location", "")
                if not location:
                    location = prompt("  Where should I search?")
                    if not location:
                        warn("No location provided.")
                        continue

                radius = action.params.get("radius", 2000)
                category = action.params.get("category", "")
                sender = get_sender_name()

                live.__init__()
                live.search_start(location)
                live.search_overpass(location)

                report = run_outreach_pipeline(location, radius, session.id, session.name, sender,
                                              category=category)

                if report.get("errors"):
                    for e in report["errors"]:
                        live.search_error(f"{e['step']}: {e['error']}")
                else:
                    s = report["search"]
                    live.search_results(s["total"], s["no_site"], s["with_site"])
                    if report.get("enrich", {}).get("enriched", 0) > 0:
                        e = report["enrich"]
                        live.enrich_done(e["enriched"], e["total"])

                session.save_data({"location": location, "radius": radius,
                                  "businesses": report.get("businesses", []),
                                  "no_website": report.get("no_site", [])}, "search_results.json")

                no_site = report.get("no_site", [])
                if no_site:
                    p(f"\n  Found {len(no_site)} businesses without websites.", C.GREEN)
                    p("  Say 'draft emails' to continue, or pick specific ones.", C.DIM)
                else:
                    warn("No businesses without websites found.")

            elif action.type == ActionType.DRAFT:
                businesses = None
                data = session.load_data("search_results.json") if session.active else {}
                businesses = data.get("no_website", data.get("businesses", []))

                if not businesses:
                    warn("No businesses to draft for. Search first.")
                    continue

                p(f"  Found {len(businesses)} businesses from last search.", C.CYAN)
                selection = action.params.get("selection", "all")
                if selection == "all":
                    p("  Draft for: 'all', 'top5', or numbers like '1,3,5'", C.DIM)
                    choice = prompt("  >")
                    if not choice:
                        choice = "all"
                    selection = choice

                selected = select_businesses_workflow(businesses, selection)
                if not selected:
                    warn("No businesses selected.")
                    continue

                sender = get_sender_name()
                live.__init__()
                live.draft_start(len(selected), ai=True)

                result = complete_outreach(selected, session.id, session.name, sender)
                drafts = result.get("drafts", [])

                if drafts:
                    for d in drafts:
                        biz = d.get("business", {})
                        live.draft_result(biz.get("name", "?"), d.get("subject", ""), ai=True)
                    live.draft_done(len(drafts), result.get("ai_used", 0))

                    sync = result.get("sync", {})
                    if sync.get("paths"):
                        live.obsidian_done(len(sync["paths"]))

                    p(f"\n  Drafted {len(drafts)} emails.", C.GREEN)
                    p("  Say 'send all' to send, or 'review emails' to edit.", C.DIM)
                else:
                    error("No drafts created.")

            elif action.type == ActionType.RESEARCH:
                data = session.load_data("search_results.json") if session.active else {}
                businesses = data.get("no_website", data.get("businesses", []))

                if not businesses:
                    warn("No businesses to research. Search first.")
                    continue

                live.__init__()
                live.research_start(len(businesses))
                results = research_workflow(businesses)
                session.save_research(results)
                live.research_done(len([r for r in results if not r.get("error")]))

            elif action.type == ActionType.SEND:
                data = session.load_data("email_drafts.json") if session.active else {}
                drafts_to_send = data.get("drafts", [])

                if not drafts_to_send:
                    warn("No drafts to send. Draft emails first.")
                    continue

                has_email = [d for d in drafts_to_send if d.get("to")]
                no_email = [d for d in drafts_to_send if not d.get("to")]

                if no_email:
                    warn(f"{len(no_email)} businesses have no email address (skipped)")
                if not has_email:
                    warn("No businesses with email addresses.")
                    continue

                p(f"  About to send {len(has_email)} emails:", C.YELLOW)
                for d in has_email:
                    p(f"    -> {d.get('to', '?')} ({d.get('business', {}).get('name', '?')})", C.WHITE)
                print()

                if not prompt_yes_no("  Send now?"):
                    info("Cancelled.")
                    continue

                sender = get_sender_name()
                live.__init__()
                live.send_start(len(has_email))

                send_result = send_emails_workflow(has_email, sender)

                for d in send_result.get("sent", []):
                    live.send_result(d.get("business", {}).get("name", "?"), d.get("to", "?"), True)
                for e in send_result.get("errors", []):
                    live.send_result(e.get("name", "?"), "", False)

                live.send_done(
                    len(send_result.get("sent", [])),
                    len(send_result.get("skipped", [])),
                    len(send_result.get("errors", [])))

            elif action.type == ActionType.SYNC:
                data = session.load_data("search_results.json") if session.active else {}
                businesses = data.get("no_website", [])
                if not businesses:
                    businesses = data.get("businesses", [])
                if not businesses:
                    warn("No businesses to sync. Search first.")
                    continue

                live.__init__()
                live.obsidian_start()
                result = obsidian_sync_workflow(businesses, session.id, session.name, businesses)
                live.obsidian_done(len(result.get("paths", [])))
                p(f"  Vault: {result.get('vault', 'N/A')}", C.DIM)

            elif action.type == ActionType.SCRAPE:
                data = session.load_data("search_results.json") if session.active else {}
                businesses = data.get("no_website", [])
                if not businesses:
                    businesses = data.get("businesses", [])
                if not businesses:
                    warn("No businesses to scrape. Search first.")
                    continue

                live.__init__()
                live.scrape_start(len(businesses))
                scraped = scrape_businesses_workflow(businesses)
                for b in scraped:
                    if b.get("social_links"):
                        live.scrape_result(b["name"], b["social_links"])
                live.scrape_done(len(scraped))

            elif action.type == ActionType.ENRICH:
                from agents.config import get_hunter_key
                hunter_key = get_hunter_key()
                if not hunter_key:
                    warn("Hunter.io API key not set. Use Setup [S] to configure.")
                    continue

                data = session.load_data("search_results.json") if session.active else {}
                businesses = data.get("no_website", [])
                if not businesses:
                    businesses = data.get("businesses", [])
                if not businesses:
                    warn("No businesses to enrich. Search first.")
                    continue

                live.__init__()
                live.enrich_start(len(businesses))
                result = enrich_workflow(businesses, hunter_key)
                for r in result["results"]:
                    live.enrich_result(r["name"], r.get("email", ""), r["found"])
                live.enrich_done(result["enriched_count"], len(businesses))

            elif action.type == ActionType.STATUS:
                live.__init__()
                data = session.load_data("search_results.json") if session.active else {}
                no_site = data.get("no_website", [])
                drafts = session.load_data("email_drafts.json").get("drafts", []) if session.active else []
                live.summary({
                    "search": {"total": len(data.get("businesses", [])),
                               "no_site": len(no_site)},
                    "drafts": drafts,
                })

            elif action.type == ActionType.LIST_SESSIONS:
                from agents.session import list_sessions
                sessions = list_sessions()
                if sessions:
                    show_sessions(sessions)
                else:
                    info("No sessions yet.")

            elif action.type == ActionType.BRAINSTORM:
                _run_brainstorm(session)

            elif action.type == ActionType.UNKNOWN:
                warn(action.response)

        except Exception as e:
            error(f"Error: {type(e).__name__}: {e}")

        print()


def _run_brainstorm(session):
    """Run the brainstorm flow interactively."""
    bs = BrainstormSession()

    print()
    typing_print("Let's set up your business profile!", C.CYAN, delay=0.03)
    p("  I'll ask you a few questions to understand your business.", C.DIM)
    p("  This helps me write better emails and find better leads.", C.DIM)
    p("  Type 'skip' to skip any question, 'done' to finish early.", C.DIM)
    print()

    while not bs.complete:
        question = bs.get_current_question()
        if not question:
            break

        progress = bs.get_progress()
        print(f"  {C.DIM}{progress}{C.RESET}")
        print()

        typing_print(f"JARVIS: {question}", C.RED, delay=0.03)
        print()

        try:
            answer = input(f"  {C.WHITE}You: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not answer:
            continue
        if answer.lower() in ("exit", "quit", "back", "menu", "q"):
            break

        response = bs.process_answer(answer)
        if response:
            typing_print(f"JARVIS: {response}", C.RED, delay=0.03)
            print()

    if not bs.complete:
        p(f"\n  Brainstorm paused. Say 'brainstorm' to continue.", C.DIM)


def _ensure_session(session):
    if not session.active:
        session.create(prompt("Project name: "))
        success(f"Session started: {session.id}")
