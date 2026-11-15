"""tests/test_security_cookie_auth.py — the launch cookie replaces the meta tag.

The document used to carry the per-launch token in a <meta> tag, so anything
that could read the page held full API authority, and it could read it again on
every load. The token now arrives once in the launch URL and leaves as an
HttpOnly SameSite=Strict cookie the page cannot read back.

Each test gets a fresh client, so a cookie set by one case cannot make the
next case's unauthenticated request look authenticated.
"""
import pytest
from fastapi.testclient import TestClient

from agents.web.auth import SESSION_COOKIE, get_launch_auth_token
from agents.web.server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def token():
    return get_launch_auth_token()


def test_document_is_locked_without_a_cookie(client, token):
    res = client.get("/")
    assert res.status_code == 200          # a lock page, not an error
    assert token not in res.text
    assert "jarvis-auth-token" not in res.text
    assert "LOCKED" in res.text


def test_launch_url_sets_httponly_strict_cookie(client, token):
    res = client.get(f"/?token={token}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/"

    raw = res.headers["set-cookie"]
    assert f"{SESSION_COOKIE}={token}" in raw
    flags = raw.lower()
    assert "httponly" in flags          # no document.cookie access
    assert "samesite=strict" in flags   # not sent cross-site
    assert "path=/" in flags

    assert res.headers["cache-control"] == "no-store"
    # Early returns get the same hardening as normal responses.
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"


def test_cookie_alone_authenticates_api_and_socket(client, token):
    client.get(f"/?token={token}")                     # follows the 302
    assert client.get("/api/status").status_code == 200
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert isinstance(msg, dict) and "type" in msg


def test_document_renders_for_the_cookie_holder(client, token):
    client.get(f"/?token={token}")
    res = client.get("/")
    assert res.status_code == 200
    assert token not in res.text
    assert "LOCKED" not in res.text
    assert "app.js" in res.text


def test_bad_launch_token_is_refused_and_mints_nothing(client):
    res = client.get("/?token=not-the-token", follow_redirects=False)
    assert res.status_code == 403
    assert "set-cookie" not in res.headers
    assert SESSION_COOKIE not in client.cookies
    assert client.get("/api/status").status_code == 401


def test_exchange_only_happens_on_the_document_paths(client, token):
    res = client.get(f"/static/app.js?token={token}", follow_redirects=False)
    assert res.status_code == 200
    assert SESSION_COOKIE not in client.cookies


def test_cookie_does_not_open_cross_origin_requests(client, token):
    """SameSite stops the browser sending the cookie cross-site; the Origin
    check is the second layer, tested here with the cookie attached."""
    client.get(f"/?token={token}")
    res = client.post("/api/goals", json={"goal": "cad_licensing"},
                      headers={"Origin": "http://evil.example"})
    assert res.status_code == 403


def test_static_assets_stay_public(client):
    assert client.get("/static/app.js").status_code == 200
