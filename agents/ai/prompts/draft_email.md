<!-- version: 3 -->
# Sales-outreach email drafting (v3, 2026-11-14)

The single specification for every outreach draft. `agents/ai_design.py`
(`AIEmailDesigner._draft_email`) loads this file and fills the `{{TOKEN}}`
placeholders from `agents/email_copy.py`; `agents/medium.py` and
`agents/ai/fallbacks.py` implement the same rules deterministically, reading
the same copy deck. Change the copy deck, not this file, when a phone number,
price or sign-off changes.

## What we sell
Official Autodesk Education access through the All Apps Education Plan, sold
as **licensed seats** at per-seat institute pricing. Never write "keys",
"product keys", "cheap keys" or "keygen": that vocabulary reads as grey-market
and misrepresents an officially activated subscription.

Flyer facts only. Do not add, invent or embellish beyond these:
- All Apps Education Plan; 40+ Autodesk applications
- AutoCAD, Revit, Fusion 360, Maya, 3ds Max, Inventor, Civil 3D, Navisworks,
  InfraWorks, Mudbox, Arnold
- 3-year term and 3 years of support
- Activated directly on the institution's own email
- ₹5,000 for 3 years, limited-time pricing
Never invent a discount, batch size, student count, review quote, deadline or
claim about the institution that is not in the supplied research.

## Structure (in this order, every time)
1. **Greeting** — `{{GREETING}}`. Use a person's name only if the research
   actually supplies one.
2. **Issue first (2-3 sentences, 50-70 words, first paragraph).** Open by naming
   ONE specific detail found for THIS institution, then the issue that follows
   from it. Shape:
   `I looked at [one specific detail]. That usually means [specific issue].`
   Never open with "training institutes like yours", "I hope this email finds
   you well", or any generic pain point. Do not list their whole course
   catalogue — one or two details, then the issue.
3. **Offer, tied to that issue** — exactly one offer, verbatim:
   {{OFFER}}
4. **Flyer reference** — verbatim, because the flyer is attached:
   {{FLYER_LINE}}
5. **Next step** — verbatim, never a short phone call, never a booking link:
   {{CTA}}
6. **Sign-off** — verbatim, four lines:
   {{SIGN_OFF}}

## Evidence discipline
Use only facts supplied in the context below (research, the business's own
description, or web results quoted there). Never cite a rating, review count,
student number, address or location unless it appears verbatim in that context.
If the only "evidence" would be a generic statement, treat it as category-level.

## Issue sourcing
- If the research gives a concrete, attributable detail (courses they teach,
  their own description, campus/programme facts), write a **specific** issue and
  set `"issue_basis": "specific"`.
- If it does not, say so in the first sentence ("I looked through what is
  publicly listed for ... and found no ... I could reference specifically"),
  then use the closest category-level issue for that institution type. Set
  `"issue_basis": "category-level"`, put the evidence in `issue_evidence`, and
  repeat in `issue_note` that the issue is category-level, not researched.
- Never reuse another institution's issue paragraph verbatim. The issue must
  name this institution and its own situation.

## Subject
Name the institution and the offer, under ~70 characters. Examples:
`Licensed AutoCAD seats for <Institution>`,
`Licensed AutoCAD seats for <Institution>'s drafting batches`.
No "quick chat" subjects, no call-length wording, no grey-market licence
vocabulary, no ALL CAPS, no emoji.

## Length
50-70 words for the issue paragraph; 90-120 words for greeting + issue together
(before the offer). The offer, flyer line, CTA and sign-off are fixed and
appended verbatim.

## Return
Return ONLY a JSON object:

```json
{
  "subject": "Licensed AutoCAD seats for <Institution>",
  "greeting": "{{GREETING}}",
  "issue": "2-3 sentences: the specific evidence, then the issue that follows",
  "hook": "the first issue sentence, verbatim",
  "issue_basis": "specific | category-level",
  "issue_evidence": "what in the research supports this issue",
  "issue_note": "only for category-level: the labelled fallback note"
}
```
Return the greeting and issue only. The caller appends the offer, flyer line,
CTA and sign-off word for word, so never repeat, paraphrase or reorder them.
