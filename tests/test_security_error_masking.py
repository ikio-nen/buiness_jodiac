"""Tests for Step 6.6: Generic error sanitization and correlation error IDs."""
import logging
import pytest
from starlette.testclient import TestClient

from agents.web.server import app
from agents.web.auth import get_launch_auth_token


@pytest.fixture
def auth_headers():
    return {"X-JARVIS-Token": get_launch_auth_token()}


def test_status_error_sanitization(auth_headers, monkeypatch, caplog):
    client = TestClient(app)

    # Simulate an internal crash with sensitive paths and details
    def mock_broken_status():
        raise RuntimeError("SecretDBConnectionFailed at C:\\secrets\\db.sqlite3: root:p@ssword123")

    monkeypatch.setattr("agents.ai_engine.is_available", mock_broken_status)

    with caplog.at_level(logging.ERROR, logger="jarvis.api"):
        res = client.get("/api/status", headers=auth_headers)

    data = res.json()
    assert "error" in data
    assert "error_id" in data
    assert len(data["error_id"]) == 8
    # Assert sensitive internals are NEVER returned to the client
    assert "SecretDBConnectionFailed" not in data["error"]
    assert "p@ssword123" not in data["error"]
    assert "C:\\secrets" not in data["error"]
    assert "An internal error occurred while processing status check." in data["error"]

    # Assert that the full exception WAS logged server-side
    assert any("SecretDBConnectionFailed" in record.message for record in caplog.records)


def test_goals_error_sanitization(auth_headers, monkeypatch):
    client = TestClient(app)

    def mock_broken_goal():
        raise ValueError("Corrupt catalog YAML: /private/var/keys/master.key")

    monkeypatch.setattr("agents.config.get_active_goal", mock_broken_goal)

    res = client.get("/api/goals", headers=auth_headers)
    data = res.json()
    assert "error" in data
    assert "error_id" in data
    assert "master.key" not in data["error"]
    assert "An internal error occurred while processing goals retrieval." in data["error"]


def test_history_error_sanitization(auth_headers, monkeypatch):
    client = TestClient(app)

    def mock_broken_mem(*args, **kwargs):
        raise OSError("Disk failure reading sqlite memory at /opt/db/jodiac.db")

    monkeypatch.setattr("agents.chat_memory.ChatMemory", mock_broken_mem)

    res = client.get("/api/history", headers=auth_headers)
    data = res.json()
    assert "error" in data
    assert "error_id" in data
    assert "Disk failure" not in data["error"]
    assert "/opt/db" not in data["error"]
    assert "An internal error occurred while processing history retrieval." in data["error"]


def test_skills_error_sanitization(auth_headers, monkeypatch):
    client = TestClient(app)

    def mock_broken_skills(*args, **kwargs):
        raise KeyError("Skill store lock timeout in internal_thread_0x99")

    monkeypatch.setattr("agents.skills.list_skills", mock_broken_skills)

    res = client.get("/api/skills", headers=auth_headers)
    data = res.json()
    assert "error" in data
    assert "error_id" in data
    assert "internal_thread" not in data["error"]
    assert "An internal error occurred while processing skills retrieval." in data["error"]

