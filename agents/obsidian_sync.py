"""Sync data to Obsidian vault with proper [[wikilinks]] and backlinks.

Creates 7 types of notes, all cross-linked:
  projects/    — session overviews with links to contacts + outreach
  contacts/    — individual business cards with links to project + industry
  reports/     — outreach tracking forms with links to contacts
  industries/  — industry overview notes (auto-created per category)
  research/    — market research notes (scraped data, trends)
  competitors/ — competitor analysis notes
  followups/   — follow-up tracking notes
  insights/    — AI-generated insights and recommendations
"""
from datetime import datetime
from pathlib import Path
from .config import (
    OBSIDIAN_VAULT, OBSIDIAN_PROJECTS, OBSIDIAN_CONTACTS, OBSIDIAN_REPORTS,
    OBSIDIAN_INDUSTRIES, OBSIDIAN_RESEARCH, OBSIDIAN_COMPETITORS,
    OBSIDIAN_FOLLOWUPS, OBSIDIAN_INSIGHTS,
)
from agents.contact_export import _phone_source


def _src_note(business: dict) -> str:
    """Small italic source note for the contact-info phone line."""
    src = _phone_source(business)
    return f" _({src})_" if src else ""


def _email_source(business: dict, enrichment: dict = None) -> str:
    """Email provenance: hunter > osm > maps (matches _resolved_email priority)."""
    if (enrichment or {}).get("email"):
        return "hunter"
    if business.get("email"):
        return "osm"
    if business.get("maps_email"):
        return "maps"
    return ""



def _slug(name: str) -> str:
    return name.replace(" ", "_").replace("'", "").replace("&", "and").lower()

def _phone_display(business: dict) -> str:
    """Phone to show in notes — prefer the OSM phone, fall back to maps phone."""
    p = business.get("phone") or business.get("maps_phone", "")
    return p[:20]


def _resolved_email(business: dict, enrichment: dict = None) -> str:
    """Best available email for the business: explicit > enrichment > maps."""
    return (
        business.get("email", "")
        or (enrichment or {}).get("email", "")
        or business.get("maps_email", "")
    )


def _resolved_phone(business: dict) -> str:
    """Best available phone: OSM explicit > maps-discovered."""
    return business.get("phone", "") or business.get("maps_phone", "")


def _contact_filename(name: str) -> str:
    return f"{_slug(name)}.md"

def _project_filename(session_id: str, project_name: str) -> str:
    return f"{session_id}_{_slug(project_name)}.md"

def _outreach_filename(session_id: str) -> str:
    return f"outreach_{session_id}.md"

def _industry_filename(category: str) -> str:
    return f"industry_{_slug(category)}.md"

def _research_filename(session_id: str) -> str:
    return f"research_{session_id}.md"

def _competitor_filename(business_name: str) -> str:
    return f"competitor_{_slug(business_name)}.md"

def _followup_filename(business_name: str, session_id: str) -> str:
    return f"followup_{_slug(business_name)}_{session_id}.md"

def _insight_filename(session_id: str) -> str:
    return f"insights_{session_id}.md"


