"""Generate the PDF proposal attached to an outreach email.

The document follows the *goal* of the search: selling licences produces a
licensing proposal, selling websites produces a website proposal, and an
unknown goal falls back to something honest and generic. Content is declarative
per goal; this module only renders it, so adding a goal never means touching
layout code.

Rendered on the shared theme (agents/pdf_theme.py) with ReportLab Platypus.
"""
from datetime import datetime

from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from agents import pdf_theme
from agents.config import PDF_DIR


def _esc(text) -> str:
    from xml.sax.saxutils import escape
    return escape(str(text if text is not None else "-"))


# ── Per-goal document content ────────────────────────────────────────
# {name} and {product} are filled in per business.

PROPOSAL_COPY = {
    "cad_licensing": {
        "title": "Licensed {product}",
        "subtitle": "Proposal for Institutions",
        "understanding": (
            "{name} is a {kind}. {where}its computer and drafting labs need "
            "software that is genuine, licensed and supported for every machine "
            "that runs it - without paying retail per-seat prices for a whole "
            "classroom."
        ),
        "offer_head": "Included in every seat:",
        "offer": [
            "Genuine {product} - fully licensed, not cracked or trial software",
            "Education pricing sized to your lab, not retail per-seat pricing",
            "Installation and activation help for lab machines",
            "Support when a machine is replaced, formatted or re-imaged",
            "Licence documentation for institutional records and audits",
            "Renewal reminders so a lab never expires mid-session",
        ],
        "why_head": "Why Institutions Switch To Licensed Seats",
        "why": [
            "Trial software expires mid-session and stops the class",
            "Unlicensed installs create audit and compliance exposure for the institute",
            "Retail per-seat pricing is what stops labs from adding machines",
            "One supplier for the whole lab means one renewal date and one support line",
        ],
        "tiers_head": "Seat Packages",
        "tiers": [
            ("Lab - up to 10 seats", "One classroom or a single drafting lab"),
            ("Department - up to 25 seats", "Multiple labs under one department"),
            ("Campus - 50+ seats", "Institute-wide licensing with a single renewal date"),
        ],
        "steps": [
            "1. A quick call to confirm how many machines need a licence",
            "2. We send a written quotation for your seat count",
            "3. Licences delivered, installed and activated for the lab",
        ],
    },
    "website": {
        "title": "A Website for {name}",
        "subtitle": "Proposal",
        "understanding": (
            "{name} is a {kind}. {where}most customers now look a business up "
            "before they call or walk in, and a directory listing they do not "
            "control is not the impression {name} should be making."
        ),
        "offer_head": "What we would build:",
        "offer": [
            "A fast, mobile-first site that loads in under two seconds",
            "Local search setup so you appear for searches near you",
            "Enquiry form that emails you the moment someone fills it in",
            "Map, directions and opening hours that you can update yourself",
            "Your photos and services laid out to match how you actually work",
            "Social links so every channel points back to one home",
        ],
        "why_head": "Why This Pays For Itself",
        "why": [
            "People search before they call - the site is your first impression",
            "A listing on someone else's platform can be changed or removed at any time",
            "Clear hours and location cut the calls asking about both",
            "Enquiries keep arriving while you are closed or busy with a customer",
        ],
        "tiers_head": "Packages",
        "tiers": [
            ("Starter - single page", "One page, enquiry form, local search basics"),
            ("Professional - multi page", "Services, gallery, blog and analytics"),
            ("Premium - bookings or shop", "Online booking or product catalogue"),
        ],
        "steps": [
            "1. A quick call about what you want the site to do",
            "2. We mock up the homepage for you to look at",
            "3. You approve it, we launch and hand over the keys",
        ],
    },
    "custom": {
        "title": "{product}",
        "subtitle": "Proposal",
        "understanding": (
            "{name} is a {kind}. {where}this proposal sets out what we would "
            "supply and how it would work in practice."
        ),
        "offer_head": "What we propose:",
        "offer": [
            "{product} supplied directly",
            "Pricing confirmed on quotation for your requirement",
            "Support included after delivery",
            "One point of contact for the whole engagement",
        ],
        "why_head": "Why This Is Worth A Conversation",
        "why": [
            "Dealing with us directly is simpler than going through a reseller",
            "Pricing is set for your scale, not a list price",
            "You get support from the people who supplied it",
        ],
        "tiers_head": "Options",
        "tiers": [
            ("Small scope", "For a single site or a first order"),
            ("Standard", "For ongoing or multi-site requirements"),
            ("Custom", "Scoped together once we understand your requirement"),
        ],
        "steps": [
            "1. A quick call about what you need",
            "2. We send a written quotation",
            "3. Delivery and handover",
        ],
    },
}


