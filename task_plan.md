# JARVIS AI Outreach System — Master Plan

## Goal
Build an intelligent business outreach system that finds businesses, researches them, drafts personalized emails, and sends them — with an AI brain that gets smarter over time.

## Current Status
Functional end to end and live-proven (2026-09-24). Everything below plus the **selling-goal system** — what JARVIS sells is pinned user state, never guessed from search wording — a **universal non-organization gate** that kills OSM structure records (buildings/grounds/venues) by noun-phrase grammar, **history-driven targeting** where the brain's 13k-judged conversion history now moves rankings and specialist prompts, and **production contact enrichment**: ddgs multi-backend site discovery, MX-validated emails, libphonenumber phones with WhatsApp links, 14-day cache, Sucuri anti-bot solving. Live proof: the FIT-85 university that every search returned "0 emails" for now gets registrar@caluniv.ac.in (MX-confirmed). Suites: contact-enricher 19/19, exclusions+history+memory 73/73, goal-state green (one pre-existing Gemini flake), self-audit 20/20.

## Phases

### Phase 1: Core System ✅ Complete
- [x] Gemini-first intent parsing with function calling
- [x] SQLite conversation memory with auto-titling
- [x] FastAPI + WebSocket real-time chat UI
- [x] Session wizard (name, product, target, tone)
- [x] Business research pipeline (Google Maps + Gemini)
- [x] Email review workflow (edit, attach, approve)
- [x] Brainstorming system + growing brain knowledge store
- [x] Category-aware search filtering (keyword + AI)

### Phase 2: Architecture Cleanup ✅ Complete
- [x] Extract action_dispatch.py (single entry point for actions)
- [x] Extract category_filter.py (filtering logic)
- [x] Move inline workflow steps from jarvis.py to pipeline_handler.py
- [x] Simplify chat_handler.py (360 → 173 lines)

### Phase 3: Integration & Polish ✅ Complete
- [x] Exclude parks/playgrounds/churches from search results
- [x] Wire action_dispatch into web server WebSocket handler (dispatch_bridge.run_action in web/ws.py)
- [x] Verify full pipeline works end-to-end (live: Bardhaman search→research→draft→send)
- [x] Test brainstorm flow in CLI mode (chat_handler inline path + parser audit)

### Phase 4: Brain Expansion ✅ Complete
- [x] Auto-learn from each session (learn.py hooks + brain.learn_business on search/draft/send)
- [x] Inject brain context into Gemini system prompt (BRAIN KNOWLEDGE section)
- [x] Add industry insights from research to brain
- [ ] Track email performance (sent/opened/replied) in brain → moved to Phase 7

### Phase 5: Advanced Features 🔸 Partially Done
- [ ] Outcome tracking (which emails got responses) → Phase 7
- [ ] Multi-location search (search several cities at once)
- [ ] Email A/B testing (draft 2 versions, track which works)
- [x] Obsidian vault auto-sync after each session (obsidian_sync in complete_outreach)

### Phase 6: Guided Campaign Mode ✅ Complete (2026-09-21)
- [x] agents/campaign.py — curation score, session-dir state machine, initial+final PDF reports
- [x] CAMPAIGN ActionType + start_campaign Gemini tool (chatbot.py, action_registry.py, action_dispatch.py)
- [x] web/campaign_ui.py — blocking checklist gate + 1-by-1 interview (ws.py routing, dispatch_bridge hook)
- [x] Interactive checklist card in office UI (js/campaign.js, v28 assets) + /api/campaign resume-on-reload
- [x] /api/report/initial + /api/report/final download endpoints
- [x] angles param threaded through draft_and_pdf_workflow / complete_outreach
- [x] Sender switched to jodiacwebservice@gmail.com (SMTP auth 235; old creds backed up in config as gmail_previous)
- [x] Live run: Bardhaman — 298 found → 10 curated → 8 approved → 8 unique drafts (7.4% max overlap) → 1 sent, 7 pending addresses

### Phase 7: Campaign Hardening 🔲 Not Started
- [ ] Move draft-uniqueness gate into draft_and_pdf_workflow itself (prompt constraint + 15% shingle post-check)
- [ ] Google Maps provider key (Outscraper/Apify) so small-town searches surface real emails/phones
- [ ] Reply classification + follow-up scheduling on incoming responses
- [ ] Send the 7 pending Bardhaman drafts once addresses exist

### Phase 8: Selling-Goal State ✅ Complete (2026-09-24)
- [x] Persisted goal state: config.get/set_active_goal (config.json), never inferred silently
- [x] icp.resolve_goal precedence: explicit per-search → PINNED goal → search wording → profile product; every resolution stamps `_source` on a COPY (registry never mutated)
- [x] GOAL intent on all three surfaces: chatbot fastpath (zero API) + Gemini `set_selling_goal` tool + registry/dispatch rows; custom goals store the user's phrase verbatim without touching profile product
- [x] Filter report ends `[goal: active goal | search wording | ...]` — misattribution is diagnosable in one line
- [x] Web UI: /api/goals GET/POST, topbar goal chip (green=pinned, amber=auto), panel with catalog + custom pin, live chip update on chat-set goals
- [x] Gemini retaught: "web design clients" is WHO we target, not WHAT we sell

