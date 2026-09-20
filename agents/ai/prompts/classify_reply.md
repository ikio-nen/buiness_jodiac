<!-- version: 1 -->
Classify ONE inbound reply to our outreach.

Return ONLY a JSON object:
{"intent": "interested|not_interested|objection|out_of_office|wrong_person|unknown",
 "next_action": "the single most useful follow-up, e.g. 'send case study, ask for a call'",
 "confidence": 0.0-1.0}

Rules:
- Judge from the reply text; use thread context only to disambiguate.
- "unknown" plus a manual-review action is a valid answer — never force a guess.
