"""Interactive campaign state machine — one per WebSocket.

Owns the two blocking gates of the guided flow, mirroring how review.py owns
the email-review conversation:

  stage 2  campaign_checklist -> the browser renders an interactive checklist
  of the curated shortlist; the user ticks businesses and approves. Until that
  approval arrives, nothing downstream runs.

  stage 4  campaign_interview -> one targeted question per approved business;
  the user's answer tunes the angle of that business's email. When the last
  answer lands, drafting runs with the user's angles attached.

The heavy lifting (curation, PDFs, drafting, sending) lives in agents/campaign.py
and agents/workflows.py; this module only owns the conversation: which gate is
open, what the next question is, and when the user is allowed to proceed.
"""

import asyncio

# ws_id -> {"send": callable, "memory": ChatMemory, "ws_id": id}
_states: dict = {}


def active(ws_id) -> bool:
    """True while this socket owes the campaign a selection or an answer."""
    return ws_id in _states


def drop(ws_id) -> None:
    """Forget this socket's conversation (disconnect or cancel).

    The persistent campaign state in the session dir is NOT touched: a reload
    or a 'stop' must not destroy the shortlist or the angles already given.
    """
    _states.pop(ws_id, None)


def _gate_open(session_id: str) -> bool:
    """True while a durable campaign gate (checklist or interview) is open."""
    from agents.campaign import get_state
    return get_state(session_id).get("phase") in ("awaiting_selection", "interview")


async def maybe_resume(send, memory, ws_id) -> None:
    """Re-open the interactive conversation if a saved gate is waiting.

    The checklist/interview outlives any socket: a reload, a reconnect, or a
    campaign started from the CLI leaves the gate open on disk with nobody
    talking. Without this, the flow waits forever on a conversation that no
    longer exists.
    """
    from agents.web.web_session import current
    session = current()
    if not session.active or not _gate_open(session.id):
        return
    state = get_state_safe(session.id)
    if state.get("phase") == "awaiting_selection":
        _states[ws_id] = {"send": send, "memory": memory, "ws_id": ws_id}
        payload = campaign_checklist_payload(state)
        if payload.get("businesses"):
            # Re-render the card too: a resumed gate with only the jarvis
            # question gives the user nothing to click after a reload.
            await send({"type": "campaign_checklist", "data": payload})
        await begin(send, memory, ws_id, payload)
    elif state.get("phase") == "interview":
        from agents.campaign import current_question
        _states[ws_id] = {"send": send, "memory": memory, "ws_id": ws_id}
        q = current_question(state)
        await send({"type": "jarvis", "interview": True, "content": q})
        if memory is not None:
            memory.add_message("jarvis", q)


def get_state_safe(session_id: str) -> dict:
    from agents.campaign import get_state
    return get_state(session_id) or {}


def campaign_checklist_payload(state: dict) -> dict:
    return {
        "location": state.get("location", ""),
        "goal": state.get("goal", ""),
        "businesses": state.get("curated", []),
        "selected": state.get("selected", []),
    }


async def begin(send, memory, ws_id, checklist: dict) -> None:
    """Show the curated checklist and open the approval gate.

    Called by dispatch_bridge when a campaign action returns its result. The
    result-frame (campaign_checklist) renders the checklist card; this adds
    the blocking question so the user knows the flow is paused on them.
    """
    if not checklist or not checklist.get("businesses"):
        return
    _states[ws_id] = {"send": send, "memory": memory, "ws_id": ws_id}
    sel = len(checklist.get("selected", []) or [])
    msg = (f"{len(checklist['businesses'])} curated candidates for "
           f"{checklist.get('location') or 'your area'}. "
           "Tick the ones you want and press Approve — I will not draft or "
           "send anything until you confirm.")
    if sel:
        msg = f"{sel} businesses already approved. The interview can continue."
    await send({"type": "jarvis", "content": msg})
    if memory is not None:
        memory.add_message("jarvis", msg)


