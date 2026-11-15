#!/usr/bin/env python3
"""Test CORS, Origin, and Host header validation on REST routes and WebSocket.

Verifies:
1. Valid host (127.0.0.1:8765 / localhost:8765) and Origin allowed.
2. Cross-origin request from malicious site (e.g. http://evil.com) is rejected with 403.
3. Spoofed Host header (e.g. evil-rebind.com) is rejected with 403.
4. WebSocket handshake from invalid Origin or Host is closed with 1008 policy violation.
"""
import sys
import unittest
from pathlib import Path
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.web.server import app


class TestSecurityOriginHost(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from agents.web.auth import get_launch_auth_token
        self.token = get_launch_auth_token()

    def test_valid_host_and_origin_rest(self):
        # Same-origin request with auth token
        res = self.client.get("/api/status", headers={
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "X-JARVIS-Token": self.token,
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://127.0.0.1:8765")

    def test_invalid_origin_rejected(self):
        # Cross-site attacker attempting to fetch API data
        res = self.client.get("/api/status", headers={
            "Host": "127.0.0.1:8765",
            "Origin": "http://attacker-evil.com",
            "X-JARVIS-Token": self.token,
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("rejected", res.json().get("error", "").lower())

    def test_spoofed_host_rejected(self):
        # DNS rebinding attempt with spoofed Host
        res = self.client.get("/api/status", headers={
            "Host": "attacker-rebind.com",
            "X-JARVIS-Token": self.token,
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("invalid host", res.json().get("error", "").lower())

    def test_websocket_valid_origin(self):
        with self.client.websocket_connect(f"/ws?token={self.token}", headers={"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}) as ws:
            data = ws.receive_json()
            self.assertEqual(data.get("type"), "jarvis")

    def test_websocket_invalid_origin_closed(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect(f"/ws?token={self.token}", headers={"Host": "127.0.0.1:8765", "Origin": "http://attacker-evil.com"}):
                pass
        self.assertEqual(cm.exception.code, 1008)

    def test_websocket_invalid_host_closed(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect(f"/ws?token={self.token}", headers={"Host": "evil-rebind.com", "Origin": "http://127.0.0.1:8765"}):
                pass
        self.assertEqual(cm.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
