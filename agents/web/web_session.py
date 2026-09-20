"""The one Session the web layer works on.

The web UI and the CLI are meant to operate on the same data, so the web
layer keeps a single shared ``Session`` and points it at the newest session
on disk rather than creating its own. That ownership used to be spread across
``server.py`` (an API route, the review flow and the socket loop each called
into it); it lives here now, so "which session is the office working on?" has
exactly one answer, in one place.
"""

from datetime import datetime

_session = None


def current():
    """The shared Session instance, created on first use."""
    global _session
    from agents.session import Session
    if _session is None:
        _session = Session()
    return _session


def resume_latest():
    """Point the shared session at the newest session on disk.

    Creates one if nothing exists yet. Called at the start of each chat turn
    so a session started in the CLI shows up in the browser without a reload.
    """
    from agents.session import list_sessions
    s = current()
    sessions = list_sessions()
    if sessions:
        latest = sessions[0]
        if s.id != latest["id"]:
            s.load(latest["id"], latest)
    elif not s.active:
        s.create(f"Web Project {datetime.now().strftime('%Y%m%d_%H%M%S')}")
    return s
