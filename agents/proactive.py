"""Proactive agent layer — JARVIS studies the data on its own and speaks up.

Two capabilities:

1. check_in()  — scans the brain, the vault follow-ups, the knowledge base and
   the session files, and produces a structured briefing: overdue follow-ups,
   WhatsApp-reachable leads, businesses we know a lot about, learning stats.
   This is what an "always active" agent uses to decide something is worth
   saying.

2. proactive_notes() — small list of things worth telling the user right now,
   each with a priority. The chat surfaces the important ones automatically
   at session start and after search/draft/send actions, so the user learns
   something without having to ask.

Nothing here blocks or crashes a chat turn — worst case it returns empty.
"""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path

from agents.config import OUTPUT_DIR


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# ── Signal gathering ─────────────────────────────────────────────────

def _overdue_followups(max_days: int = 2) -> list[dict]:
    """Pending follow-up notes older than max_days, worst first."""
    vault = Path("D:/brain/brain/followups")
    if not vault.exists():
        return []
    out = []
    today = date.today()
    for f in vault.glob("*.md"):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "status: pending" not in content:
            continue
        m = None
        name = ""
        for line in content.split("\n"):
            if line.startswith("date:") and not m:
                m = line
            if line.startswith("business:") and not name:
                name = line.split(":", 1)[1].strip()
        if not name:
            name = f.stem.replace("followup_", "").replace("_", " ")
        if not m:
            continue
        import re
        dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", m)
        if not dm:
            continue
        created = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        days = (today - created).days
        if days > max_days:
            out.append({"name": name, "days": days, "link": f.stem})
    out.sort(key=lambda x: -x["days"])
    return out


def _whatsapp_ready_leads(limit: int = 5) -> list[dict]:
    """Businesses with a usable phone from session search results."""
    out = []
    sessions_dir = OUTPUT_DIR / "sessions"
    if not sessions_dir.exists():
        return out
    for sdir in sorted(sessions_dir.iterdir(), reverse=True)[:5]:
        data = _read_json(sdir / "search_results.json", {})
        for b in data.get("no_website", data.get("businesses", [])):
            phone = b.get("phone") or b.get("maps_phone", "")
            if phone:
                out.append({"name": b.get("name", "?"), "phone": phone,
                            "category": b.get("category", "")})
            if len(out) >= limit:
                return out
    return out


def _learning_stats() -> dict:
    from agents.learn import get_kb
    try:
        return get_kb().get_summary()
    except Exception:
        return {}


def _known_business_count() -> int:
    from agents.brain import get_brain
    try:
        return len(get_brain().list_businesses())
    except Exception:
        return 0


# ── Briefing ─────────────────────────────────────────────────────────

def check_in(max_days: int = 2) -> dict:
    """Full situational briefing: everything an active agent should know."""
    return {
        "generated_at": datetime.now().isoformat(),
        "overdue_followups": _overdue_followups(max_days),
        "whatsapp_leads": _whatsapp_ready_leads(),
        "known_businesses": _known_business_count(),
        "learning": _learning_stats(),
    }


def format_briefing(brief: dict) -> str:
    """Human-readable briefing text."""
    lines = ["Agent check-in:"]

    overdue = brief.get("overdue_followups", [])
    if overdue:
        worst = overdue[0]
        lines.append(f"- {len(overdue)} follow-up(s) overdue — worst: "
                     f"{worst['name']} ({worst['days']} days). Say 'follow up' "
                     f"and I'll draft it.")
    else:
        lines.append("- No overdue follow-ups. Clean slate.")

    leads = brief.get("whatsapp_leads", [])
    if leads:
        lines.append(f"- {len(leads)} lead(s) reachable on WhatsApp, e.g. "
                     f"{leads[0]['name']} ({leads[0]['phone']}). Full list in "
                     f"the phones CSV.")

    known = brief.get("known_businesses", 0)
    learning = brief.get("learning", {})
    if known or learning.get("total_businesses_seen"):
        lines.append(f"- Brain: {known} businesses studied, "
                     f"{learning.get('total_businesses_seen', 0)} interactions logged, "
                     f"{learning.get('categories_learned', 0)} categories learned.")

    if len(lines) == 1:
        lines.append("- Nothing needs attention. Search a new area to grow the pipeline.")
    return "\n".join(lines)


# ── Proactive notes (surfaced automatically in chat) ─────────────────

def proactive_notes(max_days: int = 2) -> list[dict]:
    """Things worth telling the user unprompted, priority-sorted.

    priority: 'high' shows immediately; 'info' is one-liner only.
    """
    notes = []
    try:
        overdue = _overdue_followups(max_days)
        if overdue:
            worst = overdue[0]
            notes.append({
                "priority": "high",
                "text": f"Heads up: follow-up for {worst['name']} is {worst['days']} days overdue.",
            })
        leads = _whatsapp_ready_leads(limit=3)
        if leads:
            notes.append({
                "priority": "info",
                "text": f"{len(leads)}+ leads have WhatsApp numbers ready.",
            })
    except Exception:
        return notes
    return notes


def render_notes(notes: list[dict]) -> str:
    """Render proactive notes as a chat block (empty string if none)."""
    if not notes:
        return ""
    lines = ["[AGENT CHECK-IN]"]
    for n in notes:
        marker = "!!" if n["priority"] == "high" else "i"
        lines.append(f"  [{marker}] {n['text']}")
    return "\n".join(lines)


def auto_brief(max_days: int = 2) -> str:
    """One-shot briefing string for chat start. Never raises."""
    try:
        brief = format_briefing(check_in(max_days))
    except Exception:
        brief = ""
    # Layer 3: the specialist team speaks up too (guarded, never blocks).
    try:
        from agents.agent_team import team_proactive_notes
        team_notes = team_proactive_notes()
        if team_notes:
            extra = "\n".join(f"- {n['text']}" for n in team_notes)
            brief = f"{brief}\nAgent team:\n{extra}" if brief else f"Agent team:\n{extra}"
    except Exception:
        pass
    return brief
