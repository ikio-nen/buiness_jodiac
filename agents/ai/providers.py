"""Alternative model providers behind the AI seam (ollama, Zen, Vercel AI Gateway).

The seam's rule stands: consumers never see a provider, a base URL, or a key.
They call ``ai_engine.generate/generate_json`` and ``gemini_client.converse``;
THIS module owns the OpenAI-compatible wire for everything that is not Gemini.

Providers (all speak the OpenAI ``/v1/chat/completions`` dialect):
  gemini           — default; nothing here runs (gemini_client keeps owning it)
  ollama           — local models, zero cost, offline  (http://127.0.0.1:11434/v1)
  opencode_zen     — https://opencode.ai/zen/v1  (keyless catalog; the user's
                     OpenCode API key unlocks glm/gpt/claude/gemini models)
  vercel_gateway   — https://ai-gateway.vercel.sh/v1  (key set; Vercel blocks
                     completions until a card is on file on their site)

Config (config.json via agents.config):
  ai_provider        "gemini" (default) | "ollama" | "opencode_zen" | "vercel_gateway"
  ai_provider_model  e.g. "qwen2.5:3b" (ollama), "glm-5.3-flash" (zen)
  ai_provider_base_url  optional override
  ai_provider_key    optional bearer key (never in code, never in git)

Resilience: a provider failure falls back to the Gemini path when a key
exists; a Gemini outage never blocks (existing rule) and neither does a
provider outage. Tool calling: the Gemini tool loop is translated to the
OpenAI tools dialect here, so the specialist agents and the intent parser
run unchanged on any provider that supports function calling.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from agents.config import (
    get_ai_provider, get_ai_provider_base_url, get_ai_provider_key,
    get_ai_provider_model,
)

_TIMEOUT_LOCAL_S = 120   # ollama cold-loads a model on first call (30s+ seen)
_TIMEOUT_REMOTE_S = 60
_MAX_ATTEMPTS = 2

_DEFAULT_BASES = {
    "ollama": "http://127.0.0.1:11434/v1",
    "opencode_zen": "https://opencode.ai/zen/v1",
    "vercel_gateway": "https://ai-gateway.vercel.sh/v1",
}

# Providers whose base URL/key ship in code above; a custom base_url via
# config always wins, so new OpenAI-compatible sites are one config edit away.
_KEYS_REQUIRED = {"opencode_zen", "vercel_gateway"}


def provider_active() -> bool:
    """True when a non-Gemini provider is selected and minimally configured."""
    p = (get_ai_provider() or "gemini").strip().lower()
    if p == "gemini" or p not in _DEFAULT_BASES:
        return False
    if p in _KEYS_REQUIRED and not get_ai_provider_key():
        return False
    return True


def _base() -> str:
    p = get_ai_provider()
    return (get_ai_provider_base_url() or _DEFAULT_BASES.get(p, "")).rstrip("/")


def _timeout() -> int:
    return _TIMEOUT_LOCAL_S if get_ai_provider() == "ollama" else _TIMEOUT_REMOTE_S


def _post(path: str, payload: dict) -> dict:
    """One POST to the provider. Raises on HTTP/transport failure."""
    key = get_ai_provider_key()
    headers = {"Content-Type": "application/json",
               # urllib's default "Python-urllib/3.x" UA is banned by Cloudflare
               # (HTTP 403 error 1010) on several gateways — any named UA passes.
               "User-Agent": "jodiac-agent/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{_base()}{path}", data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_timeout()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _chat(messages: list[dict], temperature: float, max_tokens: int,
          tools: list[dict] | None = None) -> dict:
    """One chat completion with short blip retry. Raises on final failure."""
    model = get_ai_provider_model()
    if not model:
        raise RuntimeError("ai_provider_model is not set in config")
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    last: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return _post("/chat/completions", payload)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            last = RuntimeError(f"provider HTTP {e.code}: {body}")
            if e.code in (429, 500, 502, 503) and attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last
        except Exception as e:  # transport (timeout, refused, DNS)
            last = e
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last  # pragma: no cover


# ── Text generation path (ai_engine) ─────────────────────────────────

def generate(prompt: str, system: str = "", temperature: float = 0.7,
             max_tokens: int = 4096) -> str:
    """Text through the configured provider. Raises on failure."""
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": prompt})
    data = _chat(messages, temperature, max_tokens)
    try:
        return (data["choices"][0]["message"].get("content") or "")
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"provider response malformed: {e}")


# ── Gemini-type translation for the converse() tool loop ─────────────

def _tools_to_openai(tools) -> list[dict]:
    """Gemini tools (SDK ``types.Tool`` or plain dict) -> OpenAI tools JSON.

    Callers pass both shapes: agent_team builds SDK ``types.Tool`` objects
    while chatbot owns ``{"function_declarations": [...]}`` dicts — a shape
    this translator must not silently drop (that once left the provider path
    with zero tools, so every intent parsed as UNKNOWN).
    """
    out: list[dict] = []
    for tool in tools or []:
        decls = (tool.get("function_declarations") if isinstance(tool, dict)
                 else getattr(tool, "function_declarations", None)) or []
        for fd in decls:
            if isinstance(fd, dict):
                name = fd.get("name") or ""
                desc = fd.get("description") or ""
                params = fd.get("parameters")
            else:
                name = fd.name or ""
                desc = getattr(fd, "description", "") or ""
                params = getattr(fd, "parameters", None)
            decl = {"type": "function",
                    "function": {"name": name, "description": desc}}
            if params is not None:
                if isinstance(params, dict):
                    decl["function"]["parameters"] = params
                else:
                    try:
                        p = params.model_dump(exclude_none=True, mode="json")
                        # Gemini enums (Type.OBJECT) -> OpenAI's lowercase JSON-schema types
                        if isinstance(p.get("type"), str):
                            p["type"] = p["type"].lower()
                        props = p.get("properties")
                        if isinstance(props, dict):
                            for node in props.values():
                                if isinstance(node, dict) and isinstance(node.get("type"), str):
                                    node["type"] = node["type"].lower()
                        decl["function"]["parameters"] = p
                    except Exception:
                        decl["function"]["parameters"] = {
                            "type": "object", "properties": {}}
            out.append(decl)
    return out


def _contents_to_messages(contents: list, system: str) -> list[dict]:
    """Gemini ``types.Content`` history -> OpenAI messages.

    Handles text parts, function_call parts (assistant tool_calls) and
    function_response parts (role=tool results). Unrecognized parts are
    flattened to their string form so nothing is silently dropped.
    """
    messages: list[dict] = [{"role": "system", "content": system}] if system else []
    pending_calls: list[dict] = []

    def flush_calls():
        if pending_calls:
            messages.append({"role": "assistant", "content": None,
                             "tool_calls": list(pending_calls)})
            pending_calls.clear()

    for c in contents or []:
        role = getattr(c, "role", "user")
        role = "assistant" if role == "model" else role
        for part in (getattr(c, "parts", None) or []):
            fc = getattr(part, "function_call", None)
            if fc:
                pending_calls.append({
                    "id": f"call_{len(pending_calls)}_{len(messages)}",
                    "type": "function",
                    "function": {"name": fc.name or "",
                                 "arguments": json.dumps(dict(fc.args or {}))}})
                continue
            fr = getattr(part, "function_response", None)
            if fr:
                flush_calls()
                messages.append({"role": "tool",
                                 "tool_call_id": f"call_0_{max(0, len(messages) - 1)}",
                                 "content": json.dumps(dict(fr.response or {}))})
                continue
            text = getattr(part, "text", None)
            if text:
                flush_calls()
                messages.append({"role": role, "content": text})
                continue
            flush_calls()
            messages.append({"role": role, "content": str(part)})
    flush_calls()
    return messages


class _Msg:
    """Normalized assistant message from an OpenAI-style response."""

    def __init__(self, raw: dict):
        self.raw = raw or {}
        self.text = self.raw.get("content") or ""
        self.tool_calls = [
            {"name": tc["function"]["name"],
             "args": _safe_json(tc["function"].get("arguments") or "{}"),
             "id": tc.get("id", "")}
            for tc in (self.raw.get("tool_calls") or [])
            if isinstance(tc, dict) and tc.get("function")
        ]


def _safe_json(s: str) -> dict:
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def converse(*, contents: list, system: str = "", tools=None,
             temperature: float = 0.3, max_rounds: int = 1,
             execute=None, max_tokens: int = 4096):
    """The gemini_client.converse contract, over the OpenAI dialect.

    Returns the same ``ToolTurn`` shape (agents.ai.schemas) with
    ``calls``/``text``/``error`` filled; ``turn.available=False`` on
    configuration problems so callers degrade exactly as with Gemini.
    """
    from agents.ai.schemas import ToolCall, ToolTurn

    turn = ToolTurn()
    try:
        messages = _contents_to_messages(contents, system)
        openai_tools = _tools_to_openai(tools) or None
        rounds = 0
        while rounds < max(1, max_rounds):
            rounds += 1
            data = _chat(messages, temperature, max_tokens, tools=openai_tools)
            msg = _Msg(data["choices"][0]["message"])
            turn.calls.extend(ToolCall(name=c["name"], args=c["args"])
                              for c in msg.tool_calls)
            if msg.tool_calls and execute is not None:
                messages.append({"role": "assistant", "content": msg.text or None,
                                 "tool_calls": [
                                     {"id": c["id"], "type": "function",
                                      "function": {"name": c["name"],
                                                   "arguments": json.dumps(c["args"])}}
                                     for c in msg.tool_calls]})
                for c in msg.tool_calls:
                    payload = execute(c["name"], c["args"])
                    if not isinstance(payload, dict):
                        payload = {"result": payload}
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": json.dumps(payload)})
                continue
            turn.text = msg.text
            break
        turn.rounds = rounds
    except Exception as e:
        turn.rounds = locals().get("rounds", 0) or 1
        turn.error_type = type(e).__name__
        turn.error = str(e)[:200]
    return turn


# ── Introspection for status surfaces ────────────────────────────────

def status() -> dict:
    """{provider, model, base, key_set} for dashboards/debugging."""
    p = get_ai_provider() or "gemini"
    return {"provider": p, "active": provider_active(),
            "model": get_ai_provider_model(),
            "base": _base() if provider_active() else "",
            "key_set": bool(get_ai_provider_key())}
