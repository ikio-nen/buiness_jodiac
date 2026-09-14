"""Event bus -- live telemetry from every agent, bot and workflow.

A tiny thread-safe pub/sub. Workflow code running in worker threads
(asyncio.to_thread) publishes events like:

    emit("bot", bot="scout", status="running", task="Researching X")
    emit("bot", bot="strategist", status="done", task="Wrote hook")
    emit("packet", from_="search", to="brain", label="47 businesses")
    emit("brain", action="learn", detail="Saved intel on Don Bosco")
    emit("step", phase="draft", message="Drafted 3 emails", done=False)

The web server subscribes and pushes them to the browser, where the
Agent Ops floor animates little bots walking between stations.

CLI mode is unaffected: if nobody subscribes, events just pile into a
small ring buffer and cost nothing.
"""
import threading
import time
from collections import deque
from typing import Callable

_lock = threading.Lock()
_subscribers: list[Callable[[dict], None]] = []
_history: deque = deque(maxlen=300)

VALID_KINDS = {"bot", "packet", "brain", "step", "team"}


def emit(kind: str, **data):
    """Publish an event. Never raises -- telemetry must not break work."""
    if kind not in VALID_KINDS:
        return
    event = {"kind": kind, "ts": time.time(), **data}
    with _lock:
        _history.append(event)
        subs = list(_subscribers)
    for cb in subs:
        try:
            cb(event)
        except Exception:
            pass


def subscribe(callback: Callable[[dict], None]) -> None:
    """Register a callback for live events. Returns an unsubscribe fn."""
    def _wrap(event: dict):
        callback(event)
    with _lock:
        _subscribers.append(callback)

    def unsubscribe():
        with _lock:
            try:
                _subscribers.remove(callback)
            except ValueError:
                pass
    return unsubscribe


def recent(limit: int = 100) -> list[dict]:
    """Last N events (oldest first) for late-joining clients."""
    with _lock:
        return list(_history)[-limit:]


def clear_history():
    with _lock:
        _history.clear()
