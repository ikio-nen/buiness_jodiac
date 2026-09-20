<!-- version: 1 -->
Extract possible decision-maker contacts from ONE business's raw page text.

Return ONLY a JSON object:
{"candidates": [{"name": "...", "title": "...", "email": "...", "confidence": 0.0-1.0}]}

Rules:
- Only people who appear to be owners/decision-makers (owner, founder, director,
  principal, CEO, correspondent, secretary).
- Emails must appear verbatim in the text — never construct one.
- Empty candidates list is a valid answer.
