from datetime import datetime, timezone

from agents.STAGE.orchestrator import Orchestrator, TurnResult
from db import connection as db_conn
from db.repositories import message_repo
from cache import redis_client


class AgentManager:
    """Bridges the simulation loop and the STAGE framework orchestrator.

    Responsibilities:
    - persist agent messages to DB (awaited)
    - broadcast messages via Redis pub/sub (decoupled from WebSocket)
    - handle like actions (DB + broadcast)
    """

    def __init__(
        self,
        state,
        orchestrator: Orchestrator,
        logger,
        session_id: str,
        experiment_id: str = "default",
    ) -> None:
        self.state = state
        self.orchestrator = orchestrator
        self.logger = logger
        self.session_id = session_id
        self.experiment_id = experiment_id

    async def _handle_message(self, result: TurnResult) -> None:
        """Persist and broadcast a generated agent message."""
        message = result.message
        if not message:
            return

        # Add to in-memory state (for context window and message lookup).
        self.state.add_message(message)

        # Persist to DB (awaited — agent messages are primary research data).
        metadata = dict(message.metadata or {})
        metadata.update({
            "is_incivil": message.is_incivil,
            "is_like_minded": message.is_like_minded,
            "inferred_participant_stance": message.inferred_participant_stance,
            "classification_rationale": message.classification_rationale,
        })
        try:
            pool = db_conn.get_pool()
            await message_repo.insert_message(
                pool,
                message_id=message.message_id,
                session_id=self.session_id,
                experiment_id=self.experiment_id,
                sender=message.sender,
                content=message.content,
                sent_at=message.timestamp,
                reply_to=message.reply_to,
                quoted_text=message.quoted_text,
                mentions=message.mentions,
                is_incivil=message.is_incivil,
                is_like_minded=message.is_like_minded,
                inferred_participant_stance=message.inferred_participant_stance,
                classification_rationale=message.classification_rationale,
                metadata=metadata,
            )
        except Exception as exc:
            self.logger.log_error("persist_agent_message", str(exc))

        # Push to Redis context window.
        try:
            r = redis_client.get_redis()
            await redis_client.push_to_window(r, self.session_id, message.to_dict())
        except Exception as exc:
            self.logger.log_error("push_agent_message_window", str(exc))

        # Log the message event (fire-and-forget to events table).
        self.logger.log_message(message.to_dict())

        # Publish via Redis pub/sub — the subscriber loop in SimulationSession
        # will deliver this to the connected WebSocket.
        try:
            r = redis_client.get_redis()
            await redis_client.publish_event(r, self.session_id, message.to_dict())
        except Exception as exc:
            self.logger.log_error("publish_agent_message", str(exc))

    async def _handle_like(self, result: TurnResult) -> None:
        """Process an agent 'like' action — update DB and broadcast."""
        target_id = result.target_message_id
        agent_name = result.agent_name
        if not target_id:
            return

        target_msg = next(
            (m for m in self.state.messages if m.message_id == target_id),
            None,
        )
        if not target_msg:
            self.logger.log_error("like_action", f"Target message {target_id} not found")
            return

        target_msg.toggle_like(agent_name)

        # Persist updated likes to DB.
        try:
            pool = db_conn.get_pool()
            await message_repo.update_message_likes(
                pool, target_id, list(target_msg.liked_by)
            )
        except Exception as exc:
            self.logger.log_error("persist_like", str(exc))

        # Log the like event.
        self.logger.log_event("agent_like", {
            "agent_name": agent_name,
            "message_id": target_id,
            "likes_count": target_msg.likes_count,
        })

        # Broadcast via Redis pub/sub.
        like_event = {
            "event_type": "message_like",
            "message_id": target_id,
            "action": "liked",
            "likes_count": target_msg.likes_count,
            "liked_by": list(target_msg.liked_by),
            "user": agent_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            r = redis_client.get_redis()
            await redis_client.publish_event(r, self.session_id, like_event)
        except Exception as exc:
            self.logger.log_error("publish_like", str(exc))
