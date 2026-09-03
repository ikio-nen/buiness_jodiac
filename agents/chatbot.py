"""Intelligent chatbot -- Gemini-powered intent parsing with function calling.

Every user message goes through Gemini which decides what JARVIS action to take.
No more brittle regex matching. Gemini has full session context.
"""
import json
import random as _random
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


@dataclass
class Action:
    """A parsed user intent mapped to an agent action."""
    type: ActionType
    params: dict = field(default_factory=dict)
    response: str = ""  # What JARVIS says back


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
                            "description": "Business type filter (e.g. 'school', 'restaurant', 'pharmacy', 'cafe'). Empty means all types.",
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
        ],
    }
]


def parse_intent(user_input: str, context: list[dict] = None,
                 business_profile: dict = None, session_state: str = "") -> Action:
    """Parse user input using Gemini with function calling.

    Args:
        user_input: What the user typed
        context: Last N messages from conversation memory
        business_profile: Current business profile for context
        session_state: Current session state summary (businesses, drafts, etc.)
    """
    text = user_input.strip()
    if not text:
        return Action(type=ActionType.UNKNOWN, response="Type something and I'll help!")

    lower = text.lower().strip()

    # Quick brainstorm check (no API call)
    if any(w in lower for w in ("brainstorm", "set up my profile", "configure my business",
                                  "tell you about my business", "what i sell")):
        return Action(type=ActionType.BRAINSTORM, response="Let's set up your business profile!")

    # Quick help check (no API call)
    if lower in ("help", "commands", "options", "?", "what can you do"):
        return Action(type=ActionType.HELP, response="")

    # Quick greeting check (no API call)
    if lower in _GREETING_WORDS or any(lower.startswith(g) for g in _GREETING_WORDS):
        profile = business_profile or {}
        resp = _random.choice(_GREETING_RESPONSES)
        if profile.get("product"):
            resp += f"\n\n  Current mission: Selling {profile['product']}"
        else:
            resp += "\n\n  No business profile set. Press [S] to tell me what you sell."
        return Action(type=ActionType.GREETING, response=resp)

    # Try Gemini for intelligent parsing
    return _parse_with_gemini(text, context, business_profile, session_state)


def _parse_with_gemini(user_input: str, context: list[dict] = None,
                       business_profile: dict = None, session_state: str = "") -> Action:
    """Use Gemini with function calling to parse intent."""
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return Action(
                type=ActionType.UNKNOWN,
                response="AI is not configured. Set your Gemini API key in Setup [S]. "
                        "Meanwhile, try: 'find businesses in London', 'draft emails', or 'show status'."
            )

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
            return Action(
                type=ActionType.UNKNOWN,
                response="AI client not available. Check your Gemini API key."
            )

        from agents.config import get_ai_model
        model = get_ai_model()

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=_TOOLS,
                temperature=0.3,
            ),
        )

        # Parse function call response
        if response.candidates and response.candidates[0].content:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, "function_call") and part.function_call:
                return _handle_function_call(part.function_call, user_input)

            # Text response (clarification or chat)
            if hasattr(part, "text") and part.text:
                return Action(type=ActionType.UNKNOWN, response=part.text)

    except Exception as e:
        print(f"  [AI] Intent parsing error: {e}")

    return Action(
        type=ActionType.UNKNOWN,
        response="I'm not sure what you mean. Try: 'find businesses in London', "
                "'draft emails', or 'show status'."
    )


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
        "enrich_emails, show_status, show_help, show_dashboard, list_sessions, ask_user.",
        "",
        "Rules:",
        "- Always use a function call unless the user is just chatting.",
        "- For complex requests like 'find schools and draft emails', use search_businesses first.",
        "- If the user mentions a location, extract it for search_businesses.",
        "- If the user says 'draft' or 'write emails', use draft_emails.",
        "- If the user says 'send', use send_emails.",
        "- If the user says 'status' or 'dashboard', use the appropriate tool.",
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
        "list_sessions": (ActionType.LIST_SESSIONS, lambda a: "Here are your sessions..."),
        "start_brainstorm": (ActionType.BRAINSTORM, lambda a: "Let's set up your business profile!"),
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
        return f"Searching for {category}s in {location}..."
    return f"Searching for businesses in {location}..."


def _ask_user_action(args: dict) -> Action:
    question = args.get("question", "Could you provide more details?")
    return Action(type=ActionType.UNKNOWN, response=question)


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

  MULTI-STEP
    "Find schools in Bandel and draft emails for the top 5"
    "Search, research, and draft for educational centers near me"

  Just talk to me naturally -- I'll figure out what you mean.
"""
