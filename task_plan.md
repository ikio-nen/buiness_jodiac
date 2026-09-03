# JARVIS AI Outreach System — Master Plan

## Goal
Build an intelligent business outreach system that finds businesses, researches them, drafts personalized emails, and sends them — with an AI brain that gets smarter over time.

## Current Status
The system is functional with Gemini-first chatbot, conversation memory, FastAPI web UI, brainstorming, and a growing brain. Architecture was just refactored to reduce duplication.

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

### Phase 3: Integration & Polish 🔄 In Progress
- [x] Exclude parks/playgrounds/churches from search results
- [ ] Wire action_dispatch into web server WebSocket handler
- [ ] Verify full pipeline works end-to-end (search → research → draft → send)
- [ ] Test brainstorm flow in CLI mode

### Phase 4: Brain Expansion 🔲 Not Started
- [ ] Auto-learn from each session (save session summary to brain)
- [ ] Inject brain context into Gemini system prompt
- [ ] Add industry insights from research to brain
- [ ] Track email performance (sent/opened/replied) in brain

### Phase 5: Advanced Features 🔲 Not Started
- [ ] Outcome tracking (which emails got responses)
- [ ] Multi-location search (search several cities at once)
- [ ] Email A/B testing (draft 2 versions, track which works)
- [ ] Obsidian vault auto-sync after each session

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

## Next Step
Wire action_dispatch into web server, then run full end-to-end playtest.