def generate_proposal_pdf(business: dict, sender_name: str = "The Team",
                          goal=None) -> str:
    """Generate the proposal PDF for this goal. Returns the file path."""
    from agents.icp import resolve_goal, product_line

    goal = goal or resolve_goal()
    product = product_line(goal)
    copy = PROPOSAL_COPY.get(goal["key"]) or PROPOSAL_COPY["custom"]

    name = business.get("name", "Business")
    address = business.get("address", "")
    verdict = business.get("icp") or {}
    kind = (verdict.get("institution_type") or "local business").lower()
    where = f"Located at {address}, " if address else ""

    def fill(text: str) -> str:
        return (text.replace("{name}", name).replace("{product}", product)
                    .replace("{kind}", kind).replace("{where}", where))

    width = pdf_theme.PAGE_W - 2 * pdf_theme.MARGIN
    slug = "".join(c if c.isalnum() else "_" for c in name.lower())
    output_path = PDF_DIR / f"proposal_{slug}.pdf"
    doc = pdf_theme.ThemeDoc(output_path)
    story: list = []

    # ── Cover ──
    story.append(Spacer(1, 60))
    story.append(Paragraph(
        f'<font size="26" color="{pdf_theme.hexv(pdf_theme.DEEP)}"><b>'
        f'{_esc(fill(copy["title"]))}</b></font>',
        pdf_theme._s("cover", leading=32, alignment=1)))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f'<font size="13" color="{pdf_theme.hexv(pdf_theme.CORAL)}">'
        f'{_esc(copy["subtitle"])}</font>',
        pdf_theme._s("coversub", leading=18, alignment=1)))
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        f'Prepared for <b>{_esc(name)}</b>',
        pdf_theme._s("coverfor", fontSize=12, leading=16, alignment=1)))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        datetime.now().strftime("%B %d, %Y") + "  ·  Prepared by "
        + _esc(sender_name),
        pdf_theme._s("coverby", fontSize=10, leading=14,
                     textColor=pdf_theme.INK_SOFT, alignment=1)))
    story.append(PageBreak())

    # ── Body ──
    story += pdf_theme.section("Understanding Your Requirement")
    story.append(Paragraph(_esc(fill(copy["understanding"])), pdf_theme.S_BODY))

    story += pdf_theme.section("What We Propose")
    story.append(Paragraph(f"<b>{_esc(copy['offer_head'])}</b>", pdf_theme.S_BODY))
    offer_rows = [["•", _esc(fill(line))] for line in copy["offer"]]
    story.append(pdf_theme.data_table(["", ""], offer_rows,
                                      [width * 0.04, width * 0.96]))
    story.append(Spacer(1, 4))

    story += pdf_theme.section(copy["why_head"])
    why_rows = [["•", _esc(fill(line))] for line in copy["why"]]
    story.append(pdf_theme.data_table(["", ""], why_rows,
                                      [width * 0.04, width * 0.96]))

    story += pdf_theme.section(copy["tiers_head"])
    tier_rows = [[Paragraph(f"<b>{_esc(fill(t))}</b>", pdf_theme.S_CELL),
                  Paragraph(_esc(fill(d)), pdf_theme.S_CELL)]
                 for t, d in copy["tiers"]]
    story.append(pdf_theme.data_table(["Package", "Best for"], tier_rows,
                                      [width * 0.38, width * 0.62]))
    story.append(Spacer(1, 4))
    story.append(pdf_theme.callout(
        "Final pricing is confirmed on quotation — sized to your requirement, "
        "not a list price."))

    story += pdf_theme.section("Next Steps")
    step_rows = [[_esc(fill(s))] for s in copy["steps"]]
    story.append(pdf_theme.data_table(["How it goes"], step_rows, [width]))

    doc.build(story)
    return str(output_path)
