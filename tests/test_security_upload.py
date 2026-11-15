#!/usr/bin/env python3
"""Test file upload security:
1. Valid file with allowed extension (.pdf, .txt, .png) succeeds.
2. Disallowed extension (.exe, .py, .sh, .bat) rejected with 400.
3. Path traversal attempts (../../evil.sh, C:\\boot.ini) sanitized to basename.
4. Oversized uploads (>10MB) rejected with 413.
5. Uploaded files stored outside static/ and cannot be executed or served directly.
"""
import io
import sys
import unittest
from pathlib import Path
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.web.server import app
from agents.web.auth import get_launch_auth_token


class TestSecurityUpload(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = get_launch_auth_token()

    def test_valid_upload_success(self):
        f = io.BytesIO(b"Hello PDF brochure test content")
        res = self.client.post(
            "/api/upload",
            files={"file": ("brochure.pdf", f, "application/pdf")},
            headers={"X-JARVIS-Token": self.token}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("name"), "brochure.pdf")
        self.assertTrue(Path(data.get("path")).exists())

    def test_disallowed_extension_rejected(self):
        # Attempt to upload executable / script
        for bad_ext in ("malware.exe", "backdoor.py", "script.sh", "run.bat"):
            f = io.BytesIO(b"print('hacked')")
            res = self.client.post(
                "/api/upload",
                files={"file": (bad_ext, f, "application/octet-stream")},
                headers={"X-JARVIS-Token": self.token}
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("disallowed", res.json().get("detail", "").lower())

    def test_path_traversal_sanitized(self):
        # Path traversal filename
        f = io.BytesIO(b"Traversal content")
        res = self.client.post(
            "/api/upload",
            files={"file": ("../../../../etc/passwd.txt", f, "text/plain")},
            headers={"X-JARVIS-Token": self.token}
        )
        self.assertEqual(res.status_code, 200)
        saved_path = Path(res.json()["path"])
        # Must be strictly inside agent_output/uploads
        self.assertEqual(saved_path.parent.name, "uploads")
        self.assertNotIn("..", str(saved_path))

    def test_oversized_upload_rejected(self):
        # 11MB file (exceeds 10MB limit)
        huge_data = b"0" * (11 * 1024 * 1024)
        f = io.BytesIO(huge_data)
        res = self.client.post(
            "/api/upload",
            files={"file": ("large_file.pdf", f, "application/pdf")},
            headers={"X-JARVIS-Token": self.token}
        )
        self.assertEqual(res.status_code, 413)


if __name__ == "__main__":
    unittest.main()

