"""Chat handler -- conversational mode for JARVIS (Gemini-powered)."""
import random as _rand

from agents.config import get_sender_name, get_business_profile
from agents.ui import (
    C, p, success, error, info, warn, clear, banner,
    typing_print, spinner, prompt, prompt_yes_no, show_sessions,
)
from agents.chatbot import parse_intent, ActionType, HELP_TEXT
from agents.action_dispatch import dispatch
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

    # Always-active agents: proactive briefing at chat start
    from agents.proactive import auto_brief
    briefing = auto_brief()
    if briefing:
        print()
        typing_print(briefing, C.YELLOW, delay=0.02)
    print()

    memory = get_memory(session_id=session.id if session.active else "")

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
        session_state = session.get_session_state() if session.active else ""

        # Parse intent
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

        if action.type == ActionType.BRAINSTORM:
            _run_brainstorm(session)
            continue

        if action.type == ActionType.LIST_SESSIONS:
            from agents.session import list_sessions
            sessions = list_sessions()
            if sessions:
                show_sessions(sessions)
            else:
                info("No sessions yet.")
            continue

        if action.type == ActionType.REVIEW:
            _run_cli_review(session)
            continue

        if action.type == ActionType.CHECKIN:
            from agents.proactive import check_in, format_briefing
            briefing = format_briefing(check_in())
            typing_print(f"JARVIS: {briefing}", C.CYAN, delay=0.02)
            memory.add_message("jarvis", briefing)
            print()
            continue

        if action.type == ActionType.UNKNOWN:
            warn(action.response)
            continue

        # Show thinking indicator
        thinking_msgs = ["Analyzing your request", "Processing", "Thinking", "Working on it"]
        spinner(f"{_rand.choice(thinking_msgs)}...", 0.5)

        if action.response:
            typing_print(f"JARVIS: {action.response}", C.RED, delay=0.03)
            print()

        # Execute via action_dispatch
        try:
            result = dispatch(action.type, action.params, session)

            if result.get("message"):
                if result["success"]:
                    success(result["message"])
                else:
                    warn(result["message"])

            # Special handling for search (needs live updates + user interaction)
            if action.type == ActionType.SEARCH and result["success"]:
                data = result.get("data", {})
                businesses = data.get("businesses", [])
                if businesses:
                    p(f"\n  Found {len(businesses)} businesses without websites.", C.GREEN)
                    p("  Say 'draft emails' to continue, or pick specific ones.", C.DIM)

            # Special handling for draft (needs user interaction)
            elif action.type == ActionType.DRAFT and result["success"]:
                p("  Say 'send all' to send, or 'review emails' to edit.", C.DIM)

            # Special handling for send (confirmation)
            elif action.type == ActionType.SEND:
                pass  # result message already shown

        except Exception as e:
            error(f"Error: {type(e).__name__}: {e}")

        print()


def _run_cli_review(session):
    """Interactive email review for chat mode. Approved drafts are flagged and
    saved back to the session; sending is a separate 'send' step."""
    from agents.email_review import review_and_edit_workflow
    from agents.workflows import trim_draft_for_storage

    data = session.load_data("email_drafts.json") if session.active else {}
    drafts = data.get("drafts", [])
    if not drafts:
        warn("No drafts to review. Draft emails first.")
        return

    print()
    result = review_and_edit_workflow(drafts)
    approved = len(result.get("approved", []))
    skipped = result.get("skipped_count", 0)

    session.save_data({"drafts": [trim_draft_for_storage(d) for d in drafts]},
                      "email_drafts.json")
    print()
    if approved:
        success(f"{approved} email(s) approved, {skipped} skipped. "
                f"Say 'send' to send the approved ones.")
    else:
        info("No emails approved. Nothing will be sent.")


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