async def handle_action(send, data, memory, ws_id) -> None:
    """A campaign_checklist_action frame: the user approved their selection."""
    act = data.get("action", "approve")
    if act == "cancel":
        drop(ws_id)
        msg = "Campaign paused. The shortlist is saved — say 'campaign' to resume."
        await send({"type": "jarvis", "content": msg})
        if memory is not None:
            memory.add_message("jarvis", msg)
        return

    from agents.web.web_session import current
    from agents import campaign
    from agents.config import get_sender_name

    session = current()
    if not session.active:
        await send({"type": "error", "content": "No active session for this campaign."})
        return

    names = [str(n) for n in (data.get("selected") or []) if n]
    state = campaign.start_interview(session.id, names)
    if state.get("error"):
        await send({"type": "error", "content": state["error"]})
        return

    # Gate closed: the selection is locked, so this socket's conversation
    # moves on to the interview.
    drop(ws_id)

    # Stage 3: the initial PDF from the approved list (contact + phone).
    pdf_path = campaign.initial_report_pdf(state)
    if pdf_path:
        await send({"type": "jarvis",
                    "content": f"Initial report ready — click to download: {pdf_path}"})
    else:
        await send({"type": "jarvis",
                    "content": "Note: no contact sheet generated (no approved rows)."})

    selected = state.get("selected", [])
    if not selected:
        await send({"type": "error", "content": "No businesses selected."})
        return

    # Stage 4: open the 1-by-1 interview.
    _states[ws_id] = {"send": send, "memory": memory, "ws_id": ws_id}
    q = campaign.current_question(state)
    msg = (f"Approved {len(selected)} businesses. Quick tuning round — one "
           f"question per business so each email lands its own angle.\n\n{q}")
    await send({"type": "jarvis", "interview": True, "content": msg})
    if memory is not None:
        memory.add_message("jarvis", msg)


async def handle_text(user_msg: str, send, memory, ws_id) -> None:
    """Route free text by the phase of the open gate.

    The checklist phase speaks in button frames, so typed text only gets
    guidance; only the interview phase consumes text as an answer. Without
    this split, a resumed checklist would swallow 'status' as an interview
    answer and corrupt the gate state.
    """
    state = get_state_safe(current_session_id())
    if state.get("phase") == "awaiting_selection":
        msg = ("The campaign checklist is waiting for your picks — tick "
               "businesses in the panel and press Approve & Continue, or "
               "type 'stop' to pause the campaign.")
        await send({"type": "jarvis", "content": msg})
        if memory is not None:
            memory.add_message("jarvis", msg)
        return
    await handle_answer(user_msg, send, memory, ws_id)


def current_session_id():
    from agents.web.web_session import current
    s = current()
    return s.id if s.active else ""


async def handle_answer(user_msg: str, send, memory, ws_id) -> None:
    """An answer (or 'skip') for the business currently being interviewed.

    When the last answer lands, drafting runs with the collected angles and
    this socket's conversation ends.
    """
    from agents.web.web_session import current
    from agents import campaign
    from agents.config import get_sender_name
    from agents.workflows import complete_outreach

    session = current()
    if not session.active:
        drop(ws_id)
        await send({"type": "error", "content": "No active session for this campaign."})
        return

    state, done, question = campaign.answer_interview(session.id, user_msg)
    if not done and question:
        await send({"type": "jarvis", "interview": True, "content": question})
        if memory is not None:
            memory.add_message("jarvis", question)
        return

    # Interview over: drafting leg with the user's angles attached.
    drop(ws_id)
    await send({"type": "progress", "step": "draft",
                "message": "Researching approved businesses and drafting "
                           "personalized emails..."})

    selection = campaign.resolve_selection(
        session.load_data("search_results.json").get("no_website", []),
        state.get("selected", []),
    )
    if not selection:
        await send({"type": "error",
                    "content": "Could not match the approved names back to the "
                               "search results — run the campaign again."})
        return

    research = None
    try:
        from agents.workflows import research_workflow
        research = research_workflow(selection)
        session.save_research(research)
    except Exception as e:
        await send({"type": "jarvis",
                    "content": f"(research pass skipped: {e})"})

    angles = campaign.get_angles(session.id)
    result = await asyncio.to_thread(
        complete_outreach, selection, session.id, session.name or "",
        get_sender_name(), research, state.get("goal", ""), angles,
    )

    drafts = result.get("drafts", [])
    campaign.mark_drafted(session.id, state.get("initial_pdf", ""))
    n = len(drafts)
    if n:
        from agents.config import get_gmail_user
        gmail = get_gmail_user() or "the configured Gmail sender"
        msg = (f"Drafted {n} unique email(s), each tuned to its angle and "
               f"research. Say 'review emails' to edit, or 'send emails' to "
               f"send from {gmail}.")
        await send({"type": "jarvis", "content": msg})
        if memory is not None:
            memory.add_message("jarvis", msg)
        await send({"type": "draft_result", "data": {
            "count": n,
            "ai_used": result.get("ai_used", 0),
            "drafts": [
                {"business": (d.get("business") or {}).get("name", "?"),
                 "subject": d.get("subject", "?"),
                 "to": d.get("to", ""),
                 "exec_name": (d.get("business") or {}).get("exec_name", ""),
                 "exec_title": (d.get("business") or {}).get("exec_title", "")}
                for d in drafts
            ],
        }})
    else:
        errs = result.get("errors", [])
        detail = "; ".join(e.get("error", "") for e in errs[:3]) if errs else "no drafts produced"
        await send({"type": "error", "content": f"Drafting failed: {detail}"})
