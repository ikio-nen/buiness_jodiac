"""JARVIS Web Server -- FastAPI with WebSocket for real-time chat.

Run with:  python -m agents.web.server
Or from jarvis.py menu option [W].

All heavy actions (search/draft/send/research/sync/scrape/enrich) execute
through agents.action_dispatch, so the web UI and the CLI chat share exactly
the same behavior. Email review runs interactively in the browser:
the server sends each draft as a review_show card and the client answers
with review_action messages (approve/skip/cancel).
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure agents package is importable
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

# Per-WebSocket interactive state: brainstorm conversations and email reviews
_brainstorm_sessions = {}
_review_states = {}

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="JARVIS", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Web session (shared, resumed from disk) ────────────────────────────
_web_session = None


def _web_session_instance():
    global _web_session
    from agents.session import Session
    if _web_session is None:
        _web_session = Session()
    return _web_session


def _resume_latest_session():
    """Point the web session at the newest session on disk so the web UI and
    CLI keep working on the same data. Creates one if nothing exists yet."""
    from agents.session import list_sessions
    s = _web_session_instance()
    sessions = list_sessions()
    if sessions:
        latest = sessions[0]
        if s.id != latest["id"]:
            s.load(latest["id"], latest)
    elif not s.active:
        s.create(f"Web Project {datetime.now().strftime('%Y%m%d_%H%M%S')}")
    return s


# ── Static + API endpoints ─────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
async def api_status():
    """Return current session stats."""
    try:
        from agents.config import get_business_profile
        from agents import ai_engine
        s = _resume_latest_session()
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


@app.get("/api/history")
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


@app.get("/api/conversation/{conv_id}")
async def api_conversation(conv_id: int):
    """Return messages for a specific conversation."""
    try:
        from agents.chat_memory import ChatMemory
        mem = ChatMemory(conversation_id=conv_id)
        context = mem.get_context(100)
        mem.close()
        return {"messages": context}
    except Exception as e:
        return {"messages": [], "error": str(e)}


@app.post("/api/upload")
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


# ── WebSocket: real-time chat ──────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time chat with JARVIS."""
    await websocket.accept()
    ws_id = id(websocket)
    session = _resume_latest_session()

    try:
        from agents.config import get_business_profile
        from agents.chat_memory import get_memory
        from agents.chatbot import parse_intents, ActionType, HELP_TEXT

        profile = get_business_profile()
        memory = get_memory(session_id=session.id if session.active else "")

        # Send welcome (+ proactive agent briefing when there's something to say)
        try:
            from agents.proactive import auto_brief
            briefing = auto_brief()
        except Exception:
            briefing = ""
        welcome_content = "JARVIS online. What would you like to do?"
        if briefing:
            welcome_content += "\n\n" + briefing
        welcome = {
            "type": "jarvis",
            "content": welcome_content,
            "session_id": session.id if session.active else None,
            "session_name": session.name if session.active else None,
            "profile": profile,
        }
        await websocket.send_json(welcome)

        while True:
            session = _resume_latest_session()
            data = await websocket.receive_json()
            msg_type = data.get("type", "chat")

            # ── Review button responses ─────────────────────────────
            if msg_type == "review_action":
                await _handle_review_action(websocket, data, memory, ws_id)
                continue

            if msg_type == "review_cancel":
                _review_states.pop(ws_id, None)
                await websocket.send_json({
                    "type": "jarvis",
                    "content": "Email review cancelled.",
                })
                continue

            user_msg = data.get("content", "").strip()
            if not user_msg:
                continue

            # ── Active brainstorm conversation ───────────────────────
            if ws_id in _brainstorm_sessions:
                bs = _brainstorm_sessions[ws_id]
                if user_msg.lower() in ("exit", "quit", "done", "skip", "menu"):
                    del _brainstorm_sessions[ws_id]
                    await websocket.send_json({
                        "type": "jarvis",
                        "content": "Brainstorm paused. Say 'brainstorm' to continue.",
                    })
                    continue
                response = bs.process_answer(user_msg)
                if bs.complete:
                    del _brainstorm_sessions[ws_id]
                if response:
                    await websocket.send_json({
                        "type": "jarvis",
                        "content": response,
                    })
                if not bs.complete:
                    question = bs.get_current_question()
                    if question:
                        progress = bs.get_progress()
                        await websocket.send_json({
                            "type": "jarvis",
                            "content": progress + chr(10) + chr(10) + question,
                        })
                memory.add_message("jarvis", response or "Brainstorm complete!")
                continue

            # ── Active email review conversation ─────────────────────
            if ws_id in _review_states:
                if user_msg.lower() in ("exit", "quit", "done", "skip",
                                        "cancel", "menu", "back"):
                    _review_states.pop(ws_id, None)
                    await websocket.send_json({
                        "type": "jarvis",
                        "content": "Email review cancelled.",
                    })
                else:
                    await websocket.send_json({
                        "type": "jarvis",
                        "content": "Use the Approve / Skip buttons on the email "
                                   "above, or type 'cancel' to stop reviewing.",
                    })
                continue

            # Save user message
            memory.add_message("user", user_msg)

            # Send thinking indicator
            await websocket.send_json({"type": "thinking"})

            # Get conversation context for Gemini
            context = memory.get_context(10)
            profile = get_business_profile()
            session_state = session.get_session_state() if session.active else ""

            # Parse intent with session state. Multi-part messages return a
            # list of actions that run in order (e.g. "find emails for them
            # and draft an email for each" -> ENRICH then DRAFT).
            actions = parse_intents(user_msg, context=context, business_profile=profile,
                                    session_state=session_state)
            action = actions[0] if actions else None
            at = action.type.value if action else "unknown"

            # ── Lightweight intents handled inline ───────────────────
            if action and action.type == ActionType.GREETING:
                content = action.response
                await websocket.send_json({
                    "type": "jarvis", "content": content,
                    "action": at, "params": action.params,
                })
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.HELP:
                await websocket.send_json({"type": "jarvis", "content": HELP_TEXT})
                continue

            if action and action.type == ActionType.UNKNOWN:
                content = action.response or "I'm not sure what you mean."
                await websocket.send_json({"type": "jarvis", "content": content})
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.BRAINSTORM:
                from agents.brainstorm import BrainstormSession
                bs = BrainstormSession()
                _brainstorm_sessions[ws_id] = bs
                question = bs.get_current_question()
                progress = bs.get_progress()
                await websocket.send_json({
                    "type": "jarvis",
                    "content": progress + chr(10) + chr(10) + question,
                })
                memory.add_message("jarvis",
                                   action.response or "Let's set up your business profile!",
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.REVIEW:
                await _start_review(websocket, memory, ws_id)
                continue

            if action and action.type == ActionType.LIST_SESSIONS:
                from agents.session import list_sessions
                sessions = list_sessions()
                if sessions:
                    lines = [f"{i}. {s.get('name', 'Unnamed')}  ({s['id']})"
                             for i, s in enumerate(sessions[:10], 1)]
                    listing = chr(10).join(lines)
                else:
                    listing = "No sessions yet."
                content = (action.response + chr(10) + chr(10) + listing
                           if action.response else listing)
                await websocket.send_json({
                    "type": "jarvis", "content": content,
                    "action": at, "params": action.params,
                })
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            # ── Everything else runs through action_dispatch ─────────
            # Chained actions run in order; each pushes its own ack,
            # progress, and result messages to the browser.
            for chained in actions:
                await _run_dispatched(chained, websocket, session, memory)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"Error: {type(e).__name__}: {e}",
            })
        except Exception:
            pass
    finally:
        _brainstorm_sessions.pop(ws_id, None)
        _review_states.pop(ws_id, None)
        try:
            from agents.chat_memory import close_memory
            close_memory()
        except Exception:
            pass


