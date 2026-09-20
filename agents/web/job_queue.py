"""The per-socket queue of action chains — what the QUEUE panel shows.

One list per WebSocket, mirroring its dispatch gate: the first chain runs, the
rest wait, and the client can cancel a waiting one. Nothing about this is
decorative — the list *is* the real pending work, which is why cancel has to
mean something here and nowhere else.

Owned here: the item list, the ids, the status transitions, the strong
references that keep fire-and-forget chains alive, and the queue_state frames
that keep the panel honest. The work itself is supplied by the socket loop.
"""

import asyncio

# Labels of chains actually running right now, across every socket. A reload
# closes the old socket while its work keeps going, so the new socket's
# welcome needs this to say "work is still in flight" instead of showing an
# empty queue and looking as if the job vanished.
_running: dict = {}


def running_labels() -> list:
    """What is executing right now, for a freshly connected socket to report."""
    return list(_running.keys())


class JobQueue:
    """Serializes action chains for one socket and reports their state."""

    def __init__(self, send, on_error=None):
        self._send = send              # async callable: frame dict -> None
        self._on_error = on_error      # async callable: Exception -> None
        self._items: list[dict] = []
        self._seq = 0
        # The gate the rest of the socket checks before claiming to be busy.
        self.gate = asyncio.Lock()
        # Strong refs to the chain tasks: the event loop keeps only weak
        # references, so an unreferenced long-running chain can be garbage
        # collected mid-run and silently vanish.
        self._tasks: set = set()

    def busy(self) -> bool:
        """True while a chain holds the gate."""
        return self.gate.locked()

    async def push_state(self) -> None:
        """Publish the current queue so the panel renders real work."""
        try:
            await self._send({
                "type": "queue_state",
                "items": [{"id": it["id"], "label": it["label"],
                           "status": it["status"]} for it in self._items],
            })
        except Exception:
            pass

    def enqueue(self, label: str, work) -> dict:
        """Add a chain of work behind the gate and return its item.

        ``work`` is a zero-argument async callable run while holding the gate.
        An item is ``queued`` when another chain is running and ``running``
        otherwise — the same condition the panel's cancel button keys off.
        """
        self._seq += 1
        item = {"id": self._seq, "label": label,
                "status": "queued" if self.busy() else "running", "task": None}
        self._items.append(item)

        async def _run():
            async with self.gate:
                item["status"] = "running"
                _running[item["label"]] = item["id"]
                await self.push_state()
                try:
                    await work()
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    if self._on_error is not None:
                        await self._on_error(e)
                finally:
                    _running.pop(item["label"], None)
                    if item in self._items:
                        self._items.remove(item)
                    await self.push_state()

        task = asyncio.create_task(_run())
        item["task"] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return item

    def cancel(self, item_id) -> dict | None:
        """Cancel a *waiting* item; return it, or None if it already started.

        Only a queued item can be cancelled. A job that has already begun is
        not this method's business — the caller reports that to the user
        rather than the click silently doing nothing.
        """
        for it in list(self._items):
            if it["id"] == item_id and it["status"] == "queued":
                if it.get("task"):
                    it["task"].cancel()
                self._items.remove(it)
                return it
        return None
