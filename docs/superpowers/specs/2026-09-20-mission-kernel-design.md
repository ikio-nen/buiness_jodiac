# Mission Kernel — One-Shot Outreach Missions

**Date:** 2026-09-20
**Status:** Approved design (chat review, 2026-09-20)
**Path:** Architectural · Approach A — mission kernel wrapping the existing pipeline
**Related:** AGENTS.md ("Category filtering is POST-search" section), `agents/test_category_exclusions.py`

## Problem

JARVIS runs the pipeline fire-and-forget. Stages execute, logs stream, and the run ends claiming success regardless of whether each stage actually did its job. Every serious failure this month — the AI filter dropping nothing, schools resurrected by the ICP veto, contact finder reporting unexplained zeros, Gemini paths dying silently on format errors — was a stage-level defect that the current "compile + smoke" audit cannot see. The user's goal: type one message like *"find 20 academies in Kolkata, remove schools and colleges, stage emails"* and have JARVIS execute it unattended, with every stage either proving it did its job or saying honestly why it didn't.

## Goals

1. **One-shot missions.** A single chat message starts a mission that runs search → enrich → contacts → draft → stage without further prompts.
2. **Stage postconditions.** A stage is `done` only when the kernel can verify its output contract; otherwise it is `degraded` with a machine reason and a human line — never silently `done`.
3. **Crash resume.** Mission state persists in SQLite; a restarted run resumes at the last verified stage.
4. **Pre-flight doctor.** A run that cannot succeed (missing key, dead network, broken config) is stopped before burning quota, with a list of what will fall back.
5. **Honest reporting.** The end-of-mission report contains a funnel that is internally consistent by construction and a degradation list; nothing claims success it did not verify.
6. **Human sends.** Missions auto-run through staging (review queue). Nothing is sent without the user's click — the existing review flow stays the final gate.

## Non-goals

- No rewrite of `workflows.py` or `pipeline_handler.py` — the kernel wraps existing stage functions.
- No new Gemini capabilities or prompt changes.
- No scheduling, parallel missions, or open-ended runtime planning. Missions are outreach-shaped; variation comes from parameters, not new code.
- No auto-send, ever.

## 1. Mission record & lifecycle — `agents/mission.py` (new)

One SQLite store: `agent_output/memory/missions.db` (WAL mode, same pattern as `chat_memory.py`).

```sql
CREATE TABLE IF NOT EXISTS missions (
  id           TEXT PRIMARY KEY,          -- msn_<UTC timestamp>_<rand>
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  state        TEXT NOT NULL,             -- planned|preflight|running|staged|degraded|failed|cancelled
  goal         TEXT NOT NULL,             -- verbatim user text (never paraphrased)
  params       TEXT NOT NULL,             -- JSON: product, localities[], count, exclusions[], tone
  stages       TEXT NOT NULL DEFAULT '{}',-- JSON: {stage: {status, reason, human, started, ended}}
  degradations TEXT NOT NULL DEFAULT '[]',-- JSON: [{stage, reason, human}]
  outputs      TEXT NOT NULL DEFAULT '{}',-- JSON: {stage: result blob} — per-stage outputs so resume
                                          -- can continue (drafting needs search's kept list)
  result       TEXT NOT NULL DEFAULT '{}' -- JSON: funnel counts, report path
);
```

**State machine.** `planned → preflight → running → staged | degraded | failed`, plus `cancelled` from any non-terminal state. Terminal: `staged`, `degraded`, `failed`, `cancelled`. Every transition is persisted before the next stage starts.

**Single active mission.** Starting a mission fails with a clear message if a row exists in `planned | preflight | running`. (JARVIS is single-user and the web job queue already serializes overlap.)

**Resume.** On kernel init, a mission found in `planned | preflight | running` is stale from a crash; `resume()` re-runs only stages not marked `done` and continues from there. Each stage persists its output blob (JSON) alongside its status when it completes, so a resumed mission never re-runs a `done` stage — a crash during drafting resumes from the persisted search/enrich/contacts outputs and does not re-search or re-burn quota. If a persisted output blob is missing or unparsable, that stage is treated as not done and re-runs (correctness over cleverness).

**Owner rule.** `mission.py` owns mission state, orchestration, and the report. It calls existing `workflows` functions; `workflows.py` is untouched. All telemetry goes through `event_bus.emit(kind="mission")`; emit failures are swallowed (telemetry never breaks the pipeline — existing house rule).

## 2. Stage contracts — the no-silent-errors core

Each stage has one postcondition function the kernel runs before marking `done`. On failure the kernel invokes the stage's existing fallback path once, re-checks, then marks `degraded` (reason + human line) and applies the blocking policy.

| Stage | Wraps | Postcondition (all must hold) | Blocking policy |
|---|---|---|---|
| `search` | `workflows` search + ICP + `category_filter` | kept + dropped == input count; every exclusion in `params.exclusions` was applied (Stage 0 ran); if kept == 0 the report carries a reason string | **hard** — no search results, no mission |
| `enrich` | no-site verify / research | every no-site business has an attempt record (success or named failure) | soft — failures are listed, run continues |
| `contacts` | email/phone discovery | report states emails/phones found **or** an explicit "none found, source: X" | soft |
| `draft` | `ai_design` / `medium` | every kept business has a draft **or** appears in a named draft-failure list | hard if zero drafts *and* zero named failures; otherwise soft |
| `stage` | review queue | review-queue count == draft count | hard — mismatch means state desync, abort to `failed` |

