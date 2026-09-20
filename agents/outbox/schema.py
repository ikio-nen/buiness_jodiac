"""
Outbox schema — the tables, constraint, and state machines behind agent_output/outbox.db.

Defined as constants so the DAO migration and the tests read the same names
from one place.
"""

from typing import Literal

# ── tables ────────────────────────────────────────────────────────────────────

BATCHES = "batches"
RECIPIENTS = "recipients"
SUPPRESSIONS = "suppressions"

# ── columns ───────────────────────────────────────────────────────────────────

BATCH_COLUMNS = (
    "id",
    "session_id",
    "created_at",
    "approved_at",
    "cap_snapshot",
    "state",
)

RECIPIENT_COLUMNS = (
    "id",
    "batch_id",
    "business_name",
    "email",
    "subject",
    "body_ref",
    "attachment",
    "state",
    "provider_id",
    "claimed_at",
    "sent_at",
    "last_error",
    "attempts",
)

SUPPRESSION_COLUMNS = (
    "email",
    "domain",
    "reason",
    "source",
    "created_at",
)

# ── primary keys ──────────────────────────────────────────────────────────────

BATCH_PK = "batch_pkey"
RECIPIENT_PK = "recipient_pkey"
RECIPIENT_UNIQ = "recipient_batch_email_uniq"  # (batch_id, email) — the one that blocks duplicates

# ── unique constraint ─────────────────────────────────────────────────────────

RECIPIENT_UNIQUE_COLUMNS = ("batch_id", "email")

# ── body_ref convention ───────────────────────────────────────────────────────

BODY_REF_PREFIX = "body-"
BODY_REF_HTML = "html"
BODY_REF_PLAIN = "plain"

# body_ref is a filename under the session directory, like
#   body-abc123.html   or   body-abc123.txt
# Nothing about the actual message body lives in outbox.db — only the
# subject (inline, because it is short and needed for provider correlation
# and the summary line) and the reference to where the body lives.

# ── batch state machine ───────────────────────────────────────────────────────

BatchState = Literal["open", "sending", "paused", "drained", "aborted"]

BATCH_STATES: tuple[BatchState, ...] = ("open", "sending", "paused", "drained", "aborted")

BATCH_LADDER: dict[BatchState, tuple[BatchState, ...]] = {
    "open": ("sending", "paused", "aborted"),
    "sending": ("paused", "drained", "aborted"),
    "paused": ("sending", "aborted"),
    "drained": (),  # terminal
    "aborted": (),  # terminal
}

# ── recipient state machine ───────────────────────────────────────────────────

RecipientState = Literal[
    "queued", "claimed", "sent", "delivered", "bounced", "complained", "failed"
]

RECIPIENT_STATES: tuple[RecipientState, ...] = (
    "queued",
    "claimed",
    "sent",
    "delivered",
    "bounced",
    "complained",
    "failed",
)

RECIPIENT_LADDER: dict[RecipientState, tuple[RecipientState, ...]] = {
    "queued": ("claimed", "sent", "failed"),  # mark_sent can skip claim; failed for bad address
    "claimed": ("sent", "failed"),
    "sent": ("delivered", "bounced", "complained", "failed"),
    "delivered": (),                            # terminal
    "bounced": (),                              # terminal
    "complained": (),                          # terminal
    "failed": ("claimed", "sent"),             # retryable: re-claimable, or mark_sent to final-fail faster
}

# ── suppression reasons / sources ─────────────────────────────────────────────

SuppressionReason = Literal["bounce", "complaint", "unsubscribe", "manual"]
SUPPRESSION_REASONS: tuple[SuppressionReason, ...] = ("bounce", "complaint", "unsubscribe", "manual")

SuppressionSource = Literal["webhook", "one_click", "operator"]
SUPPRESSION_SOURCES: tuple[SuppressionSource, ...] = ("webhook", "one_click", "operator")


def valid_batch_state(state: str) -> bool:
    return state in BATCH_STATES


def valid_recipient_state(state: str) -> bool:
    return state in RECIPIENT_STATES


def valid_transition(
    table: str, from_state: str, to_state: str
) -> bool:
    """Is `to_state` a legal next step from `from_state` for the given table?"""
    if table == BATCHES:
        allowed = BATCH_LADDER.get(from_state, ())
        return to_state in allowed
    if table == RECIPIENTS:
        allowed = RECIPIENT_LADDER.get(from_state, ())
        return to_state in allowed
    return False
