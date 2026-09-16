"""Generate the PDF proposal attached to an outreach email.

The document follows the *goal* of the search: selling licences produces a
licensing proposal, selling websites produces a website proposal, and an
unknown goal falls back to something honest and generic. Content is declarative
per goal; this module only renders it, so adding a goal never means touching
layout code.
"""
from datetime import datetime

from fpdf import FPDF

from .config import PDF_DIR


def _latin1(text: str) -> str:
    """Make any text safe for fpdf's core Helvetica font (latin-1 only)."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


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
    from .icp import resolve_goal, product_line

    goal = goal or resolve_goal()
    product = _latin1(product_line(goal))
    copy = PROPOSAL_COPY.get(goal["key"]) or PROPOSAL_COPY["custom"]

    name = _latin1(business.get("name", "Business"))
    address = _latin1(business.get("address", ""))
    verdict = business.get("icp") or {}
    kind = _latin1((verdict.get("institution_type") or "local business").lower())
    where = f"Located at {address}, " if address else ""

    def fill(text: str) -> str:
        return (text.replace("{name}", name).replace("{product}", product)
                    .replace("{kind}", kind).replace("{where}", where))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=25)

    # ── Cover page ──
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(25, 118, 210)
    pdf.multi_cell(0, 13, fill(copy["title"]) + "\n", align="C")
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 9, _latin1(copy["subtitle"]) + "\n", align="C")
    pdf.set_font("Helvetica", "", 14)
    pdf.multi_cell(0, 9, f"Prepared for {name}\n", align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 8, f"Date: {datetime.now().strftime('%B %d, %Y')}\n", align="C")
    pdf.multi_cell(0, 8, f"Prepared by: {_latin1(sender_name)}\n", align="C")
    pdf.ln(10)

    def heading(text: str):
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(33, 33, 33)
        pdf.multi_cell(0, 10, _latin1(text) + "\n")

    def body(text: str, indent: str = "  - "):
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 7, f"{indent}{_latin1(text)}\n")

    heading("Understanding Your Requirement")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 7, _latin1(fill(copy["understanding"])) + "\n")

    heading("What We Propose")
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(0, 8, _latin1(copy["offer_head"]) + "\n")
    for line in copy["offer"]:
        body(fill(line))

    heading(copy["why_head"])
    for line in copy["why"]:
        body(fill(line))

    heading(copy["tiers_head"])
    for tier, tier_desc in copy["tiers"]:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(33, 33, 33)
        pdf.multi_cell(0, 7, "  " + _latin1(fill(tier)) + "\n")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 7, "    " + _latin1(fill(tier_desc)) + "\n")
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 7, "  Final pricing is confirmed on quotation.\n")

    heading("Next Steps")
    for step in copy["steps"]:
        body(fill(step))

    # ── Footer ──
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(150, 150, 150)
    pdf.multi_cell(0, 7, f"Generated on {datetime.now().strftime('%B %d, %Y')}\n", align="C")

    # ── Save ──
    slug = "".join(c if c.isalnum() else "_" for c in name.lower())
    output_path = PDF_DIR / f"proposal_{slug}.pdf"
    pdf.output(str(output_path))
    return str(output_path)