### Phase 9: Filter Intelligence — universal gate + history loop ✅ Complete (2026-09-24)
- [x] Rebuilt the auditorium/university/building patch-pile into ONE deterministic gate: `icp._not_an_organization()` — the noun-phrase TAIL is the head noun ("University Hostel 3" is a hostel), comma segments checked individually, strong venue words anywhere with an operator-noun escape ("Red Town Hall Cafe" survives)
- [x] Corpus regression test: 16 non-customer entities (venues, civic buildings, campus structures, grounds, gates) + 6 must-stays in one block
- [x] brain.learn_icp_feedback counts `judged` per institution type (denominators for real conversion rates)
- [x] icp.learned_type_rates (MIN_TYPE_SAMPLE=8): ≥50% → +5, <20% → −5, middling silent; every adjustment carries a visible "history: N% of judged..." reason
- [x] rank() report names best-converting types; scout/strategist/analyst prompts carry a per-goal "WHAT PAST SESSIONS TAUGHT US" block
- [x] Adversarial review (2026-09-24): contraction gap ("i'm selling X"), "i now sell X" guard miss, `goal <search>` overreach, self-contradicting goal-switch prompt line + deterministic shape-gate backstop at the emit site, silent-dead-end fall-through, int→round % truncation ×5, learned_type_rates("") CAD-fallback contamination, stale util.js?v=28 double-load (all fixed; assets → v39)

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Gemini-first chatbot (not regex) | Complex multi-step requests need AI understanding |
| SQLite for memory (not file-based) | Concurrent reads from CLI + WebSocket |
| FastAPI for web UI (not Flask) | Native WebSocket support, async |
| action_dispatch as single entry point | Eliminates 3-way duplication across chat/menu/web |
| Category filtering is post-search | Overpass returns all categories; filter after |
| Goal = pinned state, never per-search inference | "i sell websites" as a standing misbelief came from wording guesses; user state must outrank the parser |
| Place-name gate is goal-independent grammar, not per-goal name lists | One universal rule kills every future structure-record leak; per-goal lists need a new patch per leak family |
| History adjusts scores only WITH a visible reason | Learning that silently biases ranking is indistinguishable from a bug |
| AI goal-calls pass a deterministic shape gate | Prompt rules alone demonstrably failed live: Gemini fired set_selling_goal on 'goal keeper gloves supplier' |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Gemini 404 NOT_FOUND on model name | 1 | Use get_ai_model() from config, never hardcode |
| Overpass returns parks/churches as businesses | 1 | Add EXCLUDE_TAGS filter in map_search.py |
| Category mapping returns all amenities | 1 | Search ALL categories, then filter results |
| Port 8765 already in use | 1 | Kill existing process, restart |
| save_session_data arg order (filename before data) | 1 | campaign.py \_save passed dict where path expected — swapped to (sid, data, name) |
| Campaign interview answers lost on completion | 1 | answers lived only in state['interview']; promote to state['angles'] when phase→drafting |
| AI drafts same-mold across batch | 1 | Hand-rewrote 8 drafts; uniqueness gate (shingle Jaccard <15%) — move into Phase 6 workflow |
| OSM has no emails for small-town institutions | 1 | Accepted: contact-finder+exec pass run, rest flagged; Phase 7 adds Maps provider |
| WS dry-run false negative (frame budget) | 2 | Boot frames replay+queue_state arrive after welcome; read-until-marker instead of fixed counts |
| /api/campaign served stale fake gate | 1 | resume_latest() only sees registered sessions — wrote session.json for the campaign session |
| Goal fastpath missed contractions ("i'm selling X") | 1 | Regex required a SPACE before 'm/'re; restructured with apostrophe forms as their own alternative |
| "goal keeper gloves supplier" pinned a goal | 2 | _GOAL_PREFIX_RE allowed bare whitespace; then Gemini's own tool call repeated it — prompt line rewritten + shape gate at emit |
| My own prompt told Gemini to switch goals on product-named searches | 1 | Self-contradiction with the never-guess rule; model resolved it wrong live. Rewritten + deterministic backstop |
| Backstop emptied the action list on goal-only misfires | 1 | Return [] is a silent dead end; fall through to the text reply instead |
| 0.29 displayed as 28% | 1 | int(rate*100) truncates float multiply; round() in all 5 sites |
| learned_type_rates("") returned CAD history | 1 | Empty key must return {} — fallback leaked one goal's history into another |
| util.js loaded twice (v=28 + v=38) | 1 | 3 sub-imports pinned at old version; bump ALL asset URLs together on content change (v39) |

## Next Step
Await user direction. Recommended next moves: (a) Phase 7 hardening (Outscraper/Apify key for the small-town contact gap), or (b) let the history loop accumulate a few live searches, then evaluate whether type-rate bonuses measurably improve kept-list quality before adding per-location rates or decay.
