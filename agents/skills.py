"""Skills library -- teachable techniques the agent team can use.

A skill is a small playbook: {name, description, steps, agents, enabled}.
Skills live in OUTPUT_DIR/skills/library.json. Specialists get their
enabled skills (plus global ones) injected into their system prompt, so
adding a skill in the UI immediately changes how they work. Agents can
also LEARN new skills themselves via the learn_skill tool -- that's the
self-improving loop.

All functions are thread-safe (the pipeline emits from worker threads
while the web server serves reads).
"""
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from agents.config import OUTPUT_DIR

LIBRARY_PATH = OUTPUT_DIR / "skills" / "library.json"

_LOCK = threading.Lock()

# ── Seed skills: the team ships with a base playbook ────────────────

_SEED_SKILLS = [
    {
        "name": "signal-triangulation",
        "agents": ["scout"],
        "description": "Never trust one source: confirm key claims (contact, rating, size) across at least two independent sources before reporting.",
        "steps": [
            "Find the fact in source A (map listing, website, review page).",
            "Confirm in source B (web_search or read_url).",
            "If sources disagree, say which is newer and why, or mark it unverified.",
        ],
    },
    {
        "name": "review-mining",
        "agents": ["scout"],
        "description": "Mine a business's recent reviews for the owner's own words -- their stated priorities are the best personalization hooks.",
        "steps": [
            "Search '<business name>' reviews; read the 5 most recent.",
            "Extract recurring complaints (their pain) and praised strengths.",
            "Report the top pain in the owner's own phrasing.",
        ],
    },
    {
        "name": "no-site-pitch",
        "agents": ["strategist"],
        "description": "For businesses without a website, lead with missed revenue, not technology -- owners buy outcomes, not tooling.",
        "steps": [
            "Estimate what 'not findable online' costs them (bookings, calls, directions).",
            "Open with that concrete loss in one sentence.",
            "Offer the simplest next step (a one-page site or a demo), never a feature list.",
        ],
    },
    {
        "name": "hook-rotation",
        "agents": ["strategist"],
        "description": "Never reuse a hook angle for the same industry within 14 days -- check the brain first so repeats never ship.",
        "steps": [
            "brain_query the industry + business before writing.",
            "If the last hook used the same angle, pick the second-best angle.",
            "Log the new angle back into the brain.",
        ],
    },
    {
        "name": "three-touch-cadence",
        "agents": ["strategist"],
        "description": "Plan outreach as a 3-touch cadence (day 0, day 4, day 11), each touch adding new value -- never 'just following up'.",
        "steps": [
            "Touch 1: the personalized hook + one proof point.",
            "Touch 2 (day 4): a specific observation about THEIR business.",
            "Touch 3 (day 11): an easy out + a one-line case result.",
        ],
    },
    {
        "name": "debrief-patterns",
        "agents": ["analyst"],
        "description": "After every batch, record exactly one pattern and one surprise into the brain -- small, honest notes compound.",
        "steps": [
            "Compare this batch's results with the last similar batch.",
            "Write one repeating pattern (what keeps working).",
            "Write one surprise (what contradicted expectations).",
        ],
    },
]


def _empty_library() -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {"skills": [
        dict(id=uuid.uuid4().hex[:8], uses=0, enabled=True,
             source="seed", created_at=now, **s)
        for s in _SEED_SKILLS
    ]}


def _load() -> dict:
    """Load the library, seeding it on first use. Caller holds _LOCK."""
    if not LIBRARY_PATH.exists():
        lib = _empty_library()
        _save(lib)
        return lib
    try:
        with open(LIBRARY_PATH, "r", encoding="utf-8") as f:
            lib = json.load(f)
        if not isinstance(lib, dict) or "skills" not in lib:
            return _empty_library()
        return lib
    except Exception:
        return _empty_library()


def _save(lib: dict) -> None:
    """Atomic write (tmp + replace). Caller holds _LOCK."""
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=True, indent=2)
    tmp.replace(LIBRARY_PATH)


# ── Public API ───────────────────────────────────────────────────────

def list_skills(agent: Optional[str] = None, include_disabled: bool = True) -> list[dict]:
    """All skills, optionally filtered to those assigned to one agent."""
    with _LOCK:
        lib = _load()
    skills = lib["skills"]
    if agent:
        a = (agent or "").lower()
        skills = [s for s in skills
                  if a in [x.lower() for x in (s.get("agents") or [])]
                  or "*" in (s.get("agents") or [])]
    if not include_disabled:
        skills = [s for s in skills if s.get("enabled", True)]
    return sorted(skills, key=lambda s: (s.get("created_at", ""), s.get("name", "")))


