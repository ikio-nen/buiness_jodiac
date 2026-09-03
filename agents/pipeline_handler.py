"""Pipeline handler — quick outreach and full pipeline flows."""
from agents.config import get_sender_name, get_hunter_key
from agents.ui import (
    C, p, success, error, info, warn, clear, pause, banner,
    step_header, status_badge, spinner, prompt, prompt_yes_no,
    show_select_list, show_drafts, show_draft_summary, gmail_troubleshoot,
)
from agents.workflows import (
    search_businesses_workflow, enrich_workflow, select_businesses_workflow,
    draft_and_pdf_workflow, send_emails_workflow, review_and_send_workflow,
    research_workflow, obsidian_sync_workflow, complete_outreach,
)


def run_quick_outreach(session):
    """One-shot outreach: search -> research -> draft -> review -> send."""
    from agents.session import Session
    _ensure = lambda: None  # session passed in
    session_ref = session

    _ensure_session(session_ref)
    clear()
    banner()

    step_header(1, 5, "Search Businesses")
    location = prompt("Location (city/address): ")
    radius_str = prompt("Radius in meters [2000]: ")
    radius = int(radius_str) if radius_str.isdigit() else 2000
    sender = get_sender_name()

    # 1. Search + Verify + Scrape + Enrich
    status_badge("active", f"Searching '{location}'...")
    spinner("Searching + verifying + scraping businesses", 1.5)

    from agents.workflows import run_outreach_pipeline
    report = run_outreach_pipeline(location, radius, session_ref.id, session_ref.name, sender)

    if report.get("errors"):
        for e in report["errors"]:
            status_badge("error", f"{e['step']}: {e['error']}")
        return True

    search = report["search"]
    status_badge("complete", f"Found {search['total']} businesses, {search['no_site']} without website")

    enrich = report.get("enrich", {})
    if enrich.get("enriched", 0) > 0:
        status_badge("complete", f"Found emails for {enrich['enriched']}/{enrich['total']} businesses via Hunter.io")

    # 2. User selects businesses
    step_header(2, 5, "Select Businesses")
    no_site = report.get("no_site", [])
    if not no_site:
        warn("No businesses without websites found. Try a different area.")
        return True
    show_select_list(no_site)
    sel = prompt("Select businesses (numbers/all/top5): ")
    selected = select_businesses_workflow(no_site, sel)
    if not selected:
        warn("No businesses selected.")
        return True
    success(f"Selected {len(selected)} businesses")

    session_ref.save_data({"location": location, "radius": radius,
                          "businesses": report.get("businesses", []),
                          "no_website": no_site, "selected": selected}, "search_results.json")

    # 3. Research + Draft
    step_header(3, 5, "Researching + Drafting Emails")
    spinner(f"Researching {len(selected)} businesses", 1.0)
    research_data = research_workflow(selected)
    session_ref.save_research(research_data)
    researched = [r for r in research_data if not r.get("error")]
    if researched:
        status_badge("complete", f"Researched {len(researched)} businesses")

    spinner(f"Generating {len(selected)} emails + PDFs", 1.0)
    result = complete_outreach(selected, session_ref.id, session_ref.name, sender)

    drafts = result.get("drafts", [])
    errors = result.get("errors", [])
    ai_used = result.get("ai_used", 0)

    if drafts:
        success(f"Generated {len(drafts)} emails + PDFs" + (f" ({ai_used} AI-powered)" if ai_used else ""))
    if errors:
        error(f"{len(errors)} errors:")
        for e in errors[:3]:
            p(f"    {e.get('name', '?')}: {e.get('error', '')[:50]}", C.RED)

    sync = result.get("sync", {})
    if sync.get("paths"):
        status_badge("syncing", f"Synced {len(sync['paths'])} notes to Obsidian")

    # 4. Review + Send
    step_header(4, 5, "Review & Send Emails")
    if not drafts:
        warn("No drafts to send.")
        return True

    send_result = review_and_send_workflow(drafts, sender)

    if send_result.get("sent"):
        success(f"Sent {len(send_result['sent'])} emails")
    if send_result.get("attached", 0) > 0:
        status_badge("complete", f"{send_result['attached']} file(s) attached")
    if send_result.get("errors"):
        for e in send_result["errors"][:3]:
            error(f"{e.get('name', '?')}: {e.get('error', '')[:50]}")
        gmail_troubleshoot()

    success("Pipeline complete!")
    return True


def run_full_pipeline(session):
    """Full pipeline — step by step with manual control."""
    _ensure_session(session)
    info("Full Pipeline - running all steps")
    location = prompt("Search location: ")
    radius_str = prompt("Radius in meters [2000]: ")
    radius = int(radius_str) if radius_str.isdigit() else 2000

    result = search_businesses_workflow(location, radius)
    if "error" in result:
        error(result["error"])
        return
    success(f"Found {len(result['no_site'])} businesses without website")
    pause()

    hunter_key = get_hunter_key()
    if hunter_key:
        enrich_result = enrich_workflow(result["no_site"], hunter_key)
        info(f"Enriched {enrich_result['enriched_count']}/{len(result['no_site'])}")
    pause()

    show_select_list(result["no_site"])
    sel = prompt("Select businesses: ")
    selected = select_businesses_workflow(result["no_site"], sel)
    if not selected:
        warn("No businesses selected.")
        return
    pause()

    sender = get_sender_name()
    draft_result = draft_and_pdf_workflow(selected, sender)
    success(f"Drafted {len(draft_result['drafts'])} emails + PDFs")
    pause()

    obsidian_sync_workflow(result["businesses"], session.id, session.name, selected)
    pause()

    show_drafts(draft_result["drafts"])
    action = prompt("Choose (A/S/C): ").strip().upper()
    if action == "A":
        send_result = send_emails_workflow(draft_result["drafts"], sender)
        success(f"Sent {len(send_result['sent'])} emails")

    obsidian_sync_workflow(result["businesses"], session.id, session.name, selected)
    success("Pipeline complete!")


def _ensure_session(session):
    """Ensure a session is active."""
    if not session.active:
        from agents.ui import prompt as p
        session.create(p("Project name: "))
        success(f"Session started: {session.id}")
