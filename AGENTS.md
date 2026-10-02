# AGENTS.md — Learnings for Future Sessions

## Environment

- Python is at `E:\python.exe`, NOT system python. Always use `"E:\python.exe"` in commands.
- Portable data roots (added 2026-10-02): `JODIAC_HOME` env replaces the `F:/jodiac` drive letter (`OUTPUT_DIR = JODIAC_HOME/agent_output`); `JODIAC_OBSIDIAN` replaces `D:/brain`. Unset = old paths, so the F:/D:/ laptop is unaffected. The import-time mkdir loop raises a helpful OSError naming JODIAC_HOME when the drive is missing instead of a bare traceback.
- Windows default encoding is cp932 — use `encoding="utf-8"` in all `read_text()`/`write_text()` calls or em dashes and special chars crash.
- `json.dumps()` on Windows: add `ensure_ascii=True` to avoid cp932 encoding errors when writing to files.
- Node.js v24.20.0 + npm 10.2.5 available. OmniRoute (AI gateway) installed globally but has dependency issues — needs `tsx` and `ws` packages.
- Starting background processes on Windows: `Start-Process -RedirectStandardOutput` and `-RedirectStandardError` MUST go to different files or it fails silently. Git Bash `start //B ""` works for backgrounding.
- The run_terminal_command tool has no working `BACKGROUND` process_type (errors "not implemented") — detach with `powershell (Start-Process ... -PassThru).Id > /tmp/pid.txt`, then poll the pid and port in a follow-up command.
- The project's self-check suite is `agents/test_final_audit.py` (20 checks) — there is no `agents/test_audit_suite.py`. Run `"E:/python.exe" -X utf8 agents/test_final_audit.py`.
- The `websockets` package IS installed in `E:\python.exe` — drive `/ws` at the protocol level (send raw `{"type": ...}` frames) to test server handlers a browser can't reach, e.g. stale/malformed frames.

## Gemini API

- Model `gemini-2.0-flash` is dead. `gemini-2.5-flash` deprecated for new users. Use `gemini-3.5-flash-lite`.

## AI Providers (multi-model routing)

