<!-- version: 1 -->
Collapse the raw snippets about ONE business into a compact profile.

Return ONLY a JSON object:
{"industry": "...", "size_signal": "...", "pain_point": "one likely pain point",
 "hook": "one personalization hook for outreach", "summary": "two sentences max"}

Rules:
- Ground EVERYTHING in the snippets. If a field is not evidenced, return "unknown".
- Never invent facts from the business name alone.
- The hook must reference something concrete a sender could open with.
