# Progress Log — JARVIS AI Outreach System

## Session: Production contact enrichment (deep-enrichment layer)
**Date:** 2026-09-24 (afternoon)
**Status:** Complete

### Built (contact enrichment v2)
1. `agents/contact_enricher.py` — the production layer: ddgs multi-backend keyless website discovery (bing/ddg/google/brave failover, replaces single-selector Bing scrape), MX deliverability (dnspython, 1.1.1.1/8.8.8.8/9.9.9.9, 1h in-proc cache), libphonenumber validation (E.164, MOBILE→wa.me links, landlines excluded), 14-day disk cache at agent_output/contact_cache.json
2. `contact_finder.py`: `extra_search` injection seam + `_dns_resolves` pre-filter (kills the 9-domain × 3-retry NXDOMAIN storm) + `_decode_sucuri_cookie` (solves Sucuri CloudProxy JS gate in-process — base64 blob + fromCharCode concat eval) + probes only when search found nothing (fetch-credit fix: 8 credits were eaten by name-guessed probes before the real homepage)
3. `workflows.enrich_workflow` runs v2 after the basic hunter; report line now says "Deep enrichment: N deliverable email(s), M WhatsApp-ready phone(s) (K from cache)"; fixed `enriched` (list) read as count → `enriched_count`
4. CSV: `whatsapp` + `email_status` (deliverable) columns
5. `requirements.txt` created (fastapi, scrapling, reportlab, ddgs, dnspython, phonenumbers, websockets, uvicorn, python-multipart)

### Live proof
University of Calcutta College Street (FIT 85, previously "emails for 0" on every search) → **registrar@caluniv.ac.in, MX-confirmed deliverable**, promoted to recipient; cache re-hit 0.9s vs ~60s network; 19/19 new test suite (`test_contact_enricher.py`)

### Notes
- test_goal_state "search phrasing stays a SEARCH" is a pre-existing flake (parse_intent → live Gemini; 503 once, passed on rerun) — not from this work
- discovery latency ~3.5s/biz (ddgs auto backend); budget 40s/biz, DNS pre-filter keeps it honest

---

## Session: Selling-goal state + filter intelligence + adversarial review
**Date:** 2026-09-23 → 2026-09-24
**Status:** Complete

### Built (Phase 8 — goal state)
1. `config.get/set_active_goal` — persisted pin in config.json; what we sell is user state, not a guess
2. `icp.resolve_goal` precedence (explicit → pin → wording → profile) with `_source` stamped on a COPY; filter report ends `[goal: ...]`
3. GOAL intent: zero-API fastpath (contractions, discourse tails, clears) + Gemini `set_selling_goal` tool + registry/dispatch rows — all three surfaces
4. Web UI: `/api/goals` GET/POST, topbar chip (green/amber), panel with catalog + custom pin, live chip flip on chat-set goals

### Built (Phase 9 — gate + history)
5. `icp._not_an_organization()` — universal goal-independent gate (tail-is-head-noun grammar); replaced the auditorium/university/building patch pile; corpus test pins 16 non-customers + 6 must-stays
6. History loop closed: brain counts `judged` per type; `learned_type_rates` (min sample 8) → ±5 with visible reasons; rank() names best converters; specialist prompts carry per-goal learned block
7. `agents/test_goal_state.py` (26 checks) + corpus additions to `test_category_exclusions.py` (63 total)

### Adversarial review (fresh-eyes pass, 2026-09-24) — 6 defects found & fixed
- Contraction gap: "i'm selling X" / "we're selling X" missed the fastpath (space-before-apostrophe bug); "i now sell X" died at the guard
- Fastpath overreach: "goal keeper gloves supplier" pinned a goal (bare-whitespace match)
- Live-proved Gemini fired set_selling_goal on that exact search — root cause was MY prompt line telling it to switch goals on product-named searches; rewrote prompt + added deterministic shape-gate backstop at the emit site + empty-turn fall-through
- int→round % truncation in 5 display sites (0.29 showed as 28%)
- `learned_type_rates("")` CAD-fallback contamination → returns {}
- Stale `util.js?v=28` double-load (3 sub-imports pinned old) → all assets bumped together to v39

