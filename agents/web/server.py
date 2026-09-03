"""JARVIS Web Server -- FastAPI with WebSocket for real-time chat.

Run with:  python -m agents.web.server
Or from jarvis.py menu option [W].
"""
import asyncio
import json
import sys
import os
from pathlib import Path

# Ensure agents package is importable
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="JARVIS", docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/status")
async def api_status():
    """Return current session stats."""
    try:
        from agents.session import Session
        from agents.config import get_business_profile
        s = Session()
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
            "ai_configured": bool(os.environ.get("GEMINI_API_KEY")),
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time chat with JARVIS."""
    await websocket.accept()

    try:
        from agents.session import Session
        from agents.config import get_business_profile
        from agents.chat_memory import ChatMemory, get_memory
        from agents.chatbot import parse_intent, ActionType, HELP_TEXT

        session = Session()
        profile = get_business_profile()
        memory = get_memory(session_id=session.id if session.active else "")

        # Send welcome
        welcome = {
            "type": "jarvis",
            "content": "JARVIS online. What would you like to do?",
            "session_id": session.id if session.active else None,
            "profile": profile,
        }
        await websocket.send_json(welcome)

        while True:
            data = await websocket.receive_json()
            user_msg = data.get("content", "").strip()

            if not user_msg:
                continue

            # Save user message
            memory.add_message("user", user_msg)

            # Send thinking indicator
            await websocket.send_json({"type": "thinking"})

            # Get conversation context for Gemini
            context = memory.get_context(10)
            profile = get_business_profile()
            session_state = session.get_session_state() if session.active else ""

            # Parse intent with session state
            action = parse_intent(user_msg, context=context, business_profile=profile,
                                 session_state=session_state)

            # Save JARVIS response
            if action.response:
                memory.add_message("jarvis", action.response, action={"type": action.type.value, "params": action.params})

            # Build response
            response = {
                "type": "jarvis",
                "action": action.type.value,
                "params": action.params,
            }

            if action.type == ActionType.GREETING:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.HELP:
                response["content"] = HELP_TEXT
                await websocket.send_json(response)

            elif action.type == ActionType.SEARCH:
                response["content"] = action.response
                await websocket.send_json(response)

                # Execute search in background
                result = await _run_search(action.params, session, websocket)
                if result:
                    response["result"] = result
                    await websocket.send_json({
                        "type": "search_result",
                        "data": result,
                    })

            elif action.type == ActionType.DRAFT:
                response["content"] = action.response
                await websocket.send_json(response)

                result = await _run_draft(action.params, session, websocket)
                if result:
                    await websocket.send_json({
                        "type": "draft_result",
                        "data": result,
                    })

            elif action.type == ActionType.SEND:
                response["content"] = action.response
                await websocket.send_json(response)

                result = await _run_send(session, websocket)
                if result:
                    await websocket.send_json({
                        "type": "send_result",
                        "data": result,
                    })

            elif action.type == ActionType.RESEARCH:
                response["content"] = action.response
                await websocket.send_json(response)
                result = await _run_research(session, websocket)
                if result:
                    await websocket.send_json({
                        "type": "research_result",
                        "data": result,
                    })

            elif action.type == ActionType.REVIEW:
                response["content"] = "Opening email review..."
                await websocket.send_json(response)

            elif action.type == ActionType.STATUS:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.DASHBOARD:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.SYNC:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.SCRAPE:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.ENRICH:
                response["content"] = action.response
                await websocket.send_json(response)

            elif action.type == ActionType.LIST_SESSIONS:
                response["content"] = action.response
                await websocket.send_json(response)

            else:
                response["content"] = action.response or "I'm not sure what you mean."
                await websocket.send_json(response)

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
        try:
            from agents.chat_memory import close_memory
            close_memory()
        except Exception:
            pass


async def _run_search(params: dict, session, websocket) -> dict:
    """Execute search in thread to avoid blocking."""
    location = params.get("location", "")
    radius = params.get("radius", 2000)
    category = params.get("category", "")

    if not location:
        await websocket.send_json({
            "type": "jarvis",
            "content": "Where should I search? Give me a city or area.",
        })
        return None

    try:
        from agents.workflows import run_outreach_pipeline
        from agents.config import get_sender_name

        sender = get_sender_name()
        await websocket.send_json({
            "type": "progress",
            "step": "search",
            "message": f"Geocoding {location}...",
        })

        result = await asyncio.to_thread(
            run_outreach_pipeline, location, radius,
            session.id if session.active else "",
            session.name if session.active else "",
            sender,
            category=category,
        )

        if session.active:
            session.save_data({
                "location": location,
                "radius": radius,
                "businesses": result.get("businesses", []),
                "no_website": result.get("no_site", []),
            }, "search_results.json")

        no_site = result.get("no_site", [])
        return {
            "total": result.get("search", {}).get("total", 0),
            "no_site_count": len(no_site),
            "with_site_count": result.get("search", {}).get("with_site", 0),
            "businesses": [
                {"name": b.get("name", "?"), "category": b.get("category", "?"),
                 "address": b.get("address", "?"), "has_website": bool(b.get("website"))}
                for b in no_site[:20]
            ],
        }
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": f"Search error: {e}",
        })
        return None


async def _run_draft(params: dict, session, websocket) -> dict:
    """Execute draft in thread."""
    selection = params.get("selection", "all")

    try:
        data = session.load_data("search_results.json") if session.active else {}
        businesses = data.get("no_website", data.get("businesses", []))

        if not businesses:
            await websocket.send_json({
                "type": "jarvis",
                "content": "No businesses to draft for. Search first.",
            })
            return None

        from agents.workflows import select_businesses_workflow, complete_outreach
        from agents.config import get_sender_name

        selected = select_businesses_workflow(businesses, selection)
        if not selected:
            await websocket.send_json({
                "type": "jarvis",
                "content": "No businesses selected.",
            })
            return None

        sender = get_sender_name()
        await websocket.send_json({
            "type": "progress",
            "step": "draft",
            "message": f"Drafting {len(selected)} emails...",
        })

        result = await asyncio.to_thread(
            complete_outreach, selected,
            session.id if session.active else "",
            session.name if session.active else "",
            sender,
        )

        drafts = result.get("drafts", [])
        return {
            "count": len(drafts),
            "ai_used": result.get("ai_used", 0),
            "drafts": [
                {
                    "business": d.get("business", {}).get("name", "?"),
                    "subject": d.get("subject", "?"),
                    "to": d.get("to", ""),
                }
                for d in drafts
            ],
        }
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": f"Draft error: {e}",
        })
        return None


async def _run_send(session, websocket) -> dict:
    """Execute send in thread."""
    try:
        data = session.load_data("email_drafts.json") if session.active else {}
        drafts = data.get("drafts", [])
        has_email = [d for d in drafts if d.get("to")]

        if not has_email:
            await websocket.send_json({
                "type": "jarvis",
                "content": "No emails with addresses to send. Draft and enrich first.",
            })
            return None

        from agents.workflows import send_emails_workflow
        from agents.config import get_sender_name

        sender = get_sender_name()
        await websocket.send_json({
            "type": "progress",
            "step": "send",
            "message": f"Sending {len(has_email)} emails...",
        })

        result = await asyncio.to_thread(
            send_emails_workflow, has_email, sender,
        )

        sent = result.get("sent", [])
        errors = result.get("errors", [])
        return {
            "sent": len(sent),
            "errors": len(errors),
            "skipped": len(result.get("skipped", [])),
        }
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": f"Send error: {e}",
        })
        return None


async def _run_research(session, websocket) -> dict:
    """Execute research in thread."""
    try:
        data = session.load_data("search_results.json") if session.active else {}
        businesses = data.get("no_website", data.get("businesses", []))

        if not businesses:
            await websocket.send_json({
                "type": "jarvis",
                "content": "No businesses to research. Search first.",
            })
            return None

        from agents.workflows import research_workflow

        await websocket.send_json({
            "type": "progress",
            "step": "research",
            "message": f"Researching {len(businesses)} businesses...",
        })

        results = await asyncio.to_thread(research_workflow, businesses)

        return {
            "count": len(results),
            "results": [
                {
                    "name": r.get("name", "?"),
                    "rating": r.get("rating", "N/A"),
                    "review_count": r.get("review_count", 0),
                    "gaps": r.get("gaps", []),
                    "hooks": r.get("hooks", []),
                }
                for r in results
            ],
        }
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "content": f"Research error: {e}",
        })
        return None


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the JARVIS web server."""
    import uvicorn
    print(f"\n  JARVIS Web Server starting on http://{host}:{port}")
    print(f"  Open your browser to start chatting!\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
