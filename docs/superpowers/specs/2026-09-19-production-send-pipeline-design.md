# Design — Production Send Pipeline (outbox, ledger, pacing)

Status: draft for review · 2026-09-19 · Owner: Zyphr

First spec in the production-readiness series. The other four specs are
listed at the end; this one exists because a wrong or repeated email is the
only failure in this product that costs something real and cannot be undone.

## Problem

Sending today is `agents/mailer.py`: a synchronous loop that opens
`smtplib.SMTP_SSL("smtp.gmail.com", 465)` with a personal Gmail app password
and sends one message per approved draft, writing the `approached` list back
to the session file only after the batch finishes.

Five consequences, all of which must be gone before this runs unattended:

1. **A double-send is possible.** Nothing is unique or atomic, so a crash
   mid-batch, a restart, or a second click re-sends to schools already
   contacted — the single most reputation-damaging bug available here.
2. **No ceiling.** Nothing counts today's mail; a batch of any size leaves at
   any speed. A new domain that does this is treated as a spam source.
3. **No feedback.** Bounces and complaints are invisible: the provider's
   response is discarded, and nothing suppresses an address that has
   hard-bounced or asked never to be contacted again.
4. **No compliance surface.** There is no unsubscribe mechanism anywhere in
   the repo (verified: zero matches for unsubscribe/bounce/rate-limit in
   `agents/`), and no sender-identity footer.
5. **Personal Gmail as the sending identity** for cold commercial outreach,
   which risks the mailbox itself, not just the campaign.

## Scope

**In:** a durable outbox with a unique-constrained ledger; a paced, resumable
sender with a warm-up-aware daily ceiling; provider webhooks for
delivered/bounced/complained; a suppression list; working mid-batch stop; a
one-click unsubscribe that works without login; sender identity footer; and
the first provider adapter (Resend) behind an interface.

**Out (explicit non-goals):** follow-up/cadence scheduling, A-B subject
testing, reply ingestion or inbox sync, contact-discovery improvements
(the separate bottleneck found in the last playtest), multi-recipient or CC
sending, per-recipient send-time optimisation, and any new UI panel beyond a
one-line outbox summary. Also out: replacing the existing per-socket job queue
(search/draft/enrich keep using it unchanged).

## Decisions (confirmed by user)

1. **Operator model**: a single operator on a VPS. No accounts, no tenancy.
2. **Access**: one access token, enforced on `/ws` and every `/api/*` route;
   the app refuses to bind a non-loopback interface without it. (Spec 5.)
3. **Sending identity**: our own domain through a sending provider, not
   personal Gmail. Warm-up ramp is mandatory.
4. **Autonomy**: approve the batch once, machine paces it through the day
   within the cap, halts on command.
5. **Provider**: Resend first, behind an adapter interface.
6. **Shape**: sealed appliance — one process, SQLite for state that must be
   transactional, nightly offsite backup, documented restore.

## Data model — `agent_output/outbox.db` (SQLite, WAL)

Separate database from the chat DB: chat history and the outbox have
different lifecycles and different backup needs, and the outbox is the one
that must never be lost.

```
batches(id, session_id, created_at, approved_at, cap_snapshot, state)
    state: open | sending | paused | drained | aborted

recipients(id, batch_id, business_name, email, subject, body_ref,
           attachment, state, provider_id, claimed_at, sent_at,
           last_error, attempts)
    UNIQUE(batch_id, email)
    state: queued | claimed | sent | delivered | bounced | complained | failed
    body_ref: path under the session dir; message bodies stay with the
              session, the ledger holds only what sending needs
              (subject is inline because it is short and is needed for
              provider correlation and the summary line)

suppressions(email, domain, reason, source, created_at)
    reason: bounce | complaint | unsubscribe | manual
    source: webhook | one_click | operator
```

`body_ref` (not the body inline) is deliberate: the ledger must stay small
enough to back up cheaply every night, and the message text already has a
durable home in the session directory.

## Flow — one approved batch

1. The review flow finishes with N approved drafts → `outbox.enqueue(session,
   drafts)`.
2. In **one transaction** per recipient: reject if the address or its domain
   is suppressed; otherwise insert a `queued` row. Insertion failure on the
   unique index is not an error — it means "already in this batch".
3. `enqueue` returns immediately with a **plain-language summary**: how many
   queued, how many suppressed, today's remaining allowance, and how many
   roll to tomorrow. No message is sent during this step.
4. The **pacer** (one asyncio task owned by the app, started at boot) wakes on
   an interval, computes today's allowance from the warm-up schedule, then for
   each claim:
   - re-check suppression (a bounce that arrives while a batch waits must
     still stop that send),
   - `UPDATE recipients SET state='claimed', claimed_at=now() WHERE id=? AND
     state='queued'` — the atomic claim; zero rows affected means someone else
     got it,
   - call the provider adapter, write back `provider_id` and `state='sent'`.
5. Provider webhook → flip to `delivered`/`bounced`/`complained` and insert
   the suppression.
