#!/usr/bin/env python3
"""The one copy deck for outreach email drafts.

Every drafting path reads these strings: the Gemini prompt
(``agents/ai/prompts/draft_email.md``), the template agent
(``agents/medium.py``) and the heuristic fallback
(``agents/ai/fallbacks.py``). A copy change is therefore one diff, and the
three paths cannot drift into saying different things to the same prospect.

Vocabulary rule: we sell *licensed seats* on the All Apps Education Plan.
The word "keys" is grey-market language and never appears in an email.
"""

SENDER = "Autodesk Educational Solutions"
WHATSAPP = "+91 6296 142368"
ACTIVATION_PHONE = "+91 93829 64017"

# Last resort only: a real contact name wins, then the institution's own name.
DEFAULT_GREETING = "Dear Team,"


def greeting_for(contact_name: str = "", business_name: str = "") -> str:
    """The house greeting.

    A researched person wins, then the institution itself — addressing a
    training centre by its own name reads as a letter rather than a mailshot.
    "Dear Team" survives only when we know neither, and never as a placeholder
    for a name we do have.
    """
    if contact_name and contact_name.strip():
        return f"Dear {contact_name.strip()},"
    if business_name and business_name.strip():
        return f"Dear {business_name.strip()},"
    return DEFAULT_GREETING

OFFER = (
    "We provide official Autodesk Education access through the All Apps "
    "Education Plan, with licensed seats at per-seat institute pricing. This "
    "includes AutoCAD along with 40+ Autodesk applications such as Revit, "
    "Fusion 360, Maya, 3ds Max, Inventor and Civil 3D, with 3-year coverage and "
    "activation directly on email."
)

FLYER_LINE = (
    "I have attached the promotional flyer with complete details, including the "
    "plan features and pricing of \u20b95,000 for 3 years."
)

CTA_TEMPLATE = (
    "You can reply to this email, or message me on WhatsApp at {whatsapp}. "
    "For instant activation, license queries and payment details, you can also "
    "reach us on Phone / WhatsApp at {activation}, as mentioned in the attached "
    "flyer. If you would prefer to meet, we can schedule a short meeting at a "
    "time that is convenient for you."
)

SIGN_OFF_TEMPLATE = (
    "Best regards,\n"
    "{sender}\n"
    "WhatsApp: {whatsapp}\n"
    "Phone / WhatsApp (activation): {activation}"
)

# Category-level issue lines. Used only when research produced no concrete
# institution-specific issue -- the draft's metadata must say so.
ISSUE_BY_CATEGORY = {
    "training": (
        "I looked at {biz}'s CAD and design training, where every new batch "
        "needs a licensed seat before the first session. Full retail pricing at "
        "that volume does not fit standard course margins."
    ),
    "college": (
        "I looked at {biz}'s engineering and design departments, where seats are "
        "usually licensed for the main lab only. Covering every student machine "
        "at retail pricing is where the lab budget stops."
    ),
    "polytechnic": (
        "I looked at {biz}'s trades and drafting programmes, where each batch "
        "needs licensed seats across the whole classroom. Retail pricing per "
        "seat adds up faster than a course fee can absorb."
    ),
    "school": (
        "I looked through what is publicly listed for {biz} and found no "
        "computer-lab or drafting programme to reference. For schools at this "
        "stage, the recurring issue is that adding design software to a shared "
        "lab means licensing a whole classroom, and retail pricing is where the "
        "budget stops."
    ),
    "university": (
        "I looked at {biz}'s departments and lab setup, where licensing is "
        "usually negotiated one department at a time. Extending coverage to "
        "every seat at retail pricing is the part that stalls."
    ),
    "*": (
        "I looked at {biz}'s training setup, where each new batch needs a "
        "licensed seat before the first class. Full retail pricing at that "
        "volume does not fit standard course margins."
    ),
}

CATEGORY_LEVEL_NOTE = (
    "Research for this business held no institution-specific issue; the body "
    "uses the closest category-level issue ({issue}) and labels it as such."
)


def cta(whatsapp: str = "", activation: str = "") -> str:
    """The exact next-step paragraph: reply, WhatsApp, or a short meeting."""
    return CTA_TEMPLATE.format(whatsapp=whatsapp or WHATSAPP,
                               activation=activation or ACTIVATION_PHONE)


def sign_off(sender: str = "", whatsapp: str = "", activation: str = "") -> str:
    """The exact four-line sign-off; never a placeholder sender."""
    return SIGN_OFF_TEMPLATE.format(sender=sender or SENDER,
                                    whatsapp=whatsapp or WHATSAPP,
                                    activation=activation or ACTIVATION_PHONE)


def issue_line(biz_name: str, category: str = "") -> str:
    """Deterministic, category-level issue paragraph for template drafting."""
    template = ISSUE_BY_CATEGORY.get((category or "").strip().lower(),
                                     ISSUE_BY_CATEGORY["*"])
    return template.format(biz=biz_name)


def compose_body(issue: str, greeting: str = "", sender: str = "",
                 whatsapp: str = "", activation: str = "") -> str:
    """Issue-first body: greeting, issue, offer, flyer, exact CTA, sign-off."""
    return (
        f"{greeting or DEFAULT_GREETING}\n\n{issue}\n\n{OFFER}\n\n{FLYER_LINE}"
        f"\n\n{cta(whatsapp, activation)}\n\n"
        f"{sign_off(sender, whatsapp, activation)}"
    )
