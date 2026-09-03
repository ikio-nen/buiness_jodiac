"""Email review workflow — presents each drafted email for review.

Between drafting and sending, the user reviews each email:
- See subject and body
- Edit subject (single line)
- Edit body (multi-line, blank line to submit)
- Attach a file specific to this business
- Approve or skip

Returns only approved drafts with their attachments.
"""
import sys
from pathlib import Path
from typing import Optional

from agents.ui import (
    C, p, success, error, info, warn,
    section_header, divider, prompt,
)


# ── Core review workflow ───────────────────────────────────────────

def review_and_edit_workflow(drafts: list[dict]) -> dict:
    """Interactive review of all drafts. Returns approved drafts + attachments.

    Returns:
        {
            "approved": [list of approved draft dicts],
            "skipped_count": int,
            "attached_count": int,
        }
    """
    if not drafts:
        return {"approved": [], "skipped_count": 0, "attached_count": 0}

    approved = []
    skipped = 0
    attached = 0

    print()
    section_header("Email Review")
    p(f"  {C.DIM}Review each email before sending. You can edit, attach files, or skip.{C.RESET}")
    p(f"  {C.DIM}Press Enter on empty input to keep current text.{C.RESET}")

    for i, draft in enumerate(drafts):
        biz = draft.get("business", {})
        biz_name = biz.get("name", "Unknown")
        biz_category = biz.get("category", "")

        print()
        divider("-", 50)
        print(f"  {C.RED}{C.BOLD}Email {i + 1}/{len(drafts)}{C.RESET} {C.DIM}- {C.WHITE}{biz_name}{C.RESET} {C.DIM}({biz_category}){C.RESET}")
        divider("-", 50)

        # Show current email
        _show_email(draft)

        # Show current attachment if any
        current_attachment = draft.get("attachment", "")
        if current_attachment:
            p(f"  {C.GREEN}Attachment:{C.RESET} {current_attachment}")

        # Get user action
        while True:
            print()
            p(f"  {C.RED}[A]{C.RESET}pprove  {C.RED}[E]{C.RESET}dit  {C.RED}[S]{C.RESET}kip  {C.RED}[AT]{C.RESET}tach file  {C.RED}[P]{C.RESET}review")
            action = prompt("  > ").strip().upper()

            if action == "A":
                draft["approved"] = True
                approved.append(draft)
                success(f"Approved: {biz_name}")
                break

            elif action == "S":
                draft["approved"] = False
                skipped += 1
                info(f"Skipped: {biz_name}")
                break

            elif action == "E":
                _edit_email(draft)

            elif action == "AT":
                path = prompt("  Attachment path: ").strip()
                if path:
                    if Path(path).exists():
                        draft["attachment"] = path
                        attached += 1
                        success(f"Attached: {Path(path).name}")
                    else:
                        error(f"File not found: {path}")
                else:
                    info("No file specified.")

            elif action == "P":
                _show_email(draft)

            else:
                warn(f"Unknown action '{action}'. Use A, E, S, AT, or P.")

    # Show summary
    _show_summary(len(drafts), len(approved), skipped, attached)

    return {
        "approved": approved,
        "skipped_count": skipped,
        "attached_count": attached,
    }


# ── Display helpers ────────────────────────────────────────────────

def _show_email(draft: dict):
    """Display the current email content."""
    to = draft.get("to", "not set")
    subject = draft.get("subject", "(no subject)")
    body = draft.get("body", "(no body)")

    p(f"  {C.DIM}To:{C.RESET} {C.WHITE}{to}{C.RESET}")
    p(f"  {C.DIM}Subject:{C.RESET} {C.WHITE}{C.BOLD}{subject}{C.RESET}")
    print()
    p(f"  {C.DIM}Body:{C.RESET}")
    for line in body.split("\n"):
        p(f"    {C.WHITE}{line}{C.RESET}")


# ── Edit functions ─────────────────────────────────────────────────

def _edit_email(draft: dict):
    """Edit email subject and/or body."""
    print()
    p(f"  {C.DIM}Edit mode: Enter keeps current text. Blank line submits body.{C.RESET}")

    # Edit subject
    current_subject = draft.get("subject", "")
    new_subject = prompt(f"  Subject [{current_subject[:50]}]: ").strip()
    if new_subject:
        draft["subject"] = new_subject
        success("Subject updated.")

    # Edit body (multi-line)
    print()
    p(f"  {C.DIM}Body (type new body, blank line to finish):{C.RESET}")
    p(f"  {C.DIM}Current body:{C.RESET}")
    for line in draft.get("body", "").split("\n"):
        p(f"    {C.DIM}{line}{C.RESET}")
    print()

    new_lines = []
    while True:
        try:
            line = input(f"  {C.RED}>{C.RESET} ")
        except EOFError:
            break
        if line.strip() == "" and new_lines:
            # Empty line after content = submit
            break
        new_lines.append(line)

    if new_lines:
        draft["body"] = "\n".join(new_lines)
        success("Body updated.")
    else:
        info("Body unchanged.")


# ── Summary ────────────────────────────────────────────────────────

def _show_summary(total: int, approved: int, skipped: int, attached: int):
    """Show the review summary."""
    print()
    divider("=", 50)
    print(f"  {C.BOLD}Review Summary{C.RESET}")
    divider("=", 50)

    p(f"  {C.GREEN}Approved:{C.RESET} {approved}/{total}")
    if skipped:
        p(f"  {C.YELLOW}Skipped:{C.RESET} {skipped}/{total}")
    if attached:
        p(f"  {C.CYAN}Attached:{C.RESET} {attached} file(s)")

    if approved == 0:
        warn("No emails approved. Nothing will be sent.")
    elif approved == total:
        success(f"All {total} emails approved!")
    else:
        info(f"{approved} of {total} emails ready to send.")
    print()


# ── Attachment handling ────────────────────────────────────────────

def get_approved_with_attachments(approved_drafts: list[dict]) -> list[dict]:
    """Prepare approved drafts for sending, including attachment paths.

    Returns list of dicts ready for mailer.send_email():
    {to, subject, body, pdf_path, attachment_path, business}
    """
    send_list = []
    for draft in approved_drafts:
        send_list.append({
            "to": draft.get("to", ""),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "pdf_path": draft.get("pdf_path", ""),
            "attachment_path": draft.get("attachment", ""),
            "business": draft.get("business", {}),
        })
    return send_list


def has_attachments(approved_drafts: list[dict]) -> bool:
    """Check if any approved drafts have file attachments."""
    return any(d.get("attachment") for d in approved_drafts)
