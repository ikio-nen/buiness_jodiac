#!/usr/bin/env python3
"""Test per-launch auth token enforcement on mutating endpoints, sensitive reads, and WebSocket.

Verifies:
1. Mutating endpoints (POST, PATCH, DELETE) reject requests without token (401).
2. Mutating endpoints accept requests with valid X-JARVIS-Token or Bearer token (200/expected).
3. Sensitive read endpoints (e.g. /api/status, /api/history) reject unauthenticated requests (401).
4. WebSocket handshake rejects connections without token and accepts valid token.
5. Index document embeds the matching token in meta tag.
"""
import sys
import unittest
from pathlib import Path
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.web.server import app
from agents.web.auth import get_launch_auth_token


class TestSecurityAuthToken(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = get_launch_auth_token()

    def test_document_does_not_contain_the_token(self):
        """Deliberate contract change: this used to assert the <meta> tag was
        present. That tag was the hole — anything able to read the document
        (script, extension, local process) held full API authority, and it was
        re-readable on every load. The token now arrives in the launch URL and
        leaves as an HttpOnly cookie."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.token, res.text)
        self.assertNotIn("jarvis-auth-token", res.text)

    def test_launch_url_exchanges_token_for_a_cookie(self):
        res = self.client.get(f"/?token={self.token}", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        raw = res.headers.get("set-cookie", "")
        self.assertIn("jarvis_session=", raw)
        self.assertIn("httponly", raw.lower())
        self.assertIn("samesite=strict", raw.lower())

    def test_invalid_launch_token_sets_no_cookie(self):
        res = self.client.get("/?token=wrong", follow_redirects=False)
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("set-cookie", res.headers)

    def test_unauthenticated_mutating_endpoint_rejected(self):
        # POST /api/goals without token
        res = self.client.post("/api/goals", json={"goal": "cad_licensing"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("token required", res.json().get("error", "").lower())

    def test_authenticated_mutating_endpoint_accepted(self):
        # POST /api/goals with valid X-JARVIS-Token
        res = self.client.post(
            "/api/goals",
            json={"goal": "cad_licensing"},
            headers={"X-JARVIS-Token": self.token}
        )
        self.assertEqual(res.status_code, 200)

    def test_unauthenticated_sensitive_read_rejected(self):
        # GET /api/status without token
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 401)

        # GET /api/history without token
        res = self.client.get("/api/history")
        self.assertEqual(res.status_code, 401)

    def test_authenticated_sensitive_read_accepted(self):
        # GET /api/status with Bearer token
        res = self.client.get("/api/status", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(res.status_code, 200)

    def test_websocket_without_token_rejected(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/ws"):
                pass
        self.assertEqual(cm.exception.code, 1008)

    def test_websocket_with_token_accepted(self):
        with self.client.websocket_connect(f"/ws?token={self.token}") as ws:
            data = ws.receive_json()
            self.assertEqual(data.get("type"), "jarvis")

    def test_websocket_token_redacted_from_logs(self):
        import logging
        from agents.web.server import RedactQueryTokenFilter
        flt = RedactQueryTokenFilter()
        rec = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='GET /ws?token=my_secret_token_12345 HTTP/1.1 101',
            args=(),
            exc_info=None,
        )
        flt.filter(rec)
        self.assertNotIn("my_secret_token_12345", rec.msg)
        self.assertIn("GET /ws?token=[REDACTED] HTTP/1.1 101", rec.msg)

        # Test with format args
        rec2 = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=20,
            msg='%s - "%s" %s',
            args=("127.0.0.1", f"GET /ws?token={self.token} HTTP/1.1", 101),
            exc_info=None,
        )
        flt.filter(rec2)
        self.assertNotIn(self.token, rec2.args[1])
        self.assertIn("token=[REDACTED]", rec2.args[1])


if __name__ == "__main__":
    unittest.main()

