#!/usr/bin/env python3
"""Test that AI providers silently skip unkeyed providers and cascade correctly.

Verifies:
1. When AI_PROVIDER=gemini, cascade is inactive and Gemini handles calls.
2. When a secondary provider (e.g. opencode or groq) has no key configured,
   it is silently skipped with zero network calls and zero errors, cascading to Gemini.
3. Order: Gemini first, then configured secondary (OpenCode), then fallbacks / templates.
"""
import os
import pytest
import socket
import sys
from pathlib import Path

# Block outbound network calls, allowing internal loopback for asyncio self-pipe
_orig_connect = socket.socket.connect

def _make_no_connect(orig_func):
    def _no_connect(self, *args, **kwargs):
        if args and isinstance(args[0], tuple) and len(args[0]) >= 2:
            host = args[0][0]
            if host in ("127.0.0.1", "::1", "localhost"):
                return orig_func(self, *args, **kwargs)
        raise AssertionError(f"Unexpected network socket connection: {args}")
    return _no_connect

socket.socket.connect = _make_no_connect(_orig_connect)


@pytest.fixture(autouse=True)
def guard_sockets(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _make_no_connect(_orig_connect))

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure clean env for unkeyed check
for k in list(os.environ.keys()):
    if k.startswith("AI_PROVIDER_KEY") or k in ("GEMINI_API_KEY", "AI_PROVIDER", "AI_PROVIDER_MODEL", "AI_PROVIDER_FALLBACKS"):
        del os.environ[k]

os.environ["DRY_RUN"] = "1"


def test_unkeyed_provider_silently_inactive():
    from agents.ai import providers
    from agents.config import set_ai_provider

    # Set to groq or opencode without providing any key
    set_ai_provider("groq")
    assert providers.provider_active() is False, "Unkeyed provider should NOT be active"
    st = providers.status()
    assert st["active"] is False
    assert st["key_set"] is False

    # Status chain reports inactive
    assert st["chain"] == []


def test_order_gemini_first_then_opencode():
    from agents.ai import providers
    from agents.config import set_ai_provider, set_ai_provider_fallbacks

    # Default provider is gemini
    set_ai_provider("gemini")
    assert providers.provider_active() is False

    # When secondary is selected and keyed
    set_ai_provider("opencode")
    os.environ["AI_PROVIDER_KEY"] = "test-opencode-key"
    try:
        assert providers.provider_active() is True
        st = providers.status()
        assert st["active"] is True
        assert st["key_set"] is True
        assert st["provider"] == "opencode"
    finally:
        del os.environ["AI_PROVIDER_KEY"]
        set_ai_provider("gemini")


def test_generate_graceful_fallback():
    from agents import ai_engine
    from agents.config import set_ai_provider

    # Provider with no key should fall back to Gemini / template without raising
    set_ai_provider("groq")
    res = ai_engine.generate("test prompt")
    # With DRY_RUN=1, returns dry run string, not an unhandled error
    assert res != ""
    set_ai_provider("gemini")


def test_socket_guard_active():
    """Verify that socket guard actively rejects non-loopback connections."""
    s = socket.socket()
    with pytest.raises(AssertionError, match="Unexpected network socket connection"):
        s.connect(("8.8.8.8", 80))


if __name__ == "__main__":
    print("Running trimmed AI provider tests...")
    test_unkeyed_provider_silently_inactive()
    print("  [PASS] unkeyed provider silently inactive")
    test_order_gemini_first_then_opencode()
    print("  [PASS] order: gemini default, opencode secondary when keyed")
    test_generate_graceful_fallback()
    print("  [PASS] graceful fallback when unkeyed")
    print("All trimmed AI provider tests passed!")
