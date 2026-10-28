# Jodiac — the algorithm in every file

One entry per file: **what it does**, then **how the algorithm works**. Read the
data-flow section first — every file below hangs off one of those arrows.

Grouped by subsystem, but the repo is flat: `agents/*.py` are peers, the three
sub-packages (`agents/ai/`, `agents/outbox/`, `agents/web/`) own their own seam.

---

## 0. How a run flows

```
user text ──► chatbot.parse_intents ──► action_registry (what to ack/say) ──► action_dispatch.dispatch
                                                                              │
        menu key ──► jarvis.handle_choice ────────────────────────────────────┤
        browser ──► web/ws ► dispatch_bridge ─────────────────────────────────┘
                                                                              ▼
                              workflows.py  (search → enrich → draft → send → sync)
                                   │
   map_search / gmaps_source ──────┤  discovery
   category_filter / icp     ──────┤  judging
   contact_finder / enricher ──────┤  contactability
   ai/service (Gemini seam)  ──────┤  scoring, drafting, analysis
   mailer / outreach_send / outbox ┤  sending
   brain / learn / obsidian   ─────┘  memory
```

Every stage emits on `event_bus`; `web/ws.py` forwards those to the browser, and
`agents/ui.py` renders them in the terminal. **No stage raises to its caller** —
each one degrades and returns a report dict.

---

## 1. Root & entry points

### `jarvis.bat` — Windows launcher
Sets `JODIAC_HOME=%~dp0jodiac_data` and `JODIAC_OBSIDIAN=%~dp0jodiac_data\obsidian`
(so this checkout's data lands in the repo's own gitignored folder instead of the
legacy `F:\jodiac`), then runs `python -m agents.jarvis`. This is why every test
run needs those two env vars.

### `requirements.txt` — dependency manifest
`scrapling[fetchers]` is the load-bearing line: `Fetcher` resolves through
`curl_cffi → patchright → browserforge` at attribute access, so a plain
`scrapling` install makes `contact_finder`, `business_enricher` and
`maps_contact_fallback` unimportable, which in turn breaks `workflows` and the
whole pipeline at import time.

### `AGENTS.md` — the project's real documentation
Session learnings for future agents: environment quirks, which files must move
together, and the decisions behind each seam. Not code.

### `.gitignore`
Ignores both data roots (`jodiac_data/`, `agent_output/`), Python/IDE/OS litter,
and the `_*.txt` / `_*.json` / `_*.bat` scratch probes.

### `agents/__init__.py` — package façade
Re-exports the five agent tiers and the `Orchestrator` so `from agents import
Orchestrator, Task, Complexity` works. Importing it pulls `config.py`, which
creates the data directory or raises the `JODIAC_HOME` error with a fix hint.

### `agents/__main__.py` — `python -m agents`
Six lines: imports `jarvis.main()` and runs it.

---

## 2. Dispatch, session & the three UI surfaces

### `agents/jarvis.py` — thin CLI orchestrator (229 lines)
Menu loop + dispatch only. `main()` prints the boot banner/menu, reads a key, and
`handle_choice()` forwards to a handler module. `_ensure_session()` runs the
4-step session wizard (name → product → target → tone) before any work, writing
the answers into the business profile via `config.set_business_profile`.

### `agents/action_registry.py` — one row per action
A static table: for each `ActionType` → Gemini function name, ack line, progress
line, result-frame kind, and whether to skip the ack. `row_for_gemini()` is the
only source the intent parser's tool schema is built from, so adding an action
means adding one row (plus the handler in `action_dispatch`).

### `agents/action_dispatch.py` — the single execution entry (732 lines)
`dispatch(action)` looks up the registry row, acks, then switches on the action
type to `_handle_search` / `_handle_draft` / `_handle_send` / `_handle_research`
/ `_handle_sync` / `_handle_scrape` / `_handle_enrich` / `_handle_team_act` /
`_handle_ask_agent` / `_handle_campaign` / `_handle_status` / `_handle_checkin` /
`_handle_brainstorm` / `_handle_goal`. Each handler calls a pure function in
`workflows.py` (or a subsystem module), wraps the result as
`{action, ok, summary, kind, payload}`, and never lets an exception escape —
failures come back as `ok: False` with a message. Both the CLI chat and the
WebSocket route through here, so behaviour cannot diverge between them.

### `agents/chatbot.py` — intent parsing (870 lines)
Gemini-first, regex-last. `parse_intents()` runs local fast paths (greeting,
help, and a direct selling-goal statement — caught by `_has_goal_statement_shape`
/ `_match_goal_statement` so `"i sell X"` never costs an API call and is never
eaten by brainstorm), then calls Gemini with **function calling**: the tool list
is built from `action_registry`, the system prompt from
`_build_system_prompt()` (business profile + live session state + memory), and
`_handle_function_call()` turns each returned call into an `Action`.
`_requested_steps()` detects explicit follow-ups ("…then send them") and
`_make_chain_action()` appends them as a chain. Failures degrade to `UNKNOWN`.

