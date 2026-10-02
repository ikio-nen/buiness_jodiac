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

from agents.config import REPORTS_DIR, load_session_data, save_session_data
from agents import pdf_theme
from reportlab.lib import colors
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

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


# ── PDF rendering (shared theme: agents/pdf_theme.py) ────────────────

def _esc(text) -> str:
    """XML-escape for Paragraph markup, None-safe."""
    from xml.sax.saxutils import escape
    return escape(str(text if text is not None else "-"))


def kv_from(pairs: list[tuple[str, str]]):
    """Key: value lines for contact/report cards."""
    return Paragraph("<br/>".join(f"<b>{_esc(k)}:</b> {_esc(v)}" for k, v in pairs),
                     pdf_theme.S_META)


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
    goal = state.get("goal") or "outreach"
    doc = pdf_theme.ThemeDoc(path)
    story: list = []
    story.append(pdf_theme.HeaderBand(
        "Campaign Targets",
        f"Initial report  \u00b7  {len(rows)} approved businesses  \u00b7  goal: {goal}"))
    story.append(Spacer(1, 10))

    def badge_cell(b: dict):
        label, color = pdf_theme.lead_badge(pdf_theme.band_for(b.get("fit_score")))
        if not label:
            return Paragraph("-", pdf_theme.S_CELL)
        return Paragraph(pdf_theme.badge_markup(label, color, dark_text=(label == "HOT")),
                         pdf_theme.S_CELL_B)

    width = pdf_theme.PAGE_W - 2 * pdf_theme.MARGIN
    rows_out = []
    for i, b in enumerate(rows, 1):
        rows_out.append([
            Paragraph(str(i), pdf_theme.S_CELL),
            Paragraph(f"<b>{_esc(b.get('name', '?'))}</b>", pdf_theme.S_CELL),
            Paragraph(_esc(b.get("category") or "-"), pdf_theme.S_CELL),
            Paragraph(_esc(b.get("email") or "-"), pdf_theme.S_CELL),
            Paragraph(_esc(b.get("phone") or "-"), pdf_theme.S_CELL),
            Paragraph(_esc(b.get("fit_score", "-")), pdf_theme.S_CELL),
            badge_cell(b),
        ])
    story.append(pdf_theme.data_table(
        ["#", "Business", "Category", "Email", "Phone", "Fit", "Lead"],
        rows_out,
        [width * 0.05, width * 0.29, width * 0.15, width * 0.22,
         width * 0.13, width * 0.06, width * 0.10]))

    bands = [pdf_theme.band_for(b.get("fit_score")) for b in rows]
    hot, warm, cold = bands.count("hot"), bands.count("warm"), bands.count("cold")
    story.append(Spacer(1, 8))
    story.append(pdf_theme.callout(
        f"<b>Lead temperature</b>  \u00b7  {hot} hot (fit &ge; 80)  \u00b7  "
        f"{warm} warm (60&ndash;79)  \u00b7  {cold} cold (&lt; 60). Hot leads "
        "first &mdash; the contact sheet below carries the full file for each pick."))

    # Contact sheet: one card per business so nothing is squeezed in columns.
    story += pdf_theme.section("Contact sheet")
    for i, b in enumerate(rows, 1):
        detail = [("Category", b.get("category") or "-"),
                  ("Email", b.get("email") or "-"),
                  ("Phone", b.get("phone") or "-")]
        if b.get("website"):
            detail.append(("Web", b["website"]))
        if b.get("address"):
            detail.append(("Address", b["address"]))
        card = Table(
            [[Paragraph(f"{i}.  <b>{_esc(b.get('name', '?'))}</b>",
                        pdf_theme.S_CELL_B)],
             [kv_from(detail)]],
            colWidths=[width])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, pdf_theme.RULE),
            ("LINEBEFORE", (0, 0), (0, -1), 2.4, pdf_theme.DEEP),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(card)
        story.append(Spacer(1, 7))

    doc.build(story)
    return str(path)


# ── Stage 6: the final report ─────────────────────────────────────────

def final_report_pdf(sent_records: list[dict], errors: list[dict],
                     skipped_count: int, session_name: str = "") -> str:
    """Execution summary: recipient, subject, timestamp, status per email.

    Saved under agent_output/reports/campaign_final_<ts>.pdf.
    """
    path = _report_path("campaign_final")
    title = "Campaign Final Report"
    if session_name:
        title += f" - {session_name}"
    doc = pdf_theme.ThemeDoc(path)
    story: list = []
    story.append(pdf_theme.HeaderBand(
        title,
        f"{len(sent_records)} sent  \u00b7  {len(errors)} failed  \u00b7  "
        f"{skipped_count} skipped"))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Execution summary - " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        pdf_theme.S_META))
    story.append(Spacer(1, 6))

    records = list(sent_records)
    for e in errors:
        records.append({"business": {"name": e.get("name", "?")},
                        "to": "-", "subject": "-", "timestamp": "",
                        "error": e.get("error", "unknown")})

    if not records:
        story.append(pdf_theme.callout("No emails were executed in this run."))
        doc.build(story)
        return str(path)

    width = pdf_theme.PAGE_W - 2 * pdf_theme.MARGIN
    for rec in records:
        biz = rec.get("business") or {}
        name = biz.get("name", "Business") if isinstance(biz, dict) else str(biz)
        failed = bool(rec.get("error"))
        label, accent = (("FAILED", pdf_theme.CORAL) if failed
                         else ("SENT", pdf_theme.DEEP))
        head = Paragraph(
            pdf_theme.badge_markup(label, accent) + "&nbsp;&nbsp;<b>"
            + _esc(name) + "</b>",
            pdf_theme.S_CELL_B)

        phone = ((biz.get("phone", "") or biz.get("maps_phone", ""))
                 if isinstance(biz, dict) else "")
        meta_pairs = [("To", rec.get("to", "-")), ("Phone", phone or "-"),
                      ("Time", (rec.get("timestamp", "") or "-")[:19]),
                      ("Subject", rec.get("subject", "-"))]
        if failed:
            meta_pairs.append(("Error", rec.get("error", "")))

        rows = [[head], [kv_from(meta_pairs)]]
        body_txt = (rec.get("body") or "").strip().replace("\r", "")
        if body_txt:
            excerpt = body_txt[:350] + ("..." if len(body_txt) > 350 else "")
            rows.append([Paragraph(_esc(excerpt), pdf_theme.S_CELL)])
        card = Table(rows, colWidths=[width - 12])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, pdf_theme.RULE),
            ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ]))
        story.append(card)
        story.append(Spacer(1, 7))

    doc.build(story)
    return str(path)
