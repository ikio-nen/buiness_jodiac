"""Tests for Step 6.8: Secret precedence (os.environ > encrypted vault.json > config.json)
and automated plaintext key migration."""
import json
import os
import pytest
from pathlib import Path

from agents import config
from agents.web import vault


@pytest.fixture(autouse=True)
def clean_keys(tmp_path, monkeypatch):
    # Set a clean isolated directory for vault and config testing
    test_out = tmp_path / "jodiac_data"
    test_out.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", test_out)
    monkeypatch.setattr(config, "CONFIG_FILE", test_out / "config.json")
    monkeypatch.setattr(vault, "OUTPUT_DIR", test_out)
    monkeypatch.setattr(vault, "_VAULT_PATH", test_out / "vault.json")
    monkeypatch.setattr(vault, "_KEY_PATH", test_out / ".vault_key")

    # Clear relevant env vars
    for k in [
        "GEMINI_API_KEY", "AI_PROVIDER_KEY", "GMAIL_APP_PASSWORD",
        "GMAIL_USER", "EXA_API_KEY", "HUNTER_API_KEY"
    ]:
        monkeypatch.delenv(k, raising=False)


def test_secret_precedence_order(monkeypatch):
    # 1. Config fallback only
    config.save_config({"gemini_api_key": "config_key_123"})
    assert config.get_gemini_key() == "config_key_123"

    # 2. Vault secret takes precedence over config
    vault.set_vault_secret("gemini_api_key", "vault_key_456")
    assert config.get_gemini_key() == "vault_key_456"

    # 3. os.environ takes precedence over vault and config
    monkeypatch.setenv("GEMINI_API_KEY", "env_key_789")
    assert config.get_gemini_key() == "env_key_789"


def test_vault_secrets_encrypted_at_rest():
    secret_value = "super_secret_password_abc_xyz"
    vault.set_vault_secret("gmail_app_password", secret_value)

    # Read raw vault.json directly from disk
    raw_data = json.loads(vault._VAULT_PATH.read_text(encoding="utf-8"))
    encrypted_entry = raw_data.get("encrypted_secrets", {}).get("gmail_app_password")

    assert encrypted_entry is not None
    # Raw ciphertext must NOT contain the plaintext secret
    assert secret_value not in encrypted_entry
    assert secret_value not in vault._VAULT_PATH.read_text(encoding="utf-8")

    # Decrypting via vault API recovers original secret
    assert vault.get_vault_secret("gmail_app_password") == secret_value
    assert config.get_gmail_app_password() == secret_value


def test_migrate_plaintext_keys_to_vault():
    # Setup plaintext keys in config.json
    config.save_config({
        "gemini_api_key": "plain_gemini_key",
        "ai_provider_key": "plain_opencode_key",
        "exa_api_key": "plain_exa_key",
    })

    # Run migration helper
    res = config.migrate_plaintext_keys_to_vault(strip_from_config=True)
    assert res["count"] >= 3
    assert "gemini_api_key" in res["migrated"]

    # Verify keys are now in encrypted vault
    assert vault.get_vault_secret("gemini_api_key") == "plain_gemini_key"
    assert vault.get_vault_secret("ai_provider_key") == "plain_opencode_key"
    assert vault.get_vault_secret("exa_api_key") == "plain_exa_key"

    # Verify config getters resolve them seamlessly from vault
    assert config.get_gemini_key() == "plain_gemini_key"
    assert config.get_ai_provider_key() == "plain_opencode_key"
    assert config.get_exa_key() == "plain_exa_key"

    # Verify config.json was sanitized
    cfg = config.load_config()
    assert "gemini_api_key" not in cfg
    assert "ai_provider_key" not in cfg

