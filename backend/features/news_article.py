"""Feature: seed a news article at session start.

The experimental config for a treatment group should include a seed block::

    "seed": {
        "type": "news_article",
        "headline": "...",
        "source": "...",
        "body": "..."
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from models.message import Message
from features.base import BaseFeature

if TYPE_CHECKING:
    from models.session import SessionState


class NewsArticleSeed(BaseFeature):
    """Inject a news article message at the top of the chat log."""

    async def seed(self, state: SessionState, websocket_send: Callable, experiment_id: str = "default") -> None:
        seed_cfg = self.config.get("seed", {})
        headline = seed_cfg.get("headline", "")
        source = seed_cfg.get("source", "")
        body = seed_cfg.get("body", "")

        if not (headline and body):
            return

        content = headline
        if source:
            content += f" ({source})"
        content += f" — {body}"

        message = Message.create(sender="[news]", content=content)
        message.metadata = {
            "msg_type": "news_article",
            "headline": headline,
            "source": source,
            "body": body,
        }
        state.add_message(message)

        # Save to database
        try:
            from db import connection as db_conn
            from db.repositories import message_repo
            pool = db_conn.get_pool()
            await message_repo.insert_message(
                pool,
                message_id=message.message_id,
                session_id=state.session_id,
                experiment_id=experiment_id,
                sender=message.sender,
                content=message.content,
                sent_at=message.timestamp,
                metadata=message.metadata,
            )
        except Exception as exc:
            print(f"Failed to persist seed news article: {exc}")

        await websocket_send(message.to_dict())
