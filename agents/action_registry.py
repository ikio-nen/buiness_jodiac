"""The action registry — one row per JARVIS action.

Everything the three intent surfaces need to know about an action lives
here: the Gemini function name that triggers it, the acknowledgment line,
the progress line, the WebSocket frame kind that carries its result, and
whether the ack is skipped. chatbot.py, action_dispatch.py, and
web/server.py all read this table instead of each keeping a private copy
that drifts.

Adding a new ActionType = one row here + one handler in action_dispatch.
The per-surface special cases (CLI follow-up hints, WS shaping) stay in
their surfaces; this table is the shared spine.
"""

from agents.chatbot import ActionType


class Row:
    __slots__ = ("action", "gemini_name", "ack", "progress", "result_kind", "skip_ack")

    def __init__(self, action: ActionType, gemini_name: str = "",
                 ack: str = "", progress: str = "", result_kind: str = "",
                 skip_ack: bool = False):
        self.action = action
        self.gemini_name = gemini_name
        self.ack = ack
        self.progress = progress
        self.result_kind = result_kind
        self.skip_ack = skip_ack


_ROWS = [
    Row(ActionType.SEARCH, "search_businesses",
        progress="Running search pipeline (query, verify, scrape, enrich)...",
        result_kind="search_result"),
    Row(ActionType.DRAFT, "draft_emails",
        ack="Drafting personalized emails...",
        progress="Researching businesses and drafting personalized emails...",
        result_kind="draft_result"),
    Row(ActionType.SEND, "send_emails",
        ack="Sending emails now...",
        progress="Sending emails now...",
        result_kind="send_result"),
    Row(ActionType.RESEARCH, "research_businesses",
        ack="Researching businesses with AI...",
        progress="Researching businesses with AI...",
        result_kind="research_result"),
    Row(ActionType.REVIEW, "review_emails",
        ack="Opening email review..."),
    Row(ActionType.SYNC, "sync_obsidian",
        ack="Syncing to Obsidian vault...",
        progress="Syncing to Obsidian vault..."),
    Row(ActionType.SCRAPE, "scrape_websites",
        ack="Scraping business websites...",
        progress="Scraping business websites..."),
    Row(ActionType.ENRICH, "enrich_emails",
        ack="Looking up email addresses...",
        progress="Looking up email addresses..."),
    Row(ActionType.STATUS, "show_status", skip_ack=True),
    Row(ActionType.DASHBOARD, "show_dashboard", skip_ack=True),
    Row(ActionType.CHECKIN, "agent_check_in",
        ack="Scanning everything I know..."),
    Row(ActionType.ASK_AGENT, "ask_specialist",
        ack="Looping in a specialist..."),
    Row(ActionType.TEAM_ACT, "team_act",
        ack="Putting the team to work..."),
    Row(ActionType.CAMPAIGN, "start_campaign",
        progress="Running the guided campaign (discover, curate, approve)...",
        result_kind="campaign_checklist"),
    Row(ActionType.LIST_SESSIONS, "list_sessions",
        ack="Here are your sessions...", skip_ack=True),
]

REGISTRY: dict[str, Row] = {r.gemini_name: r for r in _ROWS if r.gemini_name}
_BY_ACTION: dict[ActionType, Row] = {r.action: r for r in _ROWS}
# String-keyed view for the web layer, which passes the action's .value
# ("search", "draft", ...) rather than the enum member.
_BY_VALUE: dict[str, Row] = {r.action.value: r for r in _ROWS}


def _lookup(at) -> Row | None:
    """Accept an ActionType member or its string value."""
    if isinstance(at, ActionType):
        return _BY_ACTION.get(at)
    return _BY_VALUE.get(str(at))


def row_for_action(action: ActionType) -> Row | None:
    return _BY_ACTION.get(action)


def row_for_gemini(name: str) -> Row | None:
    return REGISTRY.get(name or "")


def ack_for(action, default: str = "") -> str:
    r = _lookup(action)
    return (r.ack if r else "") or default


def progress_for(at) -> str:
    r = _lookup(at)
    return r.progress if r else ""


def result_kind_for(at) -> str:
    r = _lookup(at)
    return (r.result_kind if r else "") or ""


def skip_ack_for(at) -> bool:
    r = _lookup(at)
    return bool(r and r.skip_ack)
