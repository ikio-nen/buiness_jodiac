"""The live socket: one WebSocket per browser, and the message router.

This module owns *the conversation for one socket* — accept, subscribe to the
agent bus, route each incoming frame to the subsystem that owns it, and clean
up on disconnect. It owns no rules of its own: actions go to action_dispatch
through the bridge, queue policy to JobQueue, email review to review, and
intent parsing to the chatbot.

Routing order matters and is deliberate: review buttons, then queue
cancellation, then the interactive conversations (brainstorm, review) that
claim further messages, and only then intent parsing. Anything that arrives
while a conversation is open is an answer to it, not a new command.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents.web import review
from agents.web import campaign_ui
from agents.web.dispatch_bridge import run_action
from agents.web.job_queue import JobQueue
from agents.web.web_session import resume_latest

router = APIRouter()

# Per-socket brainstorm conversations (an interactive multi-turn wizard).
_brainstorm_sessions: dict = {}


async def _event_forwarder(websocket: WebSocket, ev_queue: asyncio.Queue):
    """Push live agent-events (from worker threads) to the browser.

    Runs as its own task so the chat loop can keep receiving while the
    Agent Ops floor gets real-time telemetry.
    """
    try:
        while True:
            ev = await ev_queue.get()
            await websocket.send_json({"type": "agent_event", "event": ev})
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


def _frame_sender(websocket: WebSocket):
    """A send that never raises, so a closed socket cannot kill real work.

    Pushing a frame to a browser that has gone away (reload, closed tab) used
    to raise out of the middle of an action chain: the remaining actions in
    that chain never ran and the job's work was lost with nothing on screen to
    say so. Frames are display; the pipeline must not depend on the display
    being alive — the same rule the event bus already follows.
    """
    async def send(frame) -> bool:
        try:
            await websocket.send_json(frame)
            return True
        except Exception:
            return False
    return send


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time chat with JARVIS."""
    await websocket.accept()
    ws_id = id(websocket)
    send = _frame_sender(websocket)
    session = resume_latest()

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
        # Work survives the tab that started it, so a new socket has to be
        # told when something is still in flight — otherwise the queue panel
        # is empty on a reconnect and the job looks lost.
        from agents.web.job_queue import running_labels
        still_running = running_labels()
        if still_running:
            welcome_content += ("\n\n⏳ Still running from another tab: "
                                + ", ".join(still_running)
                                + " — results will be saved when it finishes.")
        if briefing:
            welcome_content += "\n\n" + briefing
        await send({
            "type": "jarvis",
            "content": welcome_content,
            "session_id": session.id if session.active else None,
            "session_name": session.name if session.active else None,
            "profile": profile,
        })

        # ── Live agent telemetry: subscribe this socket to the event bus.
        # Events are emitted from worker threads, so hop into the loop.
        loop = asyncio.get_running_loop()
        ev_queue: asyncio.Queue = asyncio.Queue()

        def _on_bus_event(ev: dict):
            loop.call_soon_threadsafe(ev_queue.put_nowait, ev)

        from agents.event_bus import subscribe, recent as bus_recent
        unsub_events = subscribe(_on_bus_event)
        forwarder = asyncio.create_task(_event_forwarder(websocket, ev_queue))
        # Replay recent history so a reconnecting client re-syncs the floor.
        try:
            await send({"type": "agent_events_replay",
                        "events": bus_recent(40)})
        except Exception:
            pass

        async def _report_chain_error(e):
            try:
                await send({
                    "type": "error",
                    "content": f"Error: {type(e).__name__}: {e}",
                })
            except Exception:
                pass

        # The queue the QUEUE panel shows: one chain runs, the rest wait.
        queue = JobQueue(send, on_error=_report_chain_error)
        await queue.push_state()

        while True:
            session = resume_latest()
            data = await websocket.receive_json()
            msg_type = data.get("type", "chat")

            # ── Review button responses ─────────────────────────────
            if msg_type == "review_action":
                await review.handle_action(send, data, memory, ws_id)
                continue

            # ── Campaign checklist button (approve/cancel) ───────────
            if msg_type == "campaign_checklist_action":
                await campaign_ui.handle_action(send, data, memory, ws_id)
                continue

            if msg_type == "review_cancel":
                review.drop(ws_id)
                await send({
                    "type": "jarvis",
                    "content": "Email review cancelled.",
                })
                continue

            # ── Cancel a waiting job from the QUEUE panel ────────────
            if msg_type == "cancel_queued":
                cancelled = queue.cancel(data.get("id"))
                if cancelled:
                    await queue.push_state()
                    await send({
                        "type": "jarvis",
                        "content": f"Cancelled waiting job: {cancelled['label']}.",
                    })
                else:
                    # The button was rendered from an older frame and the job
                    # has already started (or finished). Say so: a click that
                    # silently does nothing reads as a broken button.
                    await send({
                        "type": "jarvis",
                        "content": "That job is no longer waiting — it has "
                                   "already started or finished.",
                    })
                continue

            user_msg = data.get("content", "").strip()
            if not user_msg:
                continue

            # Save user message
            memory.add_message("user", user_msg)

            # ── Attachment riding this message (composer attach button)
            # Stored on the session so the draft leg can put the file on the
            # emails it writes; acknowledged here so the user sees it landed.
            if data.get("attachment"):
                att_path = str(data["attachment"])
                att_name = str(data.get("attachment_name") or Path(att_path).name)
                try:
                    atts = session.load_attachments()
                    atts["__default__"] = att_path
                    session.save_attachments(atts)
                    note = f"Attached {att_name} to this session's emails."
                except Exception as e:
                    note = f"Could not save the attachment: {e}"
                await send({"type": "jarvis", "content": note})
                memory.add_message("jarvis", note)

            # ── Active campaign conversation (stage 2 or 4) ──────────
            # Claimed before intent parsing: an answer to the interview is
            # never a new command, the same rule the brainstorm follows.
            if not campaign_ui.active(ws_id):
                # A saved gate (checklist/interview) outlives its socket — a
                # reload or CLI-side start must still re-open the blocking
                # conversation, or the flow waits on nobody.
                await campaign_ui.maybe_resume(send, memory, ws_id)
            if campaign_ui.active(ws_id):
                if user_msg.lower() in ("exit", "quit", "stop", "cancel", "menu"):
                    campaign_ui.drop(ws_id)
                    await send({
                        "type": "jarvis",
                        "content": "Campaign interview paused. The approved list "
                                   "and angles are saved — say 'campaign' to resume.",
                    })
                    continue
                if not campaign_ui.consumes_text(campaign_ui.current_session_id(), user_msg):
                    # The gate doesn't own this text (a fresh campaign
                    # request, 'status', a question) — fall through to the
                    # intent parser. The conversation stays open so the
                    # gate's own vocabulary still lands in it.
                    pass
                else:
                    await campaign_ui.handle_text(user_msg, send, memory, ws_id)
                    continue

            # ── Active brainstorm conversation ───────────────────────
            if ws_id in _brainstorm_sessions:
                bs = _brainstorm_sessions[ws_id]
                if user_msg.lower() in ("exit", "quit", "done", "skip", "menu"):
                    del _brainstorm_sessions[ws_id]
                    await send({
                        "type": "jarvis",
                        "content": "Brainstorm paused. Say 'brainstorm' to continue.",
                    })
                    continue
                response = bs.process_answer(user_msg)
                if bs.complete:
                    del _brainstorm_sessions[ws_id]
                if response:
                    await send({
                        "type": "jarvis",
                        "content": response,
                    })
                if not bs.complete:
                    question = bs.get_current_question()
                    if question:
                        progress = bs.get_progress()
                        await send({
                            "type": "jarvis",
                            "content": progress + chr(10) + chr(10) + question,
                        })
                memory.add_message("jarvis", response or "Brainstorm complete!")
                continue

            # ── Active email review conversation ─────────────────────
            if review.active(ws_id):
                if user_msg.lower() in ("exit", "quit", "done", "skip",
                                        "cancel", "menu", "back"):
                    review.drop(ws_id)
                    await send({
                        "type": "jarvis",
                        "content": "Email review cancelled.",
                    })
                else:
                    await send({
                        "type": "jarvis",
                        "content": "Use the Approve / Skip buttons on the email "
                                   "above, or type 'cancel' to stop reviewing.",
                    })
                continue

            # Send thinking indicator
            await send({"type": "thinking"})

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
                await send({
                    "type": "jarvis", "content": content,
                    "action": at, "params": action.params,
                })
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.HELP:
                await send({"type": "jarvis", "content": HELP_TEXT})
                continue

            if action and action.type == ActionType.UNKNOWN:
                content = action.response or "I'm not sure what you mean."
                await send({"type": "jarvis", "content": content})
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.BRAINSTORM:
                from agents.brainstorm import BrainstormSession
                bs = BrainstormSession()
                _brainstorm_sessions[ws_id] = bs
                question = bs.get_current_question()
                progress = bs.get_progress()
                await send({
                    "type": "jarvis",
                    "content": progress + chr(10) + chr(10) + question,
                })
                memory.add_message("jarvis",
                                   action.response or "Let's set up your business profile!",
                                   action={"type": at, "params": action.params})
                continue

            if action and action.type == ActionType.REVIEW:
                await review.start(send, memory, ws_id)
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
                await send({
                    "type": "jarvis", "content": content,
                    "action": at, "params": action.params,
                })
                memory.add_message("jarvis", content,
                                   action={"type": at, "params": action.params})
                continue

            # ── Everything else runs through action_dispatch ─────────
            # Actions run in a background task so the office stays live:
            # you can keep chatting (status, ask scout, review) while a
            # search or team-act grinds. The per-socket gate keeps replies
            # in arrival order and chained actions atomic.
            if actions:
                label = ", ".join(a.type.value for a in actions)
                # Tell the user when their message will queue behind a long
                # action already running (search/draft/...), instead of it
                # vanishing silently for minutes.
                if queue.busy():
                    await send({
                        "type": "queued",
                        "message": f"Queued ({label}) — I'll run it when "
                                   "the current job finishes.",
                    })

                acts = list(actions)

                async def _run_chain():
                    for a in acts:
                        await run_action(a, send, session, memory, ws_id=ws_id)

                queue.enqueue(label, _run_chain)
                await queue.push_state()

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
            unsub_events()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        try:
            forwarder.cancel()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        _brainstorm_sessions.pop(ws_id, None)
        review.drop(ws_id)
        campaign_ui.drop(ws_id)
        try:
            from agents.chat_memory import close_memory
            close_memory()
        except Exception:
            pass
