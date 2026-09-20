"""Guided campaign mode — the 6-stage flow, end to end.

Stage map (what this module owns vs. what already exists):
  1. Discover & curate   -> curate_workflow()      (search + ICP + top-N)
  2. Web checklist       -> checklist_payload() / start_selection()  (BLOCKS here)
  3. Initial PDF         -> initial_report_pdf()   (emails + phones of the picks)
  4. 1-by-1 brainstorm   -> start_interview() / answer_interview()   (BLOCKS per business)
  5. Draft               -> workflows.complete_outreach(angle=...)   (existing leg)
  6. Send + final PDF    -> send_emails_workflow + final_report_pdf()

State lives in the session dir (campaign_state.json) so the office survives a
reload, exactly like search_results.json and email_drafts.json.
"""

import threading
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from agents.config import REPORTS_DIR, load_session_data, save_session_data

STATE_FILE = "campaign_state.json"


# ── Session state ──────────────────────────────────────────────────────

def _state(session_id: str) -> dict:
    return load_session_data(session_id, STATE_FILE)


def _save(session_id: str, state: dict) -> None:
    save_session_data(session_id, state, STATE_FILE)


def _mutate(session_id: str, fn) -> dict:
    """Read-modify-write one gate state under the campaign lock.

    The checklist handler, the interview answers and a CLI 'send' can all
    touch the same state file; without the lock, two of them can interleave
    and the later write silently discards the earlier one's progress.
    """
    with _STATE_LOCK:
        state = _state(session_id)
        state = fn(state) or state
        _save(session_id, state)
        return state


_STATE_LOCK = threading.Lock()


def get_state(session_id: str) -> dict:
    return _state(session_id)


def reset(session_id: str) -> None:
    _save(session_id, {})


# ── Stage 1: discover + curate ────────────────────────────────────────

def curate_workflow(location: str, radius: int, category: str, goal: str,
                    sender: str, session_id: str, session_name: str,
                    want: int = 10) -> dict:
    """Run the existing search pipeline, then curate the best `want` leads.

    Returns {curated, report} or {error}. The full search result is stored in
    search_results.json by the caller, so every downstream consumer (draft,
    send, enrich, status) keeps working unchanged — curation is a VIEW on the
    same data, not a fork of it.
    """
    from agents.workflows import run_outreach_pipeline

    if not location:
        return {"error": "No location provided."}

    report = run_outreach_pipeline(
        location, radius, session_id, session_name, sender,
        category=category, goal=goal,
    )
    if report.get("errors"):
        return {"error": "; ".join(e.get("error", "") for e in report["errors"])}

    businesses = report.get("businesses", [])
    ranked = _rank_businesses(businesses, report.get("search", {}).get("goal", ""))
    curated = ranked[:want]

    try:
        from agents.event_bus import emit
        emit("bot", bot="scout", status="done",
             task=f"Curated {len(curated)} of {len(ranked)} candidates",
             source="campaign")
        emit("packet", from_="scout", to="strategist", label="shortlist")
    except Exception:
        pass

    return {"curated": curated, "report": report}


def _rank_businesses(businesses: list[dict], goal: str) -> list[dict]:
    """Deterministic curation score. The ICP verdict is authoritative; the
    tiebreakers are contactability (we can actually reach them) and proof of
    operating (reviews say the business is real and active)."""
    def score(b: dict) -> tuple:
        icp = b.get("icp") or {}
        rank = {"fits": 0, "plausible": 1, "unlikely": 2}.get(icp.get("fit"), 1)
        has_email = 0 if (b.get("email") or b.get("maps_email")) else 1
        has_phone = 0 if (b.get("phone") or b.get("maps_phone")) else 1
        try:
            reviews = int(b.get("review_count") or 0)
        except (TypeError, ValueError):
            reviews = 0
        return (rank, has_email, has_phone, -reviews, b.get("name", "").lower())

    return sorted(businesses, key=score)


