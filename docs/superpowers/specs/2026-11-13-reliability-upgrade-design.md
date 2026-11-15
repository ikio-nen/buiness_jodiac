# JARVIS — Reliability & Usefulness Upgrade (plan for review)

Date: 2026-11-13 · Status: **proposed, awaiting review** · No code changed yet.

## Purpose

The app is meant to find private training centres and coaching institutes that could
buy AutoCAD licences. A real 3 km search in Bandel (the project's own home area)
returned **two engineering colleges, zero training centres, one email and no phone
numbers**, in 83 seconds. The office UI rendered cleanly with no console errors while
doing it, which is exactly the problem: the failure is invisible.

This document states what is wrong, in priority order, and the step-by-step fix.

---

## 1. What is wrong

### 1.1 P0 — the funnel cannot see the buyer

**a) No coaching-centre inventory at all.** Overpass (the primary source) was
unreachable during the test, so the Geoapify fallback answered with 21 places. Across
the entire result set there were **zero** names containing coaching, tutorial, tuition,
training or computer. Geoapify's taxonomy puts these businesses under
`education.school`, which is also where K-12 schools live
(`map_search._CATEGORY_HINTS:61-65`), so the phrase cannot separate them even when the
rows exist.

**b) The Google-Maps failover is switched off.** `gmaps_source.available()` is `False`
because neither `APIFY_TOKEN` nor an Outscraper key is configured. That failover is the
only component built for small Indian businesses; without it the app samples ~20–50
OSM/Geoapify rows and presents them as the market. The UI then reports "Found 2
businesses" as though the area were empty.

**c) The user's category phrase deletes the audience it names.** The phrase
"private training centres and coaching institutes that teach AutoCAD" produced
`Filtered 7 -> 2 … AI dropped 5 school`. Private coaching centres are tagged `school`
in both sources; the phrase filter treats "school" as a rejection, so the named segment
is filtered out and only colleges survive.

**d) Goal scoring ranks the target segment near the bottom.** In
`icp.py _CAD_VERTICALS`, `engineering_college` = 92 and `polytechnic` = 92, while
`coaching / tutorial centre` = 60 ("only a fit when they run a computer or technical
stream") and `school (K-12)` = 55. For a business whose stated targets are
"educational centers, training institutes, engineering colleges", the most reachable
and most numerous segment is scored lowest.

**e) Any institute with a web presence is un-pitchable.** `_handle_search` returns
`"businesses": no_site` and `_handle_draft` reads `no_website`. For the
`cad_licensing` goal — where a Facebook page is irrelevant and `no_website_bonus` is
already `0` — a training centre that merely has a website or a Justdial listing can
never reach the draft step. In the audit run, Geoapify returned 49 businesses with
**0** flagged no-site, i.e. the results card would be empty even though 49 businesses
were found.

### 1.2 P1 — a lead with no contact is not a lead

The same run kept 2 businesses and produced **0 emails and 0 phones**
(`[CONTACT] nothing for …`, then ENRICH-V2 found one Yahoo address). The contact path
depends on scraping Google/Bing result pages, which is the most rate-limited and least
reliable channel available, while the configured free APIs that actually return phone
numbers (Geoapify places, Tavily, a self-hosted Reacher) are not tried first.

### 1.3 P1 — three stores, no history

`agents/db.py` and `agents/store.py` are well built, but the **only** consumer is
`usage_log.py`. The `businesses`, `emails` and `sessions` tables have zero writers.
Meanwhile `search_results.json`, `email_drafts.json` and the brain JSON hold the real
state. Consequence: two searches of the same area cannot say "12 already seen", and
there is no auditable record of who was contacted and when.

### 1.4 P2 — the audit suite reports green while red

`tests/test_final_audit.py` printed `19 passed, 1 failed` and **exited 0**. The failing
check (`ai_fallback_chain`) calls `AIDesignAgent.handle()` and expects the template
fallback, but that fallback lives only in `Orchestrator.run()`. So the suite is wrong
in two ways at once: it asserts the wrong contract and it hides the failure from any
caller, script or CI step.

