"""Tests for Step 6.7: Security headers middleware."""
from starlette.testclient import TestClient
from agents.web.server import app
from agents.web.auth import get_launch_auth_token


def test_security_headers_present_on_document():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200

    headers = res.headers
    # Content-Security-Policy
    csp = headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "font-src 'self'" in csp
    # Typefaces are self-hosted: no third-party font origin may creep back in.
    assert "fonts.googleapis.com" not in csp
    assert "fonts.gstatic.com" not in csp
    assert "img-src 'self' data: blob:" in csp
    assert "connect-src 'self' ws://127.0.0.1:8765 ws://localhost:8765" in csp

    # Standard security hardening headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"
    assert headers.get("permissions-policy") == "camera=(), microphone=(), geolocation=()"


def test_security_headers_present_on_api_responses():
    client = TestClient(app)
    token = get_launch_auth_token()
    res = client.get("/api/status", headers={"X-JARVIS-Token": token})
    assert res.status_code == 200

    headers = res.headers
    assert "default-src 'self'" in headers.get("content-security-policy", "")
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "no-referrer"


def test_favicon_serves_cleanly():
    client = TestClient(app)
    res = client.get("/favicon.ico")
    assert res.status_code == 200
    assert "image/svg+xml" in res.headers.get("content-type", "")
    assert len(res.content) > 100
