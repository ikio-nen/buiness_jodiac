"""Sent-email receipt PDF.

After an email is sent, render a clean one-page PDF record:
  - business name
  - To / From / Subject / Body
  - sent timestamp
  - attached proposal PDF name (if any)

Saves under agent_output/pdfs/sent/<business_slug>_<timestamp>.pdf
Rendered on the shared theme (agents/pdf_theme.py); Unicode punctuation is
safe — ReportLab Paragraphs take full Unicode, no latin-1 flattening.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from agents import pdf_theme
from agents.config import PDF_DIR

_SENT_DIR = PDF_DIR / "sent"
_SENT_DIR.mkdir(parents=True, exist_ok=True)


def _slug(name: str) -> str:
    return name.replace(" ", "_").replace("'", "").lower()


def _esc(text) -> str:
    from xml.sax.saxutils import escape
    return escape(str(text if text is not None else "-"))


def sent_dir() -> Path:
    """Directory where sent-email receipt PDFs are written."""
    return _SENT_DIR


def send_receipt_pdf(
    business_name: str,
    to: str,
    subject: str,
    body: str,
    sender_name: str = "The Team",
    attached_pdf_name: str | None = None,
    out_dir: Path | None = None,
) -> str:
    """Render and save a one-page PDF record of a sent email.

    Records: business name, To, From, Subject, Body, attached proposal name,
    and the sent timestamp. Saved under agent_output/pdfs/sent/.
    """
    d = out_dir or _SENT_DIR
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_slug(business_name)}_{ts}.pdf"
    path = d / filename

    doc = pdf_theme.ThemeDoc(path)
    width = pdf_theme.PAGE_W - 2 * pdf_theme.MARGIN
    story: list = []
    story.append(pdf_theme.HeaderBand(
        "Email Sent",
        f"record  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    story.append(Spacer(1, 12))

    meta_pairs = [("Business", business_name or "-"), ("To", to or "-"),
                  ("From", sender_name or "-"), ("Subject", subject or "-")]
    if attached_pdf_name:
        meta_pairs.append(("Attached proposal", attached_pdf_name))
    story.append(pdf_theme.kv_table(meta_pairs, width))

    story += pdf_theme.section("Body")
    body_text = (body or "").strip() or "(empty body)"
    # Collapse blank lines; Paragraph needs <br/> for explicit breaks and
    # must not receive raw XML.
    lines = [_esc(ln) for ln in body_text.replace("\r", "").split("\n")]
    story.append(Paragraph("<br/>".join(lines), pdf_theme.S_BODY))

    doc.build(story)
    return str(path)