### `agents/chat_handler.py` — terminal chat mode (226 lines)
A readline loop: pull the last N memory messages, call `parse_intents`, run each
action through `action_dispatch`, print the result, store the exchange in
`chat_memory`. Also boots the proactive briefing (`proactive.auto_brief`) at
start and runs the CLI flavour of brainstorm/review when the action asks for it.

### `agents/setup_handler.py` / `agents/dashboard_handler.py`
`run_setup()` is a nested menu that edits config (Gmail creds, profile, API keys)
through `config.py` setters. `run_learning_dashboard()` prints
`learn.get_learning_dashboard()` — categories, hooks, email stats.

### `agents/pipeline_handler.py` — the menu's pipeline flows (314 lines)
Orchestrates what menu keys [1]–[9] do. `run_quick_outreach()` is the one-shot
chain — search → research → draft → review → send — calling one `workflows`
function per stage and printing through `ui.py` between them. `run_full_pipeline()`
is the same chain stepped manually, with `run_step_search` / `_enrich` / `_select`
/ `_draft` / `_review_send` / `_sync` as the individual menu entries, each
ensuring an active session first and saving its stage output as it goes.

### `agents/session.py` — session state (191 lines)
A session is a directory under `OUTPUT_DIR/sessions/<id>/` plus JSON files.
`create()` allocates the id, `save_data/load_data` are `json.dump`/`load` with a
`id is None` no-op guard, `get_session_state()` compresses everything into the
context string Gemini receives. `get_active_session()` = **newest on disk**,
which is what both the CLI and the web UI resume.

### `agents/config.py` — the single source of truth (296 lines)
Resolves `JODIAC_HOME` (falling back to `F:\jodiac`, and raising an instructive
`OSError` when the drive is missing), creates the data subdirectories at import,
then exposes ~40 `get_*/set_*` pairs over one `config.json` (keys, profile,
active goal, tone, provider chain). `save_session_data`/`load_session_data` are
the JSON read/write used everywhere. Read-modify-write of the whole JSON dict, so
callers never hold a partial config.

### `agents/ui.py` — terminal presentation (513 lines)
Pure presentation: ANSI palette (`class C`), banner/boot animation, typing and
spinner effects, and the `show_*` renderers for menus, search results, drafts and
summaries. No business logic — handlers pass data in and it formats it.

### `agents/live_updates.py` — CLI progress reporter (193 lines)
A counter-and-timestamp object with `search_start/scrape_result/draft_done/…`
methods that print `[STAGE] message (elapsed)`. Same event vocabulary as the
event bus, but aimed at the terminal.

---

## 3. Discovery — finding businesses

### `agents/map_search.py` — Overpass + no-site verification (314 lines)
1. `geocode()` asks Nominatim for lat/lon.
2. `search_businesses()` POSTs an Overpass QL query **URL-encoded** (raw POST was
   the silent-empty-results bug), retrying 3 times across 3 mirror endpoints with
   a 1 s delay, then maps each node/way/rel into a business dict with its tags.
3. `filter_no_website()` keeps only records with no `contact:website`/`website`.
4. `verify_website()` is the correction pass for OSM's blind spot: first Wikidata
   (property **P856**, official website) for the name; then DNS probing of
   generated name variations (`name.com`, `nameindustry.com`, …) inside a time
   budget. `verify_no_site_businesses()` applies it only to the no-site set.
5. `EXCLUDE_TAGS` drops non-business POIs (parks, playgrounds, places of worship,
   town halls) that Overpass happily returns.

### `agents/gmaps_source.py` — paid Maps adapters (230 lines)
`available()` is true only when an Apify token or Outscraper key exists.
`search_gmaps()` builds query terms (`_category_terms`: category first, then goal
hints), converts radius → zoom (`_zoom_for_radius`, Maps convention), runs the
chosen provider, and normalises both response shapes into the same pipeline dict
(`_convert`), including the two email encodings Apify can return (list vs string).
Used as the fallback when Overpass comes up empty.

### `agents/category_filter.py` — the exclusion gate (489 lines)
Four stages, in strict precedence:
- **Stage 0 — user exclusions (user authority).** `extract_exclusions()` pulls
  `"remove schools and cllgs"` out of the user's own phrasing (typo/plural map via
  `EXCLUSION_LEXICON` + `_KEYWORD_TYPOS`) and `_exclusion_hit()` drops matches on
  tag **or** name *before* any AI or ICP verdict can resurrect them.
- **Stage 1 — tag kill-list.** `goal.never_tags` (education-era `TAG_KILL_LIST`
  when no goal) can never match; dropped unconditionally.
- **Stage 1b — `_no_category_signal()`.** If the phrase names nothing to filter
  *by* (`"find businesses in Bandel"` → `"businesses"`), short-circuit the AI tier
  and let the ICP verdict stand — this was the "Found 0 businesses in Bandel" bug.
- **Stage 2 — `_ai_tier_filter()`.** Gemini judges in tiers (never / unlikely /
  plausible / likely) with `_evidence_note()` carrying description, operator and
  course tags as evidence; the **ICP veto** may resurrect an AI-dropped business
  only when its verdict is *direct-fit*, and that resurrection is reported as
  `[ICP veto kept N: …]`, never silent.