# ── PROJECT NOTE ─────────────────────────────────────────────────────
def create_project_note(session_id: str, project_name: str,
                        businesses: list[dict]) -> str:
    """Create a project note with [[wikilinks]] to each contact."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(businesses)
    no_site = sum(1 for b in businesses if not b.get("website"))

    lines = [
        "---",
        f"session_id: {session_id}",
        f"date: {date}",
        f"total_businesses: {total}",
        f"no_website: {no_site}",
        f"status: active",
        f"type: project",
        f"tags:",
        f"  - project",
        f"---\n",
        f"# {project_name}\n",
        f"**Created:** {date}",
        f"**Session:** `{session_id}`",
        f"**Outreach form:** [[{_outreach_filename(session_id)}]]",
        f"**Research:** [[{_research_filename(session_id)}]]",
        f"**Insights:** [[{_insight_filename(session_id)}]]\n",
        f"## Businesses Found ({total} total, {no_site} without website)\n",
        "| # | Name | Category | Website | Phone | Address |",
        "|---|------|----------|---------|-------|---------|",
    ]

    for i, b in enumerate(businesses, 1):
        has_site = "Yes" if b.get("website") else "**NO**"
        phone = _phone_display(b)
        addr = b.get("address", "")[:25]
        contact_link = f"[[{_contact_filename(b['name'])}|{b['name']}]]"
        phone_src = _phone_source(b)
        phone_cell = (f"{phone} ({phone_src})" if phone_src and phone else phone)
        lines.append(f"| {i} | {contact_link} | {b.get('category', '')} | {has_site} | {phone_cell} | {addr} |")

    # Group by category for industry links
    categories = set(b.get("category", "other") for b in businesses)
    lines.append(f"\n## Industries Represented\n")
    for cat in sorted(categories):
        lines.append(f"- [[{_industry_filename(cat)}|{cat.replace('_', ' ').title()}]]")

    path = OBSIDIAN_PROJECTS / _project_filename(session_id, project_name)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── CONTACT NOTE ─────────────────────────────────────────────────────
def create_contact_note(business: dict, enrichment: dict = None,
                        session_id: str = "", project_name: str = "") -> str:
    """Create a contact note with backlinks to project, industry, and outreach."""
    name = business.get("name", "Unknown")
    category = business.get("category", "uncategorized")
    email = _resolved_email(business, enrichment)
    phone = _resolved_phone(business)

    lines = [
        "---",
        f"business: {name}",
        f"email: {email}",
        f"phone: {phone}",
        f"email_source: {_email_source(business, enrichment)}",
        f"phone_source: {_phone_source(business)}",
        f"website: {business.get('website', '')}",
        f"address: {business.get('address', '')}",
        f"category: {category}",
        f"approached: false",
        f"tags:",
        f"  - contact",
        f"  - {category}",
        f"---\n",
        f"# {name}\n",
    ]

    # Backlinks
    if session_id and project_name:
        lines.append(f"**Project:** [[{_project_filename(session_id, project_name)}|{project_name}]]")
        lines.append(f"**Outreach:** [[{_outreach_filename(session_id)}]]")
        lines.append(f"**Industry:** [[{_industry_filename(category)}|{category.replace('_', ' ').title()}]]")
        lines.append(f"**Follow-up:** [[{_followup_filename(name, session_id)}]]\n")

    phone = business.get("phone") or business.get("maps_phone", "")
    email = (
        business.get("email", "") or business.get("maps_email", "")
        or (business.get("enrichment") or {}).get("email", "")
    )
    lines.append(f"## Contact Info\n")
    lines.append(f"- **Phone:** {phone or 'N/A'}{_src_note(business)}")
    lines.append(f"- **Email:** {email or 'Not found'}")
    lines.append(f"- **Website:** {business.get('website', 'None - needs one!')}")
    lines.append(f"- **Address:** {business.get('address', 'N/A')}")
    lines.append(f"- **Hours:** {business.get('opening_hours', 'N/A')}")

    # Scraped data
    if business.get("scraped_successfully"):
        lines.append(f"\n## Scraped Data\n")
        lines.append(f"- **Rating:** {business.get('rating', 'N/A')} ({business.get('review_count', 0)} reviews)")
        if business.get("description"):
            lines.append(f"- **Description:** {business['description'][:300]}")
        social = business.get("social_links", {})
        if social:
            lines.append(f"- **Social:** {', '.join(f'[{k}]({v})' for k, v in social.items())}")
        if business.get("emails_found"):
            lines.append(f"- **Emails found:** {', '.join(business['emails_found'])}")

    # Hunter data
    if enrichment:
        lines.append(f"\n## Hunter.io Data\n")
        lines.append(f"- Confidence: {enrichment.get('confidence', 0)}%")
        lines.append(f"- Position: {enrichment.get('position', 'N/A')}")

    path = OBSIDIAN_CONTACTS / _contact_filename(name)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── OUTREACH FORM ────────────────────────────────────────────────────
def create_outreach_form(session_id: str, businesses: list[dict],
                         project_name: str = "") -> str:
    """Create outreach tracking form with [[wikilinks]] to contacts."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "---",
        f"session_id: {session_id}",
        f"date: {date}",
        f"type: outreach_form",
        f"tags:",
        f"  - outreach",
        f"  - form",
        f"---\n",
        f"# Outreach Form - {session_id}\n",
        f"**Date:** {date}",
    ]

    if project_name:
        lines.append(f"**Project:** [[{_project_filename(session_id, project_name)}|{project_name}]]\n")

    lines.append("## Businesses Approached\n")
    lines.append("| # | Name | Email Sent | PDF Sent | Response | Follow-up | Notes |")
    lines.append("|---|------|------------|----------|----------|-----------|-------|")

    for i, b in enumerate(businesses, 1):
        contact_link = f"[[{_contact_filename(b['name'])}|{b['name']}]]"
        followup_link = f"[[{_followup_filename(b['name'], session_id)}]]"
        lines.append(f"| {i} | {contact_link} | [ ] | [ ] | [ ] | {followup_link} | |")

    lines.append(f"\n## Summary\n")
    lines.append(f"- **Total approached:** {len(businesses)}")
    lines.append(f"- **Emails sent:** /{len(businesses)}")
    lines.append(f"- **PDFs sent:** /{len(businesses)}")
    lines.append(f"- **Responses:** /{len(businesses)}")

    path = OBSIDIAN_REPORTS / _outreach_filename(session_id)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── INDUSTRY NOTE ────────────────────────────────────────────────────