**Degradation, not death.** A soft-degraded stage lets the mission finish; the report carries the degradation. A hard failure ends the mission as `failed` with the stage's reason. `staged` means zero degradations; `degraded` means completed with at least one soft degradation. There is no state in which a stage did not run and the report says the mission succeeded.

**Exclusion authority is preserved.** `search`'s postcondition re-derives exclusions from `params` via `extract_exclusions()` and asserts none of the kept businesses match — the ICP veto cannot resurrect a banned category inside a mission without the mission noticing (the veto override, if any, must appear in the filter report line, and the postcondition fails if a banned match survived silently).

## 3. Pre-flight doctor — `agents/doctor.py` (new)

Runs before stage 1. Checks, in order, each with a short timeout:

1. `config.json` loads and parses; `business_profile` present.
2. Gemini key present; optional 3 s ping (skipped if key missing → recorded as fallback, not failure).
3. Overpass reachable (3 s timeout); Nominatim reachable (3 s timeout).
4. `knowledge_base/` has its 4 JSON files (never-delete rule).
5. `brain/` directory present with `profile.json`.
6. `agent_output/memory/` DBs openable (open + close).
7. Review-queue storage writable.

Verdict: **go** (all pass) · **go-degraded** (soft items fail; the doctor lists which stage fallbacks will engage) · **no-go** (config unreadable, knowledge base broken, DBs unopenable) — abort as `failed` before any quota burn. Doctor results are stored in the mission record and echoed in the report.

## 4. Mission report

At mission end the kernel writes `agent_output/missions/<id>/report.md` and emits a final `mission` event with the summary. Contents:

- Goal (verbatim), params, started/ended, final state.
- Per-stage table: status, duration, reason (always present for `degraded`/`failed`).
- Funnel: found → kept → researched → contacted → drafted → staged. The funnel is derived from the same postcondition-verified numbers, so it cannot disagree with itself.
- Degradation list with human lines.
- Next actions (e.g. "3 drafts awaiting your review — open the review queue").

## 5. Surface — chat, CLI, web

New `MISSION` action, integrated per the house rule — all four places:

- `agents/chatbot.py`: intent parsing (`mission ...` phrasing, including bare goals when the user says "mission:"); the parsed `category` field passes the user's words **verbatim** (exclusions included — same rule as the 2026-09-19 fix).
- `agents/chat_handler.py`: CLI dispatch → `mission.start(params)`, prints the report.
- `agents/web/ws.py`: socket dispatch → same kernel; streams `mission` events to the UI.
- `agents/action_registry.py`: one row (progress line, result-frame kind, ack-skip).

Event bus: add `mission` to `VALID_KINDS`, to `handleAgentEvent` in `web/static/app.js` (mission status card in the ops area), and to the activity-strip wrapper in `web/static/js/util.js`. `web/api.py` gains `GET /api/mission` returning the latest mission record for page reload.

Plain pipeline requests keep working unchanged; missions are additive. Session attachments, review flow, and send gating are untouched.

## 6. Testing

`agents/test_mission.py`, all with **fake stage functions** (no network, no quota):

1. Happy path: planned → preflight → running → staged; funnel consistent; report written.
2. Postcondition failure with working fallback → stage `done` after fallback (fallback-once, not loops).
3. Postcondition failure with broken fallback → `degraded` with reason; mission completes; report names it.
4. Hard failure (search returns 0 kept, no reason) → `failed`, no draft stages ran.
5. Crash resume: record left mid-run → `resume()` re-runs only unfinished stages.
6. Doctor no-go → `failed` before stage 1; doctor results in record.
7. Single-active-mission enforcement.
8. Exclusion postcondition: a banned business kept by a rigged filter → postcondition fails, stage degrades.
9. Report honesty: `staged > drafted` is unconstructible (asserted by the stage contract check itself).

Regression floor: `agents/test_final_audit.py` (20/20) and `agents/test_category_exclusions.py` (27/27) stay green. One live smoke mission (Bandel, 1 locality) driven through the web preview: report.md exists, funnel consistent, review queue holds the drafts.

## Acceptance criteria

- A crashed mission resumes at the last verified stage without re-burning completed work.
- Any stage that cannot prove its postcondition appears as `degraded` with a reason — never `done`.
- The final report's funnel cannot disagree with itself and never claims unstaged drafts as staged.
- A no-go environment aborts before spending quota.
- All three suites green; the live smoke mission stages drafts that appear in the existing review queue.

## Deliberately out of scope

Typed stage-graph refactor of `workflows.py`; new AI capabilities; scheduling/recurring missions; multi-mission concurrency; auto-send; changes to the review state machine (`agents/web/review.py`), the send legs, or the filter internals (the 2026-09-19 exclusion work stands as-is).