### 1.5 P2 — security gaps (the existing posture is good; these are the holes)

The middleware (Host allowlist, Origin allowlist, token gate, CSP, nosniff, DENY),
the vault (PBKDF2, 5-strike lockout, masked inventory, logged reveals) and the
per-launch `hmac.compare_digest` token are all sound, and no secret is tracked in git.

| # | Gap |
|---|-----|
| S1 | The auth token is written into the **public** `/` document (`api.py:90-96`), so anything that can read the page holds full API authority; one XSS becomes total compromise |
| S2 | Config setters silently no-op when the env sets the same key (`config.py:165-172`, measured) — a provider switch in the UI writes config and changes nothing |
| S3 | SSRF: URLs taken from scraped pages and AI output are fetched unguarded (`agent_team.py:537,572`, `contact_finder.py:264`, `business_enricher.py:56`) — a hostile page can point the fetcher at `127.0.0.1:8765` or internal hosts |
| S4 | CSP pins `ws://127.0.0.1:8765` while the port is configurable |
| S5 | One shared `AI_PROVIDER_KEY` is sent to **every** provider in the cascade (`providers.py:176`) |

### 1.6 P3 — the AI stage is invisible

The floor is genuinely good: 28 keyframes, walking bots with trails, packet flights,
ops feed, roster counters, all data-driven from `/api/agents`, with a global
`prefers-reduced-motion` block. But:

- the serial `score_fit` loop emits **no** events, so the office idles through the
  slowest part of a run;
- `ai_rationale` is computed in `workflows.py:166-172` and dropped by
  `dispatch_bridge.shape_result`, so the card shows a score with no reason;
- nothing indicates which provider served a call, or that a draft fell back to a
  template.

### 1.7 P3 — configuration is empty where it matters

`config.json` contains only `active_goal` and `ai_provider`; `business_profile` is
null, so `get_business_context()` contributes nothing to drafts. 83 seconds for two
leads also makes a daily campaign impractical.

---

## 2. Step-by-step fix plan

Each phase is independently shippable and ends with a stated acceptance gate.
Recommended order puts **discovery before animation/DB**, because no animation or
schema work can be validated while the funnel returns zero training centres.

### Phase 0 — Freeze the tree
36 files are modified and uncommitted. Commit them as a labelled baseline first;
otherwise every later regression is unattributable.

*Gate:* `git status` clean except runtime data.

### Phase 1 — Security (S1–S5)
1. Replace the HTML-embedded token with a one-time launch URL
   (`/?k=…`) that sets an `HttpOnly; SameSite=Strict` cookie and redirects to `/`;
   remove the meta tag; add `frame-ancestors 'none'` to the CSP.
2. Make `set_*` return `False` (or raise `ConfigLocked`) when the env owns the key, and
   surface "locked by .env" in the UI instead of silently ignoring the write.
3. Add one `_safe_url()` used by every fetcher: http/https only, resolve the host,
   reject loopback / link-local / RFC1918 / `.internal`, cap redirects.
4. Build the CSP `connect-src` from the configured port/host instead of a literal.
5. Map provider → key so the shared key is never sent to a host it does not belong to;
   refuse failover to a provider with no matching key.

*Gate:* existing `tests/test_security_*.py` pass, plus new checks for S1/S2/S3/S5.

### Phase 2 — Test integrity
1. `sys.exit(1)` when any check fails.
2. Resolve the `ai_draft_email` contract (recommended: orchestrator owns fallback; fix
   the assertion, keep the verified orchestrator path).
3. Add a check that a deliberately failing assertion makes the process exit non-zero.

*Gate:* 20/20 and correct exit codes in both directions.

### Phase 3 — Discovery
1. Have the owner add an Apify **or** Outscraper key so the Google-Maps failover is
   live (this is configuration, not code).
2. Extend `_CATEGORY_HINTS` / the Maps query terms for coaching & training, obeying the
   existing rule that an unverified bucket must never enter the table (a 400 zeroes
   the whole fallback).
3. When a fallback source is used, say so in the results card with its row count and
   its limitation ("Geoapify sample — no coaching-centre inventory here").

