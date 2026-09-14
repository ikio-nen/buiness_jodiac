"""Intelligent chatbot -- Gemini-powered intent parsing with function calling.

Every user message goes through Gemini which decides what JARVIS action to take.
No more brittle regex matching. Gemini has full session context.
"""
import json
import random as _random
import re
import time
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
                "description": "Search for businesses in a location using OpenStreetMap. Returns businesses that may not have websites.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City, town, or area to search in (e.g. 'Bandel', 'London', 'Central Delhi')",
                        },
                        "category": {
                            "type": "string",
                            "description": "What the user is looking for, in the user's OWN words, including qualifiers (e.g. 'educational centers that teach AutoCAD', 'schools', 'pharmacies near hospitals'). Do NOT collapse this to one word -- the filter reasons over the full phrase.",
                        },
                        "radius": {
                            "type": "integer",
                            "description": "Search radius in meters. Default 2000.",
                        },
                    },
                    "required": ["location"],
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

    # Quick "talk to a specialist" triggers (no API call)
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

        from agents.ai_engine import _get_client
        from google.genai import types

        client = _get_client()
        if not client:
            return [Action(
                type=ActionType.UNKNOWN,
                response="AI client not available. Check your Gemini API key."
            )]

        from agents.config import get_ai_model
        model = get_ai_model()

        # Quota-proof call: free-tier 429s carry a retryDelay ("Please retry
        # in 18s"); honor it instead of degrading to "I'm not sure what you
        # mean" mid-conversation.
        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        tools=_TOOLS,
                        temperature=0.3,
                    ),
                )
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    import re as _re
                    wait = 0
                    m = _re.search(r"retry in (\d+)s", msg, _re.I)
                    if m:
                        wait = int(m.group(1)) + 1
                    wait = min(wait or (6 * (attempt + 1)), 25)
                    if attempt < 2:
                        print(f"  [AI] Quota hit — waiting {wait}s before retry")
                        time.sleep(wait)
                        continue
                raise

        # Parse function call response -- ALL parts, not just the first.
        if response.candidates and response.candidates[0].content:
            emitted_fc = False
            for part in (response.candidates[0].content.parts or []):
                if hasattr(part, "function_call") and part.function_call:
                    emitted_fc = True
                    emit(_handle_function_call(part.function_call, user_input))

            if emitted_fc:
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
                return collect

            # Text response (clarification or chat)
            part = response.candidates[0].content.parts[0] if response.candidates[0].content.parts else None
            if part is not None and hasattr(part, "text") and part.text:
                return [Action(type=ActionType.UNKNOWN, response=part.text)]

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
        "You have access to these tools: search_businesses, draft_emails, send_emails, "
        "review_emails, research_businesses, sync_obsidian, scrape_websites, "
        "enrich_emails, show_status, show_help, show_dashboard, list_sessions, "
        "ask_specialist, ask_user.",
        "",
        "Rules:",
        "- Always use a function call unless the user is just chatting.",
        "- If the user asks for MORE THAN ONE thing in one message (e.g. 'find "
        "emails for them and draft an email for each'), call EVERY tool the "
        "message names, in the order the user listed them: enrich_emails, "
        "then draft_emails. Do not stop after the first tool.",
        "- For complex requests like 'find schools and draft emails', use "
        "search_businesses first, then draft_emails in the same response.",
        "- If the user mentions a location, extract it for search_businesses.",
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


def _handle_function_call(function_call, user_input: str) -> Action:
    """Map Gemini function call to an Action."""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}

    action_map = {
        "search_businesses": (ActionType.SEARCH, _build_search_response),
        "draft_emails": (ActionType.DRAFT, lambda a: "Drafting personalized emails..."),
        "send_emails": (ActionType.SEND, lambda a: "Sending emails now..."),
        "review_emails": (ActionType.REVIEW, lambda a: "Opening email review..."),
        "research_businesses": (ActionType.RESEARCH, lambda a: "Researching businesses with AI..."),
        "sync_obsidian": (ActionType.SYNC, lambda a: "Syncing to Obsidian vault..."),
        "scrape_websites": (ActionType.SCRAPE, lambda a: "Scraping business websites..."),
        "enrich_emails": (ActionType.ENRICH, lambda a: "Looking up email addresses..."),
        "show_status": (ActionType.STATUS, lambda a: "Here's where things stand..."),
        "show_help": (ActionType.HELP, lambda a: ""),
        "show_dashboard": (ActionType.DASHBOARD, lambda a: "Loading learning dashboard..."),
        "agent_check_in": (ActionType.CHECKIN, lambda a: "Scanning everything I know..."),
        "ask_specialist": (ActionType.ASK_AGENT, lambda a: "Looping in a specialist..."),
        "team_act": (ActionType.TEAM_ACT, lambda a: "Putting the team to work..."),
        "list_sessions": (ActionType.LIST_SESSIONS, lambda a: "Here are your sessions..."),
        "ask_user": (_ask_user_action, None),
    }

    if name == "ask_user":
        return _ask_user_action(args)

    if name in action_map:
        action_type, response_fn = action_map[name]
        return Action(
            type=action_type,
            params=args,
            response=response_fn(args),
        )

    return Action(type=ActionType.UNKNOWN, response=f"Unknown action: {name}")


def _build_search_response(args: dict) -> str:
    location = args.get("location", "that area")
    category = args.get("category", "")
    if category:
        return f"Searching for: {category} in {location}..."
    return f"Searching for businesses in {location}..."


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