def create_industry_note(category: str, businesses: list[dict]) -> str:
    """Create an industry overview note with [[wikilinks]] to all businesses in that category."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    cat_name = category.replace("_", " ").title()

    lines = [
        "---",
        f"category: {category}",
        f"date: {date}",
        f"type: industry",
        f"business_count: {len(businesses)}",
        f"tags:",
        f"  - industry",
        f"  - {category}",
        f"---\n",
        f"# {cat_name} Industry\n",
        f"**Businesses tracked:** {len(businesses)}",
        f"**Last updated:** {date}\n",
        f"## Businesses\n",
    ]

    for b in businesses:
        lines.append(f"- [[{_contact_filename(b['name'])}|{b['name']}]] - {b.get('address', 'N/A')}")

    # Stats
    with_site = sum(1 for b in businesses if b.get("website"))
    without_site = len(businesses) - with_site
    lines.append(f"\n## Stats\n")
    lines.append(f"- With website: {with_site}")
    lines.append(f"- Without website: {without_site}")
    lines.append(f"- Outreach priority: {without_site} need websites\n")

    path = OBSIDIAN_INDUSTRIES / _industry_filename(category)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── RESEARCH NOTE ────────────────────────────────────────────────────
def create_research_note(session_id: str, project_name: str,
                         businesses: list[dict], scraped_data: list[dict] = None) -> str:
    """Create a market research note with [[wikilinks]] to businesses."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "---",
        f"session_id: {session_id}",
        f"date: {date}",
        f"type: research",
        f"tags:",
        f"  - research",
        f"---\n",
        f"# Research - {project_name}\n",
        f"**Project:** [[{_project_filename(session_id, project_name)}|{project_name}]]",
        f"**Date:** {date}\n",
        f"## Market Overview\n",
    ]

    # Category breakdown
    by_cat: dict[str, list] = {}
    for b in businesses:
        cat = b.get("category", "other")
        by_cat.setdefault(cat, []).append(b)

    lines.append("| Category | Businesses | With Site | Without Site |")
    lines.append("|----------|-----------|-----------|--------------|")
    for cat, biz_list in sorted(by_cat.items()):
        with_site = sum(1 for b in biz_list if b.get("website"))
        lines.append(f"| [[{_industry_filename(cat)}|{cat.replace('_', ' ').title()}]] | {len(biz_list)} | {with_site} | {len(biz_list) - with_site} |")

    # Scraped insights
    if scraped_data:
        lines.append(f"\n## Scraped Insights\n")
        ratings = [b.get("rating", 0) for b in scraped_data if b.get("rating")]
        if ratings:
            avg = sum(ratings) / len(ratings)
            lines.append(f"- **Average rating:** {avg:.1f} ({len(ratings)} rated)")

        social_counts = {}
        for b in scraped_data:
            for platform in b.get("social_links", {}):
                social_counts[platform] = social_counts.get(platform, 0) + 1
        if social_counts:
            lines.append(f"- **Social media presence:** {', '.join(f'{k}: {v}' for k, v in sorted(social_counts.items(), key=lambda x: -x[1]))}")

    # Key businesses
    lines.append(f"\n## Key Businesses\n")
    for b in businesses[:10]:
        lines.append(f"- [[{_contact_filename(b['name'])}|{b['name']}]] — {b.get('category', '')} — {b.get('address', '')[:40]}")

    path = OBSIDIAN_RESEARCH / _research_filename(session_id)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── COMPETITOR NOTE ──────────────────────────────────────────────────
