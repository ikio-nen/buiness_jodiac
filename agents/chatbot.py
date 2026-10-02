"""Intelligent chatbot -- Gemini-powered intent parsing with function calling.

Every user message goes through Gemini which decides what JARVIS action to take.
No more brittle regex matching. Gemini has full session context.
"""
import json
import random as _random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(Enum):
    SEARCH = "search"
    DRAFT = "draft"
    SEND = "send"
    SYNC = "sync"
    SCRAPE = "scrape"
    ENRICH = "enrich"
    STATUS = "status"
    HELP = "help"
    LIST_SESSIONS = "list_sessions"
    GREETING = "greeting"
    UNKNOWN = "unknown"
    RESEARCH = "research"
    REVIEW = "review"
    DASHBOARD = "dashboard"
    BRAINSTORM = "brainstorm"
    CHECKIN = "checkin"
    ASK_AGENT = "ask_agent"
    TEAM_ACT = "team_act"
    CAMPAIGN = "campaign"
    GOAL = "goal"


@dataclass
class Action:
    """A parsed user intent mapped to an agent action."""
    type: ActionType
    params: dict = field(default_factory=dict)
    response: str = ""  # What JARVIS says back


# Logical next step per action -- used to chain multi-part requests.
# If Gemini returns only the first function call for a message like
# "find emails for them and draft emails", the missing follow-up steps
# that the user explicitly asked for are appended from this map.
_NEXT_STEP = {
    ActionType.SEARCH: ActionType.DRAFT,
    ActionType.ENRICH: ActionType.DRAFT,
    ActionType.RESEARCH: ActionType.DRAFT,
}

# Actions the chain-supplement is allowed to append. SEND is deliberately
# excluded -- outbound email must stay behind an explicit user action
# (and behind the review/approval gate in action_dispatch).
_CHAINABLE = {ActionType.DRAFT, ActionType.ENRICH, ActionType.RESEARCH,
              ActionType.SCRAPE, ActionType.SYNC}


# ── Quick greeting check (no API call needed) ──────────────────────

_GREETING_WORDS = {
    "hi", "hey", "hello", "yo", "sup", "hola", "namaste",
    "greetings", "morning", "afternoon", "evening", "howdy",
    "wassup", "what's up", "hey there", "hi there", "hello there",
    "hey jarvis", "hi jarvis", "hello jarvis", "good morning",
    "good afternoon", "good evening", "how are you", "how's it going",
}

_GREETING_RESPONSES = [
    "Hey! Ready to find some businesses and send some outreach. What area should I search?",
    "Hi there! JARVIS online. What are we hunting for today?",
    "Hello! I've got the search engines warmed up. Where should we look?",
    "Hey! All systems ready. Tell me a location and I'll find businesses that need us.",
    "Hi! Good to see you. Want me to search a new area, or continue from where we left off?",
    "Hey! I'm ready to roll. Give me a city or neighborhood and I'll find targets.",
    "What's up! I'm here and ready. What's the mission?",
]


# ── Gemini function definitions for tool use ───────────────────────

