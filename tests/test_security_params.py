"""Tests for Step 6.5: Path traversal and IDOR protection on parameterized routes."""
import os
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from agents.web.server import app
from agents.web.auth import get_launch_auth_token
from agents.config import OUTPUT_DIR


@pytest.fixture
def auth_headers():
    token = get_launch_auth_token()
    return {"X-JARVIS-Token": token}


def test_conversation_id_validation(auth_headers):
    client = TestClient(app)
    # Negative and zero conversation IDs must be rejected with 400
    res = client.get("/api/conversation/0", headers=auth_headers)
    assert res.status_code == 400
    assert "Invalid conversation ID" in res.json().get("detail", "")

    res = client.get("/api/conversation/-5", headers=auth_headers)
    assert res.status_code == 400

    res = client.delete("/api/conversation/0", headers=auth_headers)
    assert res.status_code == 400

    # Non-integer traversal attempt should be rejected by schema
    res = client.get("/api/conversation/..%2f..%2fetc", headers=auth_headers)
    assert res.status_code in (404, 422)


def test_agent_id_validation(auth_headers):
    client = TestClient(app)
    # Path traversal strings or forbidden chars in agent_id
    traversals = ["../agent", "agent/sub", "agent;drop", "agent%00", "bad id with spaces"]
    for bad_id in traversals:
        res = client.post(f"/api/agents/{bad_id}/deactivate", headers=auth_headers)
        assert res.status_code in (400, 404), f"Failed to reject bad agent_id: {bad_id}"


def test_skills_id_validation(auth_headers):
    client = TestClient(app)
    bad_ids = ["../skill", "skill/hack", "skill$eval", "bad skill name"]
    for bad_id in bad_ids:
        # Delete
        res = client.delete(f"/api/skills/{bad_id}", headers=auth_headers)
        assert res.status_code in (400, 404)
        # Toggle
        res = client.post(f"/api/skills/{bad_id}/toggle", headers=auth_headers)
        assert res.status_code in (400, 404)
        # Assign
        res = client.patch(f"/api/skills/{bad_id}/assign", json={"agent": "scout"}, headers=auth_headers)
        assert res.status_code in (400, 404)

    # Filter query param with traversal
    res = client.get("/api/skills?agent=../malicious", headers=auth_headers)
    assert res.status_code == 400
    assert "Invalid agent filter" in res.json().get("detail", "")


def test_vault_reveal_allowlist(auth_headers):
    client = TestClient(app)
    # Arbitrary / traversal keys
    bad_keys = ["../../config.json", "../vault.json", "secret_admin", "os.environ", "passwd"]
    for bad_key in bad_keys:
        res = client.get(f"/api/vault/reveal/{bad_key}", headers=auth_headers)
        assert res.status_code == 404
        assert res.json().get("detail") in ("Unknown vault entry", "Not Found")


def test_report_path_traversal_prevention(auth_headers, tmp_path, monkeypatch):
    client = TestClient(app)
    reports_dir = OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Create a legitimate test report inside reports dir
    legit_pdf = reports_dir / "campaign_initial_test.pdf"
    legit_pdf.write_bytes(b"%PDF-1.4 test legit pdf")

    # Outside file that an attacker might try to read via path traversal
    outside_file = OUTPUT_DIR / "secret_data.pdf"
    outside_file.write_bytes(b"%PDF-1.4 secret data")

    from agents.web.api import _safe_report_path

    # Legitimate report is safely returned
    resolved = _safe_report_path(str(legit_pdf), "campaign_initial_*.pdf")
    assert resolved == legit_pdf.resolve()

    # Outside file in raw_path MUST NOT be accepted; fallback or 404
    resolved_outside = _safe_report_path(str(outside_file), "campaign_initial_*.pdf")
    # Must fallback to legit_pdf inside reports_dir, NOT outside_file
    assert resolved_outside == legit_pdf.resolve()

    # Traversal raw_path like ../secret_data.pdf MUST NOT be accepted
    traversal_path = str(reports_dir / ".." / "secret_data.pdf")
    resolved_traversal = _safe_report_path(traversal_path, "campaign_initial_*.pdf")
    assert resolved_traversal == legit_pdf.resolve()
