"""Alternative model providers behind the AI seam (free-tier cascade).

The seam's rule stands: consumers never see a provider, a base URL, or a key.
They call ``ai_engine.generate/generate_json`` and ``gemini_client.converse``;
THIS module owns the OpenAI-compatible wire for everything that is not Gemini.

Free providers (all speak the OpenAI ``/v1/chat/completions`` dialect;
presets verified Oct 2026 — free tiers change, re-check before depending):
  gemini           — default; nothing here runs (gemini_client keeps owning it)
  zai              — https://api.z.ai/api/paas/v4 — glm-4.7-flash permanently
                     $0 + 20M-token signup grant, no card, tool calling works
  groq             — https://api.groq.com/openai/v1 — fastest inference,
                     generous no-card free tier, reliable function calling
  deepseek         — https://api.deepseek.com/v1 — 5M-token signup grant
  openrouter       — https://openrouter.ai/api/v1 — one key, many ``:free``
                     models (~50 req/day free); models rotate
  huggingface      — https://router.huggingface.co/v1 — ~300 req/hr free
                     serverless, huge model choice
  nvidia           — https://integrate.api.nvidia.com/v1 — 1,000 signup
                     credits, 40 RPM, no card
  mistral          — https://api.mistral.ai/v1 — Experiment tier ~1B tokens/mo
                     but only ~2 RPM; SMS verification at signup
  pollinations     — https://text.pollinations.ai/openai — KEYLESS anonymous
                     tier; unofficial uptime, weak tool calling (prototyping)
  ollama           — local models, zero cost, offline (http://127.0.0.1:11434/v1)
  opencode_zen     — DEAD 2026-09-17: 403 outside the OpenCode client.
                     Kept only so old configs don't crash; do not select.
  vercel_gateway   — https://ai-gateway.vercel.sh/v1 — completions BLOCKED
                     until a card is on file (their customer_verification).

Config (config.json via agents.config):
  ai_provider            primary, e.g. "zai" (default "gemini")
  ai_provider_model      override for the PRIMARY's model (preset default wins
                         when unset; fallbacks always use their preset model)
  ai_provider_base_url   optional override for the PRIMARY's base URL
  ai_provider_fallbacks  ordered list, e.g. ["groq", "openrouter", "zai"] —
                         tried in order when the primary fails
  ai_provider_key        optional bearer key (never in code, never in git);
                         per-provider keys via env AI_PROVIDER_KEY_<NAME>
                         (e.g. AI_PROVIDER_KEY_GROQ) win over AI_PROVIDER_KEY

Cascade policy: one call runs on ONE provider — the first in
[primary, *fallbacks] that completes it. A provider is skipped on 429/5xx,
transport errors, and 401/403/404 (free-tier model IDs rotate; a dead key or
a retired model must not kill the pipeline). Other 4xx raise immediately —
that's a request-shape bug every provider would hit. When every provider is
skipped, the error propagates and ai_engine falls back to the Gemini path
(when a Gemini key exists); a Gemini outage still never blocks (existing
rule). Tool calling: the Gemini tool loop is translated to the OpenAI tools
dialect here, so the specialist agents and the intent parser run unchanged on
any provider that supports function calling (pollinations is the weak one).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from agents.config import (
    get_ai_provider, get_ai_provider_base_url, get_ai_provider_fallbacks,
    get_ai_provider_key, get_ai_provider_model,
)

_TIMEOUT_LOCAL_S = 120   # ollama cold-loads a model on first call (30s+ seen)
_TIMEOUT_REMOTE_S = 60
_MAX_ATTEMPTS = 2

# ── Provider presets ─────────────────────────────────────────────────
# name -> {base, model, needs_key, note}. `model` is the free-tier default
# used when the user has not set ai_provider_model for the primary; "" means
# the model MUST come from config (legacy ollama behavior). Free tiers move
# fast — re-check a preset before depending on it in production.
PROVIDER_PRESETS: dict[str, dict] = {
    "zai": {
        "base": "https://api.z.ai/api/paas/v4",
        "model": "glm-4.7-flash",
        "needs_key": True,
        "note": "glm-4.7-flash permanently $0; 20M-token signup grant, no card",
    },
    "groq": {
        "base": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "needs_key": True,
        "note": "fastest inference; generous no-card free tier",
    },
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "needs_key": True,
        "note": "5M-token signup grant; cheapest paid chat as backstop",
    },
    "openrouter": {
        "base": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat-v3.1:free",
        "needs_key": True,
        "note": "one key, many :free models (~50 req/day); models rotate",
    },
    "huggingface": {
        "base": "https://router.huggingface.co/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "needs_key": True,
        "note": "~300 req/hr free serverless; huge model choice",
    },
    "nvidia": {
        "base": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "needs_key": True,
        "note": "1,000 signup credits, 40 RPM, no card",
    },
    "mistral": {
        "base": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "needs_key": True,
        "note": "Experiment tier ~1B tokens/mo but ~2 RPM; SMS verify at signup",
    },
    "pollinations": {
        "base": "https://text.pollinations.ai/openai",
        "model": "openai",
        "needs_key": False,
        "note": "KEYLESS anonymous tier; unofficial uptime, weak tool calling",
    },
    # ── legacy (kept so old configs keep working) ──
    "ollama": {
        "base": "http://127.0.0.1:11434/v1",
        "model": "",
        "needs_key": False,
        "note": "local, offline; model must come from ai_provider_model",
    },
    "opencode_zen": {
        "base": "https://opencode.ai/zen/v1",
        "model": "",
        "needs_key": True,
        "note": "DEAD 2026-09-17: 403 outside the OpenCode client. Do not select.",
    },
    "vercel_gateway": {
        "base": "https://ai-gateway.vercel.sh/v1",
        "model": "",
        "needs_key": True,
        "note": "completions BLOCKED until a card is on file (customer_verification_required)",
    },
}

# Back-compat alias; custom base_url via config always wins for the primary.
_DEFAULT_BASES = {name: p["base"] for name, p in PROVIDER_PRESETS.items()}
_KEYS_REQUIRED = {name for name, p in PROVIDER_PRESETS.items() if p["needs_key"]}


class _SkipProvider(Exception):
    """Retryable across the cascade: rate limit, 5xx, transport, or a dead
    key/retired model (401/403/404). A skipped provider never kills the call —
    the next provider in the chain takes over."""


# HTTP statuses that move to the next provider instead of failing the call.
_SKIP_STATUSES = {401, 403, 404, 429, 500, 502, 503}


def _preset(name: str) -> dict:
    return PROVIDER_PRESETS.get(name, {})


def _provider_key(name: str) -> str:
    """Bearer key for one provider. Per-provider env wins, then the shared
    AI_PROVIDER_KEY env, then the manual config value. Never persisted."""
    env = os.environ.get(f"AI_PROVIDER_KEY_{name.upper()}", "")
    if env:
        return env
    return get_ai_provider_key()


def _resolve_chain() -> list[str]:
    """[primary, *fallbacks]: deduped, unknown names dropped."""
    primary = (get_ai_provider() or "gemini").strip().lower()
    chain = [primary] if primary in PROVIDER_PRESETS else []
    for fb in get_ai_provider_fallbacks():
        if fb in PROVIDER_PRESETS and fb not in chain:
            chain.append(fb)
    return chain


def _base_for(name: str) -> str:
    primary = (get_ai_provider() or "gemini").strip().lower()
    if name == primary:
        override = (get_ai_provider_base_url() or "").rstrip("/")
        if override:
            return override
    return _preset(name).get("base", "").rstrip("/")


def _model_for(name: str) -> str:
    """Resolved model id. Raises when nothing is configured (legacy ollama /
    zen / vercel have no preset default)."""
    primary = (get_ai_provider() or "gemini").strip().lower()
    if name == primary:
        configured = (get_ai_provider_model() or "").strip()
        if configured:
            return configured
    model = _preset(name).get("model", "")
    if not model:
        raise RuntimeError(
            f"ai_provider_model is not set in config (provider '{name}' "
            "has no preset default)")
    return model


def _safe_model_for(name: str) -> str:
    try:
        return _model_for(name)
    except RuntimeError:
        return ""


def provider_active() -> bool:
    """True when a non-Gemini provider is selected and minimally configured."""
    p = (get_ai_provider() or "gemini").strip().lower()
    if p == "gemini" or p not in PROVIDER_PRESETS:
        return False
    if p in _KEYS_REQUIRED and not _provider_key(p):
        return False
    return True


def _timeout_for(name: str) -> int:
    return _TIMEOUT_LOCAL_S if name == "ollama" else _TIMEOUT_REMOTE_S


def _post_to(provider: str, path: str, payload: dict) -> dict:
    """One POST to one provider. Raises _SkipProvider on retryable-across-
    providers failures, RuntimeError on request-shape 4xx."""
    key = _provider_key(provider)
    headers = {"Content-Type": "application/json",
               # urllib's default "Python-urllib/3.x" UA is banned by Cloudflare
               # (HTTP 403 error 1010) on several gateways — any named UA passes.
               "User-Agent": "jodiac-agent/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{_base_for(provider)}{path}", data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_timeout_for(provider)) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code in _SKIP_STATUSES:
            raise _SkipProvider(f"{provider} HTTP {e.code}: {body}") from e
        raise RuntimeError(f"{provider} HTTP {e.code}: {body}") from e
    except Exception as e:  # transport (timeout, refused, DNS)
        raise _SkipProvider(f"{provider} transport: {e}") from e


def _chat_for(provider: str, messages: list[dict], temperature: float,
              max_tokens: int, tools: list[dict] | None = None) -> dict:
    """One chat completion against ONE provider, with short blip retry."""
    model = _model_for(provider)
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    last: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return _post_to(provider, "/chat/completions", payload)
        except _SkipProvider as e:
            last = e
            # 429/5xx deserve one more blip retry on the SAME provider before
            # the cascade moves on; auth/404 go straight to the next provider.
            msg = str(e)
            retryable_here = any(s in msg for s in ("429", "500", "502", "503"))
            if retryable_here and attempt < _MAX_ATTEMPTS - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last  # pragma: no cover


def _chat(messages: list[dict], temperature: float, max_tokens: int,
          tools: list[dict] | None = None) -> dict:
    """One chat completion across the cascade: the first provider in
    [primary, *fallbacks] that completes the call wins. Raises the last
    error when every provider is skipped (ai_engine then falls back to the
    Gemini path, per the existing resilience rule)."""
    chain = _resolve_chain()
    if not chain:
        raise RuntimeError("no provider configured in cascade")
    last: Exception | None = None
    for provider in chain:
        try:
            return _chat_for(provider, messages, temperature, max_tokens,
                             tools=tools)
        except _SkipProvider as e:
            last = e
            continue
    raise last  # pragma: no cover


# ── Text generation path (ai_engine) ─────────────────────────────────

def generate(prompt: str, system: str = "", temperature: float = 0.7,
             max_tokens: int = 4096) -> str:
    """Text through the configured provider cascade ([primary, *fallbacks]).

    Raises on failure — ai_engine catches it and falls back to the Gemini
    path, so a dead cascade degrades instead of blocking."""
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


def _converse_on(provider: str, *, contents: list, system: str = "",
                 tools=None, temperature: float = 0.3, max_rounds: int = 1,
                 execute=None, max_tokens: int = 4096):
    """The gemini_client.converse contract, over the OpenAI dialect, pinned
    to ONE provider for the whole multi-round tool loop (no mid-conversation
    hopping). Raises _SkipProvider when this provider can't serve the call."""
    from agents.ai.schemas import ToolCall, ToolTurn

    turn = ToolTurn()
    messages = _contents_to_messages(contents, system)
    openai_tools = _tools_to_openai(tools) or None
    rounds = 0
    while rounds < max(1, max_rounds):
        rounds += 1
        data = _chat_for(provider, messages, temperature, max_tokens,
                         tools=openai_tools)
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
    return turn


