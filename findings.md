# Findings — JARVIS AI Outreach System

## Guided Campaign Mode (2026-09-21)
- **Curation score is a tuple, not a model**: `(icp_rank, has_email, has_phone, -reviews, name)` — deterministic, explainable, no AI drift. ICP verdict stays the sole judge; contactability breaks ties.
- **Blocking gates must survive reloads**: a gate that only exists in a WS conversation dies with the tab. Fix: gate state lives in the session dir (campaign_state.json) + `/api/campaign` lets a fresh page re-render it. Rule: conversation state in `_states[ws_id]`, durable state in the session dir.
- **resume_latest() only sees registered sessions** — a session built via `Session().load()` in a script never appears in the web UI until `session.json` exists on disk.
- **Campaign frames must be claimed before intent parsing** in ws.py (same rule as brainstorm/review): an interview answer is never a new command.
- **AI drafts converge on one skeleton when batched** — 8 Gemini drafts came out same-mold (subject prefix identical, para structure identical). Name-swap personalization is not uniqueness. Fixed by hand-rewrites; permanent fix (Phase 7) = prompt constraint + shingle-Jaccard check inside draft_and_pdf_workflow (8-char shingles, <15% threshold worked).
- **OSM contact coverage is the small-town bottleneck**: 298 businesses → 1 email. contact_finder (website hunt) and exec_finder both 0. Google Maps provider (Outscraper/Apify) is the real fix; config already has get_apify_token/get_outscraper_key getters and gmaps_source.py failover path.
- **save_session_data signature** is `(session_id, data, filename)` — filename second silently produced a TypeError against a dict; py_compile can't catch it, only execution did.
- **fpdf exports stay latin-1**: every PDF writer funnels text through `_latin1()`; em-dashes in AI/hand-written bodies crash Helvetica otherwise.
- **WS test harnesses**: after connect, a welcome burst (jarvis, agent_events_replay, queue_state) always precedes action replies — read-until-marker, never fixed frame counts.
- **Windows bg processes**: `Start-Process -RedirectStandardOutput/-RedirectStandardError` must point at DIFFERENT files; a `cmd &` inside a SYNC command holds the pipe until timeout even though the child survives.

## Architecture

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
