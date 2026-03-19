"""Database-backed event logger.

Keeps the same public interface as the old file-based Logger so no call sites
need signature changes.  All methods are synchronous; they schedule a
fire-and-forget asyncio task to write to the ``events`` table.

Critical operational errors are also written to ``logs/errors.jsonl`` as a
fallback in case the DB is unreachable.

Message persistence (the research data that matters most) is handled with
awaited writes in ``chatroom.py`` / ``agent_manager.py`` via
``message_repo.insert_message()`` — NOT through this logger.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Logger:
    """Logs simulation events to the database events table (fire-and-forget).

    Constructor parameters
    ----------------------
    session_id : str
        UUID of the owning session.
    experiment_id : str
        Experiment tag (e.g. ``"pilot_2026_03"``).
    """

    def __init__(self, session_id: str, experiment_id: str = "default") -> None:
        self.session_id = session_id
        self.experiment_id = experiment_id

        # Fallback file for critical operational errors only.
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        self._error_log = log_dir / "errors.jsonl"

        # Track pending fire-and-forget tasks so drain() can await them.
        self._pending_tasks: set = set()

    # ── Public interface ──────────────────────────────────────────────────────

    def log_event(self, event_type: str, data: Any) -> None:
        """Fire-and-forget: insert an event row into the DB."""
        self._schedule(event_type, data)

    def log_session_start(
        self,
        experimental_config: dict,
        simulation_config: dict,
        treatment_group: str,
        *,
        chatroom_context: str = "",
        incivility_framework: str = "",
    ) -> None:
        self.log_event("session_start", {
            "treatment_group": treatment_group,
            "experiment_id": self.experiment_id,
            "chatroom_context": chatroom_context,
            "incivility_framework": incivility_framework,
            "experimental_config": experimental_config,
            "simulation_config": simulation_config,
        })

    def log_session_end(self, reason: str = "completed") -> None:
        self.log_event("session_end", {"reason": reason})
        # HTML report is now generated on-demand via GET /session/{id}/report

    def log_message(self, message: dict) -> None:
        """Log a message event (supplements message_repo.insert_message)."""
        self.log_event("message", message)

    def log_llm_call(
        self,
        agent_name: str,
        prompt: str,
        response: str,
        error: Optional[str] = None,
    ) -> None:
        self.log_event("llm_call", {
            "agent_name": agent_name,
            "prompt": prompt,
            "response": response,
            "error": error,
        })

    def log_error(
        self,
        error_type: str,
        error_message: str,
        context: Optional[dict] = None,
    ) -> None:
        data = {
            "error_type": error_type,
            "error_message": error_message,
            "context": context or {},
        }
        self.log_event("error", data)
        # Also write to the fallback error file so operational issues are
        # visible even if the DB is unavailable.
        self._write_error_fallback(error_type, error_message, context)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _schedule(self, event_type: str, data: Any) -> None:
        """Schedule an async DB insert without blocking the caller."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._async_insert(event_type, data))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            # No running event loop (e.g. called from a sync test context).
            # Fall through silently — tests that care about events should use
            # awaited repo calls directly.
            pass

    async def drain(self) -> None:
        """Await all pending log tasks (call during session shutdown to prevent data loss)."""
        if self._pending_tasks:
            await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)

    async def _async_insert(self, event_type: str, data: Any) -> None:
        """Perform the actual DB insert (runs as a background task)."""
        try:
            from db.connection import get_pool
            from db.repositories.event_repo import insert_event
            await insert_event(
                get_pool(),
                session_id=self.session_id,
                experiment_id=self.experiment_id,
                event_type=event_type,
                data=data,
            )
        except Exception as exc:
            # Last-resort stderr output; never raise from a background task.
            print(
                f"[Logger] DB insert failed for event '{event_type}': {exc}",
                file=sys.stderr,
            )

    def _write_error_fallback(
        self,
        error_type: str,
        error_message: str,
        context: Optional[dict],
    ) -> None:
        """Append to the local errors.jsonl fallback file."""
        try:
            entry = json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": self.session_id,
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {},
            })
            with open(self._error_log, "a") as fh:
                fh.write(entry + "\n")
        except Exception:
            pass  # Don't let logging errors crash the application.
