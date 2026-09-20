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
import sys
from pathlib import Path

# Ensure agents package is importable
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agents.web import api, ws

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="JARVIS", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api.router)
app.include_router(ws.router)


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the JARVIS web server."""
    import uvicorn
    print(f"\n  JARVIS Web Server starting on http://{host}:{port}")
    print(f"  Open your browser to start chatting!\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
