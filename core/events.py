"""In-process pub/sub. Core publishes every state change; the UI (SSE/WS) and agents subscribe.

Thread-safe publish (service code runs in FastAPI's threadpool), asyncio delivery.
A small ring buffer lets a reconnecting client catch up with `?since=<id>`.
"""
from __future__ import annotations

import asyncio
import itertools
import threading
from collections import deque
from typing import Any

from .models import now_iso


class EventBus:
    def __init__(self, history: int = 2000):
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._history: deque[dict[str, Any]] = deque(maxlen=history)

    def publish(self, topic: str, order_id: str | None = None, /, **data: Any) -> dict[str, Any]:
        evt = {"id": next(self._ids), "kind": topic, "order_id": order_id, "at": now_iso(), "data": data}
        with self._lock:
            self._history.append(evt)
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, evt)
            except RuntimeError:  # loop closed
                with self._lock:
                    self._subs.discard((loop, q))
        return evt

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        with self._lock:
            self._subs.add((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {(l, qq) for (l, qq) in self._subs if qq is not q}

    def since(self, last_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._history if e["id"] > last_id]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


bus = EventBus()
