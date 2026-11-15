# How JARVIS works — the full workflow

A walkthrough of every layer, from the launch URL to a sent email, written
against this checkout (verified 2026-11-14). If a line here disagrees with the
code, the code is right — fix the line.

Contents

1. [The shape of the system](#1-the-shape-of-the-system)
2. [Three doors, one spine](#2-three-doors-one-spine)
3. [Request lifecycle, frame by frame](#3-request-lifecycle-frame-by-frame)
4. [The search leg](#4-the-search-leg)
5. [Contacts: from "no website" to a `to:`](#5-contacts-from-no-website-to-a-to)
6. [Research](#6-research)
7. [Drafting](#7-drafting)
8. [Review and send](#8-review-and-send)
9. [Guided campaign](#9-guided-campaign)
10. [The AI seam and the agent team](#10-the-ai-seam-and-the-agent-team)
11. [State on disk](#11-state-on-disk)
12. [The web layer](#12-the-web-layer)
13. [Security model](#13-security-model)
14. [The learning loop](#14-the-learning-loop)
15. [When something is down](#15-when-something-is-down)
16. [Where to change what](#16-where-to-change-what)

---

## 1. The shape of the system

JARVIS sells things to local businesses by finding them on a map, deciding
which ones could actually buy, finding a way to contact them, writing an email
that mentions something true about them, and sending it — with a human
approving every send.

Two ideas hold the whole design together:

**One spine per action.** Every action (`search`, `draft`, `send`,
`research`, …) is a member of `ActionType` in `chatbot.py`, dispatched through
`action_dispatch.dispatch()` into `workflows.py`. The CLI menu, the CLI chat
and the web socket all end up at the same handler. Adding an action means one
registry row (`action_registry.py`) and one handler — never a fourth copy of
the flow.

**Every external service may fail, and failure degrades instead of blocking.**
Overpass → Geoapify → Google Maps. AI → template fallback. Hunter → Maps
contacts → website scraping. A learning write that fails is swallowed. The
pipeline reports *why* something is empty instead of reporting "0".

```
                 ┌──────────────┬───────────────┬────────────────┐
   entry         │  CLI menu    │  CLI chat     │  web socket    │
                 │  jarvis.py   │ chat_handler  │  web/ws.py     │
                 └──────┬───────┴───────┬───────┴───────┬────────┘
                        │               │               │
                        │        chatbot.parse_intents (Gemini function calling)
                        │               │               │
                        └───────────────┴───────────────┘
                                        │
                             ActionType + params
                                        │
                        action_registry.py  (ack, progress, result kind)
                                        │
                            action_dispatch.dispatch()
                                        │
                                  workflows.py
                                        │
        ┌───────────┬──────────┬────────┼─────────┬──────────┬──────────┐
     map_search  icp.py   category_  business_  medium/ai_  outreach_
                  +geocode  filter   research   design      send
                                        │
                                  brain / learn / db / event_bus
```

---

## 2. Three doors, one spine

| Door | Entry | What it does |
|---|---|---|
| CLI menu | `jarvis.py` `[4]`–`[9]` | Interactive prompts building a **params** dict, then `dispatch()` |
| CLI chat | `chat_handler.py` | `parse_intents()` → dispatch loop |
| Web office | `agents/web/ws.py` | sockets, queue, review/campaign conversations |

`jarvis.py` is a thin dispatcher (~330 lines). The heavy lifting lives in
`pipeline_handler.py` (quick + full pipeline wizards), `chat_handler.py`,
`setup_handler.py`, `dashboard_handler.py`.

Start it:

```
python -m agents.web.server     # the office, http://127.0.0.1:8765 (see §13)
jarvis.bat                      # menu, sets JODIAC_HOME
```

---

## 3. Request lifecycle, frame by frame

A real example: the user types **"find training centres in Bandel"** in the
office.

```
browser                ws.py                 job_queue        dispatch_bridge
   │  {type:"chat",        │                     │                    │
   │   content:"find..."}  │                     │                    │
   ├──────────────────────►│                     │                    │
   │                       │ memory.add_message("user", …)             │
   │                       │ campaign/brainstorm/review claim check ───┤ (none open)
   │                       │ parse_intents(user_msg, memory) →         │
   │                       │   Action(type=search,                     │
   │                       │          params={location:"Bandel", …})   │
   │                       │ queue.push(chain) ─►│ (first runs,       │
   │                       │                     │  rest wait)        │
   │                       │                     ├───────────────────►│
   │  {type:"jarvis", ack} │◄────────────────────┤  ack frame         │
   │  {type:"progress"}    │◄────────────────────┤  progress frame    │
   │                       │                     │  to_thread(dispatch)
   │                       │                     │  ────────────────► │ action_dispatch
   │                       │                     │                    │   ↓ workflows
   │                       │                     │  result dict ◄─────┤
   │  {type:"jarvis", msg} │◄────────────────────┤  chat reply        │
   │  {type:"search_result"}◄────────────────────┤  shape_result(...) │
   │  renderSearchResults  │                     │                    │
```

Frame kinds the client understands: `jarvis`, `thinking`, `progress`, `error`,
`queued`, `queue_state`, `review_show`, `review_result`, `campaign_checklist`,
`agent_event`, `agent_events_replay` — plus the four result frames, whose names
(`search_result`, `draft_result`, `send_result`, `research_result`) come from
the registry rather than from a literal in the socket code.

Each action's `result_kind` is declared once in `action_registry.py`, so the
socket never keeps a private copy of that policy.

**One chain at a time per socket.** `job_queue.JobQueue` runs the first chain
and holds the rest; the QUEUE panel *is* that list, so `cancel_queued` means
something. A waiting job can be cancelled; a running one cannot. Reloading the
tab closes the socket but the work keeps running — the new socket is told what
is still in flight by `running_labels()`.

---

## 4. The search leg

`workflows.search_businesses_workflow(location, radius, category, goal)`.

**Step 0 — what are we selling?** `icp.resolve_goal(request=category,
explicit=goal)` decides the target for *this* search, not the account. Built-in
goals: `cad_licensing`, `website`, plus a `custom` fallback that only judges
whether something is a real, contactable business. The report stamps where the
goal came from (`[goal: pinned|inferred|profile]`) so a wrong match is
diagnosable from one line.

**Step 1 — geocode.** `map_search.geocode()` → Nominatim, via `curl`, 10 s.

**Step 2 — discover.** `map_search.search_businesses(lat, lon, radius,
phrase=category)`

- Asks Overpass for **every** business tag in the box (`shop`, `amenity`,
  `office`, `craft`, `healthcare`, `leisure`, `tourism`), URL-encoded POST,
  `out center`.
- Mirrors are tried in order inside one **100 s budget**, each endpoint getting
  its own slice, 2 attempts with 2 s / 4 s backoff.
- A mirror answering **valid JSON with 0 elements** is not success — it is
  remembered and the next endpoint is tried. Only when *every* endpoint agrees
  is an empty result believed.
- All mirrors unreachable → `_from_geoapify()` (keyed, zero-card Google Places
  substitute), using `_CATEGORY_HINTS` to keep the fallback on the category the
  user asked for.
- Non-businesses are dropped (`EXCLUDE_TAGS`: parks, playgrounds, places of
  worship, town halls…), names de-duplicated.

**Step 3 — Overpass empty? Google Maps.** If discovery returns nothing,
`workflows` fails over to `gmaps_source.search_gmaps()` when a provider key is
configured. If both are empty *and* Overpass errored, the search returns a real
reason ("Overpass failed (…) — Google Maps found nothing here either") instead
of a misleading "Found 0 businesses".

**Step 4 — ICP, deterministic.** `icp.rank(businesses, goal)` scores each
place against the goal's verticals (name signals + OSM tags + institution
type), splits `fits` / `plausible` / `unlikely`, sorts best-first. This is the
**one judge**: a classifier that needs an API call stops differentiating when
the quota runs out. Signal statistics learned per goal from the brain promote
signals that keep fitting.

**Step 5 — AI rationale, cosmetic only.** `ai_service.score_fit()` adds a "why"
to the top 5 `fits`. `fallbacks.score_fit` is the deterministic ICP verdict, so
AI can only *add* a rationale, never change a verdict.

**Step 6 — the user's phrasing.** If they gave a category,
`category_filter.filter_by_category()` narrows further:

- **Stage 0** user exclusions ("remove schools and cllgs") are parsed
  deterministically (`EXCLUSION_LEXICON`, `_KEYWORD_TYPOS`) and hard-dropped
  before anything else can resurrect them.
- **Stage 1b** a phrase that names no category (`"businesses"`) is *not* an
  intent to filter — `_no_category_signal()` short-circuits the AI tier
  filter so the deterministic verdict stands.
- **Stage 2** otherwise Gemini judges the full original phrasing in tiers
  (fits / plausible / unlikely), with `_evidence_note()` carrying
  description/operator/courses so "do they teach AutoCAD" is judged from
  evidence, not the name.
- Fail-closed: AI unavailable → strict tag filter, never the unfiltered pile.
- Every run produces a report string the UI shows ("Filtered 5 -> 0 for
  'businesses': ...").

**Step 7 — does the website actually exist?** `verify_no_site_businesses()`
web-searches the ones OSM says have no site (Wikidata P856 and search results);
`filter_no_website()` splits `no_site` from `with_site`. This is the fix for
"every institute with a website is un-pitchable" — the funnel needs the
no-site list to be *true*, and it needs to know which ones have sites for the
scrape/enrich path.

**Step 8 — learn.** `learn_from_search()`, `_remember_fit()`, plus `emit()`
telemetry for the office floor.

Returns:

```json
{"geo_display","found_raw","businesses","no_site","with_site",
 "filter_report","icp":{fits,plausible,dropped},"dropped","goal",
 "goal_label","goal_source","source":"osm|gmaps"}
```

`found_raw` matters: "Found 0" reads as "this town is empty" even when 15
places were found and every one was filtered out.

The full run is `run_outreach_pipeline()`, which wraps: search → **persist
immediately** (`search_results.json`, so minutes of API work survive a later
crash) → scrape with-site sites → enrich → phones CSV.

---

## 5. Contacts: from "no website" to a `to:`

`enrich_workflow(businesses, hunter_key)` branches on whether a Hunter key
exists:

- **With a key**, it runs on the businesses that *have* a website (Hunter needs
  a domain) and merges found emails back onto the no-site targets by name.
- **Without a key**, it runs the Maps/Google contact fallback on the no-site
  outreach targets *plus* the with-site ones, so both get phone + email.

The fallback chain behind that is `maps_contact_fallback` →
`contact_finder` → `contact_enricher`:

`contact_finder` exists because Google surfaces no contact email for most
Indian colleges, yet most of them have a `*.ac.in` site with a contact page.
Per business, best-effort and time-bounded:

1. Bing search `"<name> official website"`, take the first non-social result.
2. No site? Probe candidate domains built from the name (token-join, acronym,
   common academic TLDs).
3. Follow up to 2 contact-ish links (contact / about / admissions).
4. Rank found addresses: `contact`/`info`/`admission`/`admin`-style local parts
   first; junk (`noreply`, `sentry`, `example`) skipped.

Every fetch in that path goes through the SSRF guard (§13). A business with no
findable address keeps an empty `to:` and is simply skipped at send time.

Handles written onto each business: `email`, `contact_finder_email`,
`contact_finder_domain`, plus `phone` where found.

---

## 6. Research

`research_workflow(businesses)` → `business_research.research_batch()`:
scrapes the business (site, Google reviews page) and asks the AI for
strengths, gaps, an email hook and one concrete improvement suggestion. Every
successful result is stored in the brain as per-business knowledge
(`brain/businesses/<name>.json`), and a `packet` event animates analyst →
brain on the floor.

Research is **optional context**: drafting works without it, and a failed
research call is recorded as `{"error": …}` and skipped.

---

## 7. Drafting

`draft_and_pdf_workflow(businesses, sender_name, research_data, goal, angles)`
— one loop per business.

**Context is layered, most specific first.** This order is the design:

```
1. USER'S ANGLE FOR THIS EMAIL      the campaign interview answer — must be followed
2. learning context                 per-category style learned from past sends
3. research on this business        rating, gaps, hook, improvement
4. brain memory of this business    rating, gaps, past interactions
5. team hook                        strategist's pre-written opening (if any)
6. AI profile hook + pain point     cached one-liner, grounded in scraped snippets
```

**The email itself** goes through the orchestrator: `orch.run("ai_draft_email",
{…, goal, learning_context})` → `ai_design.AIEmailDesigner._draft_email`. That
prompt implements Ikio's v2 sales-outreach training specification (see
`docs/superpowers/specs/2026-11-14-outreach-email-v2-training.md`):
- **Research first & name evidence**: names concrete courses, batches, website,
  or reviews found about the institute; never invents facts or pricing.
- **Issue-first opening (first 2 lines)**: `"I looked at [evidence]. That
  usually means [issue]."`. Never opens with generic "institutes like yours".
- **One tied offer**: `"We help training institutes get licensed AutoCAD seats
  at per-seat institute pricing, so [benefit]..."`.
- **Never say "keys"**: always says `"licensed AutoCAD seats"` / `"per-seat
  institute pricing"`. Never "keys" (reads as grey-market).
- **Exact CTA**: `"You can reply to this email, or message me on WhatsApp at
  {whatsapp}. If you would rather meet, we can schedule a short meet when you
  are free — just tell me a time that works for you."` (WhatsApp number defaults
  to `+91 6296 142368` via `OUTREACH_WHATSAPP` config).
- **Sender**: signed with a real name (`Ikio` by default, never "The Team").
- **Length**: 90–110 words.

If Gemini is unavailable, the orchestrator raises and `medium.py` writes the
template fallback version aligned with the same v2 rules (`HOOKS_BY_GOAL`,
WhatsApp CTA, `Ikio` sign-off).

**Attachments and assets.**

- A PDF proposal is generated per business (`pdf_gen.generate_proposal_pdf`,
  headline from the goal).
- A file attached in the composer is stored on the session as `__default__`
  and rides **every** draft that has none.
- A website is generated **only** when the goal sells websites *and* the
  business has no site (`icp.delivers_websites`). A licensing pitch does not
  build people a website.

Drafts are saved to the session (`email_drafts.json`, trimmed to slim business
records) so `review`/`send` work later, and `learn_from_draft()` +
`brain.learn_business(interaction="drafted")` record that we have been in
touch.

---

## 8. Review and send

`outreach_send` owns everything after a draft exists.

- `review_and_send_workflow()` — interactive: show email, edit / attach /
  approve / skip one at a time, then send only the approved.
- `send_emails_workflow()` — send the given drafts, skipping empty `to:`.
- `parse_send_selection()` — the interface grammar: `A` all, `S` skip,
  `1,3-5` ranges.

Each send calls `_send_one()` → `mailer.send_email()`, which guards against
empty recipients, defaults sender to `Ikio`, and sends via **Gmail SMTP**
(`smtp.gmail.com:465`, app password from config) with the PDF and any extra
file attached. `is_dry_run()` short-circuits it to a fake success, so dry runs
never touch the network.

> Discrepancy worth knowing: `agents/outreach_apis.py` already has keyed
> `resend_send` / `brevo_send` clients, and `AGENTS.md` describes a
> smtp → resend → sendgrid chain, but `mailer.py` in this checkout is SMTP
> only. The chain described there is not wired yet; sending today is Gmail.

After a successful send: a receipt PDF is written (`sent_email_pdf`), the
contact is marked approached in the vault, `learn_from_send()` records what
worked, the contacted-phones CSV is rewritten, and the brain gets
`interaction="sent"`.

Web-side review is a different machine — `web/review.py` keeps per-socket
state and handles `review_action` frames so the browser can step through drafts
without the CLI loop. Both paths end at the same `_send_one`.

---

## 9. Guided campaign

`campaign.py` is the human-in-the-loop version, and it **blocks on purpose**:

| Stage | Owner | Blocks? |
|---|---|---|
| 1. Discover & curate | `curate_workflow()` (search + ICP + top N) | no |
| 2. Web checklist | `checklist_payload()` | **yes** — approve/cancel |
| 3. Initial PDF | `initial_report_pdf()` (picked emails + phones) | no |
| 4. 1-by-1 brainstorm | `start_interview()` / `answer_interview()` | **yes** — per business |
| 5. Draft | `complete_outreach(angles=…)` | no |
| 6. Send + final PDF | `send_emails_workflow` + `final_report_pdf()` | no |

State lives in the session (`campaign_state.json`) and is mutated under
`_STATE_LOCK`, because the checklist handler, an interview answer and a
CLI-side send can all touch it. A saved gate outlives its socket: on connect,
`campaign_ui.maybe_resume()` re-opens the blocking conversation, otherwise the
flow would wait on nobody after a reload.

The interview is what produces the per-business **angle** in §7 — the most
specific instruction the drafter ever receives.

---

## 10. The AI seam and the agent team

**One module owns every model call**: `agents/ai/service.py`. Consumers call
typed capabilities — `score_fit`, `summarize_profile`, `draft_email`,
`classify_reply`, `expand_query`, `extract_contact`, `converse` — never the
SDK, a prompt string, or a key.

- `ai_engine.py` is the low-level engine (key, retries, model name;
  `get_ai_model()` — never hardcode a model string, a dead one 404s).
- `gemini_client.py` is the only bridge; `converse()` owns the function-calling
  protocol and the retry/quota policy for both the intent parser and the
  specialists.
- Static prompts are versioned files in `agents/ai/prompts/` (first line
  `<!-- version: N -->`). Dynamic system instructions (persona, memory, ICP)
  are assembled by the module that owns that context.
- `fallbacks.py` gives every capability a deterministic floor.
- `cache.py` memoizes `score_fit` / `summarize_profile` per business; drafts and
  reply classifications are never cached.

**Intent parsing** (`chatbot.parse_intents`) is Gemini-first with function
calling; greetings/help/brainstorm are local for speed. Greeting patterns are
checked before help patterns, or "how do i" eats "hi". The search tool spec
passes the user's category phrase **verbatim** — synonym-expanding it strips
the exclusion half of the sentence and reintroduces the old Bandel failure.

**The team** (`agent_team.py`) is a roster of specialists (scout, strategist,
analyst, builder, mailer…) with their own brain files, tools (`brain_query`,
`web_search`, `read_url`, `vault_query`, `propose_draft`) and a `look` +
`station` published by `/api/agents`. A new teammate is **data** in
`AGENTS` — no frontend edit, because the client projects the API into its maps.
`ask_agent()` chats; `team_act()` works a batch unprompted; `get_hook_for()`
feeds the strategist's opening into drafting.

Providers: Gemini first (`GEMINI_API_KEY`); OpenCode/Vercel when
`AI_PROVIDER` is selected and keyed; template fallbacks always. Unkeyed
providers are silently skipped — no errors, no retries, no network calls.

---

## 11. State on disk

`JODIAC_HOME` (default `jodiac_data/`) → `agent_output/`:

```
config.json                     every setting; agents/config.py is the only reader/writer
sessions/<id>/search_results.json    last search (businesses, no_website, goal)
sessions/<id>/email_drafts.json      trimmed drafts, for review/send after reload
sessions/<id>/campaign_state.json    the 6-stage gate state
sessions/<id>/attachments.json       {"__default__": path} rides every draft
brain/                          profile + businesses/ industries/ strategies/ sessions/ insights/
knowledge_base/                 4 JSON files + industry_research.json cache
memory/conversations.db         chat history (SQLite, WAL)
jodiac.db                       businesses, emails, sessions, usage (agents/db.py)
usage/usage.jsonl               one record per AI call (source of truth; DB mirrors it)
reports/ , sites/ , uploads/    PDFs, generated sites, composer uploads
vault.json                      PBKDF2-hashed key-vault code (gitignored)
```

`agents/db.py` owns the one SQLite file (stdlib, WAL, `foreign_keys=ON`, one
short-lived connection per call). `agents/store.py` is the only data-access
layer and every function degrades to a safe default on DB failure — telemetry
can never break the pipeline.

Obsidian vault (`JODIAC_OBSIDIAN`, default `D:/brain`): 7 note types with
cross-links, synced after every outreach run.

---

## 12. The web layer

`server.py` is assembly only: build app, mount `/static`, include `api` + `ws`,
run uvicorn. Behaviour lives beside it.

| Module | Owns |
|---|---|
| `api.py` | HTTP routes (below) |
| `ws.py` | the socket, message routing order, conversations |
| `job_queue.py` | per-socket serial queue + `queue_state` frames |
| `dispatch_bridge.py` | action → dispatch → frames; `shape_result()` |
| `review.py` | per-socket email review state machine |
| `campaign_ui.py` | checklist/interview conversations |
| `web_session.py` | the one shared `Session` |

**Socket routing order is deliberate** — first match wins:

```
review_action → campaign_checklist_action → review_cancel → cancel_queued
→ attachment on this message → active campaign gate → active brainstorm
→ active review conversation → parse_intents → queue the action
```

Anything arriving while a conversation is open is an *answer to it*, not a new
command. That is why the conversations are checked before intent parsing.

On connect: welcome (with session id, profile, any still-running jobs, and a
proactive briefing), `agent_events_replay` of the last 40 bus events, then
`queue_state`.

**HTTP surface**: `/`, `/index.html`, `/favicon.ico`, `/api/status`,
`/api/goals` (GET/POST), `/api/history`, `/api/conversation/{id}` (GET/DELETE),
`/api/upload`, `/api/campaign`, `/api/report/initial|final`, `/api/brain`,
`/api/agents`, `/api/agents/hire`, `/api/agents/{id}/deactivate`,
`/api/events`, `/api/skills*`, `/api/vault/*`.

**The floor** (`index.html` `#opsFloor` + `app.js`) animates bots from
`agent_event` frames: `bot` (status/task), `packet` (from → to), `brain`,
`step`, `team`. Stations are CSS positions; `app.js` routes by the roster from
`/api/agents`.

The UI is deliberately **zero-build** vanilla JS: `index.html`, `style.css`,
`app.js` + `js/` ES modules. Bump `?v=N` on the document's tags **and** every
`import … from './js/x.js?v=N'` together.

---

## 13. Security model

The office is loopback-only, but loopback is not a trust boundary: a browser
extension, a scraped page, or a model answer all run in the same address space
as the API.

**Auth: launch URL → HttpOnly cookie.**

```
start_server() prints  http://127.0.0.1:8765/?token=<per-launch secret>
        │
        ├─ GET /?token=<valid>  → 302 to /  +  Set-Cookie: jarvis_session=…
        │                                       HttpOnly; Path=/; SameSite=strict
        └─ anything else without the cookie → 401 (API) / lock page (document)
```

- The token is minted per process (`secrets.token_urlsafe(32)`) and never
  appears in the document. Nothing JS-readable holds it; `document.cookie` is
  empty, so an XSS cannot lift it.
- `request_token()` in `auth.py` is the single place that decides precedence:
  `X-JARVIS-Token` → `Authorization: Bearer` → cookie → explicit query (for
  scripted clients). The HTTP middleware and the socket both use it.
- The WebSocket handshake authenticates by the same cookie.
- Restarting the server mints a new token; the old cookie simply stops working.

**Request gate** (`server.py` middleware, in order): Host allowlist (DNS
rebinding) → Origin allowlist (CSRF; a foreign Origin is 403 even with a valid
cookie) → launch exchange → auth for mutating verbs and `SENSITIVE_READ_PREFIXES`.
Public: the document (cookie-gated inside `api.index`), `/static/*`, favicon.

**Headers** on every response, early returns included: strict CSP
(`script-src 'self'`, `connect-src` limited to the local socket), `nosniff`,
`X-Frame-Options: DENY`, `no-referrer`, restrictive `Permissions-Policy`.

**Fetch guard** (`agents/url_guard.py`). Every `Fetcher.get` fed by a scraped
page or a model goes through `safe_url()`:

- http/https only, no credentials-in-URL, no control characters;
- loopback / RFC1918 / CGNAT / link-local (cloud metadata) / multicast /
  reserved / IPv6 ULA refused, plus `localhost`, `.local`, `.internal`;
- the host is **resolved** and every address must pass too (DNS rebinding);
- `MAX_REDIRECTS = 5` is passed to the client; `check_final_url()` re-checks
  where the client actually landed.

Used by `agent_team` (Bing + `read_url`), `contact_finder._fetch`,
`business_enricher` (site scrape + reviews).

**Key vault** (`web/vault.py`): access-code gated (PBKDF2, 5-strike lockout),
masked previews only; `/api/vault/reveal/{id}` with a live token is the only
route that ever returns secret material. Tokens die on restart.

**Mass assignment** is avoided by explicit payload keys; errors returned to the
client are sanitised (`_sanitize_error` → message + `error_id`).

---

## 14. The learning loop

Everything the system notices is written to the brain, and four things read it
back:

| Writes | Read back by |
|---|---|
| `learn_from_search` — which places were kept/dropped, per area | ICP ranking, next search in that area |
| `icp.learn` — signal → fits/unlikely counters per **goal** | `classify()` weighting |
| `learn_from_draft` / `learn_from_send` / `learn_from_rejection` | `get_learning_context(category)` → drafting |
| `brain.learn_business` — rating, gaps, interactions | `get_business_context(name)` → drafting, briefings |
| `agent_team._remember` — per-specialist facts | `_recall()` → that agent's prompt |
| `store.log_usage` (JSONL + DB) | `provider_stats()` — grades the provider cascade |

Learning writes are always wrapped: a brain failure must never break a search,
a draft or a send.

---

## 15. When something is down

| Failure | Behaviour |
|---|---|
| Overpass rate-limited / unreachable | Geoapify → Google Maps → honest error naming the cause |
| Overpass answers empty everywhere | Treated as a genuinely empty area (believed only if all agrees) |
| Nominatim fails | "Could not find that location" — no search runs |
| Gemini unavailable | `fallbacks.*`: ICP verdict, template email, keyword reply triage |
| Hunter key missing | Maps/Google contacts → website scraping |
| A business's site unreachable | Best-effort scrape returns nothing; the business keeps an empty `to:` and is skipped |
| Gmail not configured | `{"success": False, "error": "Gmail not configured…"}` per send; nothing else stops |
| DB / brain write fails | Swallowed by design; the run continues |
| Web socket drops mid-job | The job keeps running in its worker thread; the next socket is told via `running_labels()` |
| Server restarts | New auth token; the browser must open the new launch URL |

---

## 16. Where to change what

| You want to… | Change |
|---|---|
| add an action | `ActionType` (chatbot.py) + row in `action_registry.py` + handler in `action_dispatch.py` + dispatch in `chat_handler.py` **and** `ws.py` |
| change what a search sells | `icp.py` goals (and the goal keys in `config`) |
| change who counts as a customer | `icp._type` verticals / `goal_of` |
| change how a category is judged | `category_filter.py` (exclusions, `_no_category_signal`, tiers) |
| add a discovery source | `map_search.py` (then `workflows` failover order) |
| change the email voice | `ai_design.py` prompt (and `medium.HOOKS_BY_GOAL` for the template path) |
| change what context a draft sees | `draft_and_pdf_workflow` context stack (§7) |
| add an AI capability | new `service.py` method + versioned prompt file + `fallbacks.py` floor |
| add a teammate | one dict in `agent_team.AGENTS` (`name`/`role`/`look`/`station`) |
| add a floor event | `event_bus.VALID_KINDS` + `handleAgentEvent` in `app.js` (+ CSS) |
| restyle the office | `style.css` / `index.html` — skin only, never dispatch/queue/server |
| ship frontend changes | bump `?v=N` in `index.html` **and** every `js/*.js?v=N` import |

Self-checks: `"E:/python.exe" -X utf8 tests/test_final_audit.py` (20 checks,
exits 1 on any failure) plus the pytest suites (`tests/test_security_*.py`,
`test_url_guard.py`, `test_db.py`, `test_category_exclusions.py`, …).