- Returns `(kept, report)` where `report` is the one-line explanation shown to
  the user.

### `agents/icp.py` — goal resolution and fit scoring (906 lines)
The deterministic heart of "is this business a customer?".
- `resolve_goal()` picks the goal: a pinned goal beats inference; otherwise
  `_goal_from_text()` scores the search wording against each goal's keyword list
  (longest match wins); an unknown phrase becomes the **custom goal**.
- `classify(business, goal)` is pure and ordered: (1) `never_tags`/`never_names`
  kill-list → score 18; (2) `_not_an_organization()` — a name for a *place*
  (auditorium, library, bhawan, playground) is never a prospect, for any goal;
  (3) match every vertical's `name_signals`/`tag_signals`, take the one with the
  highest `base` score; (4) if nothing matched, an education tag still scores 55,
  else "no signal this is a business we can serve" at 25. Learned signals
  (`learned_signal_stats`, `learned_type_rates`, `known_rejections`) then nudge
  the score up or down from real history.
- `rank()` classifies a list, sorts best-fit first and splits keepers from
  rejects; `learn()` writes this batch's verdicts back into the brain (never
  raises); `context()` renders the prompt block for the current goal.

---

## 4. Enrichment — finding who to contact

### `agents/contact_finder.py` — official-site hunt (604 lines)
`find_email_for_business(biz, max_seconds=45, max_fetches=12)` runs a **budgeted
waterfall**: the business's own listed site → a search-engine hit for its name →
domains probed from name tokens. Every fetched page goes through `mine()`, which
harvests phone numbers (`tel:` links first, then regex over text),
schema.org JSON-LD contacts, Cloudflare XOR-obfuscated emails
(`_decode_cfemails`), social links and tech hints — so a hunt still enriches when
no email turns up. Guards: `_dns_resolves()` kills NXDOMAIN candidates in
milliseconds, `_looks_official()` requires a distinctive name token on a probed
homepage, `_decode_sucuri_cookie()` solves a Sucuri CloudProxy JS challenge, and
`_looks_like_phone`/email junk filters keep junk out. Results are flagged
`verified` only when the page belongs to *this* business — probed domains are
guesses and are reported as such.

### `agents/contact_enricher.py` — production layer (365 lines)
Adds validation and caching on top of the finder:
- **Cache** — `cache_get`/`cache_put` keyed on business identity with a TTL and
  city scoping, so repeat runs do no network at all.
- **Deliverability** — `mx_status()` does a DNS MX lookup per domain,
  `email_deliverability()` returns `deliverable`/`undeliverable` with a reason
  (syntax and nonexistent domains die offline; the gmail leg is a real probe).
- **Phone** — `parse_phone()` uses libphonenumber to normalise to E.164 and
  classify mobile/landline; `whatsapp_link()` returns a `wa.me` URL **only** for
  verified mobiles.
- **DNS pre-filter** — `_dns_resolves` before any HTTP.
- **Promotion** — `enrich_businesses()` mutates in place and only promotes a
  verified + deliverable contact to the `email` field.

### `agents/business_enricher.py` — website scraping (222 lines)
`scrape_business()` fetches a site with Scrapling's `Fetcher` and pulls social
links, hours, description and contact info with tolerant regex/parsing (SSL errors
are caught, never fatal). `scrape_google_maps_reviews()` grabs rating/review
count. `enrich_businesses()` maps both over a list and `save_enrichment()` writes
the session file.

### `agents/maps_contact_fallback.py` — Google-search fallback (218 lines)
Used when Hunter.io is unavailable: build a query (name + area), fetch a Google
results page, then run three regexes over the text — `PHONE_RE` with a
digit-count plausibility check, `EMAIL_RE` minus `SKIP_EMAILS`, and a rating
pattern with/without the word "reviews". Everything is best-effort and
source-labelled (`maps_phone`, `maps_email`, `maps_rating`, `maps_searched`).

### `agents/exec_finder.py` — decision-maker lookup (228 lines)
An `info@` address reaches a mailbox, not a person. `find_executives()` uses the
business domain: Hunter domain-search → `_person_score()` ranks titles by
seniority/relevance (owner/founder/director first), with an optional Apollo
fallback (`_apollo_person`) when keyed. Free/unkeyed = a no-op.

### `agents/business_research.py` — per-business research (199 lines)
`research_business()` gathers Google Maps rating/reviews plus whatever the site
says, then `_analyze_with_ai()` asks Gemini "what is this business missing that
we could offer?"; `_analyze_basic()` is the template-driven fallback.
`format_research_for_email()` flattens the insights into the string injected into
the drafting prompt.

### `agents/contact_export.py` — CSV export (97 lines)
`contact_rows()` emits one row per business that has a phone or email (recording
which source supplied each), `write_phones_csv()` writes it for WhatsApp tools.

---

## 5. The AI seam (`agents/ai/`)

The rule: **consumers call typed capability methods; nobody imports the SDK, a
prompt string, or a key.**

### `agents/ai/__init__.py`
Exports `service` (the shared `GeminiService`) — the only thing consumers import.