### Verification
- Suites: goal-state 26/26, exclusions+history 63/63, self-audit 20/20; node --check all JS
- Live UI: console clean, one copy of each module, "i'm selling autocad keys" pins via chat (chip flips green), "best goal scorers in football history" leaves the pin standing (answered as chat)
- Server restarted twice to load fixed modules; WS re-verified post-restart (11 ms connect)

## Session: Guided Campaign Mode (6-stage flow) — Build + Live Run
**Date:** 2026-09-20 → 2026-09-21
**Status:** Complete

### Built
1. `agents/campaign.py` — curation score (ICP → contactability → reviews), campaign_state.json state machine, initial/final PDF reports (fpdf, moss banner, latin-1 safe)
2. `CAMPAIGN` ActionType + `start_campaign` Gemini tool — wired through chatbot.py, action_registry.py, action_dispatch.py (all three surfaces)
3. `agents/web/campaign_ui.py` — blocking gates: checklist approval → 1-by-1 interview → drafting; ws.py claims campaign frames/answers BEFORE intent parsing (same rule as brainstorm/review)
4. Office UI: `js/campaign.js` checklist card (tick, Approve All, cancel), interview banner frames (`interview: true`), `window.wsSend` bridge, CSS in style.css; assets bumped v26→v27→v28 across index.html + all sub-imports
5. `/api/campaign` resume endpoint + client re-render on load — a saved gate survives reload
6. `/api/report/initial` + `/api/report/final` FileResponse downloads
7. `angles` param threaded through `draft_and_pdf_workflow`/`complete_outreach` — user angle leads the drafting context
8. Send leg now always writes `campaign_final_*.pdf` + persists path to campaign_final.json

### Bugs found & fixed during verification
- `save_session_data` called with swapped args (filename 2nd) — caught by dry-run script on first run
- Interview answers lost on completion (never promoted out of state['interview']) — caught by unit check; answers now copied to state['angles']
- Dry-run harness false negative: didn't budget boot frames (agent_events_replay, queue_state) — rewrote to read-until-marker
- Manually loaded session invisible to web layer (no session.json on disk) — registered it; resume_latest() then serves the right campaign

