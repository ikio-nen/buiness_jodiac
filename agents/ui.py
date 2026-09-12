"""UI concerns: colors, banner, print helpers, menu display, input prompts.

Black/Red/White theme with animated transitions and cyberpunk terminal aesthetic.
"""
import os
import sys
import time


# ── Color Theme: Black / Red / White ─────────────────────────────────

class C:
    """ANSI color codes — Black/Red/White theme."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    ITALIC  = "\033[3m"
    UNDERL  = "\033[4m"
    BLINK   = "\033[5m"
    INVERT  = "\033[7m"

    # Core palette
    WHITE   = "\033[97m"
    RED     = "\033[91m"
    DARK    = "\033[90m"
    BRIGHT  = "\033[97m"

    # Semantic
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    BLUE    = "\033[94m"

    # Theme shortcuts
    PRIMARY   = "\033[91m"
    SECONDARY = "\033[97m"
    ACCENT    = "\033[91m"
    MUTED     = "\033[90m"
    SURFACE   = "\033[0m"
    ON        = "\033[97m"


# ── Core print helpers ──────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def pause():
    print()
    sys.stdout.write(f"  {C.DIM}{C.DARK}>> Press Enter to continue...{C.RESET}")
    sys.stdout.flush()
    input()

def p(text, color=C.WHITE):
    print(f"  {color}{text}{C.RESET}")

def success(text):
    print(f"  {C.GREEN}{C.BOLD}[+]{C.RESET} {C.WHITE}{text}{C.RESET}")

def error(text):
    print(f"  {C.RED}{C.BOLD}[x]{C.RESET} {C.RED}{text}{C.RESET}")

def info(text):
    print(f"  {C.DIM}{C.DARK}[i]{C.RESET} {C.WHITE}{text}{C.RESET}")

def warn(text):
    print(f"  {C.YELLOW}{C.BOLD}[!]{C.RESET} {C.YELLOW}{text}{C.RESET}")


# ── Animated display functions ───────────────────────────────────────

def typing_print(text: str, color=C.WHITE, delay: float = 0.02):
    """Print text with a typing effect."""
    sys.stdout.write(f"  {color}")
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write(f"{C.RESET}\n")
    sys.stdout.flush()


def spinner(message: str, duration: float = 1.5):
    """Animated loading spinner with red accent."""
    frames = [" [ \\", " [ |", " [ /", " [ -"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        frame = frames[i % 4]
        sys.stdout.write(f"\r  {C.RED}{frame}]{C.RESET} {C.DIM}{message}{C.RESET}  ")
        sys.stdout.flush()
        time.sleep(0.1)
        i += 1
    sys.stdout.write(f"\r  {C.GREEN}{C.BOLD}[>]{C.RESET} {C.WHITE}{message}{C.RESET}  " + " " * 10 + "\n")
    sys.stdout.flush()


def progress_bar(current: int, total: int, width: int = 30, label: str = ""):
    """Animated progress bar with red fill."""
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = f"{'#' * filled}{'-' * (width - filled)}"
    sys.stdout.write(f"\r  {C.RED}[{bar}]{C.RESET} {pct*100:.0f}% {C.DIM}{label}{C.RESET}")
    sys.stdout.flush()
    if current >= total:
        print()


def step_header(current: int, total: int, label: str):
    """Display a step indicator with red accent."""
    print()
    step_text = f"  {C.RED}{C.BOLD}>>{C.RESET} {C.WHITE}{C.BOLD}STEP {current}/{total}{C.RESET} {C.DIM}{C.DARK}---{C.RESET} {C.WHITE}{label}{C.RESET}"
    print(step_text)
    print(f"  {C.DIM}{C.DARK}{'~' * 50}{C.RESET}")


def status_badge(status: str, text: str):
    """Display a colored status badge."""
    badges = {
        "active":   (C.RED,     "[>>]"),
        "complete": (C.GREEN,   "[OK]"),
        "error":    (C.RED,     "[x!]"),
        "syncing":  (C.YELLOW,  "[~~]"),
        "ready":    (C.GREEN,   "[OK]"),
        "loading":  (C.DIM,     "[..]"),
        "sent":     (C.GREEN,   "[>>]"),
    }
    color, label = badges.get(status.lower(), (C.WHITE, f"[?]"))
    p(f"{color}{C.BOLD}{label}{C.RESET} {C.WHITE}{text}{C.RESET}")


def divider(char: str = "=", width: int = 50):
    """Print a styled divider line."""
    print(f"  {C.DIM}{C.DARK}{char * width}{C.RESET}")


def section_header(text: str):
    """Print a section header with red accent."""
    print()
    print(f"  {C.RED}{C.BOLD}## {text.upper()} {C.RESET}")
    print(f"  {C.DIM}{C.DARK}{'-' * (len(text) + 5)}{C.RESET}")


# ── Banner and boot sequence ─────────────────────────────────────────

def _make_banner_lines():
    """Build banner art without backslash issues."""
    return [
        "",
        "          ___   ___  ____  __  __  ___  ____  ____ ",
        "         / _ | / _ \\(  _ \\(  \\/  )/ __)(  _ \\(  _ \\",
        "        ( (_|( (_) ))   / )    ( \\__ \\ )   / )   / ",
        "         \\___|\\___/(_)\\_)(__/\\/\\_)(____/(_)\\_)(__)  ",
        "",
    ]

BANNER_ART = None  # Lazy init to avoid backslash escaping issues

def _get_banner():
    global BANNER_ART
    if BANNER_ART is None:
        BANNER_ART = _make_banner_lines()
    return BANNER_ART


def boot_sequence():
    """Dramatic animated JARVIS boot sequence."""
    clear()

    # Phase 1: System initialization text
    print()
    for line in [
        f"  {C.DIM}{C.DARK}[SYS] Initializing...{C.RESET}",
        f"  {C.DIM}{C.DARK}[SYS] Loading agent subsystems...{C.RESET}",
    ]:
        print(line)
        time.sleep(0.1)

    print()

    # Phase 2: ASCII art banner (letter by letter reveal)
    sys.stdout.write(C.RED + C.BOLD)
    for line in _get_banner():
        for ch in line:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.005)
        sys.stdout.write("\n")
        sys.stdout.flush()
    sys.stdout.write(C.RESET)
    sys.stdout.flush()

    print()
    time.sleep(0.1)

    # Phase 3: Subtitle with typing effect
    subtitle = "  AI Agent Business Outreach System"
    typing_print(subtitle, C.DIM, delay=0.02)

    # Phase 4: Loading agents with animated spinner
    print()
    agents = [
        ("Lightweight Agent", 0.3),
        ("Medium Agent", 0.3),
        ("Heavy Agent", 0.3),
        ("AI Design Agent", 0.4),
        ("AI Code Agent", 0.3),
        ("Learning Engine", 0.3),
        ("Overpass API", 0.2),
    ]
    for name, delay in agents:
        spinner(f"Loading {name}", delay)

    print()

    # Phase 5: Status info
    from agents.config import OUTPUT_DIR, OBSIDIAN_VAULT
    p(f"  {C.DIM}{C.DARK}Output:{C.RESET}  {C.WHITE}{OUTPUT_DIR}{C.RESET}")
    p(f"  {C.DIM}{C.DARK}Vault:{C.RESET}   {C.WHITE}{OBSIDIAN_VAULT}{C.RESET}")

    print()

    # Phase 6: Greeting with dramatic typing
    typing_print("At your service, sir.", C.RED, delay=0.06)
    print()


def banner():
    """Static banner for re-renders (after clear)."""
    from agents.config import OUTPUT_DIR, OBSIDIAN_VAULT
    print()
    sys.stdout.write(C.RED + C.BOLD)
    for line in _get_banner():
        print(f"  {line}")
    sys.stdout.write(C.RESET)
    print(f"\n  {C.DIM}{C.DARK}AI Agent Business Outreach System{C.RESET}")
    print(f"  {C.DIM}{C.DARK}Output: {OUTPUT_DIR}  |  Vault: {OBSIDIAN_VAULT}{C.RESET}")
    print()


# ── Menu display ─────────────────────────────────────────────────────

def show_session(session_id: str | None, project_name: str | None):
    sid = session_id or "N/A"
    name = project_name or "None"
    print(f"  {C.DIM}{C.DARK}Session:{C.RESET} {C.WHITE}{name}{C.RESET} {C.DIM}{C.DARK}({sid}){C.RESET}")


def show_wizard_step(step: int, total: int, question: str, hint: str = ""):
    """Display a wizard step with question and optional hint."""
    print()
    print(f"  {C.RED}{C.BOLD}New Project Setup{C.RESET}")
    print(f"  {C.DIM}{C.DARK}{'~' * 40}{C.RESET}")
    print()
    print(f"  {C.DIM}{C.DARK}Step {step}/{total}:{C.RESET} {C.WHITE}{C.BOLD}{question}{C.RESET}")
    if hint:
        print(f"  {C.DIM}{C.DARK}{hint}{C.RESET}")


def show_wizard_summary(profile: dict):
    """Display the wizard summary after completion."""
    print()
    print(f"  {C.GREEN}{C.BOLD}[OK]{C.RESET} {C.WHITE}Profile saved!{C.RESET}")
    print()
    fields = [
        ("Project", profile.get("project_name", "")),
        ("Product", profile.get("product", "")),
        ("Target", profile.get("target_customers", "")),
        ("Tone", profile.get("email_tone", "professional")),
    ]
    for label, value in fields:
        if value:
            print(f"  {C.DIM}{C.DARK}{label}:{C.RESET} {C.WHITE}{value}{C.RESET}")
    print()


def show_research_result(research: dict, index: int, total: int):
    """Display research results for one business."""
    name = research.get("name", "?")
    rating = research.get("rating", 0)
    review_count = research.get("review_count", 0)

    print()
    print(f"  {C.RED}{C.BOLD}[RESEARCH]{C.RESET} {C.WHITE}{name}{C.RESET} ({index}/{total})")

    if rating:
        print(f"    {C.DIM}Rating:{C.RESET} {C.WHITE}{rating}/5 ({review_count} reviews){C.RESET}")

    if research.get("strengths"):
        print(f"    {C.GREEN}Strengths:{C.RESET} {', '.join(research['strengths'][:2])}")

    if research.get("gaps"):
        print(f"    {C.YELLOW}Gaps:{C.RESET} {', '.join(research['gaps'][:2])}")

    if research.get("email_hook"):
        print(f"    {C.DIM}Email hook:{C.RESET} {C.WHITE}{research['email_hook'][:80]}{C.RESET}")


def show_research_summary(research_data: list[dict]):
    """Display summary of all research results."""
    researched = [r for r in research_data if not r.get("error")]
    failed = [r for r in research_data if r.get("error")]
    print()
    if researched:
        status_badge("complete", f"Researched {len(researched)} businesses")
    if failed:
        status_badge("error", f"Failed to research {len(failed)} businesses")


def show_main_menu(has_session: bool = False):
    session_hint = "" if has_session else f"  {C.DIM}{C.DARK}>> Start with [1] New Project or [S] Setup{C.RESET}\n"

    print()
    print(f"  {C.RED}{C.BOLD}=== MAIN MENU ==={C.RESET}")
    print(f"{session_hint}")

    # Project section
    print(f"  {C.RED}{C.BOLD}PROJECT{C.RESET}")
    print(f"    {C.WHITE}[1]{C.RESET}  New Project / Session")
    print(f"    {C.WHITE}[2]{C.RESET}  Resume Session")
    print(f"    {C.WHITE}[V]{C.RESET}  View Previous Session")
    print(f"    {C.WHITE}[D]{C.RESET}  Delete Old Session")
    print()

    # Workflow section
    print(f"  {C.RED}{C.BOLD}WORKFLOW{C.RESET}")
    print(f"    {C.RED}[C]{C.RESET}  Chat with JARVIS {C.DIM}{C.DARK}(natural language){C.RESET}")
    print(f"    {C.RED}[R]{C.RESET}  Quick Outreach {C.DIM}{C.DARK}(one-shot pipeline){C.RESET}")
    print(f"    {C.WHITE}[3]{C.RESET}  Full Pipeline {C.DIM}{C.DARK}(automated){C.RESET}")
    print(f"    {C.WHITE}[4]{C.RESET}  Step 1: Search Businesses")
    print(f"    {C.WHITE}[5]{C.RESET}  Step 2: Find Emails (Hunter.io)")
    print(f"    {C.WHITE}[6]{C.RESET}  Step 3: Select Businesses")
    print(f"    {C.WHITE}[7]{C.RESET}  Step 4: Draft Emails + PDFs")
    print(f"    {C.WHITE}[8]{C.RESET}  Step 5: Review & Send")
    print(f"    {C.WHITE}[9]{C.RESET}  Sync to Obsidian")
    print()

    # Tools section
    print(f"  {C.RED}{C.BOLD}TOOLS{C.RESET}")
    print(f"    {C.WHITE}[S]{C.RESET}  Setup {C.DIM}{C.DARK}(Gmail, API keys){C.RESET}")
    print(f"    {C.WHITE}[A]{C.RESET}  Agent Stats")
    print(f"    {C.WHITE}[L]{C.RESET}  Learning Dashboard")
    print(f"    {C.RED}[W]{C.RESET}  Web UI {C.DIM}{C.DARK}(open browser chat){C.RESET}")
    print(f"    {C.RED}[Q]{C.RESET}  Quit")
    print()


# ── Data display functions ───────────────────────────────────────────

def show_search_results(no_site: list[dict], with_site: list[dict]):
    if not no_site and not with_site:
        warn("No businesses found in this area.")
        p(f"  {C.DIM}Try a larger radius, a different city, or a busier area.{C.RESET}")
        return

    print()
    section_header("Search Results")

    if no_site:
        p(f"  {C.RED}{C.BOLD}{len(no_site)} businesses WITHOUT a website{C.RESET}")
    if with_site:
        p(f"  {C.DIM}{C.DARK}{len(with_site)} businesses already have a website (skipped){C.RESET}")

    if not no_site:
        info("All businesses in this area already have websites.")
        return

    print()
    print(f"  {C.DIM}{C.DARK}{'#':<4} {'Name':<30} {'Category':<15} {'Phone':<15} {'Email'}{C.RESET}")
    print(f"  {C.DIM}{C.DARK}{'---':<4} {'---':<30} {'---':<15} {'---':<15} {'-----'}{C.RESET}")

    for i, b in enumerate(no_site, 1):
        email_addr = b.get("email") or b.get("enrichment", {}).get("email", "")
        email_color = C.GREEN if email_addr else C.RED
        print(f"  {C.RED}{C.BOLD}{i:<4}{C.RESET} {C.WHITE}{b['name'][:29]:<30}{C.RESET} {C.DIM}{b.get('category', '')[:14]:<15}{C.RESET} {C.DIM}{b.get('phone', '')[:14]:<15}{C.RESET} {email_color}{has_email}{C.RESET}")


def show_select_list(businesses: list[dict]):
    print()
    p(f"  {C.DIM}Enter numbers separated by commas (e.g. 1,3,5){C.RESET}")
    p(f"  {C.DIM}Or type 'all' to select all, or 'top5' for top 5{C.RESET}")
    print()
    for i, b in enumerate(businesses, 1):
        email = b.get("email") or b.get("enrichment", {}).get("email", "")
        has_email = f"{C.GREEN}email{C.RESET}" if email else f"{C.RED}no email{C.RESET}"
        print(f"  {C.RED}{C.BOLD}{i:>3}.{C.RESET} {C.WHITE}{b['name']:<30}{C.RESET} {C.DIM}{b.get('category', ''):<15}{C.RESET} {C.DIM}[{has_email}]{C.RESET}")


def show_drafts(drafts: list[dict]):
    from pathlib import Path
    section_header("Email Drafts")

    for i, draft in enumerate(drafts, 1):
        biz = draft.get("business", {})
        ai_tag = f" {C.RED}[AI]{C.RESET}" if draft.get("ai_powered") else ""
        print(f"\n  {C.RED}{C.BOLD}--- Draft {i}/{len(drafts)}{C.RESET} {C.WHITE}{biz.get('name', '?')}{C.RESET}{ai_tag}")
        print(f"  {C.DIM}To:{C.RESET}      {C.WHITE}{draft.get('to', 'N/A')}{C.RESET}")
        print(f"  {C.DIM}Subject:{C.RESET} {C.WHITE}{draft.get('subject', 'N/A')}{C.RESET}")
        print(f"  {C.DIM}PDF:{C.RESET}     {C.DIM}{Path(draft.get('pdf_path', '')).name if draft.get('pdf_path') else 'None'}{C.RESET}")
        print(f"\n  {C.DIM}{C.DARK}{draft.get('body', '')}{C.RESET}")

    print()
    print(f"  {C.RED}{C.BOLD}OPTIONS{C.RESET}")
    print(f"    {C.RED}[A]{C.RESET} Send ALL emails now")
    print(f"    {C.WHITE}[S]{C.RESET} Send SELECTED {C.DIM}{C.DARK}(enter numbers){C.RESET}")
    print(f"    {C.YELLOW}[R]{C.RESET} RE-DRAFT selected {C.DIM}{C.DARK}(go back to step 4){C.RESET}")
    print(f"    {C.DIM}[D]{C.RESET} SAVE drafts, don't send yet")
    print(f"    {C.DIM}[C]{C.RESET} Cancel")


def show_send_preview(send_these: list[dict]):
    print()
    p(f"  {C.RED}{C.BOLD}About to send {len(send_these)} emails:{C.RESET}")
    for d in send_these:
        print(f"    {C.RED}{C.BOLD}->{C.RESET} {C.WHITE}{d.get('to', 'N/A')}{C.RESET} {C.DIM}({d.get('business', {}).get('name', '?')}){C.RESET}")


def show_stats(stats: dict):
    section_header("Agent Statistics")
    print()
    for a in stats["agents"]:
        tasks = a["tasks_completed"]
        bar_len = min(tasks, 20)
        bar = f"{'#' * bar_len}{'.' * (20 - bar_len)}"
        print(f"  {C.RED}{C.BOLD}{a['agent_id']:12s}{C.RESET} {C.DIM}{C.DARK}|{C.RESET} {C.DIM}{a['max_complexity']:6s}{C.RESET} {C.DIM}{C.DARK}|{C.RESET} {C.WHITE}{tasks:3d} tasks{C.RESET} {C.DIM}[{bar}]{C.RESET}")


def show_sessions(sessions: list[dict]):
    section_header("Existing Sessions")
    if not sessions:
        warn("No sessions found.")
        p(f"  {C.DIM}Start a new project with [1] to create your first session.{C.RESET}")
        return
    print()
    for i, s in enumerate(sessions, 1):
        biz_count = len(s.get("businesses", []))
        date = s.get("started", "unknown")[:10]
        print(f"  {C.RED}{C.BOLD}[{i}]{C.RESET} {C.WHITE}{s.get('name', 'Unnamed')}{C.RESET} {C.DIM}{C.DARK}({s['id']}){C.RESET} {C.DIM}{C.DARK}-{C.RESET} {C.WHITE}{biz_count} businesses{C.RESET} {C.DIM}{C.DARK}{date}{C.RESET}")


def prompt(text: str) -> str:
    return input(f"  {C.RED}{C.BOLD}>{C.RESET} {C.WHITE}{text}{C.RESET} ").strip()


def prompt_yes_no(text: str) -> bool:
    """Prompt for yes/no confirmation."""
    answer = input(f"  {C.RED}{C.BOLD}{text}{C.RESET} {C.DIM}{C.DARK}(yes/no):{C.RESET} ").strip().lower()
    return answer in ("yes", "y")


def prompt_choice(text: str, valid: list[str]) -> str:
    """Prompt until user enters a valid choice."""
    while True:
        choice = input(f"  {C.RED}{C.BOLD}>{C.RESET} {C.WHITE}{text}{C.RESET} ").strip().upper()
        if choice in valid:
            return choice
        warn(f"Invalid choice. Options: {', '.join(valid)}")


def show_send_summary(result: dict):
    """Show a summary after sending emails."""
    sent = len(result.get("sent", []))
    skipped = len(result.get("skipped", []))
    errors = len(result.get("errors", []))
    total = sent + skipped + errors
    print()
    section_header("Send Results")
    if sent:
        success(f"Sent: {C.BOLD}{sent}/{total}{C.RESET} emails")
    if skipped:
        warn(f"Skipped: {skipped} (no email address)")
    if errors:
        error(f"Failed: {errors}")
        for e in result.get("errors", []):
            print(f"    {C.RED}{C.DARK}{e.get('name', '?')}: {e.get('error', 'Unknown')}{C.RESET}")
    if not sent and not errors:
        info("No emails were sent.")


def show_draft_summary(result: dict):
    """Show a summary after drafting."""
    drafts = len(result.get("drafts", []))
    errors = len(result.get("errors", []))
    print()
    section_header("Draft Results")
    if drafts:
        success(f"Drafted: {C.BOLD}{drafts}{C.RESET} emails + PDFs")
    if errors:
        error(f"Failed: {errors}")
        for e in result.get("errors", []):
            print(f"    {C.RED}{C.DARK}{e.get('name', '?')}: {e.get('error', 'Unknown')}{C.RESET}")
    if not drafts and not errors:
        warn("No drafts were created.")


def gmail_troubleshoot():
    """Show Gmail troubleshooting tips."""
    print()
    section_header("Gmail SMTP Troubleshooting")
    p(f"  {C.WHITE}1.{C.RESET} Make sure 2-Step Verification is ON in your Google account", C.DIM)
    p(f"  {C.WHITE}2.{C.RESET} Go to myaccount.google.com/apppasswords", C.DIM)
    p(f"  {C.WHITE}3.{C.RESET} Generate an App Password for 'Mail' > 'Other'", C.DIM)
    p(f"  {C.WHITE}4.{C.RESET} Use the 16-character password (spaces don't matter)", C.DIM)
    p(f"  {C.WHITE}5.{C.RESET} Make sure your Gmail address is correct in Setup [S]", C.DIM)


def farewell():
    """Goodbye message."""
    print()
    typing_print("Shutting down systems...", C.DIM, delay=0.03)
    time.sleep(0.2)
    typing_print("Goodbye, sir.", C.RED, delay=0.05)
    print()