_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "search_businesses",
                "description": "Search a location for businesses and rank them against what the user is selling on this search. Returns the prospects that fit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City, town, or area to search in (e.g. 'Bandel', 'London', 'Central Delhi')",
                        },
                        "category": {
                            "type": "string",
                            "description": "What the user is looking for, in the user's OWN words, INCLUDING their exclusions exactly as spoken (e.g. 'private computer academies that teach AutoCAD, remove schools and colleges', 'educational centers that teach AutoCAD but no schools'). Do NOT collapse this to one word, do NOT drop the 'remove X' part, and do NOT paraphrase or expand it with synonyms -- the filter reasons over the full phrase, and the exclusion half of it is binding.",
                        },
                        "radius": {
                            "type": "integer",
                            "description": "Search radius in meters. Default 2000.",
                        },
                        "goal": {
                            "type": "string",
                            "description": "What the user is SELLING on this search, in a few words - e.g. 'AutoCAD licences', 'websites', 'web design', 'laptops'. Their goal changes between searches, so pass what they are selling right now. Omit only when they never say.",
                        },
                    },
                    "required": ["location"],
                },
            },
            {
                "name": "set_selling_goal",
                "description": "Pin or clear what the user is SELLING (the outreach goal). Use when the user states it directly: 'i sell autocad keys', 'we are selling websites now', 'my goal is X', 'clear the goal'. Pass goal='' to clear back to auto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "What they are selling, in a few words - e.g. 'AutoCAD keys', 'web design services', 'laptops'. Empty string clears the goal (system infers per search again).",
                        },
                    },
                    "required": ["goal"],
                },
            },
            {
                "name": "draft_emails",
                "description": "Draft personalized outreach emails for selected businesses. Uses AI to personalize each email based on business type and research.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selection": {
                            "type": "string",
                            "description": "Which businesses to draft for: 'all', 'top5', 'top10', or comma-separated numbers like '1,3,5'",
                        },
                    },
                },
            },
            {
                "name": "send_emails",
                "description": "Send all drafted emails that have been approved.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "review_emails",
                "description": "Show drafted emails one by one for editing, attaching files, and approval before sending.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "research_businesses",
                "description": "Research businesses using Google Maps reviews and AI analysis to find strengths, gaps, and email hooks.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "sync_obsidian",
                "description": "Sync all business data, research, and outreach to Obsidian vault.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "scrape_websites",
                "description": "Scrape business websites for social links and contact info.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "enrich_emails",
                "description": "Find email addresses for businesses using Hunter.io.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "show_status",
                "description": "Show current session status: businesses found, emails drafted, emails sent, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "show_help",
                "description": "Show help text with available commands and examples.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "show_dashboard",
                "description": "Show learning dashboard with categories, patterns, and statistics.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "agent_check_in",
                "description": "Run an agent check-in: scan overdue follow-ups, WhatsApp-ready leads, and what the system has learned. Use when the user asks 'check in', 'what needs attention', 'brief me', 'any updates', or wants a status overview of outreach health.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_sessions",
                "description": "List all previous outreach sessions.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "ask_user",
                "description": "When the user's request is ambiguous or missing information, ask a clarifying question.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The clarifying question to ask the user",
                        },
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "ask_specialist",
                "description": "Route a question to a specialist teammate who remembers past conversations and can search the web. Use when the user wants an opinion, research, or analysis -- e.g. 'ask scout about schools in Bandel', 'what does strategist think?', 'how are we doing?'. Choose agent: 'scout' (finds/vets businesses and markets), 'strategist' (outreach angles and tactics), 'analyst' (numbers and what the team is learning).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Which specialist: scout, strategist, or analyst",
                        },
                        "message": {
                            "type": "string",
                            "description": "The question or topic to hand the specialist",
                        },
                    },
                    "required": ["agent", "message"],
                },
            },
            {
                "name": "start_campaign",
                "description": "Run the full guided campaign for the user's niche and location: discover businesses, curate the 10 best, show an interactive checklist to approve, export an initial PDF, interview the user about each pick one by one, draft a unique email per business, send from the configured Gmail sender, and produce a final PDF report. Use when the user asks to run a campaign, launch the 6-stage flow, or says 'campaign in <location>'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City, town, or area to target (e.g. 'Bandel', 'Central Delhi')",
                        },
                        "category": {
                            "type": "string",
                            "description": "The user's niche request VERBATIM, including any 'no X' / 'remove X' / 'dont want X' exclusions exactly as spoken. Do NOT paraphrase, synonym-expand, or drop them.",
                        },
                        "radius": {
                            "type": "integer",
                            "description": "Search radius in meters. Default 2000.",
                        },
                        "goal": {
                            "type": "string",
                            "description": "What the user is SELLING on this campaign, in a few words - e.g. 'AutoCAD licences'. Omit only when they never say.",
                        },
                    },
                    "required": ["location"],
                },
            },
            {
                "name": "team_act",
                "description": "Put the whole specialist team to work on the current prospects: Scout researches the top ones, Strategist pre-writes opening hooks, Analyst debriefs. Use when the user says things like 'team act', 'put the team on it', 'have the team research them'.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        ],
    }
]


