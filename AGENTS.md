# AGENTS.md — Learnings for Future Sessions

## Environment

- Python is at `E:\python.exe`, NOT system python. Always use `"E:\python.exe"` in commands.
- Windows default encoding is cp932 — use `encoding="utf-8"` in all `read_text()`/`write_text()` calls or em dashes and special chars crash.
- `json.dumps()` on Windows: add `ensure_ascii=True` to avoid cp932 encoding errors when writing to files.
- Node.js v24.20.0 + npm 10.2.5 available. OmniRoute (AI gateway) installed globally but has dependency issues — needs `tsx` and `ws` packages.
- Starting background processes on Windows: `Start-Process -RedirectStandardOutput` and `-RedirectStandardError` MUST go to different files or it fails silently. Git Bash `start //B ""` works for backgrounding.

## Gemini API

- Model `gemini-2.0-flash` is dead. `gemini-2.5-flash` deprecated for new users. Use `gemini-3.5-flash-lite`.
- `client.models.generate_content(config=...)` requires `types.GenerateContentConfig` object, NOT a plain dict. Dicts fail silently.
- API returns 503 under load — transient, retry works. Free tier until Dec 2026.
- API key stored in `F:/jodiac/agent_output/config.json` under `gemini_api_key`.
- Gemini model deprecation error says `404 NOT_FOUND` but the real cause is a dead model name. Always use `get_ai_model()` from config, never hardcode model strings.
- Gemini function calling: `response.candidates[0].content.parts[0].function_call.name` and `.args` (not `.arguments`). Check `hasattr(part, "function_call") and part.function_call` before accessing.
- Gemini `contents` format for multi-turn: `{"role": "user"|"model", "parts": [{"text": ...}]}`. Role must be `"model"`, NOT `"assistant"`.

## Overpass API (Map Search)

- POST data must be URL-encoded via `urllib.parse.quote()`. Raw POST silently returns empty results.
- API is flaky — add retry logic (3 attempts with 1s delay).
- Wikidata API (P856 property) finds websites OSM misses — essential for the "no site" detection that was broken (DBB Bandel bug).
- Overpass returns non-business POIs: parks (`leisure=park`), playgrounds (`leisure=playground`), churches (`amenity=place_of_worship`), government offices (`amenity=townhall`). Filter them out with EXCLUDE_TAGS in `map_search.py`.
- Category filtering is POST-search, NOT pre-search. Mapping 'education' to `amenity` tag returns ALL amenities (hospitals, restaurants). Correct: search ALL categories, then filter results by category keywords/AI.

## Scrapling (Web Scraping)

- `Fetcher.get().get_text()` does NOT exist — use `get_all_text()`.
- Basic `Fetcher` works for most sites. `StealthyFetcher` needed for Cloudflare-protected sites.
- SSL cert errors are common on Indian business sites — wrap in try/except, don't let them crash the pipeline.

## Architecture

- **Config single source of truth**: `F:/jodiac/agent_output/config.json` holds all settings. `agents/config.py` owns all access via `get_*/set_*` functions.
- **Knowledge base**: `F:/jodiac/agent_output/knowledge_base/` — 4 JSON files. Never delete this directory.
- **Brain**: `F:/jodiac/agent_output/brain/` — AI's growing knowledge store. Subdirs: `industries/`, `locations/`, `strategies/`, `sessions/`, `insights/`. Profile in `profile.json`. Grows automatically from brainstorming and sessions.
- **Obsidian vault**: `D:/brain/brain/` — 7 note types with cross-links. Sync runs after every outreach session.
- **Business profile** lives in config.json under `business_profile` key. Flows into AI prompts via `get_business_context()`.
- **Industry research cache**: `knowledge_base/industry_research.json` — new industries researched via Gemini and cached. Empty string categories must return fallback immediately (was caching `""` as a real industry).
- **jarvis.py** is now a thin dispatcher (~330 lines). Heavy logic lives in: `pipeline_handler.py`, `chat_handler.py`, `setup_handler.py`, `dashboard_handler.py`.

