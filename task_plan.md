# JARVIS AI Outreach System — Master Plan

## Goal
Build an intelligent business outreach system that finds businesses, researches them, drafts personalized emails, and sends them — with an AI brain that gets smarter over time.

## Current Status
Functional end to end and live-proven (2026-09-21): Gemini-first chatbot, agent-office web UI (Ghibli pixel floor, v28 assets), growing brain, and the **Guided Campaign Mode** — a 6-stage flow (discover→checklist→initial PDF→1-by-1 interview→unique drafts→send+final PDF) — built, audited 20/20, dry-run tested at the WS protocol level, and executed for real on Bardhaman (1 sent via jodiacwebservice@gmail.com, 7 drafts pending contact addresses).

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

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Gemini-first chatbot (not regex) | Complex multi-step requests need AI understanding |
| SQLite for memory (not file-based) | Concurrent reads from CLI + WebSocket |
| FastAPI for web UI (not Flask) | Native WebSocket support, async |
| action_dispatch as single entry point | Eliminates 3-way duplication across chat/menu/web |
| Category filtering is post-search | Overpass returns all categories; filter after |

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

## Next Step
Await user direction on Phase 7 (hardening) — recommended first move: Outscraper/Apify key setup to fix the small-town contact gap.