def parse_intents(user_input: str, context: list[dict] = None,
                  business_profile: dict = None, session_state: str = "") -> list[Action]:
    """Parse user input into an ordered list of Actions.

    Multi-part messages ("find emails for them and draft emails") return
    every requested step; single-part messages return a one-item list.

    Args:
        user_input: What the user typed
        context: Last N messages from conversation memory
        business_profile: Current business profile for context
        session_state: Current session state summary (businesses, drafts, etc.)
    """
    text = user_input.strip()
    if not text:
        return [Action(type=ActionType.UNKNOWN, response="Type something and I'll help!")]

    lower = text.lower().strip()

    actions = []
    seen_types: set[ActionType] = set()

    def emit(action: Action) -> None:
        if action.type in seen_types:
            return  # "draft and then draft again" collapses to one step
        seen_types.add(action.type)
        actions.append(action)

    # Quick GOAL check (no API call) — "i sell autocad keys" / "goal is
    # websites" pins or clears what JARVIS is selling. BEFORE the brainstorm
    # triggers, which also listen for product-y phrases ("my product").
    goal_action = _match_goal_statement(text, lower)
    if goal_action:
        return [goal_action]

    # Quick brainstorm check (no API call)
    BRAINSTORM_TRIGGERS = (
        "brainstorm", "set up my profile", "configure my business",
        "tell you about my business", "what i sell", "about my mission",
        "my mission", "what do i sell", "start a new project",
        "new project", "business profile", "my product", "my business",
    )
    if any(w in lower for w in BRAINSTORM_TRIGGERS):
        return [Action(type=ActionType.BRAINSTORM, response="Let's set up your business profile!")]

    # Quick help check (no API call)
    if lower in ("help", "commands", "options", "?", "what can you do"):
        return [Action(type=ActionType.HELP, response="")]

    # Quick status check (no API call) — must answer instantly even when
    # a long pipeline is running and the AI quota is exhausted.
    if lower in ("status", "show status", "system status", "where are we", "progress"):
        return [Action(type=ActionType.STATUS, response="")]

    # Quick check-in triggers (no API call)
    CHECKIN_TRIGGERS = (
        "check in", "checkin", "check-up", "whats new", "what's new",
        "any updates", "brief me", "briefing", "what needs attention",
        "anything due", "status of follow", "overdue",
    )
    if lower in CHECKIN_TRIGGERS or any(lower.startswith(t) for t in CHECKIN_TRIGGERS):
        return [Action(type=ActionType.CHECKIN, response="Scanning everything I know...")]

    # Quick "talk to a specialist" triggers (no API call) — resolves through
    # the roster interface so hired agents answer 'ask <name>' too.
    if lower.startswith("ask "):
        try:
            from agents.agent_team import get_agent
            rest = text[4:].strip()
            who = rest.split(" ", 1)[0].lower().strip(":,-")
            if who and get_agent(who):
                msg = rest[len(who):].strip(" :,-") \
                    or "Introduce yourself and what you can help with."
                return [Action(type=ActionType.ASK_AGENT,
                               params={"agent": who, "message": msg},
                               response=f"Looping in {who.capitalize()}...")]
        except Exception:
            pass
    for agent_key in ("scout", "strategist", "analyst"):
        if lower.startswith(f"ask {agent_key}"):
            msg = text[len(f"ask {agent_key}"):].strip(" :,-") \
                or "Introduce yourself and what you can help with."
            return [Action(type=ActionType.ASK_AGENT,
                           params={"agent": agent_key, "message": msg},
                           response=f"Looping in {agent_key.capitalize()}...")]

    # Quick team-act triggers (no API call)
    TEAM_TRIGGERS = ("team act", "teamact", "put the team on it",
                     "team get to work", "have the team research",
                     "put the team to work")
    if lower in TEAM_TRIGGERS or any(lower.startswith(t) for t in TEAM_TRIGGERS):
        return [Action(type=ActionType.TEAM_ACT,
                       response="Putting the team on the current prospects...")]

    # Quick greeting check (no API call)
    if lower in _GREETING_WORDS or any(lower.startswith(g) for g in _GREETING_WORDS):
        profile = business_profile or {}
        resp = _random.choice(_GREETING_RESPONSES)
        if profile.get("product"):
            resp += f"\n\n  Current mission: Selling {profile['product']}"
        else:
            resp += "\n\n  No business profile set. Press [S] to tell me what you sell."
        return [Action(type=ActionType.GREETING, response=resp)]

    # Try Gemini for intelligent parsing
    return _parse_with_gemini(text, context, business_profile, session_state,
                              actions, seen_types)