### `agents/ai/schemas.py` — typed models (120 lines)
Dataclasses/pydantic-style records: `Business`, `FitScore`, `BusinessProfile`,
`ContactCandidate`, `EmailDraft`, `ReplyIntent`, `QueryExpansion`, `ToolCall`,
`ToolTurn`, `UsageRecord`. Defined once so `icp`, `exec_finder`, `workflows` and
`ai_design` can't drift on field names.

### `agents/ai/service.py` — `GeminiService` (217 lines)
Seven capabilities (`score_fit`, `summarize_profile`, `draft_email`,
`classify_reply`, `expand_query`, `extract_contact`, `converse`). Each one:
load the versioned prompt (`prompts.load`), check `cache` for the memoisable ones,
call `gemini_client`, parse into a typed model, **fall back to `fallbacks.py` on
any failure**, log to `usage_log`, return. Drafts and reply classifications are
never cached (one-shot, reply-specific).

### `agents/ai/prompts.py` + `agents/ai/prompts/*.md`
One versioned markdown file per capability; line 1 is `<!-- version: N -->`.
`load()` reads and caches `(version, body)`. Editing a prompt is a file diff, and
the usage log records which version served each call.

### `agents/ai/gemini_client.py` — the only SDK touchpoint (166 lines)
`available()` = key present + client constructible. `_call_with_retry()` is the
single retry policy (honours a 429 `retryDelay`, one retry otherwise).
`converse(contents, tools, max_rounds)` runs up to `max_rounds` tool turns:
read the response → if it asks for calls, execute them → append the tool results
→ call again, returning a normalised `ToolTurn`. `generate_json()` is the
one-shot JSON path (`{}` on any failure).

### `agents/ai/providers.py` — free-provider cascade (527 lines)
The OpenAI-compatible transport behind the seam, used **only** when
`config.ai_provider != "gemini"`.
- `_resolve_chain()` builds `[primary, *fallbacks]` (deduped, unknown dropped).
- `_post_to()` posts one chat completion and raises `_SkipProvider` on
  *retryable-across-providers* failures (429/5xx/transport/401/403/404 — free-tier
  model ids rotate); other 4xx raise immediately because that means a
  request-shape bug.
- `_chat()` walks the chain and takes the first provider that completes; when all
  are skipped the error propagates so `ai_engine` can fall back to Gemini.
- `_tools_to_openai()` / `_contents_to_messages()` translate Gemini's
  `types.Tool` / `types.Content` into the OpenAI dialect (and must accept *both*
  SDK tools and plain dicts); `converse()` re-implements the tool loop over that
  dialect so consumers see one contract either way.

### `agents/ai/fallbacks.py` — heuristics for every capability (91 lines)
`score_fit` floors on the deterministic ICP verdict (AI may add a rationale, never
override it), `summarize_profile` collapses snippets to one line each,
`draft_email` is template-grade, `classify_reply` is keyword triage,
`expand_query` is a no-op, `extract_contact` is a regex pass. Same shape as the AI
answer so callers never branch.

### `agents/ai/cache.py` — memoisation (41 lines)
`business_id()` = name + location (the dedupe pair search already uses); `get/put`
hold one capability's result, `rescore()` drops one business or all. Only
`score_fit` and `summarize_profile` participate.

### `agents/ai/usage_log.py` — per-call telemetry (90 lines)
`record()` appends a `UsageRecord` to `agent_output/usage/usage.jsonl` and emits a
`brain` event; `_serving_provider()` records *which* path served it — that is the
feed that grades the cascade. `stats()` gives per-capability
calls/gemini/fallback. Never raises.

### `agents/ai/scrape_adapter.py` — dict → model (32 lines)
`to_business()` converts a pipeline dict into a typed `Business`, pulling
scraped description text in as grounding.

### `agents/ai_engine.py` — legacy low-level engine (126 lines)
`generate()` / `generate_json()` with lazy client init, returning `""` / `{}` on
failure. Routes through `providers` when a non-Gemini provider is active,
otherwise Gemini; used by older call sites and as the seam's own escape hatch.

---

## 6. The agent tiers

### `agents/base.py` — contracts (135 lines)
`Complexity` tiers, `Task` (payload + complexity), `TaskResult` (+ `summary()`),
and `BaseAgent.handle()` which wraps `_execute` with timing and error capture so
no agent can throw past the orchestrator. `can_handle()` is the routing test.

### `agents/orchestrator.py` — cheapest-capable routing (198 lines)
`_route()` picks the **cheapest** agent whose `max_complexity` ≥ task complexity
that also passes `can_handle()`; `_assign_complexity()` infers a tier when the
task doesn't declare one. `run`/`run_task`/`run_batch` route each item
independently and accumulate `stats()`.

### `agents/lightweight.py` — tier 1, no I/O (161 lines)
Deterministic helpers: keyword-frequency classification, regex email validation,
top-N keyword extraction, naive word-list sentiment in [-1, 1], address
pretty-printing, OSM-tag parsing, category count summaries.

