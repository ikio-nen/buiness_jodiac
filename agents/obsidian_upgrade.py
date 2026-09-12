"""Additional Obsidian vault features — dashboard, timeline, tags reference."""
import re
from datetime import datetime, date
from pathlib import Path
from .config import (
    OBSIDIAN_VAULT, OBSIDIAN_PROJECTS, OBSIDIAN_CONTACTS, OBSIDIAN_REPORTS,
    OBSIDIAN_INDUSTRIES, OBSIDIAN_RESEARCH, OBSIDIAN_COMPETITORS,
    OBSIDIAN_FOLLOWUPS, OBSIDIAN_INSIGHTS,
)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _frontmatter(content: str) -> dict:
    """Parse simple key: value frontmatter lines."""
    out = {}
    if not content.startswith("---"):
        return out
    for line in content.split("\n")[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _contact_filename(name: str) -> str:
    from .obsidian_sync import _contact_filename as cf
    return cf(name)


def _whatsapp_ready(phone: str) -> bool:
    """A phone is WhatsApp-able if it has enough digits."""
    return len(re.sub(r"\D", "", phone)) >= 10


def channel_intelligence() -> dict:
    """Compute channel-reachability and follow-up urgency from vault content.

    Reads every contact + follow-up note. Returns:
        contacts: total, email_ready, whatsapp_ready, never_contacted,
                  phone_source_breakdown {osm, maps, osm+maps}
        followups: pending, overdue [{name, link, days_late}]
    """
    contacts = sorted(OBSIDIAN_CONTACTS.glob("*.md"))
    followups = sorted(OBSIDIAN_FOLLOWUPS.glob("*.md"))

    email_ready = whatsapp_ready = never_contacted = 0
    phone_sources = {}
    whatsapp_list = []

    for c in contacts:
        fm = _frontmatter(_read(c))
        email = fm.get("email", "")
        phone = fm.get("phone", "")
        if email:
            email_ready += 1
        if _whatsapp_ready(phone):
            whatsapp_ready += 1
            whatsapp_list.append((fm.get("business", c.stem), phone, fm.get("phone_source", "")))
        src = fm.get("phone_source", "")
        if src:
            phone_sources[src] = phone_sources.get(src, 0) + 1
        if fm.get("approached") != "true":
            never_contacted += 1

    pending = 0
    overdue = []
    today = date.today()
    for f in followups:
        content = _read(f)
        fm = _frontmatter(content)
        if fm.get("status") != "pending":
            continue
        pending += 1
        # Overdue = follow-up note created >2 days ago and still pending
        m = re.search(r"date:\s*(\d{4})-(\d{2})-(\d{2})", content)
        if m:
            created = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            days = (today - created).days
            if days > 2:
                name = fm.get("business", f.stem)
                overdue.append({
                    "name": name,
                    "link": f.stem,
                    "days_late": days,
                })
    overdue.sort(key=lambda x: -x["days_late"])

    return {
        "contacts": {
            "total": len(contacts),
            "email_ready": email_ready,
            "whatsapp_ready": whatsapp_ready,
            "never_contacted": never_contacted,
            "phone_source_breakdown": phone_sources,
            "whatsapp_list": whatsapp_list,
        },
        "followups": {
            "pending": pending,
            "overdue": overdue,
        },
    }


def create_dashboard() -> str:
    """Create a master dashboard note linking to everything."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    projects = sorted(OBSIDIAN_PROJECTS.glob("*.md"))
    contacts = sorted(OBSIDIAN_CONTACTS.glob("*.md"))
    industries = sorted(OBSIDIAN_INDUSTRIES.glob("*.md"))
    followups = sorted(OBSIDIAN_FOLLOWUPS.glob("*.md"))
    insights = sorted(OBSIDIAN_INSIGHTS.glob("*.md"))
    research = sorted(OBSIDIAN_RESEARCH.glob("*.md"))
    competitors = sorted(OBSIDIAN_COMPETITORS.glob("*.md"))
    reports = sorted(OBSIDIAN_REPORTS.glob("*.md"))

    # Count stats
    total_contacts = len(contacts)
    approached = 0
    categories = set()
    for c in contacts:
        try:
            content = c.read_text(encoding="utf-8")
            if "approached: true" in content:
                approached += 1
            for line in content.split("\n"):
                if line.startswith("category:"):
                    categories.add(line.split(":", 1)[1].strip())
        except Exception:
            pass

    pending_followups = 0
    completed_followups = 0
    for f in followups:
        try:
            content = f.read_text(encoding="utf-8")
            if "status: pending" in content:
                pending_followups += 1
            else:
                completed_followups += 1
        except Exception:
            pass

    total_research = len([r for r in research if r.stem.startswith("research_") and r.stem != "research_"])

    # Channel + follow-up intelligence (computed from note content)
    intel = channel_intelligence()
    ci = intel["contacts"]
    fi = intel["followups"]

    lines = [
        "---",
        f"date: {date}",
        f"type: dashboard",
        f"tags:",
        f"  - dashboard",
        f"  - moc",
        f"---\n",
        "# J.A.R.V.I.S Dashboard\n",
        f"*Last updated: {date}*\n",
        "## Stats\n",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Projects | {len(projects)} |",
        f"| Total Contacts | {total_contacts} |",
        f"| Approached | {approached} |",
        f"| Pending Follow-ups | {pending_followups} |",
        f"| Completed Follow-ups | {completed_followups} |",
        f"| Industries | {len(industries)} |",
        f"| Business Research | {total_research} |",
        f"| Competitors | {len(competitors)} |",
        f"| Reports | {len(reports)} |",
        f"| Insights | {len(insights)} |",
        f"\n## Channel Reachability\n",
        f"| Channel | Contacts |",
        f"|---------|----------|",
        f"| Email-ready | {ci['email_ready']}/{ci['total']} |",
        f"| WhatsApp-ready | {ci['whatsapp_ready']}/{ci['total']} |",
        f"| Never contacted | {ci['never_contacted']} |",
    ]

    if ci["phone_source_breakdown"]:
        lines.append("")
        src_parts = [f"{k}: {v}" for k, v in sorted(ci["phone_source_breakdown"].items())]
        lines.append(f"*Phone sources — {', '.join(src_parts)}*")

    if ci["whatsapp_list"]:
        lines.append("")
        lines.append("**WhatsApp targets (send manually anytime):**")
        for name, phone, src in ci["whatsapp_list"][:10]:
            lines.append(f"- {phone} — [[{_contact_filename(name)}|{name}]]" + (f" _({src})_" if src else ""))
        if len(ci["whatsapp_list"]) > 10:
            lines.append(f"- *...and {len(ci['whatsapp_list']) - 10} more*")

    lines += [
        f"\n## What To Do Next\n",
    ]
    if fi["overdue"]:
        worst = fi["overdue"][0]
        lines.append(f"1. **{len(fi['overdue'])} overdue follow-up(s)** — oldest: "
                     f"[[{worst['link']}|{worst['name']}]] ({worst['days_late']} days)")
    elif fi["pending"]:
        lines.append(f"1. {fi['pending']} follow-up(s) pending — none overdue yet")
    else:
        lines.append("1. No pending follow-ups")
    lines.append(f"2. {ci['never_contacted']} contact(s) never approached — "
                 f"{ci['email_ready']} reachable by email, {ci['whatsapp_ready']} by WhatsApp")
    lines.append("")
    lines += [
        f"\n## Quick Actions\n",
        "- [[00 - Index|Vault Index]]",
        "- [[04 - Brain Map|Brain Map]]",
        "- Start a new project from J.A.R.V.I.S\n",
        "## Active Projects\n",
    ]

    for p in projects[-5:]:  # Last 5
        name = p.stem
        parts = name.split("_", 1)
        friendly = parts[1].replace("_", " ") if len(parts) > 1 else name
        lines.append(f"- [[{name}|{friendly}]]")

    lines.append("\n## Industries\n")
    for ind in industries[-10:]:
        name = ind.stem.replace("industry_", "").replace("_", " ").title()
        lines.append(f"- [[{ind.stem}|{name}]]")

    lines.append("\n## Pending Follow-ups\n")
    for f in followups[-10:]:
        parts = f.stem.replace("followup_", "").rsplit("_", 1)
        name = parts[0].replace("_", " ").title() if parts else f.stem
        lines.append(f"- [[{f.stem}|{name}]]")

    if insights:
        lines.append("\n## Latest Insights\n")
        for i in insights[-3:]:
            lines.append(f"- [[{i.stem}]]")

    if categories:
        lines.append("\n## Categories in Vault\n")
        for cat in sorted(categories):
            lines.append(f"- [[industry_{cat}|{cat.replace('_', ' ').title()}]]")

    path = OBSIDIAN_VAULT / "01 - Dashboard.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def create_timeline() -> str:
    """Create a timeline note showing all sessions chronologically."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    projects = sorted(OBSIDIAN_PROJECTS.glob("*.md"), reverse=True)

    lines = [
        "---",
        f"date: {date}",
        f"type: timeline",
        f"tags:",
        f"  - timeline",
        f"---\n",
        "# Session Timeline\n",
        f"*All sessions in chronological order*\n",
    ]

    for p in projects:
        name = p.stem
        parts = name.split("_", 1)
        session_id = parts[0] if parts else ""
        friendly = parts[1].replace("_", " ") if len(parts) > 1 else name

        # Try to extract date from session_id
        if len(session_id) >= 8:
            try:
                y, m, d = session_id[:4], session_id[4:6], session_id[6:8]
                session_date = f"{y}-{m}-{d}"
            except Exception:
                session_date = session_id
        else:
            session_date = session_id

        lines.append(f"### {session_date} - {friendly}")
        lines.append(f"- [[{name}|Open project]]")
        lines.append(f"- [[outreach_{name.split('_')[0]}|Outreach form]]")
        lines.append(f"- [[research_{name.split('_')[0]}|Research]]")
        lines.append(f"- [[insights_{name.split('_')[0]}|Insights]]")
        lines.append("")

    path = OBSIDIAN_VAULT / "02 - Timeline.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def create_tags_reference() -> str:
    """Create a tags reference note listing all used tags."""
    date = datetime.now().strftime("%Y-%m-%d %H:%M")

    tags_found: dict[str, list] = {}
    all_dirs = [
        OBSIDIAN_PROJECTS, OBSIDIAN_CONTACTS, OBSIDIAN_REPORTS,
        OBSIDIAN_INDUSTRIES, OBSIDIAN_RESEARCH, OBSIDIAN_COMPETITORS,
        OBSIDIAN_FOLLOWUPS, OBSIDIAN_INSIGHTS,
    ]

    for d in all_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8")
                in_tags = False
                for line in content.split("\n"):
                    if line.strip() == "tags:":
                        in_tags = True
                        continue
                    if in_tags:
                        if line.strip().startswith("- "):
                            tag = line.strip()[2:].strip()
                            tags_found.setdefault(tag, []).append(f.stem)
                        else:
                            in_tags = False
            except Exception:
                pass

    lines = [
        "---",
        f"date: {date}",
        f"type: tags_reference",
        f"tags:",
        f"  - reference",
        f"---\n",
        "# Tags Reference\n",
        f"*All tags used in the vault ({len(tags_found)} unique tags)*\n",
    ]

    for tag in sorted(tags_found.keys()):
        notes = tags_found[tag]
        lines.append(f"## #{tag} ({len(notes)} notes)\n")
        for note in sorted(notes)[:20]:  # Show up to 20 per tag
            lines.append(f"- [[{note}]]")
        if len(notes) > 20:
            lines.append(f"- *...and {len(notes) - 20} more*")
        lines.append("")

    path = OBSIDIAN_VAULT / "03 - Tags.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def update_graph_config():
    """Update .obsidian/graph.json with colors for all note types."""
    graph_config = {
        "collapse-filter": False,
        "search": "",
        "showTags": True,
        "showAttachments": False,
        "hideUnresolved": False,
        "showOrphans": True,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": "tag:#project", "color": {"a": 1, "rgb": 3447003}},
            {"query": "tag:#contact", "color": {"a": 1, "rgb": 3066993}},
            {"query": "tag:#industry", "color": {"a": 1, "rgb": 10181046}},
            {"query": "tag:#outreach", "color": {"a": 1, "rgb": 15844367}},
            {"query": "tag:#research", "color": {"a": 1, "rgb": 15105570}},
            {"query": "tag:#competitor", "color": {"a": 1, "rgb": 15158332}},
            {"query": "tag:#followup", "color": {"a": 1, "rgb": 3426654}},
            {"query": "tag:#insight", "color": {"a": 1, "rgb": 10038562}},
            {"query": "tag:#dashboard", "color": {"a": 1, "rgb": 16776960}},
            {"query": "tag:#index", "color": {"a": 1, "rgb": 16777215}},
        ],
        "collapse-display": False,
        "showArrow": True,
        "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1,
        "lineSizeMultiplier": 1,
        "collapse-forces": True,
        "centerStrength": 0.518713248970312,
        "repelStrength": 10,
        "linkStrength": 1,
        "linkDistance": 250,
    }

    import json
    graph_path = OBSIDIAN_VAULT / ".obsidian" / "graph.json"
    graph_path.write_text(json.dumps(graph_config, indent=2), encoding="utf-8")
    return str(graph_path)


def run_all_upgrades():
    """Run all vault upgrades and return paths created."""
    paths = []
    paths.append(create_dashboard())
    paths.append(create_timeline())
    paths.append(create_tags_reference())
    paths.append(update_graph_config())
    try:
        from .obsidian_sync import create_brain_map
        paths.append(create_brain_map())
    except Exception:
        pass
    return paths
