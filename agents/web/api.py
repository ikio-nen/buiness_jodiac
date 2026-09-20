"""HTTP surface of the office: the document, session stats, history, uploads,
the brain, the roster, the agent lifecycle, the event log and the skills
library.

Every route here is a thin read or a hand-off to a module that owns the rules
(``hiring`` owns who may be hired, ``skills`` owns the library, ``event_bus``
owns the log). Nothing in this file decides anything on its own, which is why
it can be read top to bottom as the API's table of contents.
"""

import json
from pathlib import Path

from fastapi import (APIRouter, File, HTTPException, UploadFile)
from fastapi.responses import FileResponse

from agents.web.web_session import resume_latest

STATIC_DIR = Path(__file__).parent / "static"

router = APIRouter()


# ── The document ───────────────────────────────────────────────────────

@router.get("/")
@router.get("/index.html")
async def index():
    """Serve the app document, never from cache.

    The document is what names the versioned asset URLs, so a cached copy
    pins the browser to an old app.js and the user silently runs a previous
    UI with no way to tell — that is how a stale floor gets reported as a
    bug in code that was already fixed. The assets under /static stay
    cacheable; their URLs change whenever they do.
    """
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# ── Session and conversation ───────────────────────────────────────────

@router.get("/api/status")
async def api_status():
    """Return current session stats."""
    try:
        from agents.config import get_business_profile
        from agents import ai_engine
        s = resume_latest()
        profile = get_business_profile()
        data = s.load_data("search_results.json") if s.active else {}
        drafts = s.load_data("email_drafts.json").get("drafts", []) if s.active else []
        return {
            "session_id": s.id if s.active else None,
            "session_name": s.name if s.active else None,
            "profile": profile,
            "businesses_found": len(data.get("businesses", [])),
            "businesses_no_site": len(data.get("no_website", [])),
            "drafts_count": len(drafts),
            "ai_configured": ai_engine.is_available(),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/history")
async def api_history():
    """Return recent conversations."""
    try:
        from agents.chat_memory import ChatMemory
        mem = ChatMemory()
        convos = mem.get_recent_conversations(20)
        mem.close()
        return {"conversations": convos}
    except Exception as e:
        return {"conversations": [], "error": str(e)}


@router.get("/api/conversation/{conv_id}")
async def api_conversation(conv_id: int):
    """Return messages for a specific conversation.

    404s when the id is unknown. Returning 200 with an empty list made a
    deleted conversation look like an empty one, so a client could never
    tell whether a delete had actually landed.
    """
    from agents.chat_memory import ChatMemory
    mem = ChatMemory(conversation_id=conv_id)
    try:
        if not mem.conversation_exists(conv_id):
            raise HTTPException(status_code=404, detail="No such conversation")
        return {"messages": mem.get_context(100)}
    finally:
        mem.close()


@router.delete("/api/conversation/{conv_id}")
async def api_delete_conversation(conv_id: int):
    """Delete a conversation and all its messages."""
    try:
        from agents.chat_memory import ChatMemory
        mem = ChatMemory()
        deleted = mem.delete_conversation(conv_id)
        mem.close()
        return {"ok": deleted,
                "error": None if deleted else f"Conversation {conv_id} not found."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Save a user-uploaded attachment (brochure, catalog) for an email."""
    import uuid
    try:
        from agents.config import OUTPUT_DIR
        up_dir = OUTPUT_DIR / "uploads"
        up_dir.mkdir(parents=True, exist_ok=True)
        name = Path(file.filename or "upload.bin").name or "upload.bin"
        dest = up_dir / f"{uuid.uuid4().hex[:8]}_{name}"
        dest.write_bytes(await file.read())
        return {"path": str(dest), "name": name, "size": dest.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


# ── Brain, roster and the floor's telemetry ────────────────────────────

@router.get("/api/campaign")
async def api_campaign():
    """Current campaign gate state, so a fresh tab can re-render the
    interactive checklist instead of the flow silently waiting on a
    card that died with the old page."""
    session = resume_latest()
    if not session.active:
        return {"phase": "none"}
    state = session.load_data("campaign_state.json")
    phase = state.get("phase", "none")
    out = {"phase": phase}
    if phase == "awaiting_selection":
        out["checklist"] = {
            "location": state.get("location", ""),
            "goal": state.get("goal", ""),
            "businesses": state.get("curated", []),
            "selected": state.get("selected", []),
        }
    elif phase == "interview":
        from agents.campaign import current_question
        out["question"] = current_question(state)
    return out


# ── Campaign report downloads ─────────────────────────────────────

@router.get("/api/report/initial")
async def api_report_initial():
    """Download the current campaign's initial PDF (approved targets)."""
    from agents.config import OUTPUT_DIR
    from fastapi.responses import FileResponse as _FR
    session = resume_latest()
    if not session.active:
        raise HTTPException(status_code=404, detail="No active session")
    path = session.load_data("campaign_state.json").get("initial_pdf", "")
    if not path or not Path(path).exists():
        # Fall back to the newest initial report on disk.
        candidates = sorted((OUTPUT_DIR / "reports").glob("campaign_initial_*.pdf"))
        if not candidates:
            raise HTTPException(status_code=404, detail="No initial report yet")
        path = str(candidates[-1])
    return _FR(path, filename=Path(path).name,
               headers={"Cache-Control": "no-cache"})


@router.get("/api/report/final")
async def api_report_final():
    """Download the most recent final campaign report PDF."""
    from agents.config import OUTPUT_DIR
    from fastapi.responses import FileResponse as _FR
    session = resume_latest()
    path = ""
    if session.active:
        path = session.load_data("campaign_final.json").get("final_pdf", "")
    if not path or not Path(path).exists():
        candidates = sorted((OUTPUT_DIR / "reports").glob("campaign_final_*.pdf"))
        if not candidates:
            raise HTTPException(status_code=404, detail="No final report yet")
        path = str(candidates[-1])
    return _FR(path, filename=Path(path).name,
               headers={"Cache-Control": "no-cache"})


@router.get("/api/brain")
async def api_brain():
    """Everything the brain knows -- powers the Agent Ops floor + status panel."""
    try:
        from agents.brain import get_brain
        from agents.config import OUTPUT_DIR
        brain = get_brain()
        stats = brain.get_stats()
        industries = []
        for name in brain.list_industries()[:12]:
            d = brain.get_industry(name)
            industries.append({
                "name": name,
                "encounters": d.get("times_encountered", 0),
                "pain_points": len(d.get("pain_points", [])),
                "hooks": len(d.get("hooks", [])),
            })
        # Recent businesses the brain has intel on
        biz_list = []
        for rec in brain.list_businesses()[:12]:
            inters = rec.get("interactions", [])
            biz_list.append({
                "name": rec.get("name", "?"),
                "category": rec.get("category", ""),
                "rating": rec.get("rating"),
                "gaps": len(rec.get("gaps", [])),
                "last": (inters[-1].get("type", "?") if inters else ""),
            })
        # Specialist agent memories (agent_brains/*.json)
        agents_out = []
        for f in sorted((OUTPUT_DIR / "agent_brains").glob("*.json")):
            if f.stem.startswith("_"):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                agents_out.append({
                    "key": f.stem,
                    "facts": sum(len(v) for v in d.get("facts", {}).values()),
                    "chats": d.get("chat_count", 0),
                    "updated": d.get("updated_at", "")[:19],
                })
            except Exception:
                continue
        return {
            "stats": stats,
            "industries": industries,
            "businesses": biz_list,
            "agents": agents_out,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/agents")
async def api_agents():
    """The roster: one record shape for built-ins and hires alike.

    `look` and `home_station` are served for EVERY agent. They used to be
    sent only for hires, because the client hardcoded the built-ins' look and
    desk — which meant an agent's identity lived in this module, in
    agent_team.py and in two JS maps, and those could drift silently. The
    roster (agent_team) owns the identity; this endpoint just publishes it;
    the client renders whatever it is handed.
    """
    try:
        from agents.agent_team import AGENTS, get_agent, all_agent_keys, _memory_count
        agents = []
        for k in all_agent_keys():
            v = get_agent(k) or {}
            agents.append({
                "key": k,
                "name": v.get("name", k),
                "role": v.get("role", ""),
                "memory": _memory_count(k),
                "hired": k not in AGENTS,
                "look": v.get("look"),
                "home_station": v.get("station") or "station-brain",
            })
        return {"agents": agents}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/agents/hire")
async def api_hire_agent(payload: dict):
    """ADD AGENT — create a specialist at runtime (hiring.py owns the rules)."""
    from agents.hiring import hire as do_hire
    from agents.event_bus import emit
    rec, err = do_hire(payload)
    if err:
        return {"ok": False, "error": err}
    emit("bot", bot=rec["id"], status="done",
         task=f"{rec['name']} joins the floor — {rec['role']}")
    return {"ok": True, "agent": rec}


@router.post("/api/agents/{agent_id}/deactivate")
async def api_deactivate_agent(agent_id: str):
    """Part the ways — soft delete; desk frees, memory stays."""
    from agents.hiring import deactivate
    from agents.event_bus import emit
    if not deactivate(agent_id):
        return {"ok": False, "error": f"No active hire named '{agent_id}'."}
    emit("bot", bot=agent_id, status="done", task="departs the floor")
    return {"ok": True}


@router.get("/api/events")
async def api_events():
    """Recent bus events (for the ops floor when a client reconnects)."""
    from agents.event_bus import recent
    return {"events": recent(60)}


# ── Skills library ─────────────────────────────────────────────────────

@router.get("/api/skills")
async def api_skills(agent: str = None):
    """The skills library, optionally filtered to one agent."""
    try:
        from agents.skills import list_skills, stats
        return {"skills": list_skills(agent=agent), "stats": stats()}
    except Exception as e:
        return {"skills": [], "error": str(e)}


@router.post("/api/skills")
async def api_skills_add(body: dict = None):
    """Add a skill: {name, description, steps[], agents[]}."""
    try:
        from agents.skills import add_skill
        body = body or {}
        skill = add_skill(body.get("name", ""), body.get("description", ""),
                          body.get("steps") or [], body.get("agents"))
        return {"ok": True, "skill": skill}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/api/skills/{skill_id}")
async def api_skills_delete(skill_id: str):
    try:
        from agents.skills import remove_skill
        return {"ok": remove_skill(skill_id)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/skills/{skill_id}/toggle")
async def api_skills_toggle(skill_id: str):
    try:
        from agents.skills import toggle_skill
        s = toggle_skill(skill_id)
        return {"ok": s is not None, "skill": s}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.patch("/api/skills/{skill_id}/assign")
async def api_skills_assign(skill_id: str, body: dict = None):
    """Assign/unassign a skill to an agent: {agent, add}."""
    try:
        from agents.skills import assign_skill
        body = body or {}
        s = assign_skill(skill_id, body.get("agent", ""),
                         bool(body.get("add", True)))
        return {"ok": s is not None, "skill": s}
    except Exception as e:
        return {"ok": False, "error": str(e)}