### `agents/medium.py` — tier 2, templates + heuristics (420 lines)
`_draft_email` composes subject/body from templates + the business's own details
and an `_extract_icebreaker`; `_score_lead` is a weighted 0–100 score (contact
present, has a site or not, category fit), `_rank_leads` sorts by it;
`_enrich_hunter` calls Hunter.io when keyed. No LLM calls — this is the
free/fast drafting path.

### `agents/heavy.py` — tier 3, generation (336 lines)
`_generate_website()` builds a one-page responsive site: `_auto_color()` picks a
palette from the business category, `_build_html()` fills the template with
escaped business data, output lands in `config.SITES_DIR`. Also `_deep_analysis`
and `_generate_full_report` over a business set.

### `agents/ai_design.py` — Gemini generation (283 lines)
The AI version of heavy/medium: website, email, proposal and PDF-content
generation through `ai_engine`. `_fallback()` delegates to the template agents
whenever Gemini is unavailable, so the capability never disappears.

### `agents/ai_code.py` — code tasks (195 lines)
Review, refactor, explain, fix and script/HTML generation via Gemini, degrading
to a plain "AI unavailable" message.

---

## 7. Campaigns, drafting & research glue

### `agents/workflows.py` — pure workflow logic (777 lines)
No UI calls; explicit params in, report dict out. Each function emits `step`
events on the bus as it goes:
- `search_businesses_workflow` — geocode → Overpass/Maps → category filter → ICP
  classify/rank → split `no_site` / `with_site`, persisting immediately so a
  minutes-long discovery survives a later crash.
- `enrich_workflow` — Hunter when keyed, otherwise the maps fallback, then the
  exec finder.
- `research_workflow`, `scrape_businesses_workflow`, `select_businesses_workflow`.
- `draft_and_pdf_workflow` — drafts through the AI seam, proposal PDF, and
  websites **only if the goal sells them**.
- `run_outreach_pipeline` / `complete_outreach` — the end-to-end chains that
  assemble the report dict (`search/enrich/draft/send/sync/errors`).

### `agents/campaign.py` — the 6-stage guided flow (484 lines)
State machine persisted per session under a lock (`_mutate` is
read-modify-write): **curate → checklist → interview → angles → draft → send**.
`curate_workflow()` runs the real search pipeline then takes the top `want`
leads using `_rank_businesses()`: a tuple sort of
`(icp_rank, has_email, has_phone, -reviews, name)` — ICP verdict authoritative,
then reachability, then proof the business is actually operating.
`initial_report_pdf()` / `final_report_pdf()` render the before/after documents.

### `agents/email_review.py` — CLI review workflow (216 lines)
Walks drafts one at a time: show → edit subject/body → approve/skip → summary,
returning approved drafts plus their attachment paths.

### `agents/proactive.py` — unsolicited briefing (204 lines)
`check_in()` scans four sources — overdue follow-ups (`_overdue_followups`,
worst first), WhatsApp-ready leads (`_whatsapp_ready_leads`), learning stats and
known-business counts — and `proactive_notes()` turns what it finds into
priority-sorted notes. `auto_brief()` is the one-shot string chat prints at start.
Data-only, never raises.

### `agents/brainstorm.py` — structured interview (211 lines)
`BrainstormSession` walks a fixed question list, `_save_answer()` files each
answer into the brain (industry/location/strategy), and `_finish()` builds the
completion message plus progress reporting.

---

## 8. Memory & knowledge

### `agents/brain.py` — the growing knowledge store (625 lines)
A directory of JSON files (`industries/`, `locations/`, `strategies/`,
`sessions/`, `insights/`, plus `profile.json` and the per-goal ICP file).
`learn_*` merges into the existing JSON; `*_context()` renders the prompt block
for each; `_migrate_icp()` folds pre-goal learning into the per-goal shape once.
`get_icp_context()` / `get_rejected_names()` are what make the ICP and filters
improve over time. Singleton via `get_brain()`.

### `agents/learn.py` — outcome learning (489 lines)
`KnowledgeBase` accumulates per-category and per-location stats:
`learn_from_email_result` bumps template success counts, `record_feedback` stores
1–5 star ratings, `learn_from_rejection` marks a pattern to avoid.
`get_best_email_patterns()` returns the winners for a category;
`suggest_refined_query()` is an optional Gemini assist for the *next* search.
Exposed as `get_kb()` + module-level wrappers.

### `agents/skills.py` — technique library (277 lines)
Skills are `{name, description, steps, agents, enabled}` records in
`OUTPUT_DIR/skills/library.json`, guarded by a lock with **atomic writes**
(tmp + replace). `skills_prompt()` renders one agent's enabled skills into their
system prompt; `learn_skill()` is the agent-facing self-learning write path;
`mark_used()` bumps counters on injected skills.

### `agents/industry_learner.py` — new-vertical research (331 lines)
`research_industry_web()` researches a vertical **for the product we actually
sell** (product line + ICP read from the merged profile, not generic advice),
caching the result in `knowledge_base/industry_research.json`.
`get_or_research_industry()` is cache-or-research; `_generic_insights()` is the
product-aware fallback, and an empty category returns fallback immediately (the
`""`-as-industry caching bug).

