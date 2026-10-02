"""Self-check for the free-provider cascade in agents/ai/providers.py.

Run:  python -X utf8 agents/test_provider_cascade.py   (repo root)
Exit 0 = all checks green. No network, no keys — _post_to is stubbed and a
fake agents.config module is injected, so the real Windows config paths and
the google-genai SDK are never touched.
"""
import importlib.util
import os
import sys
import types
import urllib.error

# ── Fake agents.config ────────────────────────────────────────────────
_CFG = {
    "ai_provider": "zai",
    "ai_provider_model": "",
    "ai_provider_base_url": "",
    "ai_provider_fallbacks": [],
    "ai_provider_key": "",
}


def _fake_config_module():
    mod = types.ModuleType("agents.config")

    def get_ai_provider():
        return _CFG["ai_provider"]

    def get_ai_provider_base_url():
        return _CFG["ai_provider_base_url"]

    def get_ai_provider_fallbacks():
        return list(_CFG["ai_provider_fallbacks"])

    def get_ai_provider_key():
        env = os.environ.get("AI_PROVIDER_KEY", "")
        return env or _CFG["ai_provider_key"]

    def get_ai_provider_model():
        return _CFG["ai_provider_model"]

    mod.get_ai_provider = get_ai_provider
    mod.get_ai_provider_base_url = get_ai_provider_base_url
    mod.get_ai_provider_fallbacks = get_ai_provider_fallbacks
    mod.get_ai_provider_key = get_ai_provider_key
    mod.get_ai_provider_model = get_ai_provider_model
    return mod


def _fake_schemas_module():
    mod = types.ModuleType("agents.ai.schemas")

    class ToolCall:
        def __init__(self, name="", args=None):
            self.name = name
            self.args = args or {}

    class ToolTurn:
        def __init__(self):
            self.calls = []
            self.text = ""
            self.error = ""
            self.error_type = ""
            self.rounds = 0
            self.available = True

    mod.ToolCall = ToolCall
    mod.ToolTurn = ToolTurn
    return mod