### Verification
- `py_compile` on all 9 touched Python files; `node --check` on app.js + all js/*.js
- agents/test_final_audit.py: **20/20 PASS** (run twice, after each wave of changes)
- Protocol-level WS dry run with injected fake shortlist: approve → initial PDF → interview [1/2] → pause → state intact
- Live UI (preview at ?v=28): checklist renders, zero console errors, ops feed live

### Live run: Bardhaman, West Bengal (education / AutoCAD licences)
- Stage 1: Overpass 298 raw → 10 curated (2 earlier transient-failure runs diagnosed: radius/coverage, not code)
- Stage 2: user approved top 8 (clinic + weak entry dropped) — gate honoured
- Stage 3: campaign_initial_20260921_004710.pdf
- Stage 4: interview — user skipped all 8 (research decides)
- Stage 5: 8 AI drafts → same-mold detected → hand-rewrote all 8; uniqueness gate: subjects unique, worst body shingle-Jaccard 7.4% (<15%)
- Stage 6: **1 sent** to Amex (info@amexindia.in) from jodiacwebservice@gmail.com; receipt pdfs/sent/amex_20260921_010058.pdf; final report campaign_final_20260921_010058.pdf; 7 drafts pending addresses
- Enrichment reality: contact-finder 0/9, exec 0 — OSM rarely carries SMB contacts in small towns (feeds Phase 7)

### Sender switch
- jodiacwebservice@gmail.com configured, SMTP auth verified (235) BEFORE any send
- Previous monaisnotapplicable (KANA) creds backed up in config.json as `gmail_previous`

### Open items (Phase 7)
- Uniqueness gate belongs inside draft_and_pdf_workflow, not as an out-of-band rewrite
- Google Maps provider key (Outscraper/Apify) for contact coverage
- 7 pending sends await addresses; reply-classification leg unbuilt

## Session: Architecture Refactoring
**Date:** 2026-09-03
**Status:** Complete

### Completed
1. Created `action_dispatch.py` — single entry point for all JARVIS actions
   - Handles: SEARCH, DRAFT, SEND, RESEARCH, SYNC, SCRAPE, ENRICH, STATUS, DASHBOARD, BRAINSTORM
   - Both CLI chat and menu dispatcher call this function
2. Created `category_filter.py` — extracted 60-line filtering logic from workflows.py
   - Two-stage: keyword matching (instant) + AI fallback (Gemini)
3. Updated `jarvis.py` — menu items [4]-[9] now call pipeline_handler step functions
   - 334 → 229 lines (-31%)
4. Simplified `chat_handler.py` — replaced 200-line if/elif chain with action_dispatch call
   - 360 → 173 lines (-52%)
5. Updated `workflows.py` — removed _filter_by_category (now in category_filter.py)
   - 603 → 538 lines (-11%)

### Test Results
- All 6 modified files compile successfully
- Action dispatch routes STATUS, DASHBOARD, BRAINSTORM correctly
- Category filter correctly separates education from pharmacy/cafe
- All pipeline step handlers import correctly
- Chat handler and jarvis imports work

### Git Commits
- `ca056e1` — feat: JARVIS AI outreach system — full architecture
- `4b038bf` — fix: exclude parks, playgrounds, churches from search results
- `c12d834` — feat: AI brainstorming system + growing brain knowledge store
- `eda59df` — refactor: extract action_dispatch and category_filter, simplify jarvis/chat_handler

### Playtest: AutoCAD Seller Flow
**Date:** 2026-09-03
**Status:** 49/49 passed (with web server running)

Tested:
- Brainstorm setup: profile, industry learning, location learning
- Category filter: education keeps schools, removes pharmacy/cafe
- EXCLUDE_TAGS: playgrounds, churches, govt offices filtered
- Action dispatch: STATUS, DASHBOARD, BRAINSTORM all route correctly
- Chatbot intent: greetings, help, brainstorm, edge cases
- Brain context: profile, industry, stats all present
- Session state: location, business count, profile injected
- Workflow signatures: search, pipeline, draft all accept params
- Web server: index, status API, history API all load
- WebSocket: welcome message, chat response both work
- Edge cases: long input, gibberish, special chars, SQL injection

### Next
- Wire action_dispatch into web server WebSocket handler
- Test full pipeline: search -> research -> draft -> send

### Brain Context Injection into System Prompt
**Date:** 2026-09-03
**Status:** Complete and verified

What was done:
1. Wired `brain.get_full_context()` into `chatbot._build_system_prompt()` 
2. Brain context flows as `BRAIN KNOWLEDGE:` section in Gemini system prompt
3. Seeded brain with AutoCAD profile from config.json
4. Tested: profile, industry knowledge, insights, strategies all appear in prompt
5. Tested edge case: empty brain doesn't crash (graceful degradation)
6. Gemini now sees: what we sell, who we target, pain points, what worked, insights

Verified:
- System prompt includes 1,065 chars of brain context
- Empty brain produces valid prompt (496 chars baseline)
- Session state + brain context both inject correctly
- Brain data persists across restarts (JSON files)

Git: commit 1dbc2ae

## Session 2026-09-21 (playtest & fix, part 2)

Drove the office UI as a first user: careless chat input, empty send, double-send,
history panel, mid-action reload, campaign gate edges. Found and fixed 5 defects:

| # | Defect | Fix |
|---|--------|-----|
| 1 | Mid-action reload + stalled scrape = search results silently lost (only saved after full pipeline) | `workflows.py` persists `search_results.json` right after search succeeds |
| 2 | One stalled site hung the scrape leg forever (CPU-idle, no timeout applied) | `business_enricher.py`: 30s daemon-thread watchdog per site, abandoned threads skipped |
| 3 | Pause message says "say 'campaign' to resume" but bare `campaign` started a NEW discovery overwriting the shortlist | `action_dispatch._handle_campaign` resumes open gates instead of restarting |
| 4 | Double final interview answer (or stale resumed replica) wiped stored angles | `campaign.answer_interview` merges, never replaces |
| 5 | "Initial report ready — click to download: F:\...pdf" rendered as dead text | `app.js` linkifies report paths to /api/report/{initial,final}; CSS class added |

Verified: watchdog unit test (stalled site skipped at 30s), live re-run of the
reload-mid-search flow end-to-end (13 businesses persisted, chain completed,
status correct from a new tab), resume-not-restart dispatch tests, angle-wipe
regression tests, linkifier in-page test, audit 20/20, node --check all green.
Not fixed (unsubstantiated): two /api/conversations 404s seen once in preview
logs, no reference in any source; not reproducible in-page.

## Session 2026-09-21 (resizable split)

User request: make the floor/chat split adjustable. Added a draggable splitter:

- `style.css`: .app grid gains a 0px grip track; --floor-fr drives the floor
  share (designed 1.9fr default unchanged); grip bar/dots styling, hover/
  active/focus states; grip hidden in the <=900px stacked layout.
- `index.html`: <button id=splitGrip> between floor and cmd (real button,
  keyboard-reachable per repo a11y convention).
- `app.js` initSplitter: pointer drag (clamped 0.2-6 fr), localStorage
  persistence (jarvis.floorFr) restored on load, arrow-key nudge (24px),
  Home/double-click reset, click-without-move never saves.

Bugs caught by live verification: setPointerCapture throws on stale pointer
ids (aborted drag setup, stuck is-resizing) -> try/catch, window listeners
carry the drag; raf-deferred write raced the pointerup read and saved stale
values -> synchronous style writes. Verified via simulated desktop rig
(zoom + matchMedia stub): floor 421->60px, chat 222->516px on drag, "Split
saved." activity line, clean restore, zero console errors, audit 20/20.

## Session 2026-09-21 (exclusion regression: "no colleges" ignored)

User complaint: curated list full of colleges again; wants TRAINING centers
(Dr. Kalam = the right kind). Root causes found:

1. `extract_exclusions` splitter regex lacked "no" (and "dont want"): the
   detector knew "no " but the splitter never split on it, so
   "training centers no colleges" parsed to ZERO exclusions. Same class
   as the Bandel "cllgs" bug, one marker word over. Fixed: splitter now
   knows no/not/dont want/don't want/do not want with word boundaries;
   "with no website" protected via lookbehind so target specs aren't bans;
   repeated markers ("no X and no Y") become separate ban items.
   10-case parser test all green; Bardhaman pool drops 5/6 college rows.

2. Playtest's resume-not-restart fix OVERSWALLOWED: an explicit new
   campaign request (location/category given) while a gate was open
   resumed the OLD checklist instead of running the corrected discovery —
   the second run's "success" was the old shortlist replayed. Fixed: only
   a bare "campaign" resumes; explicit intent always starts fresh.
   Both behaviors regression-tested.

3. chatbot tool spec now demands exclusions verbatim for start_campaign
   too (was only search_businesses).

Result: live re-run "training centers no colleges and no universities and
no schools" -> checklist = Dr. Kalam (training) + 1 clinic leaked by the
ICP veto (AI said unlikely, ICP 'plausible' resurrected it — known veto
policy tension, surfaced to user via the checklist gate rather than fixed
by policy change). Audit 20/20 after changes.
