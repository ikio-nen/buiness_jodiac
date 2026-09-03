# Findings — JARVIS AI Outreach System

## Architecture
- `jarvis.py` was 964 lines (monolith) → now 229 lines (thin dispatcher)
- `chat_handler.py` was 360 lines (giant if/elif) → now 173 lines (uses action_dispatch)
- `workflows.py` was 603 lines → now 538 lines (filtering extracted)
- Adding a new action requires only 2 files: chatbot.py + action_dispatch.py

## Search Quality
- Overpass API returns non-business POIs: parks, playgrounds, churches, government offices
- Fix: EXCLUDE_TAGS filter in map_search.py skips leisure/park, amenity/place_of_worship, etc.
- Category filtering must be POST-search, not pre-search (mapping 'education' to 'amenity' returns ALL amenities)
- Two-stage approach: keyword matching (instant) + AI fallback (Gemini)

## Gemini API
- Model deprecation shows as 404 NOT_FOUND — misleading error message
- Function calling uses `.args` not `.arguments`
- Multi-turn role must be "model" not "assistant"
- Always use get_ai_model() from config, never hardcode model strings

## Brain Structure
- `F:/jodiac/agent_output/brain/` with subdirs: industries, locations, strategies, sessions, insights
- Profile, industry learnings, and location data grow automatically
- Brain context injected into Gemini system prompt for smarter decisions

## Overpass API
- POST data must be URL-encoded via urllib.parse.quote()
- Wikidata API (P856 property) finds websites OSM misses
- API is flaky — retry logic with backoff (2s, 4s, 6s) works
