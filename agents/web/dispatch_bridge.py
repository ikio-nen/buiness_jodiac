"""Bridge between a parsed action and the browser.

One action, one behavior: run it through ``agents.action_dispatch`` in a worker
thread (so the socket stays free) and translate the result into the frames the
UI already understands — acknowledgment, progress, chat reply, and finally the
typed renderer payload. Progress lines, result-frame kinds and ack-skip all
come from the action registry, so the web layer never keeps its own copy of
that policy.

``shape_result`` is the presentation half: it converts a dispatch result into
the payload each renderer expects. It lives here, next to the thing that sends
it, rather than in the assembly module.
"""

import asyncio

from agents.action_registry import progress_for, result_kind_for, skip_ack_for


async def run_action(action, send, session, memory, ws_id=None):
    """Execute one action and push every frame it produces.

    ``ws_id`` identifies the socket, so interactive conversations (campaign
    checklist, interview) can attach to the right client.
    """
    from agents.action_dispatch import dispatch
    at = action.type.value
    ack = action.response or ""

    if ack and not skip_ack_for(at):
        await send({
            "type": "jarvis", "content": ack,
            "action": at, "params": action.params,
        })
        memory.add_message("jarvis", ack,
                           action={"type": at, "params": action.params})

    progress = progress_for(at)
    if progress:
        await send({"type": "progress", "step": at, "message": progress})

    try:
        result = await asyncio.to_thread(dispatch, action.type, action.params, session)
    except Exception as e:
        await send({
            "type": "error",
            "content": f"Error: {type(e).__name__}: {e}",
        })
        return

    content = result.get("message") or ("Done." if result.get("success")
                                        else "That didn't work.")
    if content:
        await send({
            "type": "jarvis", "content": content,
            "action": at, "params": action.params,
        })
        if content != ack:
            memory.add_message("jarvis", content,
                               action={"type": at, "params": action.params})

    kind = result_kind_for(at) if result.get("success") else None
    if kind:
        payload = shape_result(at, result.get("data") or {})
        if payload is not None:
            await send({"type": kind, "data": payload})

    # A campaign action ends at the approval gate: hand the checklist to the
    # interactive conversation so the flow blocks until the user approves.
    if at == "campaign" and result.get("success"):
        from agents.web import campaign_ui
        checklist = (result.get("data") or {}).get("campaign_checklist") or {}
        await campaign_ui.begin(send, memory, ws_id, checklist)


def _count(value, fallback: int = 0) -> int:
    """Coerce a count that may arrive as an int or as the LIST it counts.

    action_dispatch's payload carries ints (len(no_site)), while the raw
    pipeline report carries lists under the same names. A shape assumption here
    once took out the whole result frame — len() on an int raises TypeError, the
    socket reports "object of type 'int' has no len()", and the search card
    never renders even though the search itself succeeded.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple, dict, set)):
        return len(value)
    return fallback


def shape_result(at: str, data: dict):
    """Convert an action_dispatch result into the renderer payloads the
    front-end already understands."""
    if at == "search":
        businesses = data.get("businesses") or []
        total = _count(data.get("total"), len(businesses))
        return {
            "total": total,
            # found_raw is the pre-filter scene count; fall back to total so an
            # older payload still renders a sane number.
            "found_raw": _count(data.get("found_raw"), total),
            "no_site_count": _count(data.get("no_site")),
            "with_site_count": _count(data.get("with_site")),
            "targets_count": _count(data.get("targets_count"), len(businesses)),
            "website_focus": data.get("website_focus"),
            "filter_report": data.get("filter_report", "") or "",
            "icp": data.get("icp") or {},
            "source": data.get("source", "osm"),
            "businesses": [
                {"name": b.get("name", "?"),
                 "category": b.get("category", "?"),
                 "address": b.get("address", "?"),
                 "fit": (b.get("icp") or {}).get("fit", ""),
                 "fit_score": (b.get("icp") or {}).get("fit_score", 0),
                 "institution_type": (b.get("icp") or {}).get("institution_type", ""),
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
                 "to": d.get("to", ""),
                 "exec_name": (d.get("business") or {}).get("exec_name", ""),
                 "exec_title": (d.get("business") or {}).get("exec_title", "")}
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
    if at == "campaign":
        # The checklist card is the renderer for this frame; without this
        # branch the browser got an empty {} and never showed the gate.
        return data.get("campaign_checklist") or None
    return None