def create_competitor_note(business: dict, session_id: str = "") -> str:
    """Create a competitor analysis note."""
    name = business.get("name", "Unknown")
    category = business.get("category", "other")

    lines = [
        "---",
        f"business: {name}",
        f"category: {category}",
        f"type: competitor_analysis",
        f"tags:",
        f"  - competitor",
        f"  - {category}",
        f"---\n",
        f"# Competitor: {name}\n",
    ]

    if session_id:
        lines.append(f"**Related project:** [[{_project_filename(session_id, name)}]]\n")

    lines.append(f"## Profile\n")
    lines.append(f"- **Category:** [[{_industry_filename(category)}|{category.replace('_', ' ').title()}]]")
    lines.append(f"- **Website:** {business.get('website', 'None')}")
    lines.append(f"- **Rating:** {business.get('rating', 'N/A')}")
    lines.append(f"- **Reviews:** {business.get('review_count', 0)}")
    lines.append(f"- **Address:** {business.get('address', 'N/A')}")

    if business.get("description"):
        lines.append(f"\n## Description\n")
        lines.append(f"{business['description']}")

    if business.get("social_links"):
        lines.append(f"\n## Social Presence\n")
        for platform, url in business["social_links"].items():
            lines.append(f"- [{platform.title()}]({url})")

    lines.append(f"\n## Our Advantage\n")
    lines.append(f"- [ ] They have no website — we can offer a better online presence")
    lines.append(f"- [ ] They have a website — we can offer a redesign/modernization")
    lines.append(f"- [ ] Their social media is weak — we can highlight digital marketing")

    path = OBSIDIAN_COMPETITORS / _competitor_filename(name)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── FOLLOW-UP NOTE ───────────────────────────────────────────────────
def create_followup_note(business: dict, session_id: str) -> str:
    """Create a follow-up tracking note."""
    name = business.get("name", "Unknown")
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "---",
        f"business: {name}",
        f"session_id: {session_id}",
        f"date: {date}",
        f"type: followup",
        f"status: pending",
        f"tags:",
        f"  - followup",
        f"---\n",
        f"# Follow-up: {name}\n",
        f"**Contact:** [[{_contact_filename(name)}|{name}]]",
        f"**Outreach:** [[{_outreach_filename(session_id)}]]",
        f"**Created:** {date}\n",
        f"## Timeline\n",
        f"| Date | Action | Outcome | Next Step |",
        f"|------|--------|---------|-----------|",
        f"| {date} | Initial email sent | Pending | Wait 3 days |",
        f"\n## Notes\n",
        f"- [ ] Email sent",
        f"- [ ] Follow-up call scheduled",
        f"- [ ] Proposal sent",
        f"- [ ] Meeting booked",
        f"- [ ] Deal closed",
    ]

    path = OBSIDIAN_FOLLOWUPS / _followup_filename(name, session_id)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── INSIGHT NOTE ─────────────────────────────────────────────────────
