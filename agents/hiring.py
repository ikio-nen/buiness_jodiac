"""Hired agents — runtime roster persistence (the ADD AGENT seam).

One module owns the hired roster. agent_team.get_agent()/all_agent_keys()
resolve built-ins + hires through this file; consumers never read the JSON
directly. Records persist to agent_output/hired_agents.json; a corrupt
file degrades to an empty roster (never crashes the floor).

Slot allocation follows the SeatPool pattern (reserve first-free, idempotent
release) so every hire gets a stable desk on the office floor.
"""

import json
import re
from datetime import datetime
from pathlib import Path

try:
    from agents.config import AGENT_OUTPUT_DIR
    _STORE = Path(AGENT_OUTPUT_DIR) / "hired_agents.json"
except Exception:
    _STORE = Path("agent_output") / "hired_agents.json"

MAX_HIRES = 8
SLOTS = list(range(MAX_HIRES))          # desk 0..7, first-free wins

# ── Storage ──────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("agents"), list):
                return data
    except Exception:
        pass
    return {"agents": []}


def _save(data: dict) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(
        json.dumps(data, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )


# ── Resolution (what agent_team calls) ───────────────────────────────

def active_keys() -> list[str]:
    """Keys of every active hire, in creation order."""
    return [a["id"] for a in _load()["agents"] if a.get("active")]


def get_hired(key: str) -> dict | None:
    """One hire as an agent_team-shaped record, or None.

    Returns the SAME identity shape a built-in carries (`station` + `look`),
    so the web layer serves one record shape for the whole roster and the
    client never has to know which half an agent came from.
    """
    key = (key or "").lower().strip()
    for a in _load()["agents"]:
        if a.get("id") == key and a.get("active"):
            return {
                "name": a.get("name", key),
                "role": a.get("role", "specialist"),
                "persona": a.get("persona", ""),
                "hired": True,
                "station": f"station-hired-{a.get('slot', 0)}",
                "look": {
                    "skin": a.get("skin", "#f0c9a0"),
                    "hair": a.get("hair", "#2b2b33"),
                    "hairStyle": a.get("hairStyle", "short"),
                    "shirt": a.get("color", "#8a8172"),
                    "accessory": a.get("accessory", "none"),
                    "accColor": a.get("accColor", ""),
                },
            }
    return None


# ── Slot pool (SeatPool pattern) ─────────────────────────────────────

def _claimed_slots(data: dict) -> set[int]:
    claimed = set()
    for a in data["agents"]:
        if a.get("active") and isinstance(a.get("slot"), int):
            claimed.add(a["slot"])
    return claimed


def reserve_slot(data: dict) -> int | None:
    """First free desk, or None when the floor is full."""
    for s in SLOTS:
        if s not in _claimed_slots(data):
            return s
    return None


# ── Validation ───────────────────────────────────────────────────────

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def builtin_keys() -> set[str]:
    """Keys already on the floor — read from the roster, never re-listed.

    This used to be a hardcoded set here, and it had already drifted: it was
    missing scraper/enricher/builder, so those names could be hired a second
    time and "ask builder" silently became ambiguous. The roster owns itself.
    """
    try:
        from agents.agent_team import AGENTS
        return set(AGENTS) | {"jarvis"}
    except Exception:
        return {"jarvis"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "agent"


def make_id(name: str, data: dict) -> str:
    """slug + base36 timestamp suffix — unique without a collision round-trip."""
    base = _slug(name)
    taken = {a["id"] for a in data["agents"]} | builtin_keys()
    rid = f"{base}-{format(int(datetime.now().timestamp() * 1000), 'x')}"
    while rid in taken:
        rid += "x"
    return rid


def validate(payload: dict) -> tuple[dict | None, str]:
    """Returns (clean_fields, '') or (None, error_message)."""
    name = (payload.get("name") or "").strip()
    role = (payload.get("role") or "specialist").strip()
    persona = (payload.get("persona") or "").strip()
    color = (payload.get("color") or "#8a8172").strip()
    hair = (payload.get("hair") or "#2b2b33").strip()
    skin = (payload.get("skin") or "#f0c9a0").strip()

    if not (1 <= len(name) <= 30):
        return None, "Name must be 1-30 characters."
    if _slug(name) in builtin_keys():
        return None, f"'{name}' is already on the floor — pick a different name."
    taken_names = {a.get("name", "").strip().lower()
                   for a in _load()["agents"] if a.get("active")}
    if name.lower() in taken_names:
        return None, f"'{name}' is already on the floor — pick a different name."
    if len(role) > 60:
        return None, "Role must be 60 characters or fewer."
    if not (10 <= len(persona) <= 2000):
        return None, "Briefing must be 10-2000 characters."
    for label, val in (("color", color), ("hair", hair), ("skin", skin)):
        if not _HEX.match(val):
            return None, f"{label} must be a hex color like #4e8f7d."
    return {"name": name, "role": role, "persona": persona,
            "color": color, "hair": hair, "skin": skin}, ""


# ── Hire / part ──────────────────────────────────────────────────────

def hire(payload: dict) -> tuple[dict | None, str]:
    """Create + activate a hire. Returns (record, '') or (None, error)."""
    fields, err = validate(payload)
    if err:
        return None, err
    data = _load()
    if len(_claimed_slots(data)) >= MAX_HIRES:
        return None, "The floor is full — part with someone before hiring again."

    rid = make_id(fields["name"], data)
    slot = reserve_slot(data)
    if slot is None:
        return None, "The floor is full — part with someone before hiring again."

    rec = {"id": rid, "slot": slot, "active": True,
           "created_at": datetime.now().isoformat(), **fields}
    data["agents"].append(rec)
    try:
        _save(data)
    except Exception as e:
        return None, f"Could not save the roster: {e}"
    return rec, ""


def deactivate(key: str) -> bool:
    """Soft delete: sprite leaves the floor, desk frees, memory is kept."""
    data = _load()
    hit = False
    for a in data["agents"]:
        if a.get("id") == key and a.get("active"):
            a["active"] = False
            hit = True
    if hit:
        _save(data)
    return hit
