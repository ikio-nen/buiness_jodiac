"""Typed models for the Gemini service seam.

Every capability takes and returns these models — never a free-form dict.
Defined once here so icp.py, exec_finder.py, workflows.py and ai_design.py
share one ``Business`` shape instead of three drifting ones.
"""

from pydantic import BaseModel, Field


class Business(BaseModel):
    """The minimal business record a capability can be judged on."""

    id: str = ""
    name: str = ""
    category: str = ""
    location: str = ""
    website: str = ""
    phone: str = ""
    email: str = ""
    rating: float | None = None
    review_count: int | None = None
    snippets: list[str] = Field(default_factory=list)


class FitScore(BaseModel):
    """Deterministic-or-AI verdict on how well a business fits the goal."""

    score: int = 0                      # 0-100
    fit: str = "plausible"              # fits | plausible | unlikely
    institution_type: str = ""          # e.g. polytechnic, clinic, cafe
    rationale: str = ""
    source: str = "heuristic"           # heuristic | gemini | cache


class BusinessProfile(BaseModel):
    """Compact structured profile collapsed from raw snippets."""

    industry: str = "unknown"
    size_signal: str = "unknown"
    pain_point: str = "unknown"
    hook: str = "unknown"
    summary: str = ""
    source: str = "heuristic"


class ContactCandidate(BaseModel):
    """One possible decision-maker extracted from a page or provider."""

    name: str = ""
    title: str = ""
    email: str = ""
    confidence: float = 0.0
    source: str = "heuristic"


class EmailDraft(BaseModel):
    """One drafted outreach email (subject/body/greeting/hook)."""

    subject: str = ""
    body: str = ""
    greeting: str = ""
    hook: str = ""
    ai_powered: bool = True
    source: str = "gemini"


class ReplyIntent(BaseModel):
    """Classification of one inbound reply."""

    intent: str = "unknown"             # interested | not_interested | objection |
                                        # out_of_office | wrong_person | unknown
    next_action: str = ""               # suggested follow-up
    confidence: float = 0.0
    source: str = "heuristic"


class QueryExpansion(BaseModel):
    """Refined/additional search queries proposed from learning."""

    queries: list[str] = Field(default_factory=list)
    rationale: str = ""
    source: str = "heuristic"


class ToolCall(BaseModel):
    """One function call the model asked for, normalized off the SDK."""

    name: str = ""
    args: dict = Field(default_factory=dict)


class ToolTurn(BaseModel):
    """The outcome of one tool-using conversation (see gemini_client.converse).

    ``calls`` carries every function call the model emitted; ``text`` the
    reply when it answered directly instead. ``available`` is False when no
    key/client exists at all, so a caller needs no separate availability
    pre-check (the old is_available()/then-call race). ``error``/``error_type``
    describe a failed call once the retry policy has given up.
    """

    calls: list[ToolCall] = Field(default_factory=list)
    text: str = ""
    rounds: int = 0
    available: bool = True
    error: str = ""
    error_type: str = ""


class UsageRecord(BaseModel):
    """One logged Gemini call (see usage_log.py)."""

    ts: str
    capability: str
    prompt_version: str
    business_id: str = ""
    ok: bool
    used_gemini: bool
    notes: str = ""