def create_insight_note(session_id: str, project_name: str,
                        businesses: list[dict], insights: dict = None) -> str:
    """Create an AI-generated insights note."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "---",
        f"session_id: {session_id}",
        f"date: {date}",
        f"type: insight",
        f"tags:",
        f"  - insight",
        f"  - ai_generated",
        f"---\n",
        f"# Insights - {project_name}\n",
        f"**Project:** [[{_project_filename(session_id, project_name)}|{project_name}]]",
        f"**Date:** {date}\n",
    ]

    if insights:
        lines.append(f"## AI Recommendations\n")
        for key, value in insights.items():
            lines.append(f"- **{key}:** {value}")
    else:
        lines.append(f"## Summary\n")
        lines.append(f"- Total businesses: {len(businesses)}")
        without_site = [b for b in businesses if not b.get("website")]
        lines.append(f"- Need websites: {len(without_site)}")
        if without_site:
            lines.append(f"- Top outreach targets:")
            for b in without_site[:5]:
                lines.append(f"  - [[{_contact_filename(b['name'])}|{b['name']}]]")

    path = OBSIDIAN_INSIGHTS / _insight_filename(session_id)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── BUSINESS RESEARCH NOTE ──────────────────────────────────────────
def create_business_research_note(business: dict, research: dict,
                                   session_id: str = "") -> str:
    """Create a detailed research note for a single business.

    Includes Google Maps data, strengths, gaps, email hooks, and industry context.
    All fields are cross-linked to contacts, industries, and projects.
    """
    name = business.get("name", "Unknown")
    category = business.get("category", "other")
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    rating = research.get("rating", 0)
    review_count = research.get("review_count", 0)
    strengths = research.get("strengths", [])
    gaps = research.get("gaps", [])
    email_hook = research.get("email_hook", "")
    improvement = research.get("improvement_suggestion", "")
    industry_ctx = research.get("industry_context", "")

    lines = [
        "---",
        f"business: {name}",
        f"category: {category}",
        f"rating: {rating}",
        f"review_count: {review_count}",
        f"date: {date}",
        f"type: business_research",
        f"tags:",
        f"  - research",
        f"  - {category}",
        f"---\n",
        f"# Research: {name}\n",
        f"**Contact:** [[{_contact_filename(name)}|{name}]]",
        f"**Industry:** [[{_industry_filename(category)}|{category.replace('_', ' ').title()}]]",
    ]
    if session_id:
        lines.append(f"**Session:** `{session_id}`")
    lines.append("")

    # Rating section
    lines.append(f"## Google Maps Data\n")
    if rating:
        stars = "*" * int(rating) + "-" * (5 - int(rating))
        lines.append(f"**Rating:** {rating}/5 [{stars}] ({review_count} reviews)")
    else:
        lines.append(f"**Rating:** Not found")
    lines.append("")

    # Strengths
    if strengths:
        lines.append(f"## Strengths\n")
        for s in strengths:
            lines.append(f"- {s}")
        lines.append("")

    # Gaps / Improvement opportunities
    if gaps:
        lines.append(f"## Gaps / Opportunities\n")
        for g in gaps:
            lines.append(f"- {g}")
        lines.append("")

    # Email hook
    if email_hook:
        lines.append(f"## Email Hook\n")
        lines.append(f"> {email_hook}")
        lines.append("")

    # Improvement suggestion
    if improvement:
        lines.append(f"## Improvement Suggestion\n")
        lines.append(f"> {improvement}")
        lines.append("")

    # Industry context
    if industry_ctx:
        lines.append(f"## Industry Context\n")
        lines.append(f"{industry_ctx}")
        lines.append("")

    # Business details
    lines.append(f"## Business Details\n")
    lines.append(f"- **Address:** {business.get('address', 'N/A')}")
    lines.append(f"- **Phone:** {_resolved_phone(business) or 'N/A'}{_src_note(business)}")
    lines.append(f"- **Email:** {_resolved_email(business) or 'Not found'}")
    lines.append(f"- **Website:** {business.get('website', 'None - needs one!')}")
    lines.append(f"- **Hours:** {business.get('opening_hours', 'N/A')}")

    # Related notes
    lines.append(f"\n## Related Notes\n")
    lines.append(f"- [[{_contact_filename(name)}|Contact Card]]")
    lines.append(f"- [[{_industry_filename(category)}|Industry Overview]]")
    if session_id:
        lines.append(f"- [[{_followup_filename(name, session_id)}|Follow-up Tracker]]")

    path = OBSIDIAN_RESEARCH / f"research_{_slug(name)}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── BRAIN MAP NOTE ──────────────────────────────────────────────────
def create_brain_map() -> str:
    """Create a brain map note showing all connections between entities."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    contacts = sorted(OBSIDIAN_CONTACTS.glob("*.md"))
    industries = sorted(OBSIDIAN_INDUSTRIES.glob("*.md"))
    competitors = sorted(OBSIDIAN_COMPETITORS.glob("*.md"))
    research = sorted(OBSIDIAN_RESEARCH.glob("*.md"))
    followups = sorted(OBSIDIAN_FOLLOWUPS.glob("*.md"))

    lines = [
        "---",
        f"date: {date}",
        f"type: brain_map",
        f"tags:",
        f"  - brain_map",
        f"  - moc",
        f"---\n",
        "# J.A.R.V.I.S Brain Map\n",
        f"*All connections between entities — {date}*\n",
        f"*Open in Obsidian Graph View for visual representation*\n",
    ]

    # Industry -> Contacts mapping
    lines.append("## Industry -> Business Connections\n")
    lines.append("```mermaid")
    lines.append("graph LR")
    for ind in industries[:8]:
        ind_name = ind.stem.replace("industry_", "")
        # Find contacts in this industry
        for c in contacts:
            try:
                content = c.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.startswith("category:"):
                        cat = line.split(":", 1)[1].strip()
                        if cat == ind_name:
                            c_name = c.stem.replace("_", " ").title()
                            lines.append(f"    {ind_name} --> {c_name}")
                        break
            except Exception:
                pass
    lines.append("```")
    lines.append("")

    # Research connections
    if research:
        lines.append("## Research -> Business Links\n")
        for r in research[:10]:
            r_name = r.stem.replace("research_", "").replace("_", " ").title()
            lines.append(f"- [[{r.stem}|{r_name}]]")
        lines.append("")

    # Follow-up status
    if followups:
        lines.append("## Follow-up Status\n")
        pending = 0
        completed = 0
        for f in followups:
            try:
                content = f.read_text(encoding="utf-8")
                if "status: pending" in content:
                    pending += 1
                else:
                    completed += 1
            except Exception:
                pass
        lines.append(f"- **Pending:** {pending}")
        lines.append(f"- **Completed:** {completed}")
        lines.append("")

    # All contacts quick list
    lines.append("## All Contacts\n")
    for c in contacts:
        name = c.stem.replace("_", " ").title()
        lines.append(f"- [[{c.stem}|{name}]]")

    path = OBSIDIAN_VAULT / "04 - Brain Map.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