### `agents/industry_templates.py` — built-in vertical knowledge (321 lines)
Static baseline context per vertical (the ones that survive the ICP: institutions
with a classroom or computer lab). `match_category_to_template()` maps a fuzzy
category to a key, `load_custom_templates()`/`save_custom_template()` layer
AI-researched additions on top, `sync_templates_to_obsidian()` writes them out as
vault notes.

---

## 9. Obsidian sync

### `agents/obsidian_sync.py` — 7 cross-linked note types (891 lines)
Builds `projects/ contacts/ outreach/ industries/ research/ competitors/
followups/` notes, each with `[[wikilinks]]` to the others and frontmatter.
Provenance helpers decide what to show: `_resolved_email()` prefers explicit >
enrichment > maps, `_resolved_phone()` OSM > maps, `_email_source()` reports
hunter > osm > maps. `update_vault_index()` writes the map-of-content that ties
every note together, and `run_sync_workflow()` is the entry point that runs all
of it after a session.

### `agents/obsidian_upgrade.py` — vault extras (410 lines)
`create_dashboard()`, `create_timeline()` (sessions chronologically),
`create_tags_reference()` (every tag in use), plus `channel_intelligence()` which
derives reachability (WhatsApp-able phone?) and follow-up urgency from the vault,
and `update_graph_config()` colouring note types in Obsidian's graph view.

---

## 10. The specialist team

### `agents/agent_team.py` — personas with their own brains (1105 lines)
Each specialist (scout / strategist / analyst + hires) has
`agent_brains/<key>.json` holding facts + chat history: `_remember()` stores a
fact under a topic (deduped, newest first), `_recall()` renders matching topics
plus recent chats as prompt text. Tools are a plain dict of callables —
`brain_query` (keyword search of the outreach brain, checked **before**
web_search), `web_search`, `read_url`, `vault_query`, `propose_draft` (stages a
draft into the session queue) — executed by `_execute_tool()` and fed back to the
model. `ask_agent()` runs the loop; `_learn_from_chat()` remembers every chat and
promotes web-found answers to durable facts. `team_act()` drives an unprompted
batch with a `_batch_signature()` de-duplication so a batch is only handled once,
and `team_proactive_notes()` reports what the team would say unprompted
(data-only, never raises).

### `agents/hiring.py` — runtime roster (197 lines)
The only reader/writer of the hire JSON. `reserve_slot()` finds the first free
desk (floor size caps the roster), `make_id()` is slug + base36 timestamp (unique
without a collision round-trip), `validate()` returns `(clean_fields, error)`,
`hire()` creates + activates, `deactivate()` is a soft delete — sprite leaves, desk
frees, memory is kept. `builtin_keys()` reads claimed desks from the roster so
built-ins are never re-listed.

---

## 11. Sending

### `agents/mailer.py` — Gmail SMTP (75 lines)
`send_email()` builds a MIME multipart (optional PDF attachment) and sends it
over SMTP with the app password; `send_batch()` loops and collects
`{to, subject, ok, error}` results.

### `agents/outreach_apis.py` — free-tier HTTP clients (258 lines)
Thin stdlib-`urllib` clients (`_post`/`_get`), zero new dependencies, env-only
keys. `resend_send` (3k/mo) and `brevo_send` (300/day) are the send chain's
non-SMTP legs; `tavily_search`/`tavily_extract` with `_ddgs_search()` as the
keyless fallback behind `research_search()`; `geoapify_geocode`/`geoapify_places`
for geocoding and places; `reacher_verify` for self-hosted verification.
**Every function returns a dict and never raises** — failures are
`{"error": …}`. `status()` reports readiness as booleans only, never key material.

### `agents/outreach_send.py` — the send leg (234 lines)
`parse_send_selection()` turns `"A"` / `"S"` / `"1,3-5"` into draft indices.
`_send_one()` sends a single draft (mailer → resend → sendgrid order, capturing
the *real* error), writes the receipt PDF, marks the contact and records the
outcome. `review_and_send_workflow()` and `send_emails_workflow()` orchestrate the
loop, filter empty recipients, and return `{sent, skipped, errors}`.

### `agents/outbox/` — durable send state
- **`__init__.py`** — declares this as pass 1 (ledger only; no provider imports).
- **`schema.py` (140 lines)** — the tables and both state machines as constants,
  plus `valid_transition()`, so the DAO and the tests read one source of truth.
  Batches: `draft → approved → sending → sent/partial/failed/paused`; recipients:
  `queued → claimed → sent → delivered/bounced/complained` with `failed` and
  `suppressed` as terminals.
- **`ledger.py` (621 lines)** — the only writer of `outbox.db` (WAL, FK on).
  `enqueue()` is idempotent (duplicate address in a batch, or in a previous batch,
  collapses to one row; suppressed addresses/domains are refused at the door).
  `claim(limit)` atomically flips up to `limit` queued rows to `claimed` with
  `UPDATE … WHERE state='queued' … RETURNING *` inside a transaction, so two
  callers (or a restart racing the pacer) never take the same row. `allowance()`
  applies the warm-up ramp so day 1 doesn't blast a thousand messages;
  `reconcile_stuck_claimed()` surfaces rows stuck mid-send; `apply_event()` flips
  a sent row by `provider_id` and is a no-op for unknown providers.
  Duplicate sends are structurally impossible rather than merely discouraged.

