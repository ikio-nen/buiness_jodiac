"""Per-launch auth token for local API and WebSocket protection.

Generates a cryptographically strong, random token at server launch.
Requires this token for:
- All mutating endpoints (POST, PATCH, DELETE)
- WebSocket connection (/ws)
- Sensitive read endpoints (/api/status, /api/history, /api/brain, /api/campaign, /api/vault/*, /api/report/*)

The browser never reads the token. It arrives once in the launch URL, leaves
as an HttpOnly SameSite=Strict cookie, and every later request — fetch or the
WebSocket handshake — carries it automatically.
"""
import hmac
import secrets

# Generated once per process startup
_AUTH_TOKEN = secrets.token_urlsafe(32)

#: Name of the launch cookie. Deliberately not a JS-readable name: HttpOnly
#: is what keeps an XSS from turning into full API authority.
SESSION_COOKIE = "jarvis_session"


def get_launch_auth_token() -> str:
    """Return the current per-launch auth token."""
    return _AUTH_TOKEN


def verify_auth_token(provided: str) -> bool:
    """Constant-time token verification."""
    if not provided:
        return False
    return hmac.compare_digest(provided.strip(), _AUTH_TOKEN)


def request_token(headers, cookies, extra: str = "") -> str:
    """The launch token from a header, a Bearer pair, the cookie, or *extra*.

    Returns "" when none of them is valid. One place decides the order so the
    HTTP middleware and the WebSocket handler cannot disagree. A stale header
    falls through to the cookie instead of reading as unauthenticated; the
    query parameter exists for scripted clients, not for the browser.
    """
    candidates = (
        headers.get("X-JARVIS-Token") if headers else "",
        (headers.get("Authorization", "") if headers else "")
        .replace("Bearer ", "").strip(),
        (cookies or {}).get(SESSION_COOKIE, "") if cookies else "",
        extra,
    )
    for candidate in candidates:
        if candidate and verify_auth_token(candidate):
            return candidate
    return ""

