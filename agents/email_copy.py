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

import re

SENDER = "Autodesk Educational Solutions"
WHATSAPP = "+91 6296 142368"

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

# ── The body, in the order a person would write it ──────────────────
# Three short paragraphs and one question. The old deck stacked an offer, a
# flyer note, a CTA that asked for three different things and a four-line
# signature, which read as a pitch deck rather than a letter.
OFFER = (
    "We supply official Autodesk Education seats \u2014 AutoCAD plus 40+ apps on "
    "a 3-year term \u2014 activated on your institution's own email."
)

FLYER_LINE = "I have attached the flyer with the plan details and the pricing."

CTA_TEMPLATE = (
    "Would a short price sheet for your next batch be useful? "
    "Reply here, or message me on WhatsApp at {whatsapp}."
)

SIGN_OFF_TEMPLATE = "Regards,\n{sender} | {whatsapp}"

# One line, always present: the linter fails any draft without it.
OPT_OUT = ('If this is not relevant, reply "no thanks" and I will not contact '
           'you again.')

# A first email is 60-110 words; the fixed blocks are ~55 of those, so the
# researched issue paragraph is capped here rather than left to the model.
MAX_ISSUE_WORDS = 45

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


def cta(whatsapp: str = "") -> str:
    """The exact next-step paragraph: one question, one way to reply."""
    return CTA_TEMPLATE.format(whatsapp=whatsapp or WHATSAPP)


def sign_off(sender: str = "", whatsapp: str = "") -> str:
    """The exact two-line sign-off; never a placeholder sender."""
    return SIGN_OFF_TEMPLATE.format(sender=sender or SENDER,
                                    whatsapp=whatsapp or WHATSAPP)


def issue_line(biz_name: str, category: str = "") -> str:
    """Deterministic, category-level issue paragraph for template drafting."""
    template = ISSUE_BY_CATEGORY.get((category or "").strip().lower(),
                                     ISSUE_BY_CATEGORY["*"])
    return template.format(biz=biz_name)


def fit_words(text: str, limit: int = MAX_ISSUE_WORDS) -> str:
    """Trim a paragraph to `limit` words, keeping whole sentences.

    Drops trailing sentences until the paragraph fits; a single over-long
    sentence is cut at the word limit. Keeps every draft inside the length
    target without letting the model decide how long the email is.
    """
    text = (text or "").strip()
    if len(text.split()) <= limit:
        return text
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    while sentences and len(" ".join(sentences).split()) > limit:
        if len(sentences) == 1:
            return " ".join(sentences[0].split()[:limit]).rstrip(",;:") + "."
        sentences.pop()
    kept = " ".join(sentences).strip()
    return kept if kept else text


def compose_body(issue: str, greeting: str = "", sender: str = "",
                 whatsapp: str = "") -> str:
    """The letter: greeting, the issue, the offer, one question, sign-off,
    opt-out. The sender block carries one reachable contact."""
    return (
        f"{greeting or DEFAULT_GREETING}\n\n{fit_words(issue)}"
        f"\n\n{OFFER}\n\n{FLYER_LINE}"
        f"\n\n{cta(whatsapp)}\n\n"
        f"{sign_off(sender, whatsapp)}\n{OPT_OUT}"
    )