# ── UTILITY FUNCTIONS ────────────────────────────────────────────────
def mark_contact_approached(business_name: str):
    path = OBSIDIAN_CONTACTS / _contact_filename(business_name)
    if path.exists():
        content = path.read_text(encoding="utf-8")
        content = content.replace("approached: false", "approached: true")
        path.write_text(content, encoding="utf-8")


def update_vault_index():
    """Create/update the vault index (MOC) that connects ALL note types."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    projects = sorted(OBSIDIAN_PROJECTS.glob("*.md"))
    contacts = sorted(OBSIDIAN_CONTACTS.glob("*.md"))
    reports = sorted(OBSIDIAN_REPORTS.glob("*.md"))
    industries = sorted(OBSIDIAN_INDUSTRIES.glob("*.md"))
    research = sorted(OBSIDIAN_RESEARCH.glob("*.md"))
    competitors = sorted(OBSIDIAN_COMPETITORS.glob("*.md"))
    followups = sorted(OBSIDIAN_FOLLOWUPS.glob("*.md"))
    insights = sorted(OBSIDIAN_INSIGHTS.glob("*.md"))

    total_notes = len(projects) + len(contacts) + len(reports) + len(industries) + len(research) + len(competitors) + len(followups) + len(insights)

    lines = [
        "---",
        "tags:",
        "  - index",
        "  - moc",
        f"updated: {date}",
        "---\n",
        "# J.A.R.V.I.S Vault Index\n",
        f"*Last updated: {date}*",
        f"*Total notes: {total_notes}*\n",
        "## Projects\n",
    ]

    if projects:
        for p in projects:
            name = p.stem
            parts = name.split("_", 1)
            friendly = parts[1].replace("_", " ") if len(parts) > 1 else name
            lines.append(f"- [[{name}|{friendly}]]")
    else:
        lines.append("*No projects yet.*")
    lines.append("")

    # Industries
    lines.append("## Industries\n")
    if industries:
        for ind in industries:
            name = ind.stem.replace("industry_", "").replace("_", " ").title()
            lines.append(f"- [[{ind.stem}|{name}]]")
    else:
        lines.append("*No industry notes yet.*")
    lines.append("")

    # Contacts grouped by category
    lines.append("## Contacts\n")
    if contacts:
        by_cat: dict[str, list] = {}
        for c in contacts:
            content = c.read_text(encoding="utf-8")
            cat = "other"
            for line in content.split("\n"):
                if line.startswith("category:"):
                    cat = line.split(":", 1)[1].strip()
                    break
            by_cat.setdefault(cat, []).append(c)
        for cat in sorted(by_cat.keys()):
            lines.append(f"### {cat.replace('_', ' ').title()}\n")
            for c in sorted(by_cat[cat]):
                name = c.stem.replace("_", " ").title()
                lines.append(f"- [[{c.stem}|{name}]]")
            lines.append("")
    else:
        lines.append("*No contacts yet.*\n")

    # Research
    lines.append("## Research\n")
    if research:
        for r in research:
            lines.append(f"- [[{r.stem}]]")
    else:
        lines.append("*No research notes yet.*")
    lines.append("")

    # Competitors
    lines.append("## Competitors\n")
    if competitors:
        for c in competitors:
            name = c.stem.replace("competitor_", "").replace("_", " ").title()
            lines.append(f"- [[{c.stem}|{name}]]")
    else:
        lines.append("*No competitor analyses yet.*")
    lines.append("")

    # Follow-ups
    lines.append("## Follow-ups\n")
    if followups:
        for f in followups:
            parts = f.stem.replace("followup_", "").rsplit("_", 1)
            name = parts[0].replace("_", " ").title() if parts else f.stem
            lines.append(f"- [[{f.stem}|{name}]]")
    else:
        lines.append("*No follow-ups yet.*")
    lines.append("")

    # Insights
    lines.append("## Insights\n")
    if insights:
        for i in insights:
            lines.append(f"- [[{i.stem}]]")
    else:
        lines.append("*No insights yet.*")
    lines.append("")

    # Outreach
    lines.append("## Outreach Forms\n")
    if reports:
        for r in reports:
            lines.append(f"- [[{r.stem}]]")
    else:
        lines.append("*No outreach forms yet.*")
    lines.append("")

    # Quick links
    lines.append("## Quick Links\n")
    lines.append("- [[#Projects|All Projects]]")
    lines.append("- [[#Industries|All Industries]]")
    lines.append("- [[#Contacts|All Contacts]]")
    lines.append("- [[#Research|All Research]]")
    lines.append("- [[#Competitors|All Competitors]]")
    lines.append("- [[#Follow-ups|All Follow-ups]]")
    lines.append("- [[#Insights|All Insights]]")
    lines.append("- [[#Outreach Forms|All Outreach Forms]]")

    index_path = OBSIDIAN_VAULT / "00 - Index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return str(index_path)