def _parse_with_gemini(user_input: str, context: list[dict] = None,
                       business_profile: dict = None, session_state: str = "",
                       actions: list[Action] = None,
                       seen_types: set = None) -> list[Action]:
    """Use Gemini with function calling to parse intent into actions.

    Every function-call part in the model's response becomes an Action, so a
    multi-part request returns its steps in order. On top of that, a
    deterministic chain supplement fills in follow-up steps the user asked
    for but the model didn't emit (the original one-action truncation bug).
    """
    collect = actions if actions is not None else []
    seen = seen_types if seen_types is not None else set()

    def emit(action: Action) -> None:
        if action.type in seen:
            return  # duplicate step ("draft ... and draft again") collapses
        seen.add(action.type)
        collect.append(action)

    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return [Action(
                type=ActionType.UNKNOWN,
                response="AI is not configured. Set your Gemini API key in Setup [S]. "
                        "Meanwhile, try: 'find businesses in London', 'draft emails', or 'show status'."
            )]

        # Build context-aware system prompt
        system = _build_system_prompt(business_profile, session_state)

        # Build conversation context
        contents = []
        if context:
            for msg in context[-8:]:  # Last 8 messages for context
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Add current message
        contents.append({"role": "user", "parts": [{"text": user_input}]})

        # One call through the seam: the client, the model, the quota-aware
        # retry policy and the function-call protocol all live in agents/ai.
        # This module owns only the policy -- which tool means which Action.
        from agents.ai import service as ai
        turn = ai.converse("intent_parse", contents=contents, system=system,
                           tools=_TOOLS, temperature=0.3, max_rounds=1)
        if not turn.available:
            return [Action(
                type=ActionType.UNKNOWN,
                response="AI client not available. Check your Gemini API key."
            )]

        # Every function call the model emitted becomes an Action, in order.
        if turn.calls:
            for call in turn.calls:
                emit(_handle_function_call(call.name, call.args, user_input))

            # Deterministic backstop: an AI-emitted GOAL is honored only when
            # the message itself has a selling-statement shape ('i sell X',
            # 'my goal is X', 'clear the goal' ...). Gemini misreads searches
            # that merely CONTAIN the word 'goal' ('goal keeper gloves
            # supplier') as goal switches; the pin outranks the model, so a
            # shapeless goal call is dropped and the search stands alone.
            if (any(a.type == ActionType.GOAL and
                    a.params.get("source") == "ai" for a in collect)
                    and not _has_goal_statement_shape(user_input)):
                collect[:] = [a for a in collect
                              if not (a.type == ActionType.GOAL
                                      and a.params.get("source") == "ai")]

            # Chain supplement: if the user asked for a step that Gemini
            # didn't emit, append its logical follow-up. Only steps the
            # user explicitly named are supplemented -- and only safe
            # (non-SEND) actions.
            requested = _requested_steps(user_input)
            for act in list(collect):
                current = act.type
                while True:
                    nxt = _NEXT_STEP.get(current)
                    if (not nxt or nxt not in requested or nxt in seen
                            or nxt not in _CHAINABLE):
                        break
                    nxt_action = _make_chain_action(nxt, user_input)
                    if not nxt_action:
                        break
                    emit(nxt_action)
                    current = nxt
            # A backstop-dropped goal call can leave the turn empty (Gemini
            # emitted ONLY the misread goal); fall through to the text reply
            # instead of returning [] — a silent dead end otherwise.
            if collect:
                return collect

        # Text response (clarification or chat)
        if turn.text:
            return [Action(type=ActionType.UNKNOWN, response=turn.text)]

        if turn.error:
            print(f"  [AI] Intent parsing call failed: {turn.error_type} {turn.error[:120]}")

    except Exception as e:
        print(f"  [AI] Intent parsing error: {e}")

    return [Action(
        type=ActionType.UNKNOWN,
        response="I'm not sure what you mean. Try: 'find businesses in London', "
                "'draft emails', or 'show status'."
    )]