# ── Action dispatch bridge ─────────────────────────────────────────────

# Types that run through dispatch but only report back with plain text
_PROGRESS_TEXT = {
    "search": "Running search pipeline (query, verify, scrape, enrich)...",
    "draft": "Researching businesses and drafting personalized emails...",
    "send": "Sending emails now...",
    "research": "Researching businesses with AI...",
    "sync": "Syncing to Obsidian vault...",
    "scrape": "Scraping business websites...",
    "enrich": "Looking up email addresses...",
}

_RESULT_KIND = {
    "search": "search_result",
    "draft": "draft_result",
    "send": "send_result",
    "research": "research_result",
}

_ACK_SKIP = {"status", "dashboard", "list_sessions"}


async def _run_dispatched(action, websocket, session, memory):
    """Execute an action through action_dispatch in a worker thread and
    push the result back to the browser in the UI's expected shapes."""
    from agents.action_dispatch import dispatch
    at = action.type.value
    ack = action.response or ""

    if ack and at not in _ACK_SKIP:
        await websocket.send_json({
            "type": "jarvis", "content": ack,
            "action": at, "params": action.params,
        })
        memory.add_message("jarvis", ack,
                           action={"type": at, "params": action.params})

    progress = _PROGRESS_TEXT.get(at)
    if progress:
        await websocket.send_json({"type": "progress", "step": at, "message": progress})

    try:
        result = await asyncio.to_thread(dispatch, action.type, action.params, session)
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": f"Error: {type(e).__name__}: {e}",
        })
        return

    content = result.get("message") or ("Done." if result.get("success")
                                        else "That didn't work.")
    if content:
        await websocket.send_json({
            "type": "jarvis", "content": content,
            "action": at, "params": action.params,
        })
        if content != ack:
            memory.add_message("jarvis", content,
                               action={"type": at, "params": action.params})

    kind = _RESULT_KIND.get(at) if result.get("success") else None
    if kind:
        payload = _shape_result(at, result.get("data") or {})
        if payload is not None:
            await websocket.send_json({"type": kind, "data": payload})


