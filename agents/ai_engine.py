"""AI engine — wraps Google Gemini API for text/code generation.

Provides a single generate() function that all AI agents call.
Falls back to None if no API key is configured.
"""
import json
import time
from agents.config import get_gemini_key, get_ai_model

# API blips (503s under load) are common -- retry every failure a few times
# with a short backoff before giving up.
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
            # Bounded HTTP read (ms). The SDK default is 600s, and a hung
            # connection froze a whole search chain for 10+ minutes with the
            # UI stuck on "Thinking" — fail fast instead; the seam's own
            # retry policy (gemini_client._call_with_retry) then decides.
            _client = genai.Client(
                api_key=key,
                http_options={"timeout": 120 * 1000})
        except Exception:
            return None
    return _client


def is_available() -> bool:
    """Check if the configured AI path can serve calls.

    True when a non-Gemini provider is selected and configured (ollama, Zen,
    ...), else when the Gemini client is configured.
    """
    from agents.ai import providers
    if providers.provider_active():
        return True
    return _get_client() is not None


def generate(prompt: str, system: str = "", model: str = "",
             temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """Generate text from a prompt. Returns empty string on failure.

    Retries up to 3 times with a short backoff -- API blips are common.
    """
    # Non-Gemini provider selected: route there first, fall back to Gemini
    # on failure (a provider outage must not block the pipeline either).
    from agents.ai import providers
    if providers.provider_active():
        try:
            return providers.generate(prompt, system=system,
                                      temperature=temperature,
                                      max_tokens=max_tokens)
        except Exception as e:
            print(f"  [AI] provider {providers.get_ai_provider()} failed: "
                  f"{str(e)[:120]} — falling back to Gemini")
            if not _get_client():
                return ""

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

    last_err = None
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
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s

    print(f"  [AI] Generation error: {last_err}")
    return ""


def generate_json(prompt: str, system: str = "", model: str = "",
                  temperature: float = 0.3) -> dict:
    """Generate and parse JSON from a prompt. Returns {} on failure."""
    raw = generate(
        prompt=prompt,
        system=(system + "\n\nRespond ONLY with valid JSON. No markdown, no explanation.")
               if system else "Respond ONLY with valid JSON. No markdown, no explanation.",
        model=model,
        temperature=temperature,
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