# Keywords in the user's message that name an explicit follow-up step.
_STEP_KEYWORDS = {
    ActionType.SEARCH: ("find ", "search ", "search for", "look for", "locate "),
    ActionType.ENRICH: ("find email", "emails for", "lookup email", "look up email",
                        "get email", "enrich", "hunt email", "find contact",
                        "email addresses", "phone", "contact info"),
    ActionType.RESEARCH: ("research", "reviews", "what do their google"),
    ActionType.DRAFT: ("draft", "write email", "write personalized", "prepare email",
                       "compose email", "write outreach", "prepare professional"),
}


def _requested_steps(user_input: str) -> set:
    """Which follow-up steps does the user explicitly name in this message?"""
    low = user_input.lower()
    out = set()
    for act_type, keywords in _STEP_KEYWORDS.items():
        if any(k in low for k in keywords):
            out.add(act_type)
    return out


_TOP_N_RE = re.compile(r"top\s+(\d+)", re.I)


def _make_chain_action(act_type: ActionType, user_input: str = "") -> Action:
    """Build the default-param Action for a chained follow-up step.

    A chained draft honors 'top N' if the user named one in the message.
    """
    draft_params = {"selection": "all"}
    if act_type == ActionType.DRAFT:
        m = _TOP_N_RE.search(user_input or "")
        if m:
            draft_params = {"selection": f"top{m.group(1)}"}
    defaults = {
        ActionType.DRAFT: ("Drafting personalized emails...", draft_params),
        ActionType.ENRICH: ("Looking up email addresses...", {}),
        ActionType.RESEARCH: ("Researching businesses with AI...", {}),
    }
    if act_type not in defaults:
        return None
    response, params = defaults[act_type]
    return Action(type=act_type, params=dict(params), response=response)


