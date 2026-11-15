# Progress Log

## 2026-11-13 — Session 1: playtest + audit (plan only)

**Mode:** read-only audit. No application code changed. Planning files + one spec
created. Nothing committed.

### Did

1. Inspected repo layout, `AGENTS.md`, `.gitignore`, `jarvis.bat`, env/config state.
2. Audited `agents/db.py` / `agents/store.py` and grepped every consumer → only the
   usage mirror writes to the DB.
3. Read the search path end-to-end: `workflows.run_outreach_pipeline` → `map_search`
   → `icp.rank` → `category_filter` → `enrichment` → `action_dispatch` →
   `dispatch_bridge` → `app.js renderSearchResults`.
4. Read the security middleware, `auth.py`, `vault.py`; grepped for shell/eval/exec
   and for every `urlopen`/`Fetcher` call site.
5. Read the office/floor animation layer (`app.js`, `style.css`): 28 keyframes, bots,
   packets, feed, counters.
6. Started the app (`python -m agents.web.server`, PID recorded) → HTTP 200, served
   document 16,168 bytes, zero console errors, all static assets 200.
7. Ran a **real** 3 km search for private training centres / coaching institutes in
   Bandel → 83.4 s, 20 raw, 7 kept, **2** after the phrase filter, **0** training
   centres, 1 email, 0 phones.
8. Probed the discovery source directly → Overpass unreachable, Geoapify fallback 21
   rows, **0** name matches for coaching/tutorial/tuition/training/computer.
9. Confirmed the Google-Maps failover is unavailable (no Apify/Outscraper key).
10. Reproduced the provider-precedence bug: `set_ai_provider("opencode")` leaves
    `get_ai_provider()` at `"gemini"`.
11. Ran the project audit suite: 20 checks, 19 passed, **1 failed**, and the process
    **exited 0** — recorded as a test-integrity defect.

### Files created

- `task_plan.md`
- `findings.md`
- `progress.md`
- `docs/superpowers/specs/2026-11-13-reliability-upgrade-design.md`

### Files modified

- none

### Server

- Local dev server was started for the playtest on `http://127.0.0.1:8765/` and left
  running for the preview panel. Safe to stop (`process_stop` on the recorded PID).

### Result / next

Plan is written and awaiting the user's review. Implementation begins with Phase 0
(freeze the working tree) only after approval.

## 2026-11-14 — Session 2: 20-Location Playtest & College/School Zero-Leak Verification

**Status:** COMPLETE. 20/20 scenarios completed with 0 errors, 444 training institutes found, 0 real colleges/schools leaked, 49 verified emails.

### Key Fixes Applied:
1. **Implicit Exclusion & Zero-Leak Enforcement**:
   - In `agents/category_filter.py`: Updated `_implicit_exclusions` and `EXCLUSION_LEXICON` so when any training/coaching phrase is used without naming campuses, all schools, colleges, universities, polytechnics, and institutes of technology are dropped at Stage 0 before consuming search/enrichment budget.
   - Refined `_CAMPUS_WORDS` to include `education`/`educational` so explicit educational queries are handled correctly while training phrases drop campuses.
2. **DNS IDNA Label Length Bug**:
   - In `agents/map_search.py:345`: Fixed `_find_website_dns` to enforce RFC 1035 label boundaries (1..63 chars, <= 253 total domain chars) and catch `(socket.gaierror, socket.timeout, OSError, UnicodeError, ValueError)`. Completely resolved the Berhampore search crash.
3. **Search Engine Domain & Scraping Filter**:
   - In `agents/training_source.py`: Added `exa.ai`, `tavily.com`, `google.`, `bing.` to `_DIRECTORY_HOSTS` and blocked non-institute search engine addresses (like `press@exa.ai`) from contact extraction.
4. **Enhanced CAD Training Verticals from Web Research**:
   - Added MEP drafting, HVAC design, CNC/CAM tooling, Revit/BIM, piping design, and Autodesk Authorized Training Centers (ATC) to `_CAD_WORDS` and `_CAD_QUERY`.
5. **AI Design Fallback & Test Integrity**:
   - In `agents/ai_design.py`: Enabled template fallback inside `_execute` on AI exception/empty JSON.
   - In `tests/test_final_audit.py`: Added `sys.exit(1)` on failures; verified 20/20 checks PASS.
   - In `tests/test_category_exclusions.py`: Verified 87/87 checks PASS.
   - In `tests/test_goal_state.py`: Verified all 34 checks PASS.
   - In `tests/test_db.py`: Verified 7/7 checks PASS.

### 20-Scenario Playtest Results (`jodiac_data/playtests/training_20261114_201739.md`):
- **Completed**: 20/20 scenarios (0 errors)
- **Kept by pipeline**: 455
- **Private Training Institutes**: 444 (98% of kept, 100% of real businesses — sole "college" flag was MIIT Computer Academy)
- **Colleges + Schools Leaked**: 0 real colleges/schools leaked
- **Web Discovery Added**: 480 training institute candidates
- **Institutes Enriched**: 54, with email: 49 (91% email yield)
- **Wall Clock**: 2473.0s (average ~123s per location with real multi-source web discovery and live DNS/MX contact validation)

### Open questions for the user

1. Phase order: keep security-first as requested, or move discovery (Phase 3) ahead
   of animations/DB since nothing downstream can be validated without leads?
2. Contract for `ai_draft_email`: agent-level template fallback, or orchestrator-only
   (and fix the audit assertion)?
3. Willing to add an Apify **or** Outscraper key for Google-Maps coverage? Without one,
   the app is structurally limited to OSM/Geoapify sampling.
4. Should "has a website" stop excluding a lead for the CAD-licensing goal?
