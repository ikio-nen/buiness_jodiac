"""Personal key vault behind the web UI — only the owner's code opens it.

The office UI runs on the user's own machine, but the browser is shared
territory: anyone at the keyboard can open DevTools and read every response
the page ever received. So the vault's contract is:

  * No key material EVER appears in any API response unless the request
    carries a session token minted by a correct access code.
  * The code itself is never stored — only a PBKDF2-SHA256 hash with a
    random salt, in the gitignored agent_output/vault.json.
  * Wrong codes burn attempts; MAX_FAILS consecutive misses lock the vault
    for LOCKOUT_S.
  * Tokens live in process memory with a TTL — a server restart re-locks
    everything.

Routes live in web/api.py; this module owns the state machine and the key
enumeration. This is deliberately the ONLY web module allowed to touch the
config key getters.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agents.config import OUTPUT_DIR

_VAULT_PATH = OUTPUT_DIR / "vault.json"
_KEY_PATH = OUTPUT_DIR / ".vault_key"

_SALT_BYTES = 16
_HASH_ITERS = 600_000
_TOKEN_TTL_S = 15 * 60          # auto-lock timeout: 15 minutes of inactivity
_MAX_FAILS = 5                  # consecutive wrong codes before lockout
_BASE_LOCKOUT_S = 60            # starting lockout: 60s, growing with consecutive lockouts
_CODE_MIN, _CODE_MAX = 4, 128

_sessions: dict[str, float] = {}   # token -> expiry epoch


# ── Encryption for at-rest secrets in vault.json ─────────────────────

def _get_encryption_key() -> bytes:
    key_env = os.environ.get("VAULT_ENCRYPTION_KEY")
    if key_env:
        return hashlib.sha256(key_env.encode("utf-8")).digest()
    if _KEY_PATH.exists():
        try:
            return base64.b64decode(_KEY_PATH.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    key = AESGCM.generate_key(bit_length=256)
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEY_PATH.write_text(base64.b64encode(key).decode("utf-8"), encoding="utf-8")
    return key


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string using AES-256-GCM. Returns base64 string."""
    if not plaintext:
        return ""
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_secret(encrypted_b64: str) -> str:
    """Decrypt a base64 ciphertext using AES-256-GCM. Returns plaintext string."""
    if not encrypted_b64:
        return ""
    try:
        raw = base64.b64decode(encrypted_b64.encode("utf-8"))
        if len(raw) < 13:
            return ""
        nonce, ciphertext = raw[:12], raw[12:]
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def get_vault_secret(entry_id: str) -> str | None:
    """Retrieve and decrypt a secret from vault.json."""
    data = _load()
    sec_map = data.get("encrypted_secrets") or {}
    enc = sec_map.get(entry_id)
    if not enc:
        return None
    val = decrypt_secret(enc)
    return val if val else None


def set_vault_secret(entry_id: str, secret_value: str) -> None:
    """Encrypt and store a secret in vault.json."""
    data = _load()
    if "encrypted_secrets" not in data:
        data["encrypted_secrets"] = {}
    if secret_value:
        data["encrypted_secrets"][entry_id] = encrypt_secret(secret_value)
    else:
        data["encrypted_secrets"].pop(entry_id, None)
    _save(data)