def add_skill(name: str, description: str, steps: list[str],
              agents: Optional[list[str]] = None,
              source: str = "user") -> dict:
    """Add a skill. Duplicate names are rejected (use learn_skill to
    auto-merge variants instead)."""
    name = (name or "").strip().lower().replace(" ", "-")[:48]
    if not name:
        raise ValueError("skill needs a name")
    with _LOCK:
        lib = _load()
        if any(s.get("name") == name for s in lib["skills"]):
            raise ValueError(f"skill '{name}' already exists")
        skill = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "description": (description or "").strip(),
            "steps": [str(s).strip() for s in (steps or []) if str(s).strip()][:8],
            "agents": [a.lower() for a in (agents or ["*"])] or ["*"],
            "enabled": True,
            "source": source,
            "uses": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        lib["skills"].append(skill)
        _save(lib)
        return skill


def remove_skill(skill_id: str) -> bool:
    with _LOCK:
        lib = _load()
        before = len(lib["skills"])
        lib["skills"] = [s for s in lib["skills"] if s.get("id") != skill_id]
        changed = len(lib["skills"]) < before
        if changed:
            _save(lib)
        return changed


def toggle_skill(skill_id: str, enabled: Optional[bool] = None) -> Optional[dict]:
    """Flip (or force) a skill's enabled flag. Returns the skill or None."""
    with _LOCK:
        lib = _load()
        for s in lib["skills"]:
            if s.get("id") == skill_id:
                s["enabled"] = (not s.get("enabled", True)) if enabled is None else enabled
                _save(lib)
                return s
    return None


def assign_skill(skill_id: str, agent: str, add: bool = True) -> Optional[dict]:
    """Grant (or revoke) one agent's access to a skill."""
    agent = (agent or "").lower()
    with _LOCK:
        lib = _load()
        for s in lib["skills"]:
            if s.get("id") == skill_id:
                holders = [a.lower() for a in (s.get("agents") or [])]
                if add and agent not in holders:
                    holders.append(agent)
                elif not add:
                    holders = [a for a in holders if a != agent]
                s["agents"] = holders or ["*"]
                _save(lib)
                return s
    return None


def mark_used(names: list[str]) -> None:
    """Bump the usage counter for skills that were just injected."""
    if not names:
        return
    wanted = {n.lower() for n in names}
    with _LOCK:
        lib = _load()
        changed = False
        for s in lib["skills"]:
            if s.get("name") in wanted:
                s["uses"] = s.get("uses", 0) + 1
                changed = True
        if changed:
            _save(lib)


def learn_skill(name: str, description: str, steps: list[str],
                agents: Optional[list[str]] = None) -> dict:
    """Agent-driven self-learning: save a technique they discovered.
    If the name exists, refine it (new description/steps) instead of
    erroring -- refinement IS the learning loop."""
    name = (name or "").strip().lower().replace(" ", "-")[:48]
    with _LOCK:
        lib = _load()
        for s in lib["skills"]:
            if s.get("name") == name:
                if description:
                    s["description"] = description.strip()
                clean_steps = [str(x).strip() for x in (steps or []) if str(x).strip()]
                if clean_steps:
                    s["steps"] = clean_steps[:8]
                if agents:
                    merged = set(s.get("agents") or []) | {a.lower() for a in agents}
                    s["agents"] = sorted(merged)
                s["source"] = s.get("source") if s.get("source") != "seed" else "refined"
                _save(lib)
                return dict(s, refined=True)
    return add_skill(name, description, steps, agents=agents, source="learned")


def skills_prompt(agent_key: str) -> str:
    """The prompt block for one agent: their enabled skills + global ones.
    Empty string when there's nothing active (keeps prompts clean)."""
    skills = [s for s in list_skills(agent=agent_key, include_disabled=False)]
    if not skills:
        return ""
    lines = ["YOUR SKILLS (playbooks you run -- follow their steps when relevant):"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
        for i, step in enumerate(s.get("steps") or [], 1):
            lines.append(f"    {i}. {step}")
    return "\n".join(lines)


def skill_names_for(agent_key: str) -> list[str]:
    return [s["name"] for s in list_skills(agent=agent_key, include_disabled=False)]


def stats() -> dict:
    skills = list_skills()
    return {
        "total": len(skills),
        "enabled": sum(1 for s in skills if s.get("enabled", True)),
        "learned": sum(1 for s in skills if s.get("source") == "learned"),
        "total_uses": sum(s.get("uses", 0) for s in skills),
    }
