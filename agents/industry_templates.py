#!/usr/bin/env python3
"""Industry templates - baseline knowledge for the verticals we sell to.

These are the verticals that survive the ICP (agents/icp.py): institutions
with a classroom or computer lab. Anything without one is ruled out before
an email is ever drafted, so it has no template here.

Content is written for what we actually sell - official CAD/drafting software
licences for labs - rather than a generic software pitch. As the AI interacts
with real institutions it builds on this foundation through agents/learn.py.

Templates are also mirrored into Obsidian as industry notes for cross-referencing.
"""

import json
from pathlib import Path
from typing import Optional

from agents.config import KB_DIR, OBSIDIAN_VAULT

TEMPLATES_FILE = KB_DIR / "industry_templates.json"


# ── Built-in templates ─────────────────────────────────────────────

TEMPLATES = {
    "education": {
        "display_name": "Education",
        "description": "Schools, colleges and institutes running computer or drafting labs",
        "pain_points": [
            "Labs run on unlicensed or trial software that expires mid-session",
            "Students install cracked copies and bring licensing risk onto campus",
            "Per-seat licence cost blocks the lab from adding machines",
            "No owner for licence renewal - labs break at the worst time",
        ],
        "what_they_need": [
            "Genuine licensed seats sized to the lab",
            "Education pricing for the whole institution",
            "Installation, activation and renewal support",
            "Licence documentation that stands up to an audit",
        ],
        "outreach_approach": (
            "Talk to the principal or lab in-charge. Ask how the computer lab is "
            "licensed today, then quote the whole lab at education pricing - "
            "compliance and per-seat cost, never a single copy."
        ),
        "email_hooks": [
            "Quick question about how {business_name}'s computer lab is licensed",
            "Licensed seats for the whole lab at education pricing",
            "Labs lose days when trial software expires mid-session",
        ],
        "decision_maker": "Principal, Director, Lab in-charge",
        "typical_budget": "Institutional, approved per lab",
        "tags": ["education", "school", "institute", "academy", "college", "training"],
    },
    "college": {
        "display_name": "College",
        "description": "Degree colleges with science, applied-science and drawing labs",
        "pain_points": [
            "Each department needs licensed seats, each with its own budget",
            "Drawing and computer labs share machines across streams",
            "Renewals lapse because nobody owns the licence register",
        ],
        "what_they_need": [
            "Department-wise quotation for procurement",
            "Volume licensing across multiple labs",
            "Licence certificates for compliance records",
        ],
        "outreach_approach": (
            "Reach the head of the computer or drawing lab. Lead with a "
            "department-wise quotation and the cost of licensing the entire lab "
            "in one go."
        ),
        "email_hooks": [
            "Department-wise licensed seats for {business_name}'s labs",
            "One quotation to license every lab machine",
            "Compliance paperwork included with every licence",
        ],
        "decision_maker": "Principal, Head of Department, Lab in-charge",
        "typical_budget": "Institutional, per department",
        "tags": ["college", "campus", "degree", "mahavidyalaya", "university"],
    },
    "training": {
        "display_name": "Training centre",
        "description": "Computer training centres running job-oriented courses",
        "pain_points": [
            "Adding a CAD or drafting course needs licensed software before students enrol",
            "Every new batch needs another activated seat",
            "Course fees cannot absorb full retail licence pricing",
            "Machines get formatted between batches and lose activation",
        ],
        "what_they_need": [
            "Affordable per-seat licences that scale batch by batch",
            "Fast re-activation when a machine is rebuilt",
            "A CAD-ready lab so a new course can start earning quickly",
        ],
        "outreach_approach": (
            "Talk to the centre owner or course coordinator. Lead with cost per "
            "student seat and how fast a new CAD batch can start."
        ),
        "email_hooks": [
            "How fast could {business_name} start a CAD batch?",
            "Per-seat licensing that scales with every new batch",
            "Genuine licences, batch-friendly activation",
        ],
        "decision_maker": "Centre owner, Director, Course coordinator",
        "typical_budget": "Owner-approved, per batch",
        "tags": ["training", "computer", "institute", "course", "coaching", "skill"],
    },
    "polytechnic": {
        "display_name": "Polytechnic",
        "description": "Polytechnics and diploma institutes teaching engineering trades",
        "pain_points": [
            "Drafting labs run AutoCAD across several semesters",
            "Each trade (civil, mechanical, electrical) needs its own seats",
            "Lab upgrades stall on per-seat licence cost",
        ],
        "what_they_need": [
            "Trade-wise licensed seats for drafting labs",
            "Volume pricing for all semesters at once",
            "Support for lab installs and machine replacement",
        ],
        "outreach_approach": (
            "Approach the head of the drafting or computer department. Lead with "
            "trade-wise seats and a full-lab quotation."
        ),
        "email_hooks": [
            "Licensed drafting seats across all {business_name} trades",
            "One quote for every semester's lab",
            "Lab installation handled for you",
        ],
        "decision_maker": "Principal, Head of Department, Lab in-charge",
        "typical_budget": "Institutional, per trade",
        "tags": ["polytechnic", "polytecnic", "diploma", "engineering", "iti", "vocational"],
    },
    "school": {
        "display_name": "School",
        "description": "Schools with senior-secondary vocational or computer streams",
        "pain_points": [
            "Vocational streams need software the school can prove is licensed",
            "Shared lab machines are reimaged every session",
            "Tight per-student budget across the whole lab",
        ],
        "what_they_need": [
            "Budget-friendly licensed seats for shared machines",
            "Simple re-activation after lab reimaging",
            "Documentation that satisfies school audits",
        ],
        "outreach_approach": (
            "Reach the computer-lab in-charge or principal. Lead with audit-safe "
            "licensing at a per-lab price."
        ),
        "email_hooks": [
            "Audit-safe licensed seats for {business_name}'s computer lab",
            "Per-lab pricing for the whole classroom",
            "Re-activation after reimaging, handled",
        ],
        "decision_maker": "Principal, Computer lab in-charge",
        "typical_budget": "Institutional, per lab",
        "tags": ["school", "vidyalaya", "high school", "secondary", "convent"],
    },
}

