"""Shared PDF theme — one look for every document jodiax produces.

Palette and layout language borrowed from the office UI's warm Ghibli-pixel
skin and restyled toward a deep-green/cream/coral minimal print look:

  deep green  #2F5D50   headers, table header rows, footer band
  cream       #FAF6EC   page background, table row tint
  coral       #E8896B   accents, SENT badge, hot leads
  ink         #2B2B26   body text

Built on ReportLab Platypus: every visible element is a flowable in a single
story, so the layout engine — not hand-rolled y bookkeeping — places text.
The fpdf-era overlap bug (stamp drawn over the recipient line because cell()
does not advance y) is structurally impossible here: two flowables can never
occupy the same baseline.

All four generators (initial/final campaign reports, send receipt, proposal)
consume this module; restyling the brand means touching only this file.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle,
)

# ── Palette ───────────────────────────────────────────────────────────
DEEP = colors.HexColor("#2F5D50")     # deep green — headers, bands
DEEP_DARK = colors.HexColor("#24463C")
CREAM = colors.HexColor("#FAF6EC")    # page paper
CREAM_TINT = colors.HexColor("#F1EADA")  # table row stripe / callout fill
CORAL = colors.HexColor("#E8896B")    # accent — badges, hot leads
CORAL_SOFT = colors.HexColor("#F6D5C8")
INK = colors.HexColor("#2B2B26")      # body text
INK_SOFT = colors.HexColor("#6B6A5E")  # secondary text
RULE = colors.HexColor("#D8D0BC")     # hairlines

PAGE_W, PAGE_H = A4

_LEAD_BADGES = {
    "hot": ("HOT", CORAL),
    "warm": ("WARM", colors.HexColor("#C99242")),
    "cold": ("COLD", colors.HexColor("#7A9CC6")),
}


def lead_badge(band: str) -> tuple[str, colors.Color]:
    """(label, color) for a lead temperature band; unknown -> ('', white)."""
    return _LEAD_BADGES.get((band or "").lower(), ("", colors.white))


def hexv(color: colors.Color) -> str:
    """'#rrggbb' for Paragraph markup (Color.hexval() drops the hash)."""
    return "#" + color.hexval()[2:]


def badge_markup(label: str, color: colors.Color, dark_text: bool = False) -> str:
    """<font> chip markup for inside a Paragraph — SENT/HOT/WARM/COLD badges."""
    txt = "#7A2E17" if dark_text else "#FFFFFF"
    return (f'<font backColor="{hexv(color)}" color="{txt}">'
            f'&nbsp;{label}&nbsp;</font>')


def band_for(fit: int | None) -> str:
    """Hot >= 80, Warm >= 60, Cold otherwise. None/0 -> cold."""
    try:
        f = int(fit or 0)
    except (TypeError, ValueError):
        return "cold"
    return "hot" if f >= 80 else "warm" if f >= 60 else "cold"


# ── Paragraph styles ──────────────────────────────────────────────────
def _s(name: str, **kw) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13,
                textColor=INK, spaceAfter=0, spaceBefore=0)
    base.update(kw)
    return ParagraphStyle(name, **base)


S_H2 = _s("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15,
          textColor=DEEP, spaceBefore=10, spaceAfter=4)
S_BODY = _s("body", spaceAfter=4)
S_CELL = _s("cell", fontSize=9, leading=12)
S_CELL_B = _s("cellB", fontName="Helvetica-Bold", fontSize=9, leading=12)
S_CELL_WHITE = _s("cellW", fontName="Helvetica-Bold", fontSize=9, leading=12,
                  textColor=colors.white)
S_META = _s("meta", fontSize=8.5, leading=12, textColor=INK_SOFT)


# ── Page furniture ────────────────────────────────────────────────────
MARGIN = 16 * mm
_FOOTER_NOTE = "jodiax outreach  ·  confidential lead report"


def _page_decor(canv, doc):
    """Cream page, deep-green footer band, top hairline — drawn every page."""
    canv.saveState()
    canv.setFillColor(CREAM)
    canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canv.setFillColor(DEEP)
    canv.rect(0, 0, PAGE_W, 12 * mm, stroke=0, fill=1)
    canv.setFillColor(colors.HexColor("#9DB4A8"))
    canv.setFont("Helvetica", 7.5)
    canv.drawString(MARGIN, 4.5 * mm, _FOOTER_NOTE)
    canv.drawRightString(PAGE_W - MARGIN, 4.5 * mm,
                         datetime.now().strftime("generated %Y-%m-%d %H:%M"))
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.6)
    canv.line(MARGIN, PAGE_H - 12 * mm, PAGE_W - MARGIN, PAGE_H - 12 * mm)
    canv.restoreState()


class ThemeDoc(BaseDocTemplate):
    """A4 doc on the cream/deep-green page furniture."""

    def __init__(self, path: str | Path):
        super().__init__(str(path), pagesize=A4, leftMargin=MARGIN,
                         rightMargin=MARGIN, topMargin=MARGIN,
                         bottomMargin=18 * mm, title="jodiax outreach report",
                         author="jodiax outreach")
        frame = Frame(MARGIN, 18 * mm, PAGE_W - 2 * MARGIN,
                      PAGE_H - MARGIN - 18 * mm, id="body")
        self.addPageTemplates(
            [PageTemplate(id="page", frames=[frame], onPage=_page_decor)])


# ── Story building blocks ─────────────────────────────────────────────
class HeaderBand(Flowable):
    """Deep-green masthead: title + subtitle, coral corner tick."""

    def __init__(self, title: str, subtitle: str = "", width: float | None = None):
        super().__init__()
        self.title, self.subtitle = title, subtitle
        self.width = width or (PAGE_W - 2 * MARGIN)

    def wrap(self, aw, ah):
        self.height = 58 if self.subtitle else 44
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(DEEP)
        c.roundRect(0, 0, self.width, self.height, 6, stroke=0, fill=1)
        c.setFillColor(CORAL)
        c.rect(self.width - 26, self.height - 8, 6, 6, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        y = self.height - (30 if self.subtitle else 26)
        c.drawString(14, y, self.title[:90])
        if self.subtitle:
            c.setFillColor(colors.HexColor("#DCE7DF"))
            c.setFont("Helvetica", 9)
            c.drawString(14, y - 15, self.subtitle[:110])


def kv_table(rows: list[tuple[str, str]], width: float) -> Table:
    """Two-column key/value block with hairline rules."""
    data = [[Paragraph(f"<b>{k}</b>", S_META), Paragraph(v, S_META)]
            for k, v in rows]
    t = Table(data, colWidths=[width * 0.22, width * 0.78])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def section(title: str) -> list[Flowable]:
    """Section heading + coral underline tick."""
    line = Table([[""]], colWidths=[22], rowHeights=[2.2])
    line.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CORAL)]))
    line.hAlign = "LEFT"
    return [Paragraph(title, S_H2), line, Spacer(1, 5)]


def callout(text: str) -> Table:
    """Cream-tinted one-cell note box."""
    t = Table([[Paragraph(text, S_BODY)]], colWidths=[PAGE_W - 2 * MARGIN])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM_TINT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def data_table(header: list[str], rows: list[list], col_widths: list[float],
               align_right: tuple[int, ...] = ()) -> Table:
    """The standard striped table: deep-green header, cream stripes."""
    data = [[Paragraph(h, S_CELL_WHITE) for h in header]]
    for r in rows:
        data.append([c if isinstance(c, (Paragraph, Table)) else Paragraph(str(c), S_CELL)
                     for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DEEP),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CREAM_TINT]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for col in align_right:
        style.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t
