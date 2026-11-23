"""JARVIS Web Server -- FastAPI with WebSocket for real-time chat.

Run with:  python -m agents.web.server
Or from jarvis.py menu option [W].

This module is assembly, not behavior: it builds the app, mounts the static
assets, includes the HTTP API and the socket, and starts uvicorn. The pieces
that actually do the work live next to it:

    api.py              the HTTP surface (document, session, history, brain,
                        roster, hiring, events, skills)
    ws.py               the live socket: message routing for one browser
    job_queue.py        the per-socket queue of action chains (QUEUE panel)
    dispatch_bridge.py  parsed action -> action_dispatch -> UI frames
    review.py           interactive email review state machine
    web_session.py      the one shared Session the web layer works on

Each owns its state outright, so a change lands in one file. The WebSocket and
the CLI both execute actions through agents.action_dispatch, which is what
keeps their behavior identical.
"""
import logging
import mimetypes
import re
import sys
from pathlib import Path

# Ensure agents package is importable
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class RedactQueryTokenFilter(logging.Filter):
    """Filter that strips secret tokens from query strings in server/access logs."""
    _TOKEN_RE = re.compile(r"([?&]token=)[^&\s'\"]+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._TOKEN_RE.sub(r"\1[REDACTED]", record.msg)
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(self._TOKEN_RE.sub(r"\1[REDACTED]", arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True

# Attach redact filter to all uvicorn and app loggers
_redact_filter = RedactQueryTokenFilter()
for _log_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "agents"):
    logging.getLogger(_log_name).addFilter(_redact_filter)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agents.config import map_tile_config
from agents.web import api, ws
from agents.web.auth import (SESSION_COOKIE, get_launch_auth_token,
                             request_token, verify_auth_token)

STATIC_DIR = Path(__file__).parent / "static"

ALLOWED_ORIGINS = {
    "http://127.0.0.1:8765",
    "http://localhost:8765",
}
ALLOWED_HOSTS = {
    "127.0.0.1:8765",
    "localhost:8765",
    "127.0.0.1",
    "localhost",
    "testserver",
}

# Sensitive read paths that require auth token
SENSITIVE_READ_PREFIXES = (
    "/api/status",
    "/api/history",
    "/api/conversation",
    "/api/brain",
    "/api/campaign",
    "/api/vault",
    "/api/report",
    "/api/events",
    "/api/agents",
    "/api/skills",
    "/api/goals",
)

app = FastAPI(title="JARVIS", docs_url=None, redoc_url=None)

# The two paths that serve the app document. The launch exchange happens here
# and nowhere else.
INDEX_PATHS = ("/", "/index.html")


def _harden(response, origin: str | None):
    """Security headers on every response, early returns included."""
    # The location map's tile host is configurable (MAP_TILE_URL), so the CSP
    # follows it. Images only: still no third-party script, no geolocation
    # permission, and no widening of connect-src.
    tile_origin = map_tile_config()["origin"]
    img_src = "'self' data: blob:" + (f" {tile_origin}" if tile_origin else "")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        f"img-src {img_src}; "
        "connect-src 'self' ws://127.0.0.1:8765 ws://localhost:8765;"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-JARVIS-Token, X-Requested-With"
    return response


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # 1. Validate Host header to protect against DNS rebinding
    host = request.headers.get("host", "").split(",")[0].strip()
    if host and host not in ALLOWED_HOSTS:
        return _harden(JSONResponse(status_code=403,
                                    content={"error": f"Invalid Host: {host}"}),
                       request.headers.get("origin"))

    # 2. Validate Origin header on cross-origin requests
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return _harden(JSONResponse(status_code=403,
                                    content={"error": f"Cross-origin request rejected: {origin}"}),
                       origin)

    path = request.url.path
    method = request.method.upper()

    # 3. The launch URL: the one moment the token is allowed to travel in a
    # URL. It is exchanged for an HttpOnly SameSite=Strict cookie and the
    # browser is sent to the bare path, so the document that follows — and
    # every script allowed to run in it — never holds the credential.
    if path in INDEX_PATHS and "token" in request.query_params:
        supplied = request.query_params.get("token", "")
        if not verify_auth_token(supplied):
            return _harden(JSONResponse(status_code=403,
                                        content={"error": "Invalid launch token"}),
                           origin)
        redirect = RedirectResponse(url="/", status_code=302)
        redirect.set_cookie(
            SESSION_COOKIE, supplied,
            httponly=True,      # no script access, ever
            samesite="strict",  # not sent cross-site (CSRF)
            path="/",
            secure=False,       # loopback http; a wss deployment needs True
        )
        redirect.headers["Cache-Control"] = "no-store"
        return _harden(redirect, origin)

    # 4. Public paths: the document (gated by the cookie inside api.index),
    # static assets, favicon. Everything else on a mutating verb or a sensitive
    # read needs a valid token from a header, a Bearer pair or the cookie.
    is_public = (
        path in INDEX_PATHS
        or path == "/favicon.ico"
        or path.startswith("/static/")
    )

    if not is_public and method != "OPTIONS":
        requires_auth = (
            method in ("POST", "PUT", "PATCH", "DELETE")
            or any(path.startswith(prefix) for prefix in SENSITIVE_READ_PREFIXES)
        )
        if requires_auth and not request_token(request.headers, request.cookies):
            return _harden(JSONResponse(status_code=401,
                                        content={"error": "Unauthorized: valid auth token required"}),
                           origin)

    response = await call_next(request)
    return _harden(response, origin)

# The typefaces are self-hosted. Python's mimetypes has no .woff2 entry, so
# StaticFiles would serve them as application/octet-stream, which some browsers
# reject for fonts.
mimetypes.add_type("font/woff2", ".woff2")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api.router)
app.include_router(ws.router)


def launch_url(host: str = "127.0.0.1", port: int = 8765) -> str:
    """The one-time URL that exchanges the launch token for a cookie."""
    return f"http://{host}:{port}/?token={get_launch_auth_token()}"


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the JARVIS web server."""
    import uvicorn
    print(f"\n  JARVIS Web Server starting on http://{host}:{port}")
    print("  Open this launch URL once (it locks the office to your browser):")
    print(f"  {launch_url(host, port)}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    start_server()