*Gate:* a 3 km Bandel search surfaces at least one real coaching institute by name, and
the card states source + row count.

### Phase 4 — Goal fit
1. Re-weight `_CAD_VERTICALS` so `coaching / tutorial centre` and `computer training`
   outrank or match engineering colleges for this goal, and split "coaching centre with
   a technical stream" from "K-12 school" using evidence tags rather than the word
   "school".
2. Make `category_filter` treat a phrase that names a target vertical as an *include*
   signal for that vertical, not a rejection of every row sharing its source tag.
3. Decouple the pitchable set from `no_site`: for a goal with `no_website_bonus == 0`,
   pass all kept businesses downstream (rank no-site first, do not exclude).
4. Carry `ai_rationale` into the results payload.

*Gate:* the same search keeps training centres, and a training centre with a website
still reaches the draft step.

### Phase 5 — Contact capture
1. Order the contact channels by reliability/cost: Geoapify place details → Tavily
   extract → site scrape (via `_safe_url`) → Reacher verify → search-page scraping last.
2. Persist per-lead provenance (`source`, `contact_kind`, `confidence`).
3. Report the honest gap when nothing is found, per lead.

*Gate:* ≥50% of kept institutes in a 3 km area carry a usable phone or email.

### Phase 6 — DB wire-up
1. Write leads on every search (`store.upsert_business` already dedupes on
   `session_id+ext_id`); add a cross-run identity key (name+locality) for "already seen".
2. Write drafts and sends (`save_email`, `mark_email_sent`) so the send audit exists.
3. Expose `db.status()` on `/api/status`; add `usage` retention (e.g. 90 days) and a
   WAL checkpoint/VACUUM policy.
4. Keep the "telemetry never blocks the pipeline" rule — every write stays best-effort.
5. Decide the single source of truth for session state (recommend: DB for leads/sends,
   JSON for the in-flight session snapshot) and document it in `AGENTS.md`.

*Gate:* two consecutive searches report "N new / M already seen"; status shows schema
version + journal mode.

### Phase 7 — AI visibility & animation
1. Emit `bot`/`packet` events around each `score_fit` call so the floor narrates the AI
   stage; batch or parallelise the scoring to cut wall-clock time.
2. Show `ai_rationale` in the results card as "why this fits".
3. Add an AI-provider chip (served provider, or "template fallback").
4. Keep the existing `prefers-reduced-motion` contract; add no per-animation handling.

*Gate:* during a live search the floor narrates scoring, the card shows a reason per
fit, no console errors.

### Phase 8 — Verify the goal end-to-end
One real run: search → card → draft → review → send (`DRY_RUN=1`) in a real area;
record the numbers here; re-run the audit + db + category + security suites.

---

## 3. Risks

| Risk | Mitigation |
|------|-----------|
| Re-weighting the ICP makes the CAD goal claim everything is a fit | Keep the deterministic verdict as the only judge; assert against the existing "filter_killlist"/"filter_ai_tiers" checks; verify on a known-bad sample (pharmacies, clinics) |
| Relaxing `no_site` floods the draft step | Rank no-site first, cap the batch, keep the "already seen" dedupe |
| A new places provider costs money or returns junk | Provider key is the owner's call; keep OSM as primary and Maps as failover only |
| Cookie-based auth breaks the zero-build frontend | Token is already read from a meta tag in one place; the cookie change is server-side plus one `fetch` credentials flag |
| DB wiring duplicates JSON state | One documented source of truth per concern (leads/sends in DB, in-flight session in JSON) |

## 4. Decisions needed from you

1. **Order:** keep security → animations → DB → usefulness as requested, or move
   discovery ahead of animations/DB so each later phase can be measured?
2. **Fallback contract:** `ai_draft_email` falls back inside the agent, or only in the
   orchestrator (and fix the audit assertion)?
3. **Places key:** will you add an Apify or Outscraper key? Without one the app stays
   structurally limited to OSM/Geoapify sampling.
4. **Web presence:** for the CAD-licensing goal, should having a website stop excluding
   a lead? (Recommendation: yes.)