def _build_system_prompt(business_profile: dict = None,
                         session_state: str = "") -> str:
    """Build system prompt with business context and live session state."""
    profile = business_profile or {}
    product = profile.get("product", "")
    target = profile.get("target", "") or profile.get("target_customers", "")
    tone = profile.get("email_tone", "professional")
    company = profile.get("company_name", "")

    parts = [
        "You are JARVIS, an intelligent business outreach assistant.",
        "You understand natural language and can handle complex, multi-step requests.",
        "You have access to these tools: start_campaign, search_businesses, draft_emails, send_emails, "
        "review_emails, research_businesses, sync_obsidian, scrape_websites, "
        "enrich_emails, show_status, show_help, show_dashboard, list_sessions, "
        "ask_specialist, ask_user.",
        "",
        "Rules:",
        "- If the user asks for the full guided flow (run a campaign, the 6-stage "
        "flow, 'campaign in <location>'), use start_campaign - it runs discovery "
        "through the final report with the user approving at each gate.",
        "- Always use a function call unless the user is just chatting.",
        "- If the user asks for MORE THAN ONE thing in one message (e.g. 'find "
        "emails for them and draft an email for each'), call EVERY tool the "
        "message names, in the order the user listed them: enrich_emails, "
        "then draft_emails. Do not stop after the first tool.",
        "- For complex requests like 'find schools and draft emails', use "
        "search_businesses first, then draft_emails in the same response.",
        "- If the user mentions a location, extract it for search_businesses.",
        "- For search_businesses AND start_campaign, the `category` param is the user's "
        "request VERBATIM (e.g. 'private computer academies that teach autocad, remove "
        "schools and cllgs', 'training centers no colleges'). NEVER paraphrase, "
        "synonym-expand, or drop the exclusion half ('no X', 'remove X', 'dont want X') "
        "-- the pipeline parses exclusions out of their exact words and dropping them "
        "resurrects the kinds of business the user just banned.",
        "- The user's selling goal is pinned state, not a guess: they set it with "
        "'i sell X' / 'goal is X' (use set_selling_goal), it shows in the goal "
        "chip, and searches run against it. NEVER call set_selling_goal for a "
        "SEARCH message, even one containing the word 'goal' ('goal keeper "
        "gloves supplier' is a product to FIND, not to sell) — only a direct "
        "first-person selling statement sets it. Pass `goal` on "
        "search_businesses only from set_selling_goal's argument - NEVER guess "
        "it from search wording like 'web design clients in pune' (that is "
        "WHO they target, not what they sell).",
        "- If the user says 'draft' or 'write emails', use draft_emails.",
        "- If the user says 'send', use send_emails.",
        "- If the user says 'status' or 'dashboard', use the appropriate tool.",
        "- If the user wants an opinion, research, or analysis (e.g. 'ask scout ...', "
        "'what does strategist think'), use ask_specialist and pick the agent: "
        "scout (finds businesses), strategist (outreach tactics), analyst (numbers).",
        "- For greetings or casual chat, respond naturally without a tool.",
        "- If information is missing (e.g. no location for search), use ask_user.",
        "",
        "PROACTIVE BEHAVIOR:",
        "- After search: suggest 'draft emails' or 'research these businesses'.",
        "- After draft: suggest 'send all' or 'review emails'.",
        "- After research: suggest 'draft emails' to use the research.",
        "- When user says 'find X and draft', chain: search first, then draft.",
    ]

    if product:
        parts.append(f"\nBusiness context: We sell {product}.")
    if target:
        parts.append(f"Target customers: {target}.")
    if company:
        parts.append(f"Company: {company}.")
    parts.append(f"Email tone: {tone}.")

    # Inject live session state so Gemini knows what's been done
    if session_state:
        parts.append(f"\nCURRENT SESSION STATE:\n{session_state}")
        parts.append("")
        parts.append("Use this state to understand context:")
        parts.append("- If user says 'draft for those', use the businesses listed above.")
        parts.append("- If user says 'send them', use the drafts listed above.")
        parts.append("- If user says 'what did we find', reference the search results.")
        parts.append("- Always suggest the logical next step based on current state.")

    # Inject brain context — what we've learned from past sessions
    try:
        from agents.brain import get_brain
        brain = get_brain()
        brain_ctx = brain.get_full_context()
        if brain_ctx:
            parts.append(f"\nBRAIN KNOWLEDGE:\n{brain_ctx}")
            parts.append("")
            parts.append("Use this knowledge to:")
            parts.append("- Reference what we sell and who we target when drafting emails.")
            parts.append("- Use industry pain points and hooks that worked before.")
            parts.append("- Avoid approaches that failed in the past.")
            parts.append("- Suggest next steps based on what we've learned.")
    except Exception:
        pass  # brain not available, continue without it

    return "\n".join(parts)