def converse(*, contents: list, system: str = "", tools=None,
             temperature: float = 0.3, max_rounds: int = 1,
             execute=None, max_tokens: int = 4096):
    """The gemini_client.converse contract, over the OpenAI dialect.

    Tries [primary, *fallbacks] in order; the first provider that completes
    the whole call wins. Returns the same ``ToolTurn`` shape
    (agents.ai.schemas) with ``calls``/``text``/``error`` filled;
    ``turn.available=False`` on configuration problems so callers degrade
    exactly as with Gemini.
    """
    from agents.ai.schemas import ToolTurn

    turn = ToolTurn()
    chain = _resolve_chain()
    if not chain:
        turn.rounds = 1
        turn.error_type = "RuntimeError"
        turn.error = "no provider configured in cascade"
        return turn
    last: Exception | None = None
    for provider in chain:
        try:
            return _converse_on(provider, contents=contents, system=system,
                                tools=tools, temperature=temperature,
                                max_rounds=max_rounds, execute=execute,
                                max_tokens=max_tokens)
        except _SkipProvider as e:
            last = e
            continue
        except Exception as e:  # request-shape bug: every provider would hit it
            turn.rounds = 1
            turn.error_type = type(e).__name__
            turn.error = str(e)[:200]
            return turn
    turn.rounds = 1
    turn.error_type = type(last).__name__ if last else "RuntimeError"
    turn.error = str(last)[:200] if last else "all providers skipped"
    return turn


# ── Introspection for status surfaces ────────────────────────────────

def status() -> dict:
    """{provider, model, base, key_set, chain} for dashboards/debugging."""
    p = (get_ai_provider() or "gemini").strip().lower()
    active = provider_active()
    chain = _resolve_chain() if active else []
    return {"provider": p, "active": active,
            "model": _safe_model_for(p) if active else get_ai_provider_model(),
            "base": _base_for(p) if active else "",
            "key_set": bool(_provider_key(p)) if active else False,
            "chain": chain}
