"""Low-level Gemini access for the ai seam — the ONLY module that touches the SDK.

Owns the wire, and nothing else: the client, the model name, the retry and
backoff policy (including honoring a 429 ``retryDelay``), and the
function-calling protocol (call → tool results → call → text). Both the
intent parser and the specialist agents used to build their own
``GenerateContentConfig`` and drive ``client.models.generate_content``
themselves, which is how one of them ended up with quota retries and the
other with none.

What is deliberately NOT owned here: prompt text. A *static* capability
prompt lives as a versioned file under ``agents/ai/prompts/``; a *dynamic*
system instruction (an agent's persona + memory + skills + ICP, or the
chatbot's intent prompt) is assembled by the module that owns that context
and passed in. The seam's rule is that the SDK, the key, the model name and
the retry policy appear in exactly one file — this one.
"""

import re
import time

from agents.ai.schemas import ToolCall, ToolTurn

VERSION = "1.1.0"

_MAX_ATTEMPTS = 3
# Quota exhaustion carries a retryDelay; these are transient blips under load.
_QUOTA_CODES = ("429", "RESOURCE_EXHAUSTED")
_BLIP_CODES = ("503", "500", "UNAVAILABLE", "DEADLINE_EXCEEDED")


def available() -> bool:
    """True when a Gemini key is configured and the client can be built."""
    from agents import ai_engine
    return ai_engine.is_available()


def generate_json(prompt: str, system: str = "", temperature: float = 0.3) -> dict:
    """One JSON call through the shared engine. {} on any failure."""
    from agents import ai_engine
    return ai_engine.generate_json(prompt, system=system, temperature=temperature)


def _call_with_retry(client, types, model, contents, config):
    """One model call, with the seam's single retry/quota policy.

    A 429 tells us how long to wait; a 5xx blip gets a short backoff. Anything
    else is not retryable and is raised on the first attempt.
    """
    last_err = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config)
        except Exception as e:
            last_err = e
            msg = str(e)
            if attempt >= _MAX_ATTEMPTS - 1:
                break
            if any(code in msg for code in _QUOTA_CODES):
                m = re.search(r"retry in (\d+)s", msg, re.I)
                wait = min((int(m.group(1)) + 1) if m else (6 * (attempt + 1)), 25)
                print(f"  [AI] Quota hit — waiting {wait}s before retry")
            elif any(code in msg for code in _BLIP_CODES):
                wait = 1.5 * (attempt + 1)
                print(f"  [AI] Server blip ({msg[:60]}) — retrying in {wait:.0f}s")
            else:
                raise
            time.sleep(wait)
    raise last_err


def _read_turn(response) -> tuple[object, list[ToolCall], str]:
    """Normalize one response into (model content, calls, text).

    The content object stays opaque here — it's only needed to append to the
    conversation history in a tool loop, which is this module's job.
    """
    content = None
    calls: list[ToolCall] = []
    text = ""
    if response.candidates and response.candidates[0].content:
        content = response.candidates[0].content
        for part in (content.parts or []):
            fc = getattr(part, "function_call", None)
            if fc:
                calls.append(ToolCall(name=fc.name or "", args=dict(fc.args or {})))
            elif not text and getattr(part, "text", None):
                text = part.text
    return content, calls, text


def converse(*, contents: list, system: str = "", tools: list | None = None,
             temperature: float = 0.3, max_rounds: int = 1,
             execute=None) -> ToolTurn:
    """Run up to ``max_rounds`` tool-using model turns over ``contents``.

    With ``execute`` given, the function-calling protocol is completed here:
    the model's call is handed to ``execute(name, args)``, whose dict return is
    fed back as the tool result, and the model is called again until it answers
    in text or the round budget runs out. Without ``execute``, the calls are
    simply returned for the caller to interpret (the intent parser turns them
    into Actions and never executes them itself).

    Never raises: a failed call comes back as ``ToolTurn.error``.
    """
    from agents.ai_engine import _get_client
    from agents.config import get_ai_model

    turn = ToolTurn()
    client = _get_client()
    if client is None:
        turn.available = False
        return turn

    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature)
    if tools:
        config.tools = tools

    history = list(contents or [])
    model = get_ai_model()
    rounds = 0
    while rounds < max(1, max_rounds):
        rounds += 1
        try:
            response = _call_with_retry(client, types, model, history, config)
        except Exception as e:
            turn.rounds = rounds
            turn.error_type = type(e).__name__
            turn.error = str(e)[:200]
            return turn

        content, calls, text = _read_turn(response)
        turn.calls.extend(calls)

        if calls and execute is not None:
            history.append(content)
            for call in calls:
                payload = execute(call.name, call.args)
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                history.append(types.Content(role="user", parts=[
                    types.Part(function_response=types.FunctionResponse(
                        name=call.name, response=payload))]))
            continue

        turn.text = text
        break

    turn.rounds = rounds
    return turn