### `agents/sent_email_pdf.py` — send receipts (82 lines)
Renders a one-page PDF record (business, recipient, subject, timestamp, status)
into `sent_dir()`.

### `agents/pdf_gen.py` — proposal PDF (216 lines)
`generate_proposal_pdf()` picks the document shape from the **goal** — a
licensing proposal for licences, a website proposal for website sales — fills it
with the business's contact and fit data, and returns the path.

### `agents/pdf_theme.py` — shared print theme (223 lines)
Palette, page furniture (`_page_decor`: cream page, deep-green footer band) and
reusable flowables — `ThemeDoc`, `HeaderBand`, `kv_table`, `section`, `callout`,
`data_table`. `band_for()` maps a fit score to HOT/WARM/COLD (≥80/≥60/else) and
`badge_markup()` renders the chip. Every document in the app uses these, so
campaign reports and proposals look identical.

---

## 12. Data layer

### `agents/db.py` — SQLite seam (156 lines)
One file (`OUTPUT_DIR/jodiac.db`), stdlib `sqlite3`, WAL + `foreign_keys=ON`,
one short-lived connection per call (no cross-thread sharing hazard).
`migrate()` applies idempotent, versioned migrations recorded in
`schema_migrations`; `status()` reports path/version/journal/tables.

### `agents/store.py` — data access (257 lines)
Plain dicts in, plain dicts out: `upsert_business` (dedup on `session_id+ext_id`),
`list_businesses` (fit filter), `save_email`/`mark_email_sent`/`list_emails`,
`register_session`/`get_session`, `log_usage`, `usage_stats`, `provider_stats`
(the per-provider ok-rate that grades the cascade). Every function degrades to a
safe default on DB failure — telemetry can never break the pipeline.

### `agents/chat_memory.py` — conversation storage (246 lines)
SQLite at `OUTPUT_DIR/memory/conversations.db`. Rows are inserted on the first
**write**, not construction (read-only callers don't litter the DB),
`get_context()` returns the last N messages for Gemini, and `_ensure()` re-opens
the connection if `close_memory()` closed it — that guard is what stops
"Cannot operate on a closed database" after a WebSocket drop.

### `agents/event_bus.py` — telemetry pub/sub (69 lines)
Thread-safe subscribe/emit with a bounded `recent()` ring for late joiners.
Kinds: `bot`, `packet`, `brain`, `step`, `team`. `emit()` never raises —
telemetry must not break the work it observes.

---

## 13. Web layer (`agents/web/`)

### `server.py` — assembly only (52 lines)
Builds the FastAPI app, mounts `/static`, includes the routers, starts uvicorn on
8765. No behaviour lives here.

### `api.py` — HTTP surface (481 lines)
Serves the document with `Cache-Control: no-cache` (the HTML names the asset
versions, so it must never be cached), session stats, goals (pin/clear), history
and conversations, uploads, brain/roster/events/skills reads and writes, and the
vault routes. Each route is a thin guard over the module that owns the state.

### `ws.py` — the live socket (409 lines)
One WebSocket per browser: subscribe to the event bus and forward
`agent_event` frames, then route each incoming frame to whoever owns it
(chat → `chatbot` → `dispatch_bridge`, review → `review`, campaign →
`campaign_ui`, queue cancel → `job_queue`, …). `_frame_sender()` swallows send
errors so a closed socket can't kill real work; cleanup unsubscribes and closes
memory on disconnect.

### `dispatch_bridge.py` — action → frames (135 lines)
Runs one parsed action through `action_dispatch` **in a worker thread** (so the
socket stays free) and translates the result into the frame payloads the renderer
expects.

### `job_queue.py` — per-socket queue (106 lines)
One list per socket mirroring its dispatch gate: first chain runs, the rest wait,
and `cancel()` only succeeds while an item is still `queued`. `push_state()`
publishes the queue so the QUEUE panel shows real overlap.

### `review.py` — email review state machine (154 lines)
Per-socket: which draft is showing, what the user answered. `start()` opens the
first card, `handle_action()` applies approve/skip and advances, `_finish()`
persists the approved drafts through the session.

### `campaign_ui.py` — campaign gates (291 lines)
The other two blocking conversations (checklist approval and the 1-by-1
interview), `consumes_text()` decides whether free text belongs to the open gate
or to the intent parser, and `maybe_resume()` re-opens a saved gate after a
reload.

### `vault.py` — key vault (254 lines)
PBKDF2-hashed access code in gitignored `OUTPUT_DIR/vault.json`, 5-strike
5-minute lockout (`_sweep()` sweeps failures, `locked_info()` reports the wait),
in-memory session tokens with a TTL. `entries()` returns **masked previews only**
(4-char prefix + 2-char suffix); `reveal()` is the single function that ever
returns a full secret, and `log_event()` records every touch to an on-disk ring.

### `web_session.py` — the one shared Session (40 lines)
`current()` lazily creates the app's single `Session`; `resume_latest()` points it
at the newest on disk. Review, API and socket all read this instance, so "which
session is active" has exactly one definition.

---

## 14. Frontend (`agents/web/static/`)

Zero-build vanilla ES modules — no package.json, no bundler. `index.html` loads
`app.js` as `type="module"`, and `app.js` imports the rest with `?v=N` cache
versions.

### `index.html` (288 lines)
The two-pane office: living pixel floor on the left, command centre (chat /
agents / skills tabs) on the right, roster strip along the bottom. Note that an
inline `style=` here beats any CSS rule — that's the first thing to check when a
panel won't show.

### `style.css` (1887 lines)
The warm Ghibli-pixel skin (cream / moss / wood), the floor-station positions as
CSS percentages, and a global `prefers-reduced-motion` block at the end that
suppresses every animation.

### `app.js` (1758 lines) — entry module
- **Socket** — `connect()` opens `ws://…/ws` with backoff, `sendFrame()` JSON-encodes,
  `handleMessage()` switches on the frame type and routes to a renderer.
- **Messages** — `addMessage` / `addSystemMessage` / `addProgressMessage`, plus
  card renderers (`renderSearchResults`, `renderDraftResults`,
  `renderSendResults`, `renderResearchResults`) and `makeActivatable()` which
  gives click-target divs `role=button` + keyboard activation.
- **Ops floor** — `BOT_HOME` / `LOOKS` / `ROSTER_META` are *projected* from
  `/api/agents`, then bots animate between stations on `agent_event` frames:
  `moveBot()` tweens percentage coordinates, `stationCenterPx` /
  `botDockPoint` compute anchors, `spawnTrail`/`burstAt` draw effects, and
  `botSay`/`setBotStatus` show bubbles. A floor with fewer bots than the API
  returns means a stale document, not missing map entries.

### `js/util.js`
`esc()` (XSS-safe text), the activity strip with idle decay, and
`wrapAgentEvent()` — installed at init to narrate bus events, so it must be
assigned *after* `STATUS_TEXT` is declared.

### `js/transitions.js`
`vtAppend` / `vtSwap` wrapping `document.startViewTransition`; DOM changes land in
an async callback, so a read immediately after sees the old state.

### `js/queue.js`
Renders the server's `queue_state` frame and reports work back to the server.

### `js/attachments.js`
Composer attachments: `takeAttachment()` hands the pending file to the send path,
chips render what's attached.

### `js/campaign.js`
`renderChecklist()` builds the curated checklist card with its approve/edit
controls; `renderInterview()` draws the one-business-at-a-time question card.

### `js/voice.js`
Dictation via the Web Speech API, writing into the composer input.

### `js/music.js`
The ambient corner widget — pure decoration.

### `js/vault.js` (276 lines)
Locked / setup / unlocked / change-code views, a live TTL countdown for the
session token, and revealed values written into the clicked button's text (wiped
after 15 s) — never into the DOM list.

