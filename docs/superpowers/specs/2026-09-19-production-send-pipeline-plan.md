# Implementation Plan: Production Send Pipeline (outbox, ledger, pacing)

**Date:** 2026-09-19
**Depends on:** Spec at `2026-09-19-production-send-pipeline-design.md`
**Shape:** sealed appliance, risk-first. This plan is only spec 1 of 6.

---

## Architecture: Who Owns What

```
┌───────────────────────────────────────────────────────────────┐
│  agents/web/ws.py + api.py                                    │
│  - socket routing, HTTP surface                               │
│  - NO send knowledge: it asks the outbox for state            │
├───────────────────────────────────────────────────────────────┤
│  agents/outbox/ledger.py                                      │
│  - THE ONLY writer of outbox.db                               │
│  - unique constraint, state machine, suppression, allowance    │
├───────────────────────────────────────────────────────────────┤
│  agents/outbox/pacer.py                                       │
│  - the loop: allowance -> claim -> send -> record             │
│  - owns pace timing and the paused flag                       │
├───────────────────────────────────────────────────────────────┤
│  agents/outbox/providers.py                                   │
│  - adapter interface + Resend over plain HTTP (requests)      │
│  - knows nothing about batches or caps                        │
├───────────────────────────────────────────────────────────────┤
│  agents/outbox/webhooks.py      agents/outbox/footer.py       │
│  - verify signature -> ledger   - identity + unsubscribe      │
├───────────────────────────────────────────────────────────────┤
│  agents/action_dispatch.py  ->  enqueues, never sends         │
│  agents/mailer.py           ->  shrinks to a Gmail adapter    │
└───────────────────────────────────────────────────────────────┘
```

**State ownership rules:**

- `outbox.db` owns: what was approved, what has been sent, what must never
  be sent, today's allowance. Nothing else may write send state.
- Session files own: the message text (`body_ref`), the batch's business
  records. The ledger holds only what sending needs.
- `config.json` owns: caps, pacing, warm-up, provider keys, identity line.
- The event bus is the only way send progress reaches the UI — `pacer` and
  `webhooks` emit; the floor and the outbox line render.
- `action_dispatch` decides *what to enqueue*; `pacer` decides *when it
  leaves*. Neither does the other's job.

## Decisions taken while planning

