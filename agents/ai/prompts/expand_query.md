<!-- version: 1 -->
Propose refined search queries for finding businesses that fit what we sell,
given a seed query and what past searches taught us.

Return ONLY a JSON object:
{"queries": ["up to 5 improved or additional queries"],
 "rationale": "one sentence on what the learnings changed"}

Rules:
- Keep queries runnable against Maps/Overpass: place-based, category-oriented.
- Use the learnings: avoid what returned junk, lean into what produced fits.
- If learnings are empty, sharpen the seed query only.
