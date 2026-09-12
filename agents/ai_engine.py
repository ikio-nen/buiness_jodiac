"""AI engine — wraps Google Gemini API for text/code generation.

Provides a single generate() function that all AI agents call.
Falls back to None if no API key is configured.
"""
import json
import time
from agents.config import get_gemini_key, get_ai_model

# Transient API failures worth retrying (503 under load per our AGENTS.md notes).
# Anything else (bad key, dead model 404) fails fast -- no point burning time.
_RETRY_MARKERS = ("503", "500", "504", "429", "deadline", "unavailable",
                  "exhausted", "timeout", "internal error", "reset")
_MAX_ATTEMPTS = 3


_client = None


def _get_client():
    """Lazy-init the Gemini client."""
    global _client
    key = get_gemini_key()
    if not key:
        return None
    if _client is None:
        try:
            from google import genai
            _client = genai.Client(api_key=key)
        except Exception:
            return None
    return _client


def is_available() -> bool:
    """Check if Gemini API is configured and reachable."""
    return _get_client() is not None


def generate(prompt: str, system: str = "", model: str = "",
             temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """Generate text from a prompt. Returns empty string on failure.

    Retries transient API failures (503/429/timeout) with a short backoff;
    permanent failures (bad key, dead model) return immediately.
    """
    client = _get_client()
    if not client:
        return ""

    model = model or get_ai_model()

    from google.genai import types
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    if system:
        config.system_instruction = system

    last_err: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return response.text or ""
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            transient = any(marker in msg for marker in _RETRY_MARKERS)
            if not transient or attempt == _MAX_ATTEMPTS - 1:
                break
            time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s

    print(f"  [AI] Generation error: {last_err}")
    return ""


def generate_json(prompt: str, system: str = "", model: str = "") -> dict:
    """Generate and parse JSON from a prompt. Returns {} on failure."""
    raw = generate(
        prompt=prompt,
        system=(system + "\n\nRespond ONLY with valid JSON. No markdown, no explanation.")
               if system else "Respond ONLY with valid JSON. No markdown, no explanation.",
        model=model,
        temperature=0.3,
    )
    if not raw:
        return {}
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]  # remove opening ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