def _handle_function_call(name: str, args: dict, user_input: str) -> Action:
    """Map one function call (name + args off the seam) to an Action."""
    args = dict(args or {})

    if name == "ask_user":
        return _ask_user_action(args)

    if name == "set_selling_goal":
        return _goal_action(args.get("goal", ""), source="ai")

    # The action registry is the single source of truth for the mapping
    # (gemini function name -> ActionType -> ack). SEARCH's ack is built
    # dynamically from its args.
    from agents.action_registry import row_for_gemini
    row = row_for_gemini(name)
    if row:
        response = _build_search_response(args) if row.action == ActionType.SEARCH else row.ack
        return Action(type=row.action, params=args, response=response)

    if name == "show_help":
        return Action(type=ActionType.HELP, params=args, response="")

    if name == "start_campaign":
        return Action(type=ActionType.CAMPAIGN, params=args,
                      response="Starting guided campaign: discovery, curation, "
                               "and your approval checklist...")

    return Action(type=ActionType.UNKNOWN, response=f"Unknown action: {name}")


_GOAL_CLEAR_RE = re.compile(
    r"^\s*(?:(?:clear|reset|remove|forget)\s+(?:the\s+)?(?:selling\s+)?goal"
    r"(?:\s+back\s+to\s+auto)?|(?:selling\s+)?goal\s+back\s+to\s+auto)\s*$",
    re.IGNORECASE)
_GOAL_SET_RE = re.compile(
    r"^\s*(?:my\s+goal\s+is|the\s+goal\s+is|our\s+goal\s+is|goal[:=])\s*(.+?)\s*$",
    re.IGNORECASE)
_GOAL_SELL_RE = re.compile(
    r"^\s*(?:(?:i|we)\s+(?:(?:now\s+)?(?:sell|selling)|"
    r"(?:am|are)\s+selling)|(?:i|we)'(?:m|re)\s+selling)\s+(.+?)\s*$",
    re.IGNORECASE)
_GOAL_PREFIX_RE = re.compile(
    r"^\s*(?:set\s+)?(?:selling\s+)?goal(?:\s+(?:is|to)\s+|:\s*)(.+?)\s*$",
    re.IGNORECASE)


_GOAL_STATEMENT_SHAPE_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:now\s+)?(?:sell|selling)|(?:am|are)\s+selling)"
    r"|\b(?:i|we)'(?:m|re)\s+selling"
    r"|\b(?:my|our|the)\s+goal\s+is\b"
    r"|\b(?:set\s+)?(?:selling\s+)?goal\s*[:=]"
    r"|\bset\s+(?:selling\s+)?goal\b"
    r"|\b(?:clear|reset|remove|forget)\s+(?:the\s+)?(?:selling\s+)?goal\b"
    r"|\bgoal\s+back\s+to\s+auto\b",
    re.IGNORECASE)


def _has_goal_statement_shape(text: str) -> bool:
    """Does this message CONTAIN a selling-goal statement anywhere?

    Looser than the fastpath's full-message match: 'i'm selling laptops now,
    find clients in pune' reaches Gemini (the anchored regexes pass on it),
    and its set_selling_goal call must survive. What this gates out is a goal
    call on a message with no statement shape at all ('goal keeper gloves
    supplier').
    """
    return _GOAL_STATEMENT_SHAPE_RE.search(text or "") is not None


