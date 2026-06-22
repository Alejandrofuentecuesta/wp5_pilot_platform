"""Base feature defining the hook interface for experiment-specific behaviour.

A feature customises one aspect of session lifecycle without modifying the
core platform.  Subclasses override one or both hooks; the defaults are
no-ops so combining features that only implement one hook is safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from models.session import SessionState


class BaseFeature:
    """No-op feature — does nothing.  Subclass and override hooks."""

    def __init__(self, config: dict):
        """Receive the experimental_config dict for this treatment group."""
        self.config = config

    async def seed(self, state: SessionState, websocket_send: Callable, experiment_id: str = "default") -> None:
        """Inject content at session start, before the clock loop launches.

        Called once per session.  Default: no-op.
        """

    def agents_active(self, state: SessionState) -> bool:
        """Return True when agents should be allowed to act.

        Called on every tick of the clock loop.  Default: always True.
        """
        return True