## Chatbot Patterns

- Greeting patterns MUST be checked BEFORE help patterns — "how do i" matches HELP and would catch "hi" if greetings aren't first in the chain.
- `parse_intent()` is Gemini-first (not regex-first). Greetings, help, and brainstorm are checked locally for speed, everything else goes through Gemini with function calling.
- Chat memory (`chat_memory.py`) stores all messages in SQLite at `F:/jodiac/agent_output/memory/conversations.db`. Use `get_memory(session_id)` to get the active memory instance.
- The chatbot passes conversation context (last 10 messages) AND session state (businesses found, drafts, profile) to Gemini so it can reference earlier turns.
- SQLite uses `PRAGMA journal_mode=WAL` for concurrent reads/writes (CLI + WebSocket can access the same DB). Close connections in `finally` blocks to prevent leaks on WebSocket disconnect.
- Adding a new ActionType requires updating THREE files: `chatbot.py` (parsing + function call handler), `chat_handler.py` (CLI dispatch), `web/server.py` (WebSocket dispatch).

## Web UI (FastAPI)

- FastAPI + WebSocket server at `agents/web/server.py`. Start with `python -m agents.web.server` or press `[W]` in main menu.
- Port 8765 (default). If port is busy, kill existing process or change port in `server.py`.
- Static files in `agents/web/static/`: `index.html`, `style.css`, `app.js`. Black/red/white terminal theme.
- WebSocket endpoint at `/ws` for real-time chat. Sends JSON messages with `type` field (jarvis/thinking/progress/search_result/draft_result/send_result/research_result/error).
- The chat UI uses Gemini for ALL intent parsing (not regex). Greetings and help are fast-pathed locally.
- `chat_handler.py` is the CLI mode (menu `[C]`). Web UI goes through `web/server.py` WebSocket handler independently.
- Business profile context flows into Gemini system prompt automatically.

## Cleanup Safety

- `cleanup_raw_files()` only deletes files matching prefixes: `test`, `legacy`, `flat-`, `nested-`, `nosite-`, `script-`. User-generated sites are NEVER deleted.
- Cleanup shows warning before deleting: "Rest businesses data will be deleted!"
- Summary PDF is always preserved. Knowledge base is always preserved.

## User Preferences (Zyphr)

- Business: sells AutoCAD product keys with official licenses.
- Targets: educational centers, training institutes, engineering colleges.
- Wants self-learning system that improves with each session.
- Wants session wizard (name, product, target, tone) instead of just project name.
- Wants per-business file attachments and full email editing before send.
- Wants JARVIS to research each business (Google reviews, what they're missing) and include insights in emails.
- Prefers persistent memory across sessions — system should remember style and get smarter over time.
- UI preference: black/red/white theme, animated, cyberpunk terminal aesthetic.

## File Changes That Must Move Together

- `config.py` + `config.json`: adding a new config field requires updating both the getter/setter functions AND the default in `get_business_profile()`.
- `chatbot.py` + `jarvis.py`: adding a new ActionType requires updating BOTH the pattern matching in chatbot AND the dispatch handler in jarvis.py.
- `ai_design.py` + `medium.py`: changing email prompt structure requires updating BOTH agents (AI and template) to stay consistent.
- `industry_learner.py` + `ai_design.py` + `medium.py`: industry context flows from learner → both email agents. All three must agree on the data format.
- `chatbot.py` + `chat_handler.py` + `web/server.py`: all three parse user intent. If you change ActionType or add new actions, update ALL three (chatbot for parsing, chat_handler for CLI dispatch, web/server.py for WebSocket dispatch).
- `chat_memory.py`: used by both `chat_handler.py` (CLI) and `web/server.py` (WebSocket). Schema changes require both consumers to be updated.
