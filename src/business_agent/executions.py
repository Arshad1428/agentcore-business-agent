"""Execution management: bounded session cache + execution records.

In-memory and per-process (a Runtime microVM session). Good enough to track and
inspect runs; use DynamoDB / AgentCore Memory if you need persistence across sessions.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable


class SessionCache:
    """One agent (conversation) per session id, with LRU eviction and idle TTL."""

    def __init__(self, factory: Callable[[], Any], max_sessions: int = 100,
                 ttl_seconds: int = 1800, clock: Callable[[], float] = time.monotonic):
        self._factory, self._max, self._ttl, self._clock = factory, max_sessions, ttl_seconds, clock
        self._items: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str):
        with self._lock:
            now = self._clock()
            self._evict_expired(now)
            if session_id in self._items:
                agent, _ = self._items.pop(session_id)
            else:
                agent = self._factory()
            self._items[session_id] = (agent, now)  # most recently used goes last
            while len(self._items) > self._max:
                self._items.popitem(last=False)
            return agent

    def _evict_expired(self, now: float) -> None:
        for sid in [s for s, (_, seen) in self._items.items() if now - seen > self._ttl]:
            del self._items[sid]

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._items


class ExecutionStore:
    """Bounded log of executions (agent runs and workflow runs) with status."""

    def __init__(self, max_records: int = 500):
        self._max = max_records
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def start(self, kind: str, session_id: str, name: str | None = None) -> str:
        eid = f"exe-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._items[eid] = {
                "execution_id": eid, "kind": kind, "name": name, "session_id": session_id,
                "status": "running", "started_at": time.time(), "finished_at": None,
            }
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return eid

    def finish(self, eid: str, status: str, **details: Any) -> None:
        with self._lock:
            rec = self._items.get(eid)
            if rec is not None:
                rec.update(status=status, finished_at=time.time(), **details)

    def get(self, eid: str) -> dict | None:
        with self._lock:
            rec = self._items.get(eid)
            return dict(rec) if rec else None

    def list(self, session_id: str | None = None, limit: int = 20) -> list[dict]:
        with self._lock:
            recs = [dict(r) for r in self._items.values() if session_id in (None, r["session_id"])]
        return recs[-limit:][::-1]  # newest first
