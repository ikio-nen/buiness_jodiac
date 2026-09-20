"""Interactive email review: one state machine per WebSocket.

The browser reviews the session's drafts one card at a time and answers with
approve/skip. This module owns that state — which draft is showing, what the
user edited, and when the review is finished — so the socket loop only has to
recognize the message types and hand them over. Approved drafts are written
back to the session by the same code that presented them, which is what keeps
"review" from being a view concern.
"""

from pathlib import Path

# ws_id -> {"index": int, "drafts": [...]}
_states: dict = {}


def active(ws_id) -> bool:
    """True while this socket is in the middle of a review."""
    return ws_id in _states


def drop(ws_id) -> None:
    """Forget a socket's review (disconnect, cancel, or stray text)."""
    _states.pop(ws_id, None)


async def start(send, memory, ws_id):
    """Begin browser-based review of the session's drafts."""
    from agents.web.web_session import current
    session = current()
    data = session.load_data("email_drafts.json")
    drafts = data.get("drafts", [])
    if not drafts:
        msg = "No drafts to review. Draft emails first."
        await send({"type": "jarvis", "content": msg})
        memory.add_message("jarvis", msg)
        return

    _states[ws_id] = {"index": 0, "drafts": drafts}
    msg = f"Opening email review for {len(drafts)} draft(s)..."
    await send({"type": "jarvis", "content": msg})
    memory.add_message("jarvis", msg)
    await _send_card(send, ws_id)


async def handle_action(send, data, memory, ws_id):
    """Process an approve/skip answer for the current review card."""
    st = _states.get(ws_id)
    if not st:
        await send({
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
        await send({
            "type": "jarvis", "content": f"Approved: {name}.",
        })
    elif act == "skip":
        d["approved"] = False
        await send({
            "type": "jarvis", "content": f"Skipped: {name}.",
        })
    else:
        await send({
            "type": "jarvis",
            "content": "Unknown review action.",
        })
        return

    st["index"] += 1
    if st["index"] >= len(drafts):
        await _finish(send, memory, ws_id)
    else:
        await _send_card(send, ws_id)


async def _send_card(send, ws_id):
    """Send the current draft to the browser as an editable review card.

    Only ever called with a draft still in hand: ``start`` returns early on
    an empty list, and ``handle_action`` finishes the review instead of
    advancing past the end. That invariant is why there is no "past the end"
    branch here to get wrong.
    """
    st = _states.get(ws_id)
    if not st:
        return
    drafts = st["drafts"]
    idx = st["index"]
    if idx >= len(drafts):
        drop(ws_id)
        return

    d = drafts[idx]
    biz = (d.get("business") or {}).get("name") or d.get("business_name") or "Business"
    att = d.get("attachment") or d.get("attachment_path") or ""
    att_name = Path(att).name if att else ""
    await send({
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


async def _finish(send, memory, ws_id):
    """Persist approved drafts and summarize the review."""
    from agents.workflows import trim_draft_for_storage
    from agents.web.web_session import current
    st = _states.get(ws_id)
    if not st:
        return
    drafts = st["drafts"]
    approved = [d for d in drafts if d.get("approved") is True]
    skipped = len(drafts) - len(approved)

    session = current()
    session.save_data({"drafts": [trim_draft_for_storage(d) for d in drafts]},
                      "email_drafts.json")
    _states.pop(ws_id, None)

    await send({
        "type": "review_result",
        "data": {"approved": len(approved), "skipped": skipped, "total": len(drafts)},
    })
    msg = (f"Review complete: {len(approved)} approved, {skipped} skipped. "
           f"Say 'send emails' to send the approved ones.")
    await send({"type": "jarvis", "content": msg})
    if memory is not None:
        memory.add_message("jarvis", msg)
