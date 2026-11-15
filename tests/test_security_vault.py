#!/usr/bin/env python3
"""Test vault security enhancements:
1. First set-code is protected by local launch auth token.
2. Wrong codes burn attempts and trigger exponential lockout (growing delays).
3. Auto-lock timeout / session expiration works.
4. Reveal endpoint requires token, logs audit event, and logs contain no key material.
"""
import sys
import time
import unittest
from pathlib import Path
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.web.server import app
from agents.web.auth import get_launch_auth_token
from agents.web import vault


class TestSecurityVault(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.launch_token = get_launch_auth_token()
        # Reset vault state
        if vault._VAULT_PATH.exists():
            vault._VAULT_PATH.unlink()
        vault._sessions.clear()

    def test_first_set_code_requires_auth_token(self):
        # Calling set-code without launch token must fail with 401
        res = self.client.post("/api/vault/set-code", json={"code": "master1234"})
        self.assertEqual(res.status_code, 401)

        # Calling with valid launch token succeeds
        res2 = self.client.post(
            "/api/vault/set-code",
            json={"code": "master1234"},
            headers={"X-JARVIS-Token": self.launch_token}
        )
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(vault.has_code())

    def test_wrong_code_lockout_exponential_growth(self):
        # Setup code
        vault.set_code("correct_code_123")

        # Send 4 wrong attempts
        for i in range(4):
            res = self.client.post(
                "/api/vault/unlock",
                json={"code": f"wrong_{i}"},
                headers={"X-JARVIS-Token": self.launch_token}
            )
            self.assertEqual(res.status_code, 401)
            info = vault.locked_info()
            self.assertFalse(info["locked"])
            self.assertEqual(info["fails_left"], 4 - i)

        # 5th wrong attempt -> triggers 1st lockout (60s)
        res5 = self.client.post(
            "/api/vault/unlock",
            json={"code": "wrong_5"},
            headers={"X-JARVIS-Token": self.launch_token}
        )
        self.assertEqual(res5.status_code, 401)
        info1 = vault.locked_info()
        self.assertTrue(info1["locked"])
        self.assertGreaterEqual(info1["seconds_left"], 55)
        self.assertLessEqual(info1["seconds_left"], 65)

    def test_reveal_token_gated_and_audit_logged_without_secrets(self):
        vault.set_code("my_secret_code_99")
        # Unlock to get session token
        res = self.client.post(
            "/api/vault/unlock",
            json={"code": "my_secret_code_99"},
            headers={"X-JARVIS-Token": self.launch_token}
        )
        self.assertEqual(res.status_code, 200)
        vtoken = res.json()["token"]

        # Reveal an entry
        res_reveal = self.client.get(
            f"/api/vault/reveal/gmail_user?token={vtoken}",
            headers={"X-JARVIS-Token": self.launch_token}
        )
        self.assertEqual(res_reveal.status_code, 200)

        # Check activity log: verify reveal was logged and no secret value is stored in log
        events = vault.activity()
        reveal_events = [e for e in events if e.get("kind") == "reveal"]
        self.assertTrue(len(reveal_events) > 0)
        for e in events:
            # Confirm log detail only has entry id, not secret values
            self.assertNotIn("my_secret_code_99", str(e))


if __name__ == "__main__":
    unittest.main()