def _match_goal_statement(text: str, lower: str) -> Action | None:
    """Catch direct goal statements locally - no API call, no guess.

    Handles: 'i sell X', 'we are selling X now', 'my goal is X',
    'goal: X', 'set goal X', and 'clear the goal'. Only fires on statements
    ABOUT the goal, never on searches.
    """
    if "goal" not in lower and not re.search(
            r"\b(?:i|we)\s+(?:(?:now\s+)?(?:sell|selling)|"
            r"(?:am|are)\s+selling)|\b(?:i|we)'(?:m|re)\s+selling", lower):
        return None

    m = _GOAL_CLEAR_RE.match(text.strip())
    if m:
        return _goal_action("", source="user")

    body = None
    for rx in (_GOAL_SET_RE, _GOAL_SELL_RE, _GOAL_PREFIX_RE):
        m = rx.match(text.strip())
        if m:
            body = (m.group(1) or "").strip()
            break
    if body is None:
        return None
    # A bare 'goal' with no product body is a question, not a statement.
    if not body or body.lower() in ("what", "what?", "?"):
        return None
    # Discourse tail on sell statements: "i'm selling laptops now" pins
    # 'laptops', not 'laptops now'.
    body = re.sub(r"\s+(?:now|instead|too|also|these\s+days)\s*$", "",
                  body, flags=re.IGNORECASE).strip()
    return _goal_action(body, source="user")


def _goal_action(goal_text: str, source: str = "user") -> Action:
    """Build the GOAL action - set, switch, or clear what we are selling."""
    return Action(
        type=ActionType.GOAL,
        params={"goal": (goal_text or "").strip(), "source": source},
        response="Updating what we're selling...",
    )


def _build_search_response(args: dict) -> str:
    location = args.get("location", "that area")
    category = args.get("category", "")
    goal = args.get("goal", "")
    if category:
        line = f"Searching for: {category} in {location}..."
    else:
        line = f"Searching for businesses in {location}..."
    if goal:
        line += f"\nSelling: {goal} - ranking these against that."
    return line


def _ask_user_action(args: dict) -> Action:
    question = args.get("question", "Could you provide more details?")
    return Action(type=ActionType.UNKNOWN, response=question)


def parse_intent(user_input: str, context: list[dict] = None,
                 business_profile: dict = None, session_state: str = "") -> Action:
    """Back-compat single-action wrapper: first action of parse_intents().

    Single-part messages behave exactly as before. Multi-part messages are
    truncated to the first action here -- use parse_intents() to get all of
    them.
    """
    actions = parse_intents(user_input, context=context,
                            business_profile=business_profile,
                            session_state=session_state)
    return actions[0] if actions else Action(type=ActionType.UNKNOWN,
                                             response="I'm not sure what you mean.")


# ── Help text ────────────────────────────────────────────────────────

HELP_TEXT = """
I can help you with business outreach. Here's what I understand:

  FINDING BUSINESSES
    "Find restaurants in Manchester"
    "Search for shops in Bandel without websites"
    "Look for offices near Central London"
    "Find me 5 schools near Bandel that teach autocad"

  DRAFTING & EMAILS
    "Draft emails for the businesses"
    "Write personalized outreach emails"
    "Prepare professional emails for them"
    "Draft for the top 5"

  SENDING
    "Send all emails"
    "Ship it"
    "Go ahead and send"

  SELLING GOAL
    "I sell autocad keys" / "we are selling websites now"
    "My goal is X" / "Set goal X" / "Clear the goal"

  RESEARCH
    "Research these businesses"
    "What do their Google reviews say?"

  REVIEW
    "Review the emails"
    "Let me edit before sending"

  SCRAPING & ENRICHMENT
    "Scrape the websites"
    "Find emails for these businesses"
    "Enrich with Hunter.io"

  OBSIDIAN
    "Sync to Obsidian"
    "Update my vault"

  STATUS & DASHBOARD
    "What's the status?"
    "Show me the dashboard"

  MY TEAM (specialist agents)
    "Ask scout about restaurants in Bandel"
    "Ask strategist how to pitch schools"
    "Ask analyst how we're doing"
    "Ask scout to read dbbandel.org and summarize it"
    "Ask strategist to draft an email for Don Bosco"
    "Team act" (Scout researches, Strategist writes hooks, Analyst debriefs)
    "What does scout think about this?"

  MULTI-STEP
    "Find schools in Bandel and draft emails for the top 5"
    "Search, research, and draft for educational centers near me"

  Just talk to me naturally -- I'll figure out what you mean.
"""
