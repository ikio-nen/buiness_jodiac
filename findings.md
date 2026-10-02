# Findings — JARVIS AI Outreach System

## Selling-Goal State (2026-09-23/24)
- **The original misbelief was inference, not storage**: the profile was always right (AutoCAD keys); the Gemini parser GUESSED the goal from each search's wording ("web design *clients*" → goal=websites) and nothing user-settable could override it. Fix shape: persisted pin → resolution precedence → visible `_source` stamp. Don't fix a wrong-belief bug by editing the belief; fix who gets to SAY what the belief is.
- **Precedence order that works**: explicit per-search goal (real declarations only) → pinned active goal → search wording → profile product. The pin must sit ABOVE wording or a stale parser guess bypasses it structurally.
- **Custom goals store the PHRASE verbatim** ("laptops"), resolved as a custom goal whose product is that phrase — never clobber `profile.product`, which is the stable identity; the pin is a mutable overlay on top.
- **Pinning regexes need three separate allowances**: no space before contractions (`i'm` ≠ `i 'm`), guard and matcher must know the same verb forms (the guard rejected `i now sell` before the good regex ever ran), and `goal` + bare whitespace must NOT match (searches contain the word "goal").
- **Discourse tails on statements**: "i'm selling laptops NOW" pins `laptops` — strip trailing now/instead/also/these days before storing.
- **A prompt line can be the bug**: "if their search names a different product, assume they are switching goals" contradicted the never-guess rule two lines later; Gemini resolved the contradiction live by firing set_selling_goal on "goal keeper gloves supplier". Deterministic shape-gate at the emit site now backstops the model: AI goal-calls survive only if the message has statement shape ANYWHERE (looser than the fastpath's full-match, so multi-part turns still work).
- **A dropped action must not leave an empty action list** — parser returning [] is the documented silent dead end; fall through to the text reply.

## Universal Place-Name Gate (2026-09-24)
- **The patch-pile anti-pattern is real**: auditorium fix → university fix → building fix, each a per-leak-family name list. Rebuilt as ONE goal-independent rule: a name that is a place, not an organization, is not a customer for ANY goal.
- **Noun-phrase grammar is the engine**: the TAIL is the head noun. "University Hostel 3" is a hostel (a university owns it; the university has its own record — keeping structure records double-counts the campus). "St. Xaviers College Main Building" is a building despite the org noun — my first escape hatch for org nouns was wrong-headed (literally looking at the head of the phrase).
- Each comma segment needs its own tail check ("Main Gate, Rajabazar Campus" hides 'gate' before the comma); trailing numbering must be cleaned off ("block - 3", "wing c") or the tail check misses.
- **Strong venue words anywhere** (auditorium/bhawan/planetarium/museum/town hall) catch venue-tenant hybrids ("Ambedkar Bhawan - Cultural Research Institute"), with an operator-noun escape so "Red Town Hall Cafe" survives.
- Probe gotcha: `_not_an_organization` is called on LOWERCASED names in production; testing it with mixed-case names gives different results and "false" failures.

## History-Driven Targeting (2026-09-24)
- **The brain accumulated 13,234 judged / 1,406 fits for CAD** — schools 793×, colleges 462× — and none of it reached anything: no denominators (no rate computable) and the formatter wired only into the chatbot blur. A learning loop that only accumulates is dead weight.
- Rate design: MIN_TYPE_SAMPLE=8 (below that the sample says more about where we searched than what converts); ≥50% → +5, <20% → −5, in between SILENT (a mediocre record is not evidence in either direction). Every adjustment lands in the card's reasons.
- `learned_type_rates("")` must return {} — a CAD fallback for an empty key would leak one goal's history into another's ranking (all behavior is per-goal).
- `int(rate*100)` truncates on float multiply (0.29→28%); use `round()` in every display site.

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
