#!/usr/bin/env python3
"""Industry templates - baseline knowledge for common business types.

The AI uses these as a starting point when it encounters a business type.
As it interacts with real businesses, it builds on this foundation.
Templates are stored in Obsidian as industry notes for cross-referencing.
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
        "description": "Schools, colleges, training institutes, coaching centers",
        "pain_points": [
            "Need online presence for admissions and parent communication",
            "Parents want to check results, schedules, and updates online",
            "Competing with schools that have modern websites",
            "Limited budget for IT infrastructure",
            "No online enrollment or fee payment system",
        ],
        "what_they_need": [
            "Website with admission forms and photo gallery",
            "Parent portal for results and announcements",
            "Online fee payment integration",
            "Google My Business listing for local search",
        ],
        "outreach_approach": "Lead with parent communication pain point. Schools care about reputation and parent satisfaction.",
        "email_hooks": [
            "Parents want to check results online - give them a portal",
            "Your Google listing is the first thing new parents see",
            "Competing schools have websites - here's what you're missing",
        ],
        "decision_maker": "Principal, Director, or IT Admin",
        "typical_budget": "Low to medium - depends on school size",
        "tags": ["school", "college", "training", "coaching", "education", "university"],
    },
    "food_and_drink": {
        "display_name": "Food & Drink",
        "description": "Restaurants, cafes, canteens, bakeries, food stalls",
        "pain_points": [
            "Losing orders to Zomato/Swiggy commission fees",
            "No direct online ordering from their own website",
            "Customers can't see menu or prices before visiting",
            "No way to build a loyal customer base directly",
            "Google reviews go unanswered - reputation suffers",
        ],
        "what_they_need": [
            "Website with menu, photos, and online ordering",
            "Google My Business optimization",
            "Social media presence and review management",
            "WhatsApp ordering integration",
        ],
        "outreach_approach": "Lead with commission savings. 'Zomato takes 25-30% per order - what if customers ordered directly from you?'",
        "email_hooks": [
            "Zomato takes 25-30% per order - keep that revenue",
            "Customers search 'restaurants near me' - are you showing up?",
            "Your menu deserves more than a photo on WhatsApp",
        ],
        "decision_maker": "Owner or Manager",
        "typical_budget": "Low to medium",
        "tags": ["restaurant", "cafe", "canteen", "bakery", "food", "dining"],
    },
    "healthcare": {
        "display_name": "Healthcare",
        "description": "Clinics, hospitals, pharmacies, nursing homes, diagnostic centers",
        "pain_points": [
            "Patients can't find you when they search online",
            "No online appointment booking - phone lines jammed",
            "Competitors with websites get more patient trust",
            "Google reviews are unmanaged - one bad review hurts",
            "Patients want to check doctor availability and fees",
        ],
        "what_they_need": [
            "Website with doctor profiles and appointment booking",
            "Google My Business with working phone and hours",
            "Online reputation management",
            "Patient testimonial showcase",
        ],
        "outreach_approach": "Lead with patient acquisition. 'When someone searches [clinic type] near me, do you show up?'",
        "email_hooks": [
            "Patients search online before choosing a doctor - are you visible?",
            "Your Google reviews shape first impressions - manage them",
            "Online appointment booking reduces no-shows by 30%",
        ],
        "decision_maker": "Doctor/Owner or Admin Manager",
        "typical_budget": "Medium - healthcare values professionalism",
        "tags": ["clinic", "hospital", "pharmacy", "nursing", "diagnostic", "medical"],
    },
    "shop": {
        "display_name": "Retail & Shops",
        "description": "Pharmacies, grocery stores, electronics shops, clothing stores",
        "pain_points": [
            "Losing customers to Amazon and Flipkart",
            "No online presence - only foot traffic",
            "Customers check prices online then buy elsewhere",
            "No way to showcase new arrivals or offers",
            "No customer loyalty system",
        ],
        "what_they_need": [
            "Website with product catalog and pricing",
            "Google My Business with stock availability",
            "WhatsApp catalog for quick browsing",
            "Local SEO to beat online competitors",
        ],
        "outreach_approach": "Lead with local advantage. 'Amazon can't match your same-day availability and personal service - but they can match your online visibility.'",
        "email_hooks": [
            "Amazon can't match your service - but they can match your visibility",
            "Customers check prices on their phone while standing in your shop",
            "Your new arrivals deserve more than a poster on the door",
        ],
        "decision_maker": "Owner",
        "typical_budget": "Low to medium",
        "tags": ["shop", "store", "pharmacy", "retail", "grocery", "electronics"],
    },
    "professional": {
        "display_name": "Professional Services",
        "description": "CA firms, law offices, consulting, coaching, tutoring",
        "pain_points": [
            "No website means no credibility for new clients",
            "Referrals dry up without online presence",
            "Competitors with websites appear more established",
            "No way to showcase expertise and past work",
            "Clients want to see fees and services before calling",
        ],
        "what_they_need": [
            "Professional website with service descriptions",
            "Client testimonials and case studies",
            "Contact forms and consultation booking",
            "LinkedIn and Google presence optimization",
        ],
        "outreach_approach": "Lead with credibility. 'Your first impression is your website - or lack of one.'",
        "email_hooks": [
            "Your first impression is your website - or lack of one",
            "Clients Google you before hiring - what do they find?",
            "Professional services need a professional online presence",
        ],
        "decision_maker": "Partner or Principal",
        "typical_budget": "Medium to high - values quality",
        "tags": ["CA", "lawyer", "consultant", "tutor", "coach", "advisor"],
    },
    "home_services": {
        "display_name": "Home Services",
        "description": "Plumbers, electricians, painters, carpenters, AC repair",
        "pain_points": [
            "Only found through word of mouth - limited reach",
            "No way for new customers to find them online",
            "Competitors with Google listings get all the calls",
            "No portfolio of past work to show potential clients",
            "Can't compete with urban company / housejoy",
        ],
        "what_they_need": [
            "Google My Business with photos of past work",
            "Simple website with services and pricing",
            "WhatsApp business for quick quotes",
            "Local SEO for 'near me' searches",
        ],
        "outreach_approach": "Lead with lead generation. 'When someone's pipe bursts at 2am, they Google 'plumber near me' - are you there?'",
        "email_hooks": [
            "When a pipe bursts at 2am, they Google 'plumber near me'",
            "Your past work speaks for itself - but only if people can see it",
            "Urban Company takes 25% commission - get direct leads instead",
        ],
        "decision_maker": "Owner",
        "typical_budget": "Low - but high value from new leads",
        "tags": ["plumber", "electrician", "painter", "carpenter", "repair", "AC"],
    },
    "automotive": {
        "display_name": "Automotive",
        "description": "Car dealerships, mechanics, spare parts, driving schools",
        "pain_points": [
            "No online presence for local car buyers",
            "Service customers don't know about maintenance packages",
            "Competitors with websites dominate Google search",
            "No way to showcase inventory online",
            "Driving schools lose students to apps",
        ],
        "what_they_need": [
            "Website with inventory/service catalog",
            "Google My Business with service booking",
            "Customer review management",
            "WhatsApp for service reminders",
        ],
        "outreach_approach": "Lead with inventory visibility. 'Your car inventory deserves more than a photo on the showroom floor.'",
        "email_hooks": [
            "Car buyers check online before visiting the showroom",
            "Service reminders via WhatsApp reduce missed appointments",
            "Your showroom deserves a showroom on the web",
        ],
        "decision_maker": "Owner or Service Manager",
        "typical_budget": "Medium",
        "tags": ["car", "mechanic", "dealer", "automotive", "driving school"],
    },
    "logistics": {
        "display_name": "Logistics & Transport",
        "description": "Couriers, movers, trucking, warehousing, delivery services",
        "pain_points": [
            "No online tracking or booking system",
            "Competitors with tech platforms win enterprise clients",
            "Manual quote process is slow and error-prone",
            "No visibility into delivery status for customers",
            "Hard to differentiate from local competitors",
        ],
        "what_they_need": [
            "Website with quote request and tracking",
            "Google My Business for local discovery",
            "Automated booking and confirmation system",
            "Customer portal for shipment tracking",
        ],
        "outreach_approach": "Lead with operational efficiency. 'Manual quotes take 30 minutes - an online form takes 30 seconds.'",
        "email_hooks": [
            "Manual quotes take 30 minutes - an online form takes 30 seconds",
            "Enterprise clients check your website before signing contracts",
            "Real-time tracking reduces 'where is my order?' calls by 80%",
        ],
        "decision_maker": "Operations Manager or Owner",
        "typical_budget": "Medium to high",
        "tags": ["courier", "mover", "transport", "logistics", "delivery", "warehouse"],
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