def _shape_result(at: str, data: dict):
    """Convert an action_dispatch result into the renderer payloads the
    front-end already understands."""
    if at == "search":
        businesses = data.get("businesses", [])
        return {
            "total": data.get("total", 0),
            "no_site_count": data.get("no_site", len(businesses)),
            "with_site_count": data.get("with_site", 0),
            "businesses": [
                {"name": b.get("name", "?"),
                 "category": b.get("category", "?"),
                 "address": b.get("address", "?"),
                 "has_website": bool(b.get("website"))}
                for b in businesses[:20]
            ],
        }
    if at == "draft":
        drafts = data.get("drafts", [])
        return {
            "count": len(drafts),
            "ai_used": data.get("ai_used", 0),
            "drafts": [
                {"business": (d.get("business") or {}).get("name", "?"),
                 "subject": d.get("subject", "?"),
                 "to": d.get("to", "")}
                for d in drafts
            ],
        }
    if at == "send":
        return {
            "sent": len(data.get("sent", [])),
            "errors": len(data.get("errors", [])),
            "skipped": len(data.get("skipped", [])),
        }
    if at == "research":
        results = data.get("results", [])
        return {
            "count": len(results),
            "results": [
                {"name": r.get("name", "?"),
                 "rating": r.get("rating", 0),
                 "review_count": r.get("review_count", 0),
                 "gaps": r.get("gaps", []),
                 "hooks": [r["email_hook"]] if r.get("email_hook") else []}
                for r in results
            ],
        }
    return None


# ── Interactive email review ───────────────────────────────────────────

