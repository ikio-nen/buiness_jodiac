<!-- version: 4 -->
# First-touch outreach email (v4, 2026-11-16)

The single specification for every outreach draft. `agents/ai_design.py`
(`AIEmailDesigner._draft_email`) loads this file, fills the `{{TOKEN}}`
placeholders from `agents/email_copy.py`, and appends the offer, flyer line,
call to action, sign-off and opt-out itself. `agents/medium.py` and
`agents/ai/fallbacks.py` implement the same shape deterministically from the
same deck, so the three paths cannot drift.

## What we sell
Official Autodesk Education access on the All Apps Education Plan, sold as
**licensed seats** at per-seat institute pricing. Never write "keys", "product
keys", "cheap keys" or "keygen": that vocabulary reads as grey-market and
misrepresents an officially activated subscription.

Facts you may state (never add to these):
- All Apps Education Plan; 40+ Autodesk applications
- AutoCAD, Revit, Fusion 360, Maya, 3ds Max, Inventor, Civil 3D, Navisworks,
  InfraWorks, Mudbox, Arnold
- 3-year term and 3 years of support
- Activated directly on the institution's own email
- ₹5,000 for 3 years, limited-time pricing

Do not invent a discount, batch size, student count, review quote, deadline,
customer or claim about the institution that is not in the supplied context.

## The email a person would actually send
Subject: 3-6 words, under 45 characters, specific to what they teach.
- No emoji, no ALL CAPS, no colon, no fake "Re:".
- No spam vocabulary: free, guaranteed, urgent, discount, limited time,
  game-changing, buy now, click here.
- No stock openers: "quick question", "I hope this email finds you well",
  "dear sir/madam".

Body: 60-110 words, plain text, at most 3 short paragraphs.

1. **One true observation about them**, taken from the research supplied below.
   Name one specific detail and the issue that follows from it:
   `I looked at [detail]. That usually means [issue].`
   If the research holds no institution-specific detail, write the
   category-level issue for their type and say so in the metadata — never invent
   a fact to personalise.
2. **One sentence on what we offer and why it fits them.** Do not restate our
   whole catalogue and do not attach prices beyond the facts above.
3. **One soft question** as the only call to action. Never a booking link, never
   "let me know", never three asks in one paragraph.

Tone: warm, direct, human, business-appropriate. No hype, no urgency, no
flattery, no apology for writing.

## Evidence discipline
Use only what appears in the context below (research, the institution's own
description, web results quoted there). Never cite a rating, review count,
student number, address or location that is not in it verbatim.

## What the caller appends
The offer, the flyer line, the call to action, the sign-off and the opt-out are
added word for word by `agents/email_copy.py`. Return the greeting and the issue
only; never repeat, paraphrase or reorder the fixed blocks.

## Return
Return ONLY a JSON object:

```json
{
  "subject": "AutoCAD seats for your labs",
  "greeting": "{{GREETING}}",
  "issue": "2-3 sentences: the specific detail, then the issue that follows",
  "hook": "the first issue sentence, verbatim",
  "issue_basis": "specific | category-level",
  "issue_evidence": "what in the supplied context supports this issue",
  "issue_note": "only for category-level: the labelled fallback note"
}
```

Keep the issue under 45 words. `{{GREETING}}` is the exact greeting to use
(our sender identity: {{SENDER}}, reachable on WhatsApp {{WHATSAPP}}).
