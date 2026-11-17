"""Post-generation gate for outreach drafts. Pure stdlib. Never raises.

`lint(subject, body)` returns a list of problems; an empty list means the draft
is sendable. A draft that fails is regenerated once and then replaced by the
template, so a long, spammy or opt-out-less email can never reach the review
screen looking finished.

The thresholds follow the 2026 research summarised in guides/03: subject 3-6
words and under 45 characters, body 60-110 words across at most 3 short
paragraphs, one question, one link, no spam or stock phrases, and an opt-out.
The hard fail lines sit slightly outside the target band (40 and 120 words) so a
draft is not rejected over a word or two.
"""

import re

SPAM = ("free", "guaranteed", "guarantee", "act now", "urgent", "limited time",
        "game-changing", "game changing", "100%", "risk-free", "winner",
        "click here", "buy now", "exclusive offer", "no obligation", "discount")
STOCK = ("i hope this email finds you well", "hope this finds you well",
         "dear sir", "dear madam", "just bumping", "quick question")
OPT_OUT = re.compile(r"(no thanks|not relevant|unsubscribe|opt.?out)", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
SIGN_OFF = re.compile(r"^(regards|thanks|best|cheers|sincerely|warm regards)", re.I)


def _body_words(body: str) -> int:
    """Words in the message itself, excluding the sign-off and opt-out block.

    The signature and the opt-out are fixed copy the sender must not lose to a
    word count, so they are stripped before counting.
    """
    parts = re.split(r"\n\s*\n", (body or "").strip())
    while parts:
        last = parts[-1].strip()
        if OPT_OUT.search(last) or "|" in last or SIGN_OFF.match(last):
            parts.pop()
        else:
            break
    return len(re.findall(r"\S+", " ".join(parts)))


def lint(subject: str, body: str) -> list:
    """Problems with one draft, as plain sentences. Empty list = pass."""
    try:
        problems = []
        subject = (subject or "").strip()
        body = (body or "").strip()
        if not subject:
            problems.append("subject is empty")
        else:
            words = len(subject.split())
            if not 3 <= words <= 7:
                problems.append(f"subject has {words} words (want 3-6)")
            if len(subject) > 45:
                problems.append(f"subject is {len(subject)} characters (max 45)")
            if subject.isupper():
                problems.append("subject is ALL CAPS")
            if EMOJI.search(subject):
                problems.append("subject contains an emoji")
            if ":" in subject:
                problems.append("subject has a colon or a fake Re:")

        low = f"{subject} {body}".lower()
        for word in SPAM:
            if re.search(r"\b" + re.escape(word) + r"\b", low):
                problems.append(f"spam word: {word}")
        for phrase in STOCK:
            if phrase in low:
                problems.append(f"stock phrase: {phrase}")

        words = _body_words(body)
        if words < 40:
            problems.append(f"body too short ({words} words, want 60-110)")
        elif words > 120:
            problems.append(f"body too long ({words} words, want 60-110)")
        if not OPT_OUT.search(body):
            problems.append("no opt-out line")
        if body.count("?") > 1:
            problems.append("more than one question: keep a single call to action")
        if len(re.findall(r"https?://", body)) > 1:
            problems.append("more than one link")
        if EMOJI.search(body):
            problems.append("body contains an emoji")
        return problems
    except Exception as exc:  # the pipeline rule: telemetry never breaks the run
        return [f"lint error: {exc}"]


def main() -> int:
    """Smoke output for `python -m agents.email_lint` / tools/email_lint.py."""
    good_subject = "AutoCAD seats for your labs"
    good_body = (
        "Hi Priya,\n\n"
        "I noticed your institute runs AutoCAD and drafting courses, and licence "
        "renewals for lab machines can be costly and fiddly to manage across "
        "batches of students.\n\n"
        "We supply official Autodesk licences with invoicing and set-up help, so "
        "each new batch can start on time without delays or paperwork.\n\n"
        "Would it be useful if I sent a short price sheet?\n\n"
        "Regards,\nAsha | Zyphr | asha@example.com\n"
        'If this is not relevant, reply "no thanks" and I will not contact you again.'
    )
    bad_subject = "URGENT: FREE Game-Changing AutoCAD Offer!!!"
    bad_body = "Dear sir, I hope this email finds you well. " + "Buy now. " * 5
    print("good:", lint(good_subject, good_body))
    print("bad:", lint(bad_subject, bad_body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