6. On boot, rows stuck in `claimed` for more than 10 minutes are reconciled
   with the provider (look up the message id) or marked `failed` for review —
   never blindly re-sent.

Pacing: randomised gaps of 2–7 minutes, a 10-per-hour limit, and a daily
ceiling (`warm-up: start_date, day 1–3 = 10/day, +5/day, ceiling 50`). The
ceiling is enforced inside the same transaction that claims rows, so
simultaneous clicks cannot exceed it. All four numbers live in config, not in
code.

Stop mid-batch: a `paused` flag on the batch, read before every claim.

## Unsubscribe and identity

Every message carries a real sender name, an entity/address line, and
`List-Unsubscribe` (mailto + one-click URL). The one-click route must work
without the access token (a recipient has no token and must not get one), so
it carries an **HMAC token per (batch, email)** verified server-side; a valid
hit writes a suppression and returns a plain confirmation page. The footer is
assembled in one place so a future copy change is one edit.

## Code shape

New `agents/outbox/` package, each module owning one thing:

```
agents/outbox/__init__.py
agents/outbox/ledger.py       # schema + the DAO; the only writer of outbox.db
agents/outbox/pacer.py        # the loop, allowance, claims, stop flag
agents/outbox/providers.py    # the adapter interface + Resend implementation
agents/outbox/webhooks.py     # signature verification -> ledger transitions
agents/outbox/footer.py       # identity + unsubscribe + List-Unsubscribe
```

Changed:

- `agents/mailer.py` — keeps the Gmail path for personal/manual sends and
  becomes one adapter implementation; the send loop is deleted.
- `agents/action_dispatch.py` — `_handle_send` enqueues and reports counts;
  it no longer sends.
- `agents/web/api.py` — `/api/outbox` summary; the signed webhook route; the
  public unsubscribe route.
- `agents/web/ws.py` — a `paused` message type and an outbox summary frame.
- `agents/config.py` — `get_outbox_config()` (ceiling, ramp, pacing,
  provider key, webhook secret, unsubscribe signing key), defaulted in
  `get_business_profile()`'s sibling style.
- `agents/web/static/js/queue.js` / `util.js` — show the outbox line beside
  the existing queue; no new panel.

Untouched: the review cards, the AI seam, the ICP layer, the per-socket job
queue, and every frontend panel.

## Failure modes this design makes impossible

| Failure | Why it can't happen now |
|---|---|
| Same school emailed twice | `UNIQUE(batch_id, email)` + atomic `queued→claimed` transition |
| Batch exceeds the cap | allowance computed and enforced in the claiming transaction |
| Emailing a hard bounce or an unsubscribe | suppression checked at enqueue *and* at claim |
| Crash mid-batch loses the thread | state lives in SQLite; pacer resumes on boot |
| Silent failure | every transition is a row plus an event-bus emit the floor renders |
| A forged webhook corrupts the ledger (marks unsent mail delivered, or suppresses a live lead) | HMAC-verified signatures, secret from config, and no state change without a matching signature |

## Testing

- Ledger: double-enqueue inserts once; unique index holds under a simulated
  concurrent claim; state machine rejects illegal transitions.
- Pacer: allowance respected across a faked clock; warm-up ramp days 1/3/10;
  pause stops claims within one tick; resume continues.
- Adapter: a fake provider records calls; a provider error leaves the row
  `failed` with `attempts` incremented and does not consume the day's cap.
- Webhooks: valid signature flips state; invalid signature is rejected;
  bounce writes a suppression that blocks the next enqueue.
- Unsubscribe: valid HMAC suppresses; tampered token 404s; re-using a token is
  idempotent.
- Extend `agents/test_final_audit.py` with an outbox check that runs against a
  temp database (and cleans up after itself, per the session-litter lesson).

## Rollout

1. Ledger + enqueue path. Sending still goes out through the existing Gmail
   transport, so behaviour is visible but unchanged.
2. Pacer + cap + warm-up, provider adapter, flag-flip to Resend.
3. Webhooks + suppression + unsubscribe footer.
4. Only then: start the warm-up clock on the real domain.

## The rest of the series (context for this spec)

| # | Spec | Why this order |
|---|---|---|
| 1 | **This one** — send safety and the ledger | The only irreversible failure mode |
| 2 | Durable state — atomic session writes, SQLite backups, corrupt-file recovery, nightly offsite archive + restore drill | Everything else stands on it |
| 3 | Secrets — env-first config, validated at boot, fail loud at startup | Deploy needs it before deploy exists |
| 4 | Deploy — pinned requirements, systemd unit, `/healthz`, logging with levels, one-command install/restore | Makes the appliance real |
| 5 | Access — the access token on `/ws` + `/api/*`, refuse non-loopback bind without it, auth-failure throttle | The box must not be open |
| 6 | Operability — weekly cost/usage rollup, fallback-rate visibility, a bound on the skills library | Needed, but nothing breaks without it |
