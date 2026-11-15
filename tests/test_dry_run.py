#!/usr/bin/env python3
"""Test DRY_RUN enforcement across all outreach, email, search, enrichment, and AI providers.

Verifies that when DRY_RUN=1 is set:
1. No external network connections (sockets) are established.
2. Mailer, Outreach APIs, Hunter/Apollo, Gmaps, and AI return mock dry_run responses.
"""
import os
import pytest
import socket
import sys
from pathlib import Path

# Force DRY_RUN mode before imports
os.environ["DRY_RUN"] = "1"
# Set dummy keys so key presence checks pass and we test the actual call interception
os.environ["RESEND_API_KEY"] = "re_dummy_123"
os.environ["BREVO_API_KEY"] = "xkeysib-dummy-123"
os.environ["EXA_API_KEY"] = "exa-dummy-123"
os.environ["TAVILY_API_KEY"] = "tvly-dummy-123"
os.environ["GEOAPIFY_API_KEY"] = "geo-dummy-123"
os.environ["HUNTER_API_KEY"] = "hunter-dummy-123"
os.environ["APOLLO_KEY"] = "apollo-dummy-123"
os.environ["GEMINI_API_KEY"] = "gemini-dummy-123"

sys.path.insert(0, str(Path(__file__).parent.parent))

# Guard socket.connect to ensure zero outbound non-local network calls occur
def _make_forbidden_connect(orig_func):
    def _forbidden_connect(self, *args, **kwargs):
        if args and isinstance(args[0], tuple) and len(args[0]) >= 2:
            host = args[0][0]
            # Allow internal Windows asyncio self-pipe loopback
            if host in ("127.0.0.1", "::1", "localhost"):
                return orig_func(self, *args, **kwargs)
        raise AssertionError(f"Network connect attempt blocked during DRY_RUN: {args}")
    return _forbidden_connect

# Global patch for standalone execution
_orig_connect = socket.socket.connect
socket.socket.connect = _make_forbidden_connect(_orig_connect)


@pytest.fixture(autouse=True)
def guard_sockets(monkeypatch):
    """Enforce socket block for every pytest in this module."""
    monkeypatch.setattr(socket.socket, "connect", _make_forbidden_connect(_orig_connect))


def test_mailer_dry_run():
    from agents.mailer import send_email
    res = send_email("test@example.com", "Subject", "Body")
    assert res.get("dry_run") is True, f"Mailer failed dry run: {res}"
    assert res.get("success") is True


def test_outreach_apis_dry_run():
    from agents.outreach_apis import (
        resend_send, brevo_send, exa_search, tavily_search,
        tavily_extract, geoapify_geocode, geoapify_places
    )
    r1 = resend_send("test@example.com", "Subject", "Body")
    assert r1.get("dry_run") is True

    r2 = brevo_send("test@example.com", "Subject", "Body")
    assert r2.get("dry_run") is True

    r3 = exa_search("test query")
    assert r3.get("dry_run") is True

    r4 = tavily_search("test query")
    assert r4.get("dry_run") is True

    r5 = tavily_extract(["https://example.com"])
    assert r5.get("dry_run") is True

    r6 = geoapify_geocode("Kolkata")
    assert r6.get("dry_run") is True

    r7 = geoapify_places(22.57, 88.36, "education.school")
    assert r7.get("dry_run") is True


def test_exec_finder_and_medium():
    from agents.exec_finder import find_executives
    from agents.medium import MediumAgent

    r_exec = find_executives([{"name": "Test Org", "website": "https://testorg.com"}])
    assert r_exec.get("dry_run") is True

    med = MediumAgent()
    r_med = med._enrich_hunter({"domain": "testorg.com"}, {})
    assert r_med.get("dry_run") is True


def test_gmaps_source_dry_run():
    from agents.gmaps_source import search_gmaps
    res = search_gmaps(22.57, 88.36, 1000, "school")
    assert len(res) > 0
    assert res[0].get("source") == "gmaps:dry_run"


def test_ai_dry_run():
    from agents.ai_engine import generate
    from agents.ai import providers
    t1 = generate("Hello world")
    assert "DRY RUN" in t1

    t2 = providers._post_to("groq", "/chat/completions", {})
    assert "choices" in t2


def test_socket_guard_active():
    """Verify that socket guard actively rejects non-loopback connections during tests."""
    s = socket.socket()
    with pytest.raises(AssertionError, match="Network connect attempt blocked during DRY_RUN"):
        s.connect(("8.8.8.8", 80))


if __name__ == "__main__":
    print("Running DRY_RUN safety tests...")
    test_mailer_dry_run()
    print("  [PASS] mailer dry run")
    test_outreach_apis_dry_run()
    print("  [PASS] outreach APIs dry run")
    test_exec_finder_and_medium()
    print("  [PASS] exec finder and medium dry run")
    test_gmaps_source_dry_run()
    print("  [PASS] gmaps source dry run")
    test_ai_dry_run()
    print("  [PASS] AI engine & providers dry run")
    print("All DRY_RUN tests passed: zero network sockets touched.")