def _display(b: dict) -> dict:
    """The slim shape the browser checklist and PDFs render."""
    return {
        "name": b.get("name", "?"),
        "category": b.get("category", ""),
        "address": b.get("address", "") or b.get("city", ""),
        "email": b.get("email") or b.get("maps_email") or "",
        "phone": b.get("phone") or b.get("maps_phone") or "",
        "website": b.get("website", ""),
        "rating": b.get("rating"),
        "review_count": b.get("review_count"),
        "fit": (b.get("icp") or {}).get("fit", "plausible"),
        "fit_score": (b.get("icp") or {}).get("fit_score", 0),
        "type": (b.get("icp") or {}).get("institution_type", ""),
    }


def checklist_payload(state: dict) -> dict:
    """Frame payload for the interactive checklist."""
    return {
        "location": state.get("location", ""),
        "goal": state.get("goal", ""),
        "businesses": state.get("curated", []),
        "selected": state.get("selected", []),
    }


# ── Stage 2: checklist approval (the BLOCKING gate) ───────────────────

def start_selection(session_id: str, location: str, radius: int,
                    category: str, goal: str, curated: list[dict]) -> dict:
    """Enter stage 2: store the shortlist and wait for the user's picks."""
    state = {
        "phase": "awaiting_selection",
        "location": location, "radius": radius,
        "category": category, "goal": goal,
        "curated": [_display(b) for b in curated],
        "names": [b.get("name", "?") for b in curated],
        "selected": [], "drafted": False, "sent": False,
        "interview": None, "angles": {},
        "started": datetime.now().isoformat(),
    }
    _save(session_id, state)
    return state


def start_interview(session_id: str, selection: list[str]) -> dict:
    """Approve the checklist picks and enter the 1-by-1 interview (stage 4)."""
    state = _state(session_id)
    if not state or not state.get("curated"):
        return {"error": "No campaign in progress. Run one first."}
    if not selection:
        return {"error": "No businesses selected — tick at least one."}

    # Honor only names that are actually on the shortlist; anything else is a
    # stale checkbox from an older render, not a business we curated.
    # 'curated' is the single source of truth (it also feeds the checklist
    # card), so approval always matches what the user actually saw — the
    # parallel 'names' key can go stale after state edits/resumes.
    known = [(b.get("name", "") or "").lower() for b in state.get("curated", [])]
    if not known:
        known = [n.lower() for n in state.get("names", [])]
    picked = [n for n in selection if n.lower() in known]
    if not picked:
        return {"error": "None of the selected businesses are on the current shortlist."}

    state["phase"] = "interview"
    state["selected"] = picked
    state["interview"] = {"index": 0, "answers": {}}
    _save(session_id, state)

    try:
        from agents.event_bus import emit
        emit("step", phase="select", message=f"Approved {len(picked)} businesses", done=True)
    except Exception:
        pass
    return state


def current_question(state: dict) -> str:
    """The interview question for the business at the cursor."""
    sel = state.get("selected", [])
    i = (state.get("interview") or {}).get("index", 0)
    if i >= len(sel):
        return ""
    name = sel[i]
    total = len(sel)
    return (f"[{i + 1}/{total}] {name}\n"
            f"Any angle for THIS one? A pain point to lead with, a detail to "
            f"open with, the tone you want — or type 'skip' and I'll decide "
            f"from their reviews and footprint.")


def answer_interview(session_id: str, answer: str) -> tuple[dict, bool, str]:
    """Record one answer. Returns (state, done, question_for_next).

    'skip' / 'you decide' means: no constraint, research decides the angle.
    """
    state = _state(session_id)
    iv = state.get("interview") or {}
    sel = state.get("selected", [])
    i = iv.get("index", 0)
    if i >= len(sel):
        # Already completed (double-send, reconnect replay): promote any
        # answers one more time but never wipe stored angles — the original
        # completion may have carried user work.
        state["phase"] = "drafting"
        if iv.get("answers"):
            state["angles"] = dict(iv["answers"])
        state["interview"] = None
        _save(session_id, state)
        return state, True, ""

    name = sel[i]
    text = (answer or "").strip()
    if text.lower() in ("skip", "you decide", "up to you", "nothing", "-"):
        text = ""
    if text:
        iv.setdefault("answers", {})[name] = text[:600]
    iv["index"] = i + 1
    state["interview"] = iv

    if iv["index"] >= len(sel):
        state["phase"] = "drafting"
        # Merge, never replace: a stale replica (resumed after completion)
        # carries empty answers and must not wipe angles already given.
        if iv.get("answers"):
            state["angles"] = {**state.get("angles", {}), **iv["answers"]}
        state["interview"] = None
        _save(session_id, state)
        return state, True, ""

    _save(session_id, state)
    return state, False, current_question(state)


