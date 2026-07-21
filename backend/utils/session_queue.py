"""In-memory session queue for cap enforcement.

When concurrent active sessions reach SESSION_CAP, arriving participants
are placed in a FIFO queue keyed by their token. The token is NOT consumed
while queued; it is consumed only when the participant claims a slot via
the normal POST /session/start path.

The queue is passive (polled by the frontend every 30 s). A periodic
reaper evicts entries that haven't polled within QUEUE_TTL_SECONDS.
Entries whose slot has been offered but not claimed within
`offer_timeout_seconds` (QUEUE_OFFER_TIMEOUT_MINUTES env var,
default 10 minutes) are rotated to the back to prevent starvation.

Single-worker, single-event-loop; all methods are synchronous (no awaits
inside queue operations, so no lock is needed).
"""

from __future__ import annotations

import math
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

QUEUE_TTL_SECONDS = 300


@dataclass
class QueueEntry:
    token: str
    joined_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    offered_at: Optional[float] = None


class SessionQueue:
    _instance: Optional["SessionQueue"] = None

    def __init__(self, cap: int = 50, offer_timeout_seconds: int = 600) -> None:
        self.cap = cap
        self.offer_timeout_seconds = offer_timeout_seconds
        self._queue: OrderedDict[str, QueueEntry] = OrderedDict()
        self._inflight: int = 0

    @classmethod
    def get(cls) -> "SessionQueue":
        if cls._instance is None:
            cls._instance = SessionQueue()
        return cls._instance

    def _active_count(self) -> int:
        from utils.session_manager import session_manager
        running = sum(1 for s in session_manager._sessions.values() if s.running)
        now = time.monotonic()
        pending = sum(
            1 for info in session_manager._pending.values()
            if now - info.get("_reserved_at", now) < 120
        )
        return running + pending

    def has_capacity(self) -> int:
        return self.cap - self._active_count() - self._inflight

    def position(self, token: str) -> int:
        for i, key in enumerate(self._queue, 1):
            if key == token:
                return i
        return 0

    def enqueue(self, token: str) -> tuple[int, int]:
        """Add a token to the queue or refresh an existing entry.

        Returns (position, estimated_wait_minutes).
        """
        if token in self._queue:
            self._queue[token].last_seen = time.monotonic()
        else:
            self._queue[token] = QueueEntry(token=token)

        pos = self.position(token)
        wait = self._estimate_wait(pos)
        return pos, wait

    def check_status(self, token: str) -> Optional[dict]:
        """Poll status for a queued token. Returns None if not in queue."""
        entry = self._queue.get(token)
        if entry is None:
            return None

        entry.last_seen = time.monotonic()
        pos = self.position(token)
        free = self.has_capacity()
        slot_available = pos <= free and free > 0

        if slot_available and entry.offered_at is None:
            entry.offered_at = time.monotonic()
        elif not slot_available:
            entry.offered_at = None

        return {
            "position": pos,
            "estimated_wait_minutes": self._estimate_wait(pos),
            "slot_available": slot_available,
        }

    def remove(self, token: str) -> None:
        self._queue.pop(token, None)

    def is_empty(self) -> bool:
        return len(self._queue) == 0

    def admits_newcomer(self) -> bool:
        """Whether a newcomer (not in the queue) may start directly."""
        free = self.has_capacity()
        return free > 0 and (self.is_empty() or free > len(self._queue))

    def admits_token(self, token: str) -> bool:
        """Whether a specific token (possibly queued) may start."""
        free = self.has_capacity()
        if free <= 0:
            return False
        if token in self._queue:
            return self.position(token) <= free
        return self.admits_newcomer()

    def _estimate_wait(self, position: int) -> int:
        from utils.session_manager import session_manager
        now = datetime.now(timezone.utc)

        end_times = []
        for session in session_manager._sessions.values():
            if not session.running:
                continue
            started = getattr(session.state, "start_time", None)
            duration = getattr(session.state, "duration_minutes", 20)
            if started:
                # Paused time extends the wall-clock end (the countdown is
                # frozen while the participant is disconnected).
                paused = getattr(session.state, "paused_seconds", 0.0)
                pause_started = getattr(session, "_pause_started_monotonic", None)
                if pause_started is not None:
                    paused += time.monotonic() - pause_started
                projected = started + timedelta(minutes=duration, seconds=paused)
                end_times.append(projected)

        if not end_times:
            return 1

        end_times.sort()
        idx = min(position - 1, len(end_times) - 1)
        wait_seconds = max(0, (end_times[idx] - now).total_seconds())
        return max(1, math.ceil(wait_seconds / 60))

    def reap_stale(self) -> int:
        """Evict entries that haven't polled in QUEUE_TTL_SECONDS, and
        rotate offers that haven't been claimed in OFFER_TTL_SECONDS."""
        now = time.monotonic()
        expired = [t for t, e in self._queue.items()
                   if now - e.last_seen > QUEUE_TTL_SECONDS]
        for t in expired:
            del self._queue[t]

        rotate = [t for t, e in self._queue.items()
                  if e.offered_at is not None
                  and now - e.offered_at > self.offer_timeout_seconds]
        for t in rotate:
            entry = self._queue.pop(t)
            entry.offered_at = None
            self._queue[t] = entry

        return len(expired)


session_queue = SessionQueue.get()
