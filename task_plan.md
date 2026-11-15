# Task Plan — JARVIS: audit + step-by-step upgrade

**Goal:** make this app actually deliver its stated job — find private training
centres / coaching institutes in a given area, with a contactable decision-maker,
and pitch AutoCAD licensing — without breaking what already works.

**Status:** AUDIT COMPLETE. **AWAITING USER REVIEW.** No code has been changed.

**Next Step:** user reviews `docs/superpowers/specs/2026-11-13-reliability-upgrade-design.md`
and approves (or re-orders) Phases 0–7. Implementation starts only after that.

---

## The one-line verdict

The office UI, the ICP seam, the security middleware and the provider cascade are
all in visibly better shape than the repo's own notes suggest. **The thing that is
broken is the middle of the funnel:** the discovery source cannot see private
coaching centres at all, the goal scoring ranks them near-lowest, the user's own
category phrase deletes them, and the pipeline only ever hands "businesses with no
website" to the draft step. Result from a real playtest: *a 3 km search for
"private training centres … that teach AutoCAD" returned 2 engineering colleges,
0 training centres, 0 usable phone numbers.*

---

## Phases

| # | Phase | Why it is in this position | Status |
|---|-------|---------------------------|--------|
| 0 | Freeze the working tree | 36 modified files / +1287 lines are uncommitted; no audit can tell "new bug" from "old bug" | pending |
| 1 | Security fixes | Cheapest to fix, independent of the funnel work | pending |
| 2 | Test + audit integrity | A suite that exits 0 while failing makes every later phase unverifiable | pending |
| 3 | Discovery: be able to *see* coaching centres | Root cause of the playtest failure; everything downstream is noise without it | pending |
| 4 | Goal fit: score the actual buyer | Needs Phase 3 data to validate against | pending |
| 5 | Contact capture (phone / email) | A lead without a contact is not a lead | pending |
| 6 | DB audit + wire-up | Turns one-shot runs into a queryable campaign history | pending |
| 7 | AI animation / rationale surfacing | Polish that only matters once 3–6 produce leads | pending |
| 8 | End-to-end verification gate | Prove the goal on a real area before calling it done | pending |

### Phase 0 — Freeze the working tree
- `git stash list` / inspect the 36 modified files; commit them as one reviewed
  baseline (or leave a written note of what is pre-existing).
- Acceptance: `git status --short` is clean except intentionally-ignored runtime
  data, so every later diff belongs to the upgrade.

### Phase 1 — Security fixes (details in spec §1)
1. S1 Auth token is injected into the **public** `/` document (`api.py:90-96`,
   `auth.py:15`). Move to a launch-URL token → `HttpOnly; SameSite=Strict` cookie;
   strip the meta tag. Add `frame-ancestors 'none'` to the CSP.
2. S2 Config setters are silently ignored when the env var is set
   (`config.py:165-172`; verified: `set_ai_provider("opencode")` then
   `get_ai_provider()` still `"gemini"`). Setters must report env-lock and the UI
   must say "locked by .env".
3. S3 SSRF: `agent_team.py:537,572`, `contact_finder.py:264`,
   `business_enricher.py:56` fetch arbitrary scraped/AI URLs. Add one `_safe_url()`
   guard (http/https only, no loopback/link-local/RFC1918, redirect cap).
4. S4 CSP hardcodes `ws://127.0.0.1:8765` while the port is configurable.
5. S5 `providers.py:176` sends the **shared** `AI_PROVIDER_KEY` to every provider
   in the cascade — a key can be presented to the wrong host.
- Acceptance: existing `tests/test_security_*.py` all pass, plus new checks for S1,
  S2, S3, S5.

### Phase 2 — Test + audit integrity
1. `tests/test_final_audit.py` prints "19 passed, 1 failed" and **exits 0**
   (verified). Make it `sys.exit(1)` on any failure.
2. The failing check `ai_fallback_chain` asserts `AIDesignAgent.handle()` falls back
   to the template drafter; the fallback lives only in `Orchestrator.run()`
   (`orchestrator.py:131-142`). Decide the contract, then fix code **or** assertion
   (recommend: keep orchestrator as the contract, fix the assertion, and add an
   explicit agent-level test only if agent-level fallback is wanted).
- Acceptance: `tests/test_final_audit.py` exits 0 with 20/20, and exits 1 when a
  check is deliberately broken.

### Phase 3 — Discovery: see the actual market
**Source decision (measured 2026-11-13): add Overture Maps Places as the primary
local source — free, no key, 1,979 places in the Bandel 3 km box vs 20 today,
including 13 `computer_coaching` + 8 `tutoring_service` + 1 `test_preparation` with
phones.** See `findings.md` §10.