def _load_providers():
    pkg = types.ModuleType("agents")
    pkg.__path__ = []
    sys.modules["agents"] = pkg
    sys.modules["agents.config"] = _fake_config_module()
    ai_pkg = types.ModuleType("agents.ai")
    ai_pkg.__path__ = []
    sys.modules["agents.ai"] = ai_pkg
    sys.modules["agents.ai.schemas"] = _fake_schemas_module()
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "ai", "providers.py")
    spec = importlib.util.spec_from_file_location("agents.ai.providers", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agents.ai.providers"] = mod
    spec.loader.exec_module(mod)
    return mod


providers = _load_providers()

CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def _http_error(code):
    return urllib.error.HTTPError(
        "https://x.test/v1/chat/completions", code, "err", {}, None)


# ── Chain resolution ──────────────────────────────────────────────────
@check("chain: primary + fallbacks, deduped, unknowns dropped")
def _():
    _CFG.update({"ai_provider": "zai",
                 "ai_provider_fallbacks": ["groq", "zai", "nope", "openrouter"]})
    assert providers._resolve_chain() == ["zai", "groq", "openrouter"]


@check("chain: fallbacks listed even when primary is gemini (cascade idle)")
def _():
    _CFG.update({"ai_provider": "gemini", "ai_provider_fallbacks": ["groq"]})
    # provider_active() is False, so the cascade never runs — the Gemini
    # path owns the call. Chain content is informational only here.
    assert providers._resolve_chain() == ["groq"]
    assert providers.provider_active() is False


# ── Key resolution ────────────────────────────────────────────────────
@check("keys: per-provider env wins over shared env over config")
def _():
    os.environ["AI_PROVIDER_KEY"] = "shared-key"
    os.environ["AI_PROVIDER_KEY_GROQ"] = "groq-key"
    try:
        assert providers._provider_key("groq") == "groq-key"
        assert providers._provider_key("zai") == "shared-key"
    finally:
        del os.environ["AI_PROVIDER_KEY_GROQ"]
        del os.environ["AI_PROVIDER_KEY"]
    _CFG["ai_provider_key"] = "cfg-key"
    try:
        assert providers._provider_key("zai") == "cfg-key"
    finally:
        _CFG["ai_provider_key"] = ""


@check("provider_active: keyed provider needs a key; keyless does not")
def _():
    _CFG.update({"ai_provider": "zai"})
    assert providers.provider_active() is False
    os.environ["AI_PROVIDER_KEY"] = "k"
    try:
        assert providers.provider_active() is True
    finally:
        del os.environ["AI_PROVIDER_KEY"]
    _CFG.update({"ai_provider": "ollama"})
    assert providers.provider_active() is True


# ── Model / base resolution ───────────────────────────────────────────
@check("models: preset default when unset; config wins for primary")
def _():
    _CFG.update({"ai_provider": "zai", "ai_provider_model": ""})
    assert providers._model_for("zai") == "glm-4.7-flash"
    assert providers._model_for("groq") == "llama-3.3-70b-versatile"
    _CFG.update({"ai_provider_model": "glm-4.7-flash-999"})
    assert providers._model_for("zai") == "glm-4.7-flash-999"
    assert providers._model_for("groq") == "llama-3.3-70b-versatile"
    _CFG.update({"ai_provider_model": ""})


@check("models: legacy preset without default raises a clear error")
def _():
    _CFG.update({"ai_provider": "ollama", "ai_provider_model": ""})
    try:
        providers._model_for("ollama")
    except RuntimeError as e:
        assert "ai_provider_model is not set" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


@check("base: config override wins for primary only")
def _():
    _CFG.update({"ai_provider": "zai",
                 "ai_provider_base_url": "https://custom.test/v1/"})
    assert providers._base_for("zai") == "https://custom.test/v1"
    assert providers._base_for("groq") == "https://api.groq.com/openai/v1"
    _CFG.update({"ai_provider_base_url": ""})


# ── Cascade behavior (stubbed transport) ──────────────────────────────
def _stub_post_to(behaviors):
    """behaviors: {provider: ('ok', text) | ('http', code) | ('boom', msg)}"""
    def fake(provider, path, payload):
        mode = behaviors.get(provider, ("ok", "default"))
        if mode[0] == "ok":
            return {"choices": [{"message": {"content": mode[1]}}]}
        if mode[0] == "http":
            raise providers._SkipProvider(f"{provider} HTTP {mode[1]}: x")
        raise providers._SkipProvider(f"{provider} transport: {mode[1]}")
    return fake


@check("cascade: 503 on primary -> fallback serves the call")
def _():
    _CFG.update({"ai_provider": "zai", "ai_provider_fallbacks": ["groq"]})
    orig = providers._post_to
    providers._post_to = _stub_post_to(
        {"zai": ("http", 503), "groq": ("ok", "from groq")})
    try:
        assert providers.generate("hi") == "from groq"
    finally:
        providers._post_to = orig


@check("cascade: 401 dead key on primary -> skipped, not fatal")
def _():
    _CFG.update({"ai_provider": "zai",
                 "ai_provider_fallbacks": ["groq", "openrouter"]})
    orig = providers._post_to
    providers._post_to = _stub_post_to(
        {"zai": ("http", 401), "groq": ("http", 429),
         "openrouter": ("ok", "from openrouter")})
    try:
        assert providers.generate("hi") == "from openrouter"
    finally:
        providers._post_to = orig


@check("cascade: all skipped -> error propagates (ai_engine falls to Gemini)")
def _():
    _CFG.update({"ai_provider": "zai", "ai_provider_fallbacks": ["groq"]})
    orig = providers._post_to
    providers._post_to = _stub_post_to(
        {"zai": ("boom", "dns"), "groq": ("http", 500)})
    try:
        providers.generate("hi")
    except providers._SkipProvider:
        pass
    else:
        raise AssertionError("expected _SkipProvider")
    finally:
        providers._post_to = orig


@check("converse: whole tool loop stays on the fallback provider")
def _():
    _CFG.update({"ai_provider": "zai", "ai_provider_fallbacks": ["groq"]})
    seen = []
    groq_rounds = {"n": 0}

    class _Part:
        text = "find coaching centers"
        function_call = None
        function_response = None

    class _Content:
        role = "user"
        parts = [_Part()]

    def fake(provider, path, payload):
        seen.append(provider)
        if provider == "zai":
            raise providers._SkipProvider("zai HTTP 503: x")
        groq_rounds["n"] += 1
        if groq_rounds["n"] == 1:
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "search_businesses",
                                             "arguments": "{}"}}]}}]}
        return {"choices": [{"message": {"content": "done"}}]}

    orig = providers._post_to
    providers._post_to = fake
    try:
        turn = providers.converse(
            contents=[_Content()], system="s", max_rounds=3,
            execute=lambda name, args: {"ok": True})
        assert turn.text == "done", turn.text
        assert turn.error == "", turn.error
        assert len(turn.calls) == 1 and turn.calls[0].name == "search_businesses"
        # zai hit twice = the one same-provider blip retry, then the whole
        # 2-round tool loop runs on groq with no hopping back.
        assert seen == ["zai", "zai", "groq", "groq"], seen
    finally:
        providers._post_to = orig


@check("status: reports provider, resolved model, and chain")
def _():
    _CFG.update({"ai_provider": "zai", "ai_provider_fallbacks": ["groq"],
                 "ai_provider_model": ""})
    os.environ["AI_PROVIDER_KEY"] = "k"
    try:
        st = providers.status()
        assert st["active"] is True
        assert st["model"] == "glm-4.7-flash"
        assert st["chain"] == ["zai", "groq"]
        assert st["key_set"] is True
    finally:
        del os.environ["AI_PROVIDER_KEY"]


def main():
    failed = 0
    for name, fn in CHECKS:
        # reset shared config between checks
        _CFG.update({"ai_provider": "zai", "ai_provider_model": "",
                     "ai_provider_base_url": "", "ai_provider_fallbacks": [],
                     "ai_provider_key": ""})
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