- `agents/ai/providers.py` is the OpenAI-compatible transport behind the seam; `ai_engine.generate`/`gemini_client.converse` route to it ONLY when `config.ai_provider != "gemini"` (`providers.provider_active()`), and fall back to Gemini on provider failure (proven live). Gemini stays the default and untouched path.
- Providers: `ollama` (local, http://127.0.0.1:11434/v1, ~30s cold-load per model — timeout is 120s for this), `opencode_zen` (https://opencode.ai/zen/v1), `vercel_gateway` (https://ai-gateway.vercel.sh/v1). Switch: `set_ai_provider('ollama')` + `set_ai_provider_model('qwen2.5:3b')` in `agents/config.py`.
- No-cost reality (checked 2026-09-21): Vercel gateway key validates but completions are BLOCKED until a card is added on vercel.com (their `customer_verification_required`). OpenCode Zen's free tier only serves from inside the OpenCode client (`FreeTierError`); glm/gpt/claude need the user's OpenCode API key in `AI_PROVIDER_KEY` env or `config.ai_provider_key`. Only truly-$0: `inclusionai/ling-3.0-flash-*-free`, `poolside/laguna-s-2.1-free` on Vercel; `deepseek-v4-flash-free`, `nemotron-*-free`, `ling-*-free`, `mimo-v2.5-free` on Zen (still key-gated).
- Free-provider cascade (added 2026-10-02, `agents/ai/providers.py`): `PROVIDER_PRESETS` names every free OpenAI-compat provider — `zai` (glm-4.7-flash permanently $0), `groq` (llama-3.3-70b-versatile), `deepseek`, `openrouter` (…`:free`), `huggingface`, `nvidia`, `mistral`, `pollinations` (KEYLESS, weak tools), plus legacy `ollama`/`opencode_zen`/`vercel_gateway`. `set_ai_provider_fallbacks([...])` sets the chain; one call runs on ONE provider — first of `[primary, *fallbacks]` that completes it. Skip-across-providers on 429/5xx/transport/401/403/404 (free-tier model IDs rotate; a dead key must not kill the pipeline); other 4xx raise immediately (request-shape bug). When all are skipped the error propagates and `ai_engine` falls back to Gemini (existing rule). Preset `model` is the free default when `ai_provider_model` is unset (fallbacks always use their preset); `ai_provider_base_url` overrides the PRIMARY only. Per-provider keys: `AI_PROVIDER_KEY_<NAME>` env (e.g. `AI_PROVIDER_KEY_GROQ`) > `AI_PROVIDER_KEY` env > manual config — no setter by design, never in git. `providers.status()` now also reports `chain`. Self-check: `agents/test_provider_cascade.py` (12 checks, stubbed transport, no keys/network).
- opencode_zen is DEAD (2026-09-17: 403 outside the OpenCode client) — kept in presets only so old configs don't crash; never select it. GitHub Models retired 2026-07-30; Chutes/Novita/SambaNova free tiers ended 2026 — do not add them as presets.

## Database (SQLite seam)

- `agents/db.py` owns the one SQLite file (`OUTPUT_DIR/jodiac.db`, so `JODIAC_HOME` moves it too) — stdlib `sqlite3`, zero new deps. WAL mode + `PRAGMA foreign_keys=ON`, one short-lived connection per call (no shared-connection threading hazards), same pattern as `chat_memory.py`. Migrations are idempotent and versioned in `schema_migrations`.
- `agents/store.py` is the only data-access layer: plain dicts in/out, `upsert_business` (dedup on session_id+ext_id), `list_businesses` (verdict filter), `save_email`/`mark_email_sent`/`list_emails`, `register_session`/`get_session`, `log_usage`, `usage_stats`, `provider_stats`. Every function degrades to safe defaults on DB failure — telemetry can never break the pipeline (same rule as the event bus).
- v1 tables: `businesses`, `emails` (drafts + sent, FK to businesses), `sessions` (registry), `usage` (per AI call incl. serving `provider` — the grading feed for the provider cascade). Session JSON files are NOT migrated yet — the DB is additive in v1; cutover is a future step.
- `usage_log.record` dual-writes: JSONL stays the source of truth, the DB mirror adds the serving provider (`gemini` when used_gemini else the active cascade provider). `provider_stats()` gives per-provider calls + ok-rate — this is what grades the free-provider cascade over time.
- Self-check: `agents/test_db.py` (7 checks, real SQL against a tmp DB, stubbed config).

## Outreach APIs (free tier)

- `agents/outreach_apis.py` — thin stdlib-urllib clients, zero new deps, env-only keys (never in git): `resend_send` (3k/mo free, no card), `brevo_send` (300/day free, volume backup), `tavily_search`/`tavily_extract` (1k credits/mo recurring, no card), `geoapify_geocode`/`geoapify_places` (3k credits/day, no card — the zero-card Google Places substitute, phone/website fields, caching allowed), `reacher_verify` (self-hosted Reacher at `REACHER_URL`, default localhost:8080, truly $0 unlimited). Every function returns a dict, never raises — failures are `{"error": ...}`. `research_search()` prefers Tavily when keyed, else keyless ddgs. `status()` reports readiness as booleans only (never key material).
- Env vars: `RESEND_API_KEY`, `BREVO_API_KEY`, `OUTREACH_FROM_EMAIL`, `TAVILY_API_KEY`, `GEOAPIFY_API_KEY`, `REACHER_URL`.
- `outreach.py` send chain is now smtp → **resend** → sendgrid (Resend first: free tier beats SendGrid's trial-only). Apify was already wired in `gmaps_source.py` (token via `get_apify_token()`); Hunter.io stays the email-finding path in `medium.py`.
- Self-check: `agents/test_outreach_apis.py` (8 checks, stubbed transport asserting URLs/headers/payloads).
- Tool loop: Gemini `types.Tool`/`types.Content` translate to OpenAI tools/messages in providers.py (`_tools_to_openai`, `_contents_to_messages`) — `_tools_to_openai` must accept BOTH shapes: SDK `types.Tool` AND chatbot's plain `{"function_declarations": [...]}` dicts (a dict-only caller once left the provider path with zero tools → every intent parsed UNKNOWN). SDK `types.Schema` has NO `to_json_schema()` — serialize with `model_dump(exclude_none=True, mode="json")` and lowercase the type enums for the OpenAI dialect.
- Provider benchmark (2026-09-21, real parser + real campaign businesses): gemini-3.5-flash-lite 8/8 intents correct at 1.4–5s and rich grounded rationales; qwen2.5:3b via ollama 1/8 (6–9s, wrong tools, misses params, one 99s outlier). Local-only mode is NOT good enough for daily campaigns on a 3B model; a ≥8B tool-tuned local model might close the gap but is untested. Benchmark harness gotcha: `set_ai_model()` is shared with Gemini's `ai_model` — when benchmarking a non-Gemini provider, restore the saved model before the Gemini leg or the Gemini leg 404s and silently heuristic-falls-back.
- Provider keys live in env (`AI_PROVIDER_KEY`) or manual config edit — no setter by design so code paths can't persist them; keys must never enter git-tracked files.
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
- A category phrase that names NO category is not an intent to filter by. `_no_category_signal()` (Stage 1b in `category_filter.py`, judged on the post-exclusion `positive_phrase`) short-circuits the AI tier filter and lets the deterministic ICP verdict stand. Root cause: the chat parser passes `category` VERBATIM (`"find businesses in Bandel"` -> `"businesses"`), so `_ai_tier_filter` asked the model "The user is looking for: businesses" and the rubric's "unlikely" tier ate all 5 schools the ICP had just kept -- `Filtered 5 -> 0 for "businesses": ... AI dropped 5 school`, i.e. "Found 0 businesses" while the same run's ICP line said 5 plausible. Empty phrases deliberately do NOT count as signal-less (that path owns its own report), and one specific word ("business consultants", "coaching centres that teach autocad") keeps the AI judge in play. Regression suite: `agents/test_category_exclusions.py`.
- User exclusions ("remove schools and cllgs") are USER AUTHORITY in `category_filter.py`: `extract_exclusions()` parses them deterministically (typos/plurals map via EXCLUSION_LEXICON + `_KEYWORD_TYPOS`), and Stage 0 hard-drops matches BEFORE the ICP veto or the AI can resurrect them. The ICP veto (which once silently kept every AI-dropped school at 92 fit) is now surfaced in the report as "[ICP veto kept N: names]" — never let a filter stage silently override another. chatbot.py's search_businesses tool spec must pass the user's category phrase VERBATIM; synonym-expanding it there strips the exclusion half and reintroduces the Bandel failure. `_evidence_note()` carries description/operator/brand/courses tags to the AI judge so "do they teach AutoCAD" is judged from source evidence, not name strings.

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
- **Event bus**: `agents/event_bus.py` is a thread-safe pub/sub. Workflows, brain, and agent_team `emit()` telemetry; `web/ws.py` subscribes per-WebSocket and forwards as `agent_event` frames. Kinds: `bot`, `packet`, `brain`, `step`, `team`. Emit must never raise — telemetry can't break the pipeline.
- **Brain ↔ bots channel**: specialist agents (scout/strategist/analyst) have a `brain_query` tool (`agents/agent_team.py`) that keyword-searches the outreach brain (businesses, industries, strategies, insights). Prompt tells them to check brain_query BEFORE web_search for our own history.
- **Agent Ops floor**: `index.html` `#opsFloor` + `app.js` ops section animate little bots between stations on `agent_event` WS frames. Station positions are CSS %; adding a station means HTML + CSS position + `app.js` routing maps (`BOT_HOME`, packet to/from mapping).

## Gemini Service Seam (agents/ai/)

- One module owns every Gemini call: `agents/ai/service.py` (`GeminiService`). Consumers call typed capability methods (`score_fit`, `summarize_profile`, `draft_email`, `classify_reply`, `expand_query`, `extract_contact`) — never the SDK, a prompt string, or a key.
- `ai_engine.py` stays the low-level engine (key, retries, model name); `agents/ai/gemini_client.py` is the only bridge. A new AI behavior = a new capability method + a versioned prompt file in `agents/ai/prompts/` (first line must be `<!-- version: N -->`), never an inline prompt in a consumer.
- Every capability has a heuristic fallback in `fallbacks.py` (score_fit's floor is the deterministic ICP verdict — AI may only add a rationale, never override the verdict). A Gemini outage degrades, never blocks.
- `score_fit`/`summarize_profile` are memoized per business in `cache.py` (`rescore()` to invalidate); drafts and reply classifications are never cached.
- `gemini_client.converse()` owns the function-calling protocol and the retry/quota policy for BOTH the intent parser (`chatbot.py`) and the specialist agents (`agent_team.py`) — a `converse` call must be the only way a consumer reaches the model. Prompt TEXT is not the seam's business: a static capability prompt is a versioned file, a dynamic system instruction (persona/memory/skills/ICP) is assembled by the module that owns that context and passed in.
- `usage_log.py` writes one JSONL record per call under `agent_output/usage/usage.jsonl` and emits a `brain` event (`action="ai"`) the office feed renders. `stats()` gives per-capability call/gemini/fallback counts.
- Pipeline dicts → typed models go through `agents/ai/scrape_adapter.py:to_business()`; snippets carry scraped description text for grounding.

## Chatbot Patterns

- Greeting patterns MUST be checked BEFORE help patterns — "how do i" matches HELP and would catch "hi" if greetings aren't first in the chain.
- `parse_intent()` is Gemini-first (not regex-first). Greetings, help, and brainstorm are checked locally for speed, everything else goes through Gemini with function calling.
- Chat memory (`chat_memory.py`) stores all messages in SQLite at `F:/jodiac/agent_output/memory/conversations.db`. Use `get_memory(session_id)` to get the active memory instance.
- The chatbot passes conversation context (last 10 messages) AND session state (businesses found, drafts, profile) to Gemini so it can reference earlier turns.
- SQLite uses `PRAGMA journal_mode=WAL` for concurrent reads/writes (CLI + WebSocket can access the same DB). Close connections in `finally` blocks to prevent leaks on WebSocket disconnect.
- `ChatMemory` inserts its conversation row on first WRITE, not on construction, so read-only callers no longer litter the DB with empty "New conversation" rows; `conversation_exists(id)` is the public existence check that lets a read endpoint 404 instead of returning an empty list.
- `chat_memory.get_memory()` caches ONE shared `ChatMemory`; `close_memory()` (WS disconnect) closes that connection — any code still holding the cached instance crashes with "Cannot operate on a closed database". Fix lives in `ChatMemory._ensure()`: every method re-opens the connection if closed. Never assume `.conn` stays valid across a disconnect.
- Adding a new ActionType requires updating THREE files: `chatbot.py` (parsing + function call handler), `chat_handler.py` (CLI dispatch), `web/ws.py` (WebSocket dispatch) — plus one row in `agents/action_registry.py` (progress line, result-frame kind, ack-skip).

## Web UI (FastAPI)

- `agents/web/server.py` is ASSEMBLY only (~50 lines): builds the app, mounts `/static`, includes two routers, starts uvicorn. The behavior lives beside it — `api.py` (HTTP routes), `ws.py` (the socket + message routing), `job_queue.py` (per-socket action queue), `dispatch_bridge.py` (action → action_dispatch → UI frames), `review.py` (email review state machine), `web_session.py` (the one shared Session). Put a change in the module that owns it, not in `server.py`. Start with `python -m agents.web.server` or press `[W]` in main menu.
- Port 8765 (default). If port is busy, kill existing process or change port in `server.py`.
- Static files in `agents/web/static/`: `index.html`, `style.css`, `app.js` (entry) + `js/` ES modules (`util.js` = esc + activity strip, `transitions.js` = vtAppend/vtSwap, `queue.js`, `attachments.js`, `voice.js`, `music.js`). `app.js` imports them directly — `<script type="module">`, still zero-build. Two-pane agent-office: living pixel floor LEFT, command center (chat/agents/skills tabs) RIGHT (~65/35), roster strip along the bottom. Warm Ghibli pixel theme (cream/moss/wood) — NOT the old black/red cyberpunk. Bump `?v=N` on the css/js `<link>`/`<script>` in index.html AND on every `import ... from './js/x.js?v=N'` in app.js when shipping asset changes — versioning only the entry leaves sub-imports on a stale cache (and an unversioned nested import like `js/util.js` loads a SECOND copy of the module).
- Bumping asset URLs is NOT enough when index.html itself is cached: force a fresh document by navigating to `/?v=N` (query on the page URL), then confirm the served `?v=` via preview_evaluate before testing changes — a reload alone can keep serving the old HTML.
- `/` and `/index.html` now send `Cache-Control: no-cache, must-revalidate` (before, the document had no cache header at all and `/index.html` 404'd). The document names the asset versions so it must never be cached; versioned `/static` assets stay cacheable. A browser holding a pre-header document can still look stale for one load.
- **A `style=` attribute in index.html beats every rule in style.css.** A stray `style="display:none"` on `#statusPanel` made the status button permanently dead while `.status-panel.open { display: block }` was correct. If a panel won't show but its classes look right, grep index.html for `style="display` before touching CSS.
- The QUEUE panel renders only from the server's `queue_state` frame and appears only while jobs actually overlap; `cancel_queued` is honoured only while an item is still `queued` (a stale click now gets a "no longer waiting" reply instead of silence).
- The office UI is deliberately ZERO-BUILD vanilla JS (no package.json, React, or Tailwind). UI skills that require a Node toolchain (shadcn etc.) don't apply — adapt their patterns with native browser APIs instead of scaffolding a toolchain; user confirmed keeping it dependency-free.
- Validate static JS with `node --check` over `agents/web/static/app.js` and every `agents/web/static/js/*.js` — there is no frontend build or test runner. Node 24's module detection lets `--check` accept the `import` syntax in app.js. BUT `--check` on a `.js` file parses in **CommonJS goal, which is not what Chrome uses** — app.js executes as an ES module, and this session `--check` ACCEPTED a file the module parser rejected (a duplicated `switch` head line → SyntaxError → blank page, console-only symptom). Always ALSO copy to `.mjs` and check that: `cp agents/web/static/app.js /tmp/a.mjs && node --check /tmp/a.mjs` — the module goal is the Chrome-faithful check.
- New clickable divs must use `makeActivatable()` in app.js (adds role=button, tabIndex, Enter/Space) or be real `<button>`s — an a11y audit found every clickable div was keyboard-unreachable.
- Tab clicks sync `.is-active` AND `aria-selected` on `.tab` buttons in the same handler; the panes-only version (no button highlight) shipped broken for a long time — keep both in sync when touching tabs.
- View transitions use native `document.startViewTransition` (`vtAppend`/`vtSwap` in app.js). DOM changes land in an async callback — reads right after triggering see the OLD state; wait ~400ms before asserting in live verification.
- A global `prefers-reduced-motion` block at the end of style.css kills ALL animations/transitions — new decorative animations are covered automatically; don't add per-animation handling.
- WebSocket endpoint at `/ws` for real-time chat. Sends JSON messages with `type` field (jarvis/thinking/progress/search_result/draft_result/send_result/research_result/error).
- The chat UI uses Gemini for ALL intent parsing (not regex). Greetings and help are fast-pathed locally.
- `chat_handler.py` is the CLI mode (menu `[C]`). Web UI goes through the `web/ws.py` socket handler independently — an inline action handled there (`GREETING`/`HELP`/`UNKNOWN`/`BRAINSTORM`/`REVIEW`/`LIST_SESSIONS`) never reaches the dispatch queue, so a message parsed to `[]` gets no reply at all (silent dead end — intent parsing is Gemini-first, so it varies between identical strings).
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
- UI preference: warm Ghibli pixel office (approved; supersedes the earlier black/red cyberpunk ask). When asked to restyle, change the SKIN only — integration, queuing, dispatch, and server stay untouched ("make everything as it is").

## File Changes That Must Move Together

- `config.py` + `config.json`: adding a new config field requires updating both the getter/setter functions AND the default in `get_business_profile()`.
- `chatbot.py` + `jarvis.py`: adding a new ActionType requires updating BOTH the pattern matching in chatbot AND the dispatch handler in jarvis.py.
- `ai_design.py` + `medium.py`: changing email prompt structure requires updating BOTH agents (AI and template) to stay consistent.
- `industry_learner.py` + `ai_design.py` + `medium.py`: industry context flows from learner → both email agents. All three must agree on the data format.
- `chatbot.py` + `chat_handler.py` + `agents/web/ws.py`: all three parse user intent. If you change ActionType or add new actions, update ALL three (chatbot for parsing, chat_handler for CLI dispatch, ws.py for WebSocket dispatch).
- `event_bus.py` consumers: adding a new event `kind` requires updating `VALID_KINDS` in `event_bus.py`, the `handleAgentEvent` switch in `web/static/app.js` (plus optional CSS), and the activity-strip wrapper in `web/static/js/util.js` if the strip should narrate it. `app.js` installs that wrapper at init (`handleAgentEvent = wrapAgentEvent(handleAgentEvent, STATUS_TEXT)`) — the assignment must stay AFTER `STATUS_TEXT`'s `const`, or it hits the TDZ.
- `skills.py` ↔ `agent_team.py`: skills flow library → `skills_prompt()` into each agent's system prompt; the `learn_skill` tool writes back via `learn_skill()`. A new roster member is DATA in `agent_team.py AGENTS` only (`name`/`role`/`look`/`station`) — no frontend edit: `app.js` keeps no roster of its own, it projects `/api/agents` into empty `BOT_HOME`/`LOOKS`/`ROSTER_META` maps, so a floor with fewer bots/cards than the API returns is a STALE DOCUMENT, not a missing map entry. Check the loaded `app.js?v=` before editing anything client-side.
- `chat_memory.py`: used by both `chat_handler.py` (CLI) and `agents/web/ws.py` (WebSocket). Schema changes require both consumers to be updated.
- `agents/web/review.py` persists approved drafts via its own `_finish`; `agents/web/web_session.py:current()` is the only place a `Session` is built for the web layer — the review flow, the API and the socket all read the same instance, so a change to "which session is active" belongs there.
- **Key vault**: `agents/web/vault.py` owns the code-locked key vault (PBKDF2-hashed access code in gitignored `agent_output/vault.json`, 5-strike/5-min lockout, in-memory 30-min token sessions); `web/api.py /api/vault/*` routes are thin guards. The invariant: only `/api/vault/reveal/{id}` with a valid token ever returns secret material — `/api/vault/keys` returns masked previews only (4-char prefix + 2-char suffix), and the frontend puts revealed values in the clicked button's text (wiped after 15s), never in the DOM list. Tokens die on server restart. Frontend: `web/static/js/vault.js` + 🔑 topbar button.
- Session attachments: a composer upload is stored as `__default__` in `agent_output/sessions/<id>/attachments.json` and silently rides EVERY future draft for that session — any playtest that attaches a file must delete that key (files land in `agent_output/uploads/`).
- `Session.__init__` takes no arguments (`Session(session_id=...)` raises TypeError) and `load_data`/`save_data` no-op while `id is None`, so constructing a bare `Session()` for inspection has no side effects; use `.load(id, data)` to attach it.