1. **pytest is added** (pinned in spec 4's `requirements.txt`). The send
   pipeline needs fixtures — a temp database, a faked clock, a recording
   provider — that the standalone-assert style of `test_final_audit.py`
   cannot express cleanly. The audit script stays as the end-to-end smoke
   suite; it gains one outbox check.
2. **No Resend SDK.** `requests` 2.34.2 is already present; the API is two
   endpoints, so the adapter talks HTTP directly and the dependency count
   stays where it is (relevant because spec 4 pins it).
3. **`outbox.db` lives beside the session data** (`agent_output/outbox.db`)
   so the nightly archive in spec 2 catches it with one path.

---

## Pass 1: The ledger (no sending yet)

**Goal:** the database exists and makes a duplicate impossible, proven by
tests, with nothing wired to it yet.

### Files

| File | Change |
|---|---|
| `agents/outbox/__init__.py` | new, exports `Ledger` |
| `agents/outbox/ledger.py` | new: schema, migrations, DAO |
| `tests/conftest.py` | new: temp-DB fixture |
| `tests/test_ledger.py` | new |

### Interface

```python
class Ledger:
    def __init__(self, path: Path): ...          # opens WAL, applies schema
    def enqueue(self, session_id, drafts) -> EnqueueResult
    def allowance(self, today) -> int            # from warm-up schedule
    def claim(self, limit) -> list[Row]          # atomic queued -> claimed
    def mark_sent(self, row_id, provider_id)
    def mark_failed(self, row_id, error)
    def apply_event(self, provider_id, event)    # delivered/bounced/complained
    def suppress(self, email, domain, reason, source)
    def is_suppressed(self, email) -> bool
    def summary(self) -> dict                    # for /api/outbox + the UI line
    def pause(self, batch_id, paused: bool)
```

`EnqueueResult` is a plain dataclass: `queued, suppressed, over_cap,
rolls_to_tomorrow, batch_id`.

### Tests (written first)

- enqueueing the same draft twice leaves one row (`UNIQUE(batch_id, email)`).
- two connections claiming concurrently never return the same row.
- an illegal transition (`delivered -> claimed`) raises.
- `claim()` respects the allowance: with allowance 3 and 10 queued rows, it
  returns 3.
- warm-up: `warmup_start` = today, `initial` 10, `increment` 5, `ceiling 50`
  → day 1 = 10, day 3 = 20, day 10 = 50, day 30 = 50.
- a suppressed address is refused at enqueue and counted, not raised.

**Done when:** `E:/python.exe -m pytest tests/test_ledger.py -q` is green and
`outbox.db` schema is committed as an explicit constant (no auto-migration
surprises).

---

## Pass 2: Enqueue replaces the send loop

**Goal:** approving a batch queues it and returns counts; nothing sends.

### Files

| File | Change |
|---|---|
| `agents/action_dispatch.py` | `_handle_send` → `outbox.enqueue(...)`, return counts |
| `agents/web/ws.py` | `send_result` payload gains `queued/suppressed/over_cap` |
| `agents/config.py` | `get_outbox_config()` + `set_outbox_config()` |
| `agents/ai/schemas.py` | not touched (no AI here) |

### Behaviour

`_handle_send` keeps its message contract ("Sending emails now…" becomes the
enqueue summary, in plain language): *"12 queued — 4 were suppressed, 2 hold
for tomorrow (daily cap 10)."* If `outbox.enabled` is false the old Gmail path
runs unchanged, so this pass can ship behind the flag.

### Tests

- `_handle_send` with a stubbed ledger returns the summary and calls the
  provider zero times.
- with `enabled: false`, the old transport is used (guard against silently
  disabling sending on upgrade).

**Done when:** in the live UI, "send emails" says "queued", and
`/api/outbox` reports the rows.

---

## Pass 3: The pacer

**Goal:** approved rows leave slowly, within the cap, and stop on command.

### Files

| File | Change |
|---|---|
| `agents/outbox/pacer.py` | new: the loop |
| `agents/web/server.py` | start the pacer at boot, cancel on shutdown |
| `agents/web/api.py` | `GET /api/outbox`, `POST /api/outbox/pause` |
| `agents/web/ws.py` | `outbox_pause` message type; `outbox_state` frame |
| `agents/web/static/js/queue.js` | render the outbox line beside QUEUE |

### Behaviour

One asyncio task, started with the app. Each tick: `allowance(today)` →
`claim(n)` → for each row, re-check suppression, call the adapter, record.
Sleep a random gap inside `[pace_min, pace_max]`, honouring `hourly_cap`. On
boot, claim rows stuck in `claimed` > 10 minutes and reconcile with the
provider before any new claim.

### Tests (faked clock, recording provider)

- with a 3-row batch and allowance 2, exactly 2 leave today.
- pausing mid-batch stops further claims within one tick; resuming continues.
- a provider exception marks the row `failed`, increments `attempts`, and does
  **not** consume an allowance slot.
- 20 queued rows across two days: the second day's ceiling applies on its own.
- a bounce arriving while a batch waits prevents that specific send.

**Done when:** a 10-row batch against a fake provider drains over a few
minutes with `attempts`/states visible in `outbox.db`, and Ctrl-C mid-batch
resumes correctly on restart.

---

## Pass 4: The Resend adapter

**Goal:** real mail goes out.

### Files

| File | Change |
|---|---|
| `agents/outbox/providers.py` | new: protocol + `GmailAdapter` (moved) + `ResendAdapter` |
| `agents/mailer.py` | keeps only the Gmail transport, becomes `GmailAdapter` |
| `agents/config.py` | provider key, from/reply-to, entity line |

### Interface

```python
class Provider(Protocol):
    def send(self, to, subject, body, attachment=None) -> SendResult  # provider_id | error
```

`ResendAdapter` sends over `https://api.resend.com/emails` with `requests`,
retries only on 429/5xx with backoff, and maps 4xx to a permanent failure so
the pacer does not burn cap on an unrecoverable address.

**Done when:** one email to a test address arrives, `provider_id` is recorded,
and the existing `mailer_guard` check in the audit suite still passes.

---

## Pass 5: Webhooks, suppression, unsubscribe

**Goal:** the loop closes — bounces stop future sends, and anyone can opt out.

### Files

| File | Change |
|---|---|
| `agents/outbox/webhooks.py` | new: signature verify → ledger event |
| `agents/outbox/footer.py` | new: identity + `List-Unsubscribe` + one-click URL |
| `agents/web/api.py` | `POST /api/webhooks/resend`, `GET /u/{token}` (public) |
| `agents/outbox/ledger.py` | `suppressions` queries used by webhook + one-click |

### Behaviour

The webhook verifies the provider signature against `webhook_secret` and maps
its events onto ledger transitions; an unknown `provider_id` is logged and
ignored, never invented. The one-click route verifies an HMAC over
`(batch_id, email)` with `unsubscribe_secret`, writes a suppression, and
returns a small HTML page — idempotent, and the only unauthenticated
state-changing route in the app.

**Done when:** a replayed-and-tampered webhook changes nothing; a valid
unsubscribe URL (opened in a browser with no session) suppresses the address
and the next enqueue refuses it.

---

## Pass 6: Wire-up and the audit check

**Goal:** the whole thing is reachable, visible, and covered by the smoke suite.

### Files

| File | Change |
|---|---|
| `agents/test_final_audit.py` | one `outbox` check against a temp DB, self-cleaning |
| `AGENTS.md` | record the outbox as the owner of send state |

**Done when:** audit suite is 20/21 (or 21/21) green, the office shows the
outbox line, and sending a 3-row test batch to your own address completes
end-to-end through the real provider.

---

## Config (all new keys live under `outbox`)

| Key | Default | Notes |
|---|---|---|
| `enabled` | `false` | master switch; false keeps the Gmail path |
| `provider` | `"resend"` | adapter name |
| `provider_api_key` | `""` | env var wins (spec 3) |
| `webhook_secret` | `""` | signature verification |
| `unsubscribe_secret` | `""` | HMAC signing key |
| `daily_ceiling` | `50` | absolute cap |
| `warmup_start` | `""` | ISO date; empty = no ramp |
| `warmup_initial` | `10` | day-1 allowance |
| `warmup_increment` | `5` | per-day growth |
| `pace_min_seconds` | `120` | random gap floor |
| `pace_max_seconds` | `420` | random gap ceiling |
| `hourly_cap` | `10` | burst guard |
| `from_name` / `from_email` | — | sending identity |
| `entity_line` | — | required in every footer |

## Ordering rules

- Passes 1–3 are the risk removal; 4–5 make it useful; 6 makes it visible.
- Nothing in this plan touches the AI seam, ICP layer, review cards, or the
  per-socket job queue.
- `outbox.enabled` stays false until pass 5 is green — the cap and suppression
  must both be live before real mail moves to a new domain, or warm-up begins
  unprotected.

## Not in this plan

Specs 2–6: durable state + backups; env-first secrets; deploy (systemd,
pinned requirements, `/healthz`, logging levels); access token; operability
and the skills-library bound.