def migrate_from_config(strip_from_config: bool = False) -> dict:
    """Migrate plaintext secrets from config.json into encrypted vault.json.
    Strictly opt-in: never runs automatically, creates a backup before stripping."""
    from agents.config import CONFIG_FILE, load_config, save_config
    cfg = load_config()
    secret_keys = [
        "gemini_api_key",
        "ai_provider_key",
        "gmail_app_password",
        "gmail_user",
        "exa_api_key",
        "hunter_api_key",
        "resend_api_key",
        "brevo_api_key",
        "tavily_api_key",
        "geoapify_api_key",
        "apollo_key",
    ]
    migrated = []
    for k in secret_keys:
        val = cfg.get(k)
        if val and isinstance(val, str) and val.strip():
            set_vault_secret(k, val.strip())
            migrated.append(k)
            if strip_from_config:
                cfg.pop(k, None)

    backup_path = None
    if strip_from_config and migrated:
        if CONFIG_FILE.exists():
            backup_path = CONFIG_FILE.with_suffix(f".json.bak.{int(time.time())}")
            backup_path.write_text(CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        save_config(cfg)

    log_event("migrate_keys", f"Migrated {len(migrated)} keys into encrypted vault")
    out = {"migrated": migrated, "count": len(migrated)}
    if backup_path:
        out["backup"] = str(backup_path)
    return out


# ── code hash file ────────────────────────────────────────────────────


def _load() -> dict:
    try:
        return json.loads(_VAULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    _VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _VAULT_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _hash_code(code: str, salt: bytes, iters: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, iters).hex()


def has_code() -> bool:
    return bool(_load().get("code_hash"))


def set_code(code: str, current: str | None = None) -> bool | str:
    """Set (first time) or change (owner session) the access code.

    Returns True on success, "exists" when a code is set and `current`
    does not verify, or "length" when the code is out of bounds.
    """
    code = (code or "").strip()
    if not (_CODE_MIN <= len(code) <= _CODE_MAX):
        return "length"
    data = _load()
    if data.get("code_hash"):
        if not current or not verify_code_only(str(current), data):
            return "exists"
        log_event("code_change")
    else:
        log_event("code_set")
    was_new = not data.get("code_hash")
    salt = secrets.token_bytes(_SALT_BYTES)
    data.update({"salt": salt.hex(), "iters": _HASH_ITERS,
                 "code_hash": _hash_code(code, salt, _HASH_ITERS),
                 "fails": 0, "locked_until": 0,
                 "set_at": time.strftime("%Y-%m-%d %H:%M")})
    _save(data)
    log_event("code_set" if was_new else "code_change")
    return True


def verify_code_only(code: str, data: dict) -> bool:
    """Constant-time code check against a loaded file — no lockout logic."""
    try:
        salt = bytes.fromhex(data["salt"])
        iters = int(data.get("iters", _HASH_ITERS))
    except Exception:
        return False
    return hmac.compare_digest(_hash_code(code, salt, iters), data.get("code_hash", ""))


# ── sessions ──────────────────────────────────────────────────────────


def _sweep() -> None:
    now = time.time()
    for tok in [t for t, exp in _sessions.items() if exp <= now]:
        _sessions.pop(tok, None)


def locked_info() -> dict:
    data = _load()
    until = float(data.get("locked_until") or 0)
    left = max(0, int(until - time.time()))
    return {"locked": left > 0, "seconds_left": left,
            "fails_left": max(0, _MAX_FAILS - int(data.get("fails") or 0))}


def verify(code: str) -> str | None:
    """Check the access code; on success mint a session token.

    Returns None on wrong code, unknown code state, or while locked out.
    """
    data = _load()
    if not data.get("code_hash"):
        return None
    if time.time() < float(data.get("locked_until") or 0):
        log_event("locked_attempt")
        return None
    if not verify_code_only((code or "").strip(), data):
        data["fails"] = int(data.get("fails") or 0) + 1
        strikes = data["fails"]
        lockout = strikes >= _MAX_FAILS
        if lockout:
            lockout_count = int(data.get("lockout_count") or 0) + 1
            data["lockout_count"] = lockout_count
            # Growing lockout delay: 60s, 120s, 240s, capped at 1 hour (3600s)
            lockout_duration = min(3600, _BASE_LOCKOUT_S * (2 ** (lockout_count - 1)))
            data["locked_until"] = time.time() + lockout_duration
            data["fails"] = 0
        # state first, log last: _save writes the pre-log snapshot, so a
        # log_event before it would be clobbered (read-modify-write order).
        _save(data)
        if lockout:
            log_event("lockout", f"{_MAX_FAILS} wrong codes, locked for {lockout_duration}s")
        else:
            log_event("wrong_code", f"strike {strikes}/{_MAX_FAILS}")
        return None
    data["fails"] = 0
    data["locked_until"] = 0
    data["lockout_count"] = 0
    _save(data)
    _sweep()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _TOKEN_TTL_S
    log_event("unlock")
    return token


def check(token: str) -> bool:
    _sweep()
    exp = _sessions.get(token or "")
    if exp and exp > time.time():
        # Rolling activity auto-lock timeout: refresh activity window on use
        _sessions[token] = time.time() + _TOKEN_TTL_S
        return True
    return False


def lock(token: str) -> None:
    if token and token in _sessions:
        log_event("lock")
    _sessions.pop(token or "", None)


def ttl(token: str) -> int:
    return max(0, int((_sessions.get(token) or 0) - time.time()))


# ── key enumeration (the only consumer of the secret getters) ─────────


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••"
    return f"{secret[:4]}…{secret[-2:]}"


def _key_source(env_var: str, vault_key: str) -> str:
    if os.environ.get(env_var):
        return "env"
    if get_vault_secret(vault_key):
        return "vault"
    return "config"


def _provider_source() -> str:
    return _key_source("AI_PROVIDER_KEY", "ai_provider_key")


# ── activity log (the owner's "who touched my keys" answer) ──────────

_LOG_MAX = 50


def log_event(kind: str, detail: str = "") -> None:
    """Append one vault event to the on-disk ring. Never raises."""
    try:
        data = _load()
        log = data.get("log") or []
        log.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
                    "detail": detail[:80]})
        data["log"] = log[-_LOG_MAX:]
        _save(data)
    except Exception:
        pass  # telemetry can never break the vault


def activity() -> list[dict]:
    """Newest-first event log (token-gated by the caller in api.py)."""
    log = _load().get("log") or []
    return list(reversed(log))[:_LOG_MAX]


def entries() -> list[dict]:
    """Everything the vault shows. Masked previews ONLY — never full values."""
    from agents import config
    rows = [
        {"id": "gemini_api_key", "label": "Gemini API key",
         "secret": config.get_gemini_key(), "source": _key_source("GEMINI_API_KEY", "gemini_api_key")},
        {"id": "ai_provider_key", "label": "AI provider key (OpenCode/Vercel/Groq)",
         "secret": config.get_ai_provider_key(), "source": _provider_source()},
        {"id": "gmail_app_password", "label": "Gmail app password",
         "secret": config.get_gmail_app_password(), "source": _key_source("GMAIL_APP_PASSWORD", "gmail_app_password")},
        {"id": "gmail_user", "label": "Gmail account", "secret": "", "source": ""},
    ]
    out = []
    for r in rows:
        if r["id"] == "gmail_user":
            out.append({"id": r["id"], "label": r["label"],
                        "kind": "info",
                        "value": config.get_gmail_user()})
            continue
        sec = r.pop("secret") or ""
        out.append({"id": r["id"], "label": r["label"], "kind": "secret",
                    "set": bool(sec), "masked": _mask(sec),
                    "source": r["source"]})
    return out


def reveal(entry_id: str) -> str | None:
    """Full secret for one entry — called only with a valid session token."""
    from agents import config
    getters = {
        "gemini_api_key": config.get_gemini_key,
        "ai_provider_key": config.get_ai_provider_key,
        "gmail_app_password": config.get_gmail_app_password,
        "gmail_user": config.get_gmail_user,
    }
    getter = getters.get(entry_id)
    if getter:
        log_event("reveal", entry_id)
        return getter() or ""
    return None


def vault_file_path() -> Path:
    return _VAULT_PATH