def initial_report_for(session_id: str) -> str:
    """Path of the current campaign's initial PDF, if one was generated."""
    return (_state(session_id) or {}).get("initial_pdf", "")


def get_angles(session_id: str) -> dict:
    """name -> user angle note for the selected businesses (stage 4 output)."""
    state = _state(session_id)
    iv = (state or {}).get("interview") or {}
    return dict(iv.get("answers", {})) or dict((state or {}).get("angles", {}))

def mark_drafted(session_id: str, pdf_path: str) -> None:
    def _apply(state: dict) -> dict:
        if state:
            state["phase"] = "drafted"
            state["drafted"] = True
            state["initial_pdf"] = pdf_path
        return state
    _mutate(session_id, _apply)


def mark_sent(session_id: str) -> None:
    def _apply(state: dict) -> dict:
        if state:
            state["phase"] = "sent"
            state["sent"] = True
        return state
    _mutate(session_id, _apply)


def angles_context(angles: dict, businesses: list[dict]) -> str:
    """Per-business user angle notes as drafting context (empty when none)."""
    if not angles:
        return ""
    lines = ["--- User's angle notes for this run (follow these) ---"]
    for b in businesses:
        note = angles.get(b.get("name", ""))
        if note:
            lines.append(f"{b.get('name', '?')}: {note}")
    return "\n".join(lines) if len(lines) > 1 else ""


def resolve_selection(businesses: list[dict], names: list[str]) -> list[dict]:
    """Full business records for the approved names, preserving shortlist order."""
    wanted = {n.lower() for n in names}
    return [b for b in businesses if (b.get("name", "") or "").lower() in wanted]


# ── PDF rendering helpers ─────────────────────────────────────────────