1. New `agents/overture_source.py`: DuckDB over the public S3 parquet, `bbox`
   prefilter then `ST_Distance` for the radius, mapping
   `taxonomy.primary` → the existing pipeline dict shape (name, lat, lon, phone,
   website, email, address, category, tags, source="overture").
2. Cache each search box to a local parquet under `OUTPUT_DIR` so repeat searches
   skip the 30–45 s scan; skip the source cleanly if DuckDB is not installed.
3. Keep OSM/Overpass and Geoapify as the fast/no-dependency fallbacks; add TomTom
   (5k Discover/month, no card, phones+websites) as an optional keyed source for
   sub-second radius searches, and Google Places IDs-only as an optional
   top-up for the 1,000 free Enterprise lookups.
4. Fix the Geoapify phrase mapping for coaching/training
   (`map_search._CATEGORY_HINTS`), keeping the documented rule that an
   unverified bucket must never enter the table.
5. Record source coverage honestly in the card: which source answered, how many
   rows it had, and what it cannot see.
- Acceptance: a 3 km Bandel search surfaces ≥1 real coaching institute by name, and
  the card names the source and its row count.

### Phase 4 — Goal fit for the actual buyer
1. `icp.py` `_CAD_VERTICALS`: `coaching/tutorial` = 60 and `school (K-12)` = 55
   rank *below* engineering colleges (92) — backwards for this business.
2. `category_filter.py`: the phrase "private training centres …" caused
   `Filtered 7 -> 2 … AI dropped 5 school`; private institutes are tagged `school`
   in both sources, so the phrase deletes the named audience.
3. `action_dispatch._handle_search` returns `businesses: no_site`, and
   `_handle_draft` reads `no_website` — so an institute **with** any web presence
   can never be pitched, even for a licence sale. This is the most expensive bug in
   the funnel.
- Acceptance: for the same area, the kept list contains training centres, and a
  training centre with a Facebook-only presence still reaches the draft step.

### Phase 5 — Contact capture
- Playtest: 2 kept → 0 emails, 0 phones; `[CONTACT] nothing for …`; ENRICH-V2 found
  one Yahoo address across both.
- Work the configured free tiers (`GEOAPIFY_API_KEY` for phones, `REACHER_URL`,
  Tavily) before scraping Google/Bing result pages.
- Acceptance: ≥1 usable contact (phone or email) for ≥50% of kept institutes in a
  3 km area, with per-lead provenance.

### Phase 6 — DB audit + wire-up
- `agents/store.py` has exactly one consumer (`usage_log.py:53`); `businesses`,
  `emails`, `sessions` have **zero** writers. Either wire them or drop them — dead
  schema is worse than no schema because it implies history that does not exist.
- Add: lead persistence + cross-run dedupe, send audit trail, `db.status()` on
  `/api/status`, `usage` retention, one `VACUUM`/checkpoint policy.
- Acceptance: two consecutive searches show "3 new / 12 already seen"; `/api/status`
  reports schema version + journal mode.

### Phase 7 — AI animation and rationale
- `workflows.py:166-172` computes `ai_rationale` and `dispatch_bridge.shape_result`
  drops it → the card shows a score with no reason.
- The 5 serial `score_fit` calls emit **no** events, so the floor idles through the
  slowest phase. Add `bot`/`packet` events per scored lead and a "why this fits"
  line in the results card.
- Add an AI-provider chip (served provider, or "template fallback") so the cascade
  is visible.
- Acceptance: during a live search the floor narrates the AI stage; the card shows
  the AI's reason for each fit; no console errors.

### Phase 8 — Verification gate
- One real end-to-end run: search → results card → draft → review → send (DRY_RUN=1)
  in a real area, with the numbers recorded in `progress.md`.
- Re-run `tests/test_final_audit.py` + `test_db.py` + `test_category_exclusions.py`
  + the security suites.

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Audit-and-plan only this session | User explicitly asked for a plan-mode summary and will review before code changes |
| Recommend re-ordering the user's requested order (security → animations → DB → usefulness) to put discovery before animations | Animation and DB work cannot be validated while the funnel returns 0 training centres |
| Treat "businesses with a website are un-pitchable" as P0 funnel bug | Contradicts the CAD-licensing goal, where web presence is irrelevant |
| No provider recommendation for places data | Gravity search returned no valid substitute; the existing Apify/Outscraper adapters are the correct tools and only need a key |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| `AUDIT_EXIT=0` while the suite printed `1 failed` | 1 | Recorded as Phase 2 finding; not yet fixed (plan-only) |
| Overpass unreachable during playtest | 1 | Confirmed the Geoapify fallback path fired; recorded as Phase 3 evidence |
| `set_ai_provider("opencode")` did not change the resolved provider | 1 | Root-caused to env precedence in `config.py:165`; recorded as S2 |