---

## 15. Tests (`tests/`)

All suites live here now; run them from the repo root with `JODIAC_HOME` set
(see `jarvis.bat`).

| File | What it proves |
|---|---|
| `test_final_audit.py` | The 20-check self-audit: imports, session round-trip, map search, drafting, the orchestrator's AI-unavailable fallback, category filtering, outreach persistence, PDF/website generation. Scratch sessions are deleted through `_rm_session()`, which uses `OUTPUT_DIR` rather than a hardcoded path. |
| `test_category_exclusions.py` | The Bandel regression: user exclusions gate before ICP/AI can resurrect them, in all three AI modes, with the ICP veto scoped to direct-fit only. |
| `test_goal_state.py` | A pinned goal beats search-wording inference; direct goal statements parse locally; `resolve_goal` stamps a copy and never mutates the shared `GOALS` registry. |
| `test_contact_enricher.py` | Phone validation, deliverability, cache TTL/city scoping, promotion rules, the NXDOMAIN pre-filter, the Sucuri decoder, CSV columns. |
| `test_provider_cascade.py` | Skip-across-providers on 429/5xx/transport/401/403/404, immediate raise on other 4xx, chain resolution, status reporting — all with `_post_to` stubbed and a fake config module. |
| `test_outreach_apis.py` | URL, header and payload shape of every free-tier client with `urlopen` stubbed; `status()` must leak no key material. |
| `test_db.py` | Real SQL against a tmp DB with a stubbed `agents.config`, including safe defaults when the DB path is broken. |
| `test_ledger.py` (pytest) | Duplicate enqueue collapses to one row, suppressions block at enqueue, illegal transitions raise, `claim` respects the warm-up allowance, stuck claims are reconciled. |
| `conftest.py` | Per-test temporary ledger, closed and deleted afterwards (WAL/SHM companions included). |

---

## 16. Docs & history

- `docs/superpowers/specs/*.md` — design docs and implementation plans, in date
  order. Historical record: they describe the state at the time, not today.
- `docs/patches/*.patch` — the three applied `format-patch` files (free outreach
  APIs, portable paths, SQLite seam), kept for provenance.
- `docs/ALGORITHMS.md` — this file.