def _latin1(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _banner(pdf: FPDF, title: str, subtitle: str) -> None:
    pdf.set_fill_color(122, 154, 104)          # moss
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_text_color(255, 248, 236)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_y(8)
    pdf.cell(0, 10, _latin1(title), align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_y(19)
    pdf.cell(0, 6, _latin1(subtitle), align="C")
    pdf.set_text_color(33, 33, 33)


def _stamp(pdf: FPDF) -> None:
    pdf.set_y(-14)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 6, "Generated by Jodiax outreach - "
             + datetime.now().strftime("%Y-%m-%d %H:%M"), align="C")


def _report_path(prefix: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"


# ── Stage 3: the initial report ───────────────────────────────────────

def initial_report_pdf(state: dict) -> str:
    """One PDF with every approved business: contact + phone + fit.

    Saved under agent_output/reports/campaign_initial_<ts>.pdf. Returns the
    path (empty string when nothing was approved, so no empty file is left).
    """
    businesses = state.get("curated", [])
    selected = set(n.lower() for n in state.get("selected", []))
    rows = [b for b in businesses if (b.get("name", "") or "").lower() in selected]
    if not rows:
        return ""

    path = _report_path("campaign_initial")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    goal = state.get("goal") or "outreach"
    _banner(pdf, "Campaign Targets - Initial Report",
            f"{len(rows)} approved businesses - goal: {goal}")

    y = 38
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(14, y)
    pdf.multi_cell(180, 5, _latin1(
        f"Location: {state.get('location', '-')}   |   Approved: "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}   |   "
        f"Phones and emails below are the current contact file for this campaign."))
    y = pdf.get_y() + 4

    pdf.set_fill_color(233, 223, 200)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(14, y)
    for w, t in ((8, "#"), (52, "Business"), (34, "Category"), (48, "Email"),
                 (30, "Phone"), (16, "Fit")):
        pdf.cell(w, 7, _latin1(t), border=1, fill=True)
    y += 7

    pdf.set_font("Helvetica", "", 9)
    for i, b in enumerate(rows, 1):
        if y > 265:
            pdf.add_page()
            y = 20
        pdf.set_xy(14, y)
        pdf.cell(8, 7, str(i), border=1)
        pdf.cell(52, 7, _latin1(b.get("name", "?"))[:44], border=1)
        pdf.cell(34, 7, _latin1(b.get("category", ""))[:28], border=1)
        pdf.cell(48, 7, _latin1(b.get("email", "-") or "-")[:34], border=1)
        pdf.cell(30, 7, _latin1(b.get("phone", "") or "-")[:20], border=1)
        pdf.cell(16, 7, _latin1(str(b.get("fit_score", ""))), border=1)
        y += 7

    # Contact sheet: one block per business so nothing is squeezed in columns.
    y += 8
    for b in rows:
        if y > 250:
            pdf.add_page()
            y = 20
        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(33, 33, 33)
        pdf.cell(0, 7, _latin1(b.get("name", "?")))
        y += 7
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(70, 70, 70)
        detail = (f"Category: {b.get('category', '-') or '-'}   |   "
                  f"Email: {b.get('email', '-') or '-'}   |   "
                  f"Phone: {b.get('phone', '-') or '-'}")
        if b.get("website"):
            detail += f"   |   Web: {b['website']}"
        pdf.set_x(14)
        pdf.multi_cell(180, 5, _latin1(detail))
        y = pdf.get_y() + 3

    _stamp(pdf)
    pdf.output(str(path))
    return str(path)


# ── Stage 6: the final report ─────────────────────────────────────────

def final_report_pdf(sent_records: list[dict], errors: list[dict],
                     skipped_count: int, session_name: str = "") -> str:
    """Execution summary: recipient, subject, timestamp, status per email.

    Saved under agent_output/reports/campaign_final_<ts>.pdf.
    """
    path = _report_path("campaign_final")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    title = "Campaign Final Report"
    if session_name:
        title += f" - {session_name}"
    _banner(pdf, title,
            f"{len(sent_records)} sent - {len(errors)} failed - {skipped_count} skipped")

    y = 38
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(33, 33, 33)
    pdf.set_xy(14, y)
    pdf.cell(0, 6, f"Execution summary - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y += 9

    records = list(sent_records)
    for e in errors:
        records.append({"business": {"name": e.get("name", "?")},
                        "to": "-", "subject": "-", "timestamp": "",
                        "error": e.get("error", "unknown")})

    if not records:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_xy(14, y)
        pdf.multi_cell(180, 6, _latin1("No emails were executed in this run."))
        _stamp(pdf)
        pdf.output(str(path))
        return str(path)

    for rec in records:
        if y > 240:
            pdf.add_page()
            y = 20
        biz = rec.get("business") or {}
        name = biz.get("name", "Business") if isinstance(biz, dict) else str(biz)
        failed = bool(rec.get("error"))

        pdf.set_xy(14, y)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(192, 80, 77) if failed else pdf.set_text_color(111, 158, 88)
        pdf.cell(0, 6, _latin1(("FAILED - " if failed else "SENT - ") + name))
        y += 6

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(70, 70, 70)
        phone = (biz.get("phone", "") or biz.get("maps_phone", "")) if isinstance(biz, dict) else ""
        line = f"To: {rec.get('to', '-')}   |   Phone: {phone or '-'}   |   {rec.get('timestamp', '')[:19]}"
        pdf.set_x(14)
        pdf.multi_cell(180, 5, _latin1(line))
        y = pdf.get_y() + 1
        pdf.set_x(14)
        pdf.multi_cell(180, 5, _latin1(f"Subject: {rec.get('subject', '-')}"))
        y = pdf.get_y() + 1
        if failed:
            pdf.set_x(14)
            pdf.multi_cell(180, 5, _latin1(f"Error: {rec.get('error', '')}"))
            y = pdf.get_y() + 1
        body = (rec.get("body") or "").strip().replace("\r", "")
        if body:
            excerpt = body[:350] + ("..." if len(body) > 350 else "")
            pdf.set_x(14)
            pdf.multi_cell(180, 5, _latin1(excerpt))
        y = pdf.get_y() + 6

    _stamp(pdf)
    pdf.output(str(path))
    return str(path)