# ── Functions ──────────────────────────────────────────────────────

def get_template(category: str) -> Optional[dict]:
    """Get a built-in template for a business category."""
    # Normalize: lowercase, replace spaces/slashes with underscore
    key = category.lower().strip().replace(" ", "_").replace("/", "_").replace("-", "_")
    return TEMPLATES.get(key)


def get_template_context(category: str) -> str:
    """Get a context string from the template for AI prompt injection."""
    tmpl = get_template(category)
    if not tmpl:
        return ""

    lines = [f"Industry: {tmpl['display_name']}"]
    lines.append(f"About: {tmpl['description']}")

    if tmpl["pain_points"]:
        lines.append("Common pain points:")
        for pp in tmpl["pain_points"][:3]:
            lines.append(f"  - {pp}")

    if tmpl["outreach_approach"]:
        lines.append(f"Best approach: {tmpl['outreach_approach']}")

    if tmpl["email_hooks"]:
        lines.append("Email hooks that work:")
        for hook in tmpl["email_hooks"][:2]:
            lines.append(f'  - "{hook}"')

    if tmpl["decision_maker"]:
        lines.append(f"Decision maker: {tmpl['decision_maker']}")

    return "\n".join(lines)


def get_all_templates() -> dict:
    """Return all built-in templates."""
    return TEMPLATES.copy()


def match_category_to_template(category: str) -> Optional[str]:
    """Try to match a category string to a known template key."""
    key = category.lower().strip().replace(" ", "_").replace("/", "_").replace("-", "_")

    # Direct match
    if key in TEMPLATES:
        return key

    # Partial match (e.g., "education_center" matches "education")
    for tmpl_key in TEMPLATES:
        if tmpl_key in key or key in tmpl_key:
            return tmpl_key

    # Tag match
    for tmpl_key, tmpl in TEMPLATES.items():
        if any(tag in key for tag in tmpl.get("tags", [])):
            return tmpl_key

    return None


# ── Obsidian sync ──────────────────────────────────────────────────

def sync_templates_to_obsidian():
    """Create industry notes in Obsidian vault from templates."""
    industries_dir = OBSIDIAN_VAULT / "industries"
    industries_dir.mkdir(parents=True, exist_ok=True)

    for key, tmpl in TEMPLATES.items():
        note_path = industries_dir / f"industry_{key}.md"

        # Build wikilinks for related contacts
        contacts_dir = OBSIDIAN_VAULT / "contacts"
        related_contacts = []
        if contacts_dir.exists():
            for f in contacts_dir.glob("*.md"):
                content = f.read_text(encoding="utf-8").lower()
                if any(tag in content for tag in tmpl.get("tags", [])):
                    name = f.stem.replace("_", " ").title()
                    related_contacts.append(f"[[{f.stem}|{name}]]")

        lines = [
            "---",
            f"industry: {key}",
            f"display_name: {tmpl['display_name']}",
            f"description: {tmpl['description']}",
            "tags:",
            "  - industry",
            f"  - {key}",
            "---",
            "",
            f"# {tmpl['display_name']}",
            "",
            f"**Description:** {tmpl['description']}",
            "",
            "## Pain Points",
            "",
        ]
        for pp in tmpl["pain_points"]:
            lines.append(f"- {pp}")

        lines.extend(["", "## What They Need", ""])
        for need in tmpl["what_they_need"]:
            lines.append(f"- {need}")

        lines.extend([
            "", "## Outreach Strategy", "",
            f"**Approach:** {tmpl['outreach_approach']}", "",
            "**Email Hooks:**",
        ])
        for hook in tmpl["email_hooks"]:
            lines.append(f'1. "{hook}"')

        lines.extend([
            "", f"**Decision Maker:** {tmpl['decision_maker']}", "",
            f"**Typical Budget:** {tmpl['typical_budget']}", "",
        ])

        if related_contacts:
            lines.append("## Related Contacts")
            lines.append("")
            for c in related_contacts[:10]:
                lines.append(f"- {c}")
            lines.append("")

        note_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"  Synced {len(TEMPLATES)} industry templates to Obsidian")


# ── Load from file (for user-added templates) ─────────────────────

def load_custom_templates() -> dict:
    """Load any user-added templates from the knowledge base."""
    if not TEMPLATES_FILE.exists():
        return {}
    try:
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_custom_template(category: str, template: dict):
    """Save a custom template (e.g., from a new industry the AI researched)."""
    custom = load_custom_templates()
    custom[category] = template
    TEMPLATES_FILE.write_text(
        json.dumps(custom, indent=2, ensure_ascii=True), encoding="utf-8"
    )


def get_all_with_custom() -> dict:
    """Get all templates (built-in + custom)."""
    all_tmpls = TEMPLATES.copy()
    all_tmpls.update(load_custom_templates())
    return all_tmpls