async def _start_review(websocket, memory, ws_id):
    """Begin browser-based review of the session's drafts."""
    session = _web_session_instance()
    data = session.load_data("email_drafts.json")
    drafts = data.get("drafts", [])
    if not drafts:
        msg = "No drafts to review. Draft emails first."
        await websocket.send_json({"type": "jarvis", "content": msg})
        memory.add_message("jarvis", msg)
        return

    _review_states[ws_id] = {"index": 0, "drafts": drafts}
    msg = f"Opening email review for {len(drafts)} draft(s)..."
    await websocket.send_json({"type": "jarvis", "content": msg})
    memory.add_message("jarvis", msg)
    await _send_review_card(websocket, ws_id)


async def _send_review_card(websocket, ws_id):
    """Send the current draft to the browser as an editable review card."""
    st = _review_states.get(ws_id)
    if not st:
        return
    drafts = st["drafts"]
    idx = st["index"]
    if idx >= len(drafts):
        await _finish_review(websocket, ws_id)
        return

    d = drafts[idx]
    biz = (d.get("business") or {}).get("name") or d.get("business_name") or "Business"
    att = d.get("attachment") or d.get("attachment_path") or ""
    att_name = Path(att).name if att else ""
    await websocket.send_json({
        "type": "review_show",
        "index": idx,
        "total": len(drafts),
        "business": biz,
        "to": d.get("to", ""),
        "subject": d.get("subject", ""),
        "body": d.get("body", ""),
        "attachment_name": att_name,
        "ai_powered": bool(d.get("ai_powered")),
    })


async def _handle_review_action(websocket, data, memory, ws_id):
    """Process an approve/skip answer for the current review card."""
    st = _review_states.get(ws_id)
    if not st:
        await websocket.send_json({
            "type": "jarvis",
            "content": "No active email review.",
        })
        return

    if int(data.get("index", -1)) != st["index"]:
        return  # stale button press, ignore

    drafts = st["drafts"]
    d = drafts[st["index"]]
    name = (d.get("business") or {}).get("name") or d.get("business_name") or "Email"
    act = data.get("action")

    if act == "approve":
        subject = (data.get("subject") or "").strip()
        if subject:
            d["subject"] = subject
        body = data.get("body")
        if body is not None:
            d["body"] = body
        d["approved"] = True
        if data.get("attachment"):
            d["attachment"] = data["attachment"]
        await websocket.send_json({
            "type": "jarvis", "content": f"Approved: {name}.",
        })
    elif act == "skip":
        d["approved"] = False
        await websocket.send_json({
            "type": "jarvis", "content": f"Skipped: {name}.",
        })
    else:
        await websocket.send_json({
            "type": "jarvis",
            "content": "Unknown review action.",
        })
        return

    st["index"] += 1
    if st["index"] >= len(drafts):
        await _finish_review(websocket, memory, ws_id)
    else:
        await _send_review_card(websocket, ws_id)


async def _finish_review(websocket, memory, ws_id):
    """Persist approved drafts and summarize the review."""
    from agents.workflows import trim_draft_for_storage
    st = _review_states.get(ws_id)
    if not st:
        return
    drafts = st["drafts"]
    approved = [d for d in drafts if d.get("approved") is True]
    skipped = len(drafts) - len(approved)

    session = _web_session_instance()
    session.save_data({"drafts": [trim_draft_for_storage(d) for d in drafts]},
                      "email_drafts.json")
    _review_states.pop(ws_id, None)

    await websocket.send_json({
        "type": "review_result",
        "data": {"approved": len(approved), "skipped": skipped, "total": len(drafts)},
    })
    msg = (f"Review complete: {len(approved)} approved, {skipped} skipped. "
           f"Say 'send emails' to send the approved ones.")
    await websocket.send_json({"type": "jarvis", "content": msg})
    memory.add_message("jarvis", msg)


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the JARVIS web server."""
    import uvicorn
    print(f"\n  JARVIS Web Server starting on http://{host}:{port}")
    print(f"  Open your browser to start chatting!\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
