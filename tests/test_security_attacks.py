"""Step 6.11 Penetration Testing Suite: Attack Your Own Fixes.

Simulates adversarial attacks against all hardened layers:
1. Cross-origin fetch & WebSocket attacks from http://evil.com -> 403 / 1008
2. Spoofed Host header (DNS rebinding / Host header injection) -> 403
3. Mutating & sensitive read operations without launch auth token -> 401
4. Vault brute-force code guessing -> lockout
5. Directory traversal file upload -> strictly sanitized & isolated inside uploads/
6. Oversized upload exhaustion attack (15 MB) -> 413 Payload Too Large
7. Malformed JSON payload injection -> 400 / 422 with zero internal trace disclosure
"""
import io
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from agents.web.server import app
from agents.web.auth import get_launch_auth_token
from agents.web import vault
from agents.config import OUTPUT_DIR


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-JARVIS-Token": get_launch_auth_token()}


# ── 1. Cross-Origin Attacks ──────────────────────────────────────────

def test_attack_cross_origin_rest_rejected(client):
    """Malicious website attempting cross-origin read or mutate."""
    res = client.get(
        "/api/goals",
        headers={"Origin": "http://evil.com", "X-JARVIS-Token": get_launch_auth_token()}
    )
    assert res.status_code == 403
    assert "Cross-origin request rejected" in res.json().get("error", "")


def test_attack_cross_origin_websocket_rejected(client):
    """Malicious website attempting cross-site WebSocket hijacking (CSWSH)."""
    token = get_launch_auth_token()
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws?token={token}", headers={"Origin": "http://evil.com"}) as ws:
            ws.receive_json()


# ── 2. DNS Rebinding / Spoofed Host Attacks ──────────────────────────

def test_attack_spoofed_host_rejected(client):
    """Attacker using DNS rebinding with custom domain."""
    for bad_host in ["evil.com", "attacker.local", "192.168.1.100:8765", "victim.com:8765"]:
        res = client.get("/", headers={"Host": bad_host})
        assert res.status_code == 403
        assert "Invalid Host" in res.json().get("error", "")


# ── 3. Missing Auth Token Attacks ────────────────────────────────────

def test_attack_unauthenticated_mutations_rejected(client):
    """Attacker script without per-launch auth token trying to mutate state."""
    # Attempt goal update
    res = client.post("/api/goals", json={"goal": "evil_goal"})
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("error", "")

    # Attempt conversation deletion
    res = client.delete("/api/conversation/1")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("error", "")

    # Attempt sensitive read
    res = client.get("/api/vault/keys")
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("error", "")


# ── 4. Vault Brute-Force Lockout ─────────────────────────────────────

def test_attack_vault_brute_force_lockout(client, auth_headers):
    """Attacker trying brute-force guessing against the personal key vault."""
    # Ensure code is set
    vault.set_code("correct_pin_9876")

    # Burn 5 attempts with wrong pins
    for _ in range(5):
        res = client.post("/api/vault/unlock", json={"code": "0000"}, headers=auth_headers)
        assert res.status_code == 401

    # 6th attempt must be locked out
    res6 = client.post("/api/vault/unlock", json={"code": "correct_pin_9876"}, headers=auth_headers)
    assert res6.status_code == 401
    detail = res6.json().get("detail", {})
    assert detail.get("locked") is True
    assert detail.get("message") == "Vault locked"


# ── 5. Path Traversal File Upload ────────────────────────────────────

def test_attack_path_traversal_upload_sanitized(client, auth_headers):
    """Attacker attempting path traversal via filename to overwrite system files."""
    uploads_dir = (OUTPUT_DIR / "uploads").resolve()

    # Disallowed extensions with traversal are rejected immediately with 400
    res_disallowed = client.post(
        "/api/upload",
        files={"file": ("../../boot.ini", io.BytesIO(b"harmless"), "text/plain")},
        headers=auth_headers
    )
    assert res_disallowed.status_code == 400
    assert "Disallowed file extension" in res_disallowed.json().get("detail", "")

    # Allowed extension with directory traversal must be sanitized inside uploads_dir
    traversal_names = [
        "../../system32_exploit.txt",
        "..\\..\\windows\\win_exploit.txt",
        "/etc/passwd.txt"
    ]
    for bad_name in traversal_names:
        file_bytes = b"safe harmless payload"
        res = client.post(
            "/api/upload",
            files={"file": (bad_name, io.BytesIO(file_bytes), "text/plain")},
            headers=auth_headers
        )
        assert res.status_code == 200
        saved_path = Path(res.json()["path"]).resolve()

        # Target file MUST stay strictly inside uploads_dir
        assert str(saved_path).startswith(str(uploads_dir))
        assert saved_path.exists()
        assert ".." not in saved_path.name


# ── 6. Resource Exhaustion: Oversized Upload ─────────────────────────

def test_attack_oversized_upload_rejected(client, auth_headers):
    """Attacker attempting DOS via huge multi-megabyte payload."""
    oversized = b"X" * (11 * 1024 * 1024)  # 11 MB > 10 MB limit
    res = client.post(
        "/api/upload",
        files={"file": ("large_catalog.pdf", io.BytesIO(oversized), "application/pdf")},
        headers=auth_headers
    )
    assert res.status_code == 413
    assert "exceeds maximum size limit" in res.json().get("detail", "")


# ── 7. Malformed JSON Payload Injection ──────────────────────────────

def test_attack_malformed_json_sanitized(client, auth_headers):
    """Attacker sending malformed payloads; server must not leak raw traceback."""
    res = client.post(
        "/api/goals",
        content=b"{ bad json ::: invalid syntax",
        headers={**auth_headers, "Content-Type": "application/json"}
    )
    # FastAPI returns 422 or 400 for unparseable body
    assert res.status_code in (400, 422)
    text = res.text
    # Must not leak traceback or file paths
    assert "Traceback" not in text
    assert "File \"" not in text
    assert "line " not in text.lower() or "json_invalid" in text
