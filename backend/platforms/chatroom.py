import asyncio
import random
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from models import Message, Agent, SessionState
from utils import Logger
from utils.llm.llm_manager import LLMManager
from agents.agent_manager import AgentManager
from agents.STAGE.classifier import DEFAULT_CLASSIFIER_PROMPT_TEMPLATE
from agents.STAGE.orchestrator import Orchestrator
from features import load_features
from db import connection as db_conn
from db.repositories import session_repo, message_repo
from cache import redis_client


class SimulationSession:
    """Core platform logic for a chatroom session (STAGE framework).

    Responsibilities:
    - manages platform event loop with tick-based pacing
    - delegates all agent decisions to the Director->Performer->Moderator->Classifier pipeline
      via the Orchestrator and AgentManager
    - persists all messages to PostgreSQL and broadcasts via Redis pub/sub
    - wiring platform-level config, lifecycle and websocket attachment
    """

    def __init__(
        self,
        session_id: str,
        websocket_send: Callable,
        treatment_group: str,
        user_name: str = "participant",
        experiment_id: str = "default",
        *,
        _preloaded_messages: Optional[List[dict]] = None,
        _preloaded_blocks: Optional[dict] = None,
        _config: Optional[Dict] = None,
        _started_at: Optional[datetime] = None,
    ):
        self.session_id = session_id
        self.experiment_id = experiment_id
        self.logger = Logger(session_id, experiment_id)

        if not _config:
            raise RuntimeError(
                f"No config provided for session {session_id}. "
                "Config must be loaded from DB before creating a session."
            )

        # Unpack DB-backed config
        self.simulation_config = _config["simulation"]
        experimental_full = _config["experimental"]

        if not (isinstance(experimental_full, dict) and "groups" in experimental_full):
            raise RuntimeError("Experimental config must define a 'groups' table")
        group_map = experimental_full["groups"]
        if treatment_group not in group_map:
            raise RuntimeError(f"treatment_group '{treatment_group}' not found in experimental config groups")
        self.experimental_config = group_map[treatment_group]
        self.treatment_group = treatment_group

        self.treatment = self.experimental_config.get("treatment", "")
        if not self.treatment:
            raise RuntimeError(f"treatment_group '{treatment_group}' has no 'treatment' description")

        self.chatroom_context = experimental_full.get("chatroom_context", "")
        self.redirect_url = experimental_full.get("redirect_url", "")

        # Create LLM managers for each pipeline stage
        self.director_llm = LLMManager.from_simulation_config(self.simulation_config, role="director")
        self.performer_llm = LLMManager.from_simulation_config(self.simulation_config, role="performer")
        self.moderator_llm = LLMManager.from_simulation_config(self.simulation_config, role="moderator")
        self.classifier_llm = LLMManager.from_simulation_config(self.simulation_config, role="classifier")

        self._rng = random.Random(int(self.simulation_config["random_seed"]))

        # Initialise session state with agent personas
        agent_names = self.simulation_config["agent_names"]
        agent_personas = self.simulation_config.get("agent_personas", [])
        # Pad personas list if shorter than names
        while len(agent_personas) < len(agent_names):
            agent_personas.append("")
        agents = [Agent(name=name, persona=persona) for name, persona in zip(agent_names, agent_personas)]

        self.state = SessionState(
            session_id=session_id,
            agents=agents,
            duration_minutes=self.simulation_config["session_duration_minutes"],
            experimental_config=self.experimental_config,
            treatment_group=treatment_group,
            simulation_config=self.simulation_config,
            user_name=user_name,
        )

        # Restore original start time on reconstruction so the timer is accurate.
        if _started_at is not None:
            self.state.start_time = _started_at

        # Preload persisted messages into in-memory state (crash recovery / reconstruction).
        if _preloaded_messages:
            for m in _preloaded_messages:
                self.state.messages.append(Message(
                    sender=m["sender"],
                    content=m["content"],
                    timestamp=datetime.fromisoformat(m["timestamp"]),
                    message_id=m["message_id"],
                    reply_to=m.get("reply_to"),
                    quoted_text=m.get("quoted_text"),
                    mentions=m.get("mentions"),
                    liked_by=set(m.get("liked_by", [])),
                    reported=m.get("reported", False),
                    is_incivil=m.get("is_incivil"),
                    is_like_minded=m.get("is_like_minded"),
                    inferred_participant_stance=m.get("inferred_participant_stance"),
                    classification_rationale=m.get("classification_rationale"),
                    metadata={k: v for k, v in m.items()
                               if k not in ("sender", "content", "timestamp",
                                            "message_id", "reply_to", "quoted_text",
                                            "mentions", "liked_by", "reported",
                                            "likes_count", "is_incivil",
                                            "is_like_minded", "inferred_participant_stance",
                                            "classification_rationale")},
                ))

        # Preload agent blocks (crash recovery / reconstruction).
        if _preloaded_blocks:
            for agent_name, blocked_iso in _preloaded_blocks.items():
                self.state.block_agent(agent_name, blocked_iso)

        # Wrap provided websocket_send so we can apply per-sender blocking rules.
        # After wrapping, replace with Redis pub/sub delivery.
        self._ws_send_fn: Optional[Callable] = None
        self._subscriber_task: Optional[asyncio.Task] = None

        orchestrator = Orchestrator(
            director_llm=self.director_llm,
            performer_llm=self.performer_llm,
            moderator_llm=self.moderator_llm,
            classifier_llm=self.classifier_llm,
            state=self.state,
            logger=self.logger,
            context_window_size=int(self.simulation_config["context_window_size"]),
            chatroom_context=self.chatroom_context,
            classifier_prompt_template=self.simulation_config.get(
                "classifier_prompt_template",
                DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
            ),
            rng=self._rng,
        )

        self.features = load_features(self.experimental_config)

        # AgentManager uses publish_event (Redis) for delivery, not direct websocket.
        self.agent_manager = AgentManager(
            state=self.state,
            orchestrator=orchestrator,
            logger=self.logger,
            session_id=session_id,
            experiment_id=experiment_id,
        )

        # websocket_send kept for the blocking-wrapper logic used during attach.
        self._raw_ws_send = websocket_send or self._noop_send
        # Expose a wrapped send for callers that still need direct delivery
        # (e.g. scenario seed before pub/sub subscriber is up).
        self.websocket_send = self._wrap_send(self._raw_ws_send)

        self.clock_task: Optional[asyncio.Task] = None
        self.running = False
        self._seeded = False
        self._turn_lock = asyncio.Lock()  # serialise turns so each sees prior messages

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start a fresh session (seed scenario + launch clock loop)."""
        self.running = True
        self.logger.log_session_start(
            self.experimental_config, self.simulation_config,
            self.treatment_group, chatroom_context=self.chatroom_context,
        )

        pool = db_conn.get_pool()
        await session_repo.activate_session(
            pool,
            session_id=self.session_id,
            started_at=self.state.start_time,
            random_seed=int(self.simulation_config["random_seed"]),
            simulation_config=self.simulation_config,
            experimental_config=self.experimental_config,
        )

        await self.features.seed(self.state, self.websocket_send)
        self._seeded = True
        self.clock_task = asyncio.create_task(self._clock_loop())
        print(f"Session {self.session_id} started")

    async def resume(self) -> None:
        """Resume a reconstructed session (skip seed, restart clock loop)."""
        if self.running:
            return
        self.running = True
        self._seeded = True
        self.clock_task = asyncio.create_task(self._clock_loop())
        print(f"Session {self.session_id} resumed (crash recovery)")

    async def stop(self, reason: str = "completed") -> None:
        """Stop the session and persist end state."""
        self.running = False
        if self.clock_task:
            self.clock_task.cancel()
            try:
                await self.clock_task
            except asyncio.CancelledError:
                pass
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

        self.logger.log_session_end(reason)
        # Flush any pending fire-and-forget log tasks before closing DB connection.
        await self.logger.drain()

        try:
            pool = db_conn.get_pool()
            await session_repo.end_session(
                pool,
                session_id=self.session_id,
                reason=reason,
                ended_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            print(f"[Session {self.session_id}] DB end_session failed: {exc}")

        print(f"Session {self.session_id} stopped: {reason}")

    # ── Clock loop ────────────────────────────────────────────────────────────

    async def _clock_loop(self) -> None:
        """Main simulation loop — tick-based pacing with messages_per_minute gate.

        Turns are dispatched as background tasks so the clock keeps ticking
        while LLM calls are in flight.  A semaphore caps concurrency to
        prevent overwhelming LLM providers.
        """
        tick_interval = 1.0
        mpm = self.simulation_config["messages_per_minute"]
        post_probability = mpm / 60.0

        while self.running:
            try:
                if self.state.is_expired():
                    await self._publish_session_end("duration_expired")
                    await asyncio.sleep(0.5)  # let pub/sub deliver before teardown
                    await self.stop(reason="duration_expired")
                    break

                if not self.features.agents_active(self.state):
                    await asyncio.sleep(tick_interval)
                    continue

                if self._rng.random() < post_probability:
                    await self._guarded_turn()

                await asyncio.sleep(tick_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error("clock_loop", str(e))
                print(f"Error in clock loop: {e}")

    # Typing speed for realistic delay: ~7 chars/sec ≈ 80 WPM fast typer.
    TYPING_CHARS_PER_SECOND = 7.0
    TYPING_DELAY_MIN = 0.5   # minimum delay even for very short messages
    TYPING_DELAY_MAX = 8.0   # cap so long messages don't stall too long

    async def _guarded_turn(self) -> None:
        """Execute a single agent turn sequentially.

        Publishes typing_start/typing_stop events around the LLM pipeline
        so the frontend can show a "someone is writing..." indicator.
        After the LLM returns a message, a length-based typing delay is
        applied before the message is persisted and broadcast.
        """
        async with self._turn_lock:
            try:
                await self._publish_typing(started=True)
                result = await self.agent_manager.orchestrator.execute_turn(
                    self.treatment,
                )

                if result is None:
                    return

                # Apply realistic typing delay based on message length.
                if result.message and result.message.content:
                    delay = len(result.message.content) / self.TYPING_CHARS_PER_SECOND
                    delay = max(self.TYPING_DELAY_MIN, min(delay, self.TYPING_DELAY_MAX))
                    await asyncio.sleep(delay)

                # Delegate persistence + broadcast to AgentManager.
                if result.action_type == "like":
                    await self.agent_manager._handle_like(result)
                else:
                    await self.agent_manager._handle_message(result)
            except Exception as e:
                self.logger.log_error("guarded_turn", str(e))
            finally:
                await self._publish_typing(started=False)

    async def _publish_session_end(self, reason: str) -> None:
        """Publish a session_end event via Redis pub/sub so the frontend can redirect."""
        event = {
            "event_type": "session_end",
            "reason": reason,
            "redirect_url": self.redirect_url or "",
        }
        try:
            r = redis_client.get_redis()
            await redis_client.publish_event(r, self.session_id, event)
        except Exception as exc:
            self.logger.log_error("publish_session_end", str(exc))

    async def _publish_typing(self, *, started: bool) -> None:
        """Publish a typing indicator event via Redis pub/sub."""
        event = {
            "event_type": "typing_start" if started else "typing_stop",
        }
        try:
            r = redis_client.get_redis()
            await redis_client.publish_event(r, self.session_id, event)
        except Exception as exc:
            self.logger.log_error("publish_typing", str(exc))

    # ── User message handling ─────────────────────────────────────────────────

    async def handle_user_message(
        self,
        content: str,
        reply_to: Optional[str] = None,
        quoted_text: Optional[str] = None,
        mentions: Optional[list] = None,
    ) -> None:
        """Handle an incoming user message — persist to DB and broadcast."""
        message = Message.create(
            sender=self.state.user_name,
            content=content,
            reply_to=reply_to,
            quoted_text=quoted_text,
            mentions=mentions,
        )
        self.state.add_message(message)

        # Persist to DB (awaited — user messages are primary research data).
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
                metadata=message.metadata,
            )
        except Exception as exc:
            self.logger.log_error("persist_user_message", str(exc))

        # Push to Redis context window.
        try:
            r = redis_client.get_redis()
            await redis_client.push_to_window(r, self.session_id, message.to_dict())
        except Exception as exc:
            self.logger.log_error("push_user_message_window", str(exc))

        self.logger.log_message(message.to_dict())

        # Publish via Redis so the pub/sub loop delivers it to the WebSocket.
        try:
            r = redis_client.get_redis()
            await redis_client.publish_event(r, self.session_id, message.to_dict())
        except Exception as exc:
            self.logger.log_error("publish_user_message", str(exc))
            # Fall back to direct send if Redis publish fails.
            try:
                await self.websocket_send(message.to_dict())
            except Exception as send_exc:
                self.logger.log_error("fallback_send_user_message", str(send_exc))

    # ── WebSocket attachment / detachment ─────────────────────────────────────

    async def attach_websocket(self, websocket_send: Callable) -> None:
        """Attach (or re-attach) a WebSocket and replay missed messages.

        Messages are replayed from the DB so reconnects to a different worker
        (or after a crash) get the full history.
        """
        self._raw_ws_send = websocket_send
        self.websocket_send = self._wrap_send(websocket_send)

        # Cancel previous subscriber task if any.
        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

        # Replay messages from DB (covers cross-worker reconnect).
        try:
            pool = db_conn.get_pool()
            past_messages = await message_repo.get_session_messages(pool, self.session_id)
            replayed = 0
            for m in past_messages:
                try:
                    await self.websocket_send(m)
                    replayed += 1
                except Exception as exc:
                    self.logger.log_error("replay_single_message", str(exc))
                    continue
        except Exception as exc:
            self.logger.log_error("replay_messages", str(exc))
            replayed = 0

        self.logger.log_event("websocket_attach", {"replayed_messages": replayed})

        # Start the pub/sub subscriber task for future messages.
        self._ws_send_fn = self.websocket_send
        self._subscriber_task = asyncio.create_task(
            self._pubsub_loop(self.websocket_send)
        )

    def detach_websocket(self) -> None:
        """Detach WebSocket — session continues running; messages continue to DB."""
        self._raw_ws_send = self._noop_send
        self.websocket_send = self._noop_send
        self._ws_send_fn = None

        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            self._subscriber_task = None

        self.logger.log_event("websocket_detach", {})

    # ── Pub/sub loop ──────────────────────────────────────────────────────────

    async def _pubsub_loop(self, send_fn: Callable) -> None:
        """Subscribe to the session Redis channel and forward events to the WebSocket."""
        try:
            r = redis_client.get_redis()
            async for event in redis_client.subscribe_session(r, self.session_id):
                try:
                    await send_fn(event)
                except Exception as exc:
                    self.logger.log_error("pubsub_send", str(exc))
                    break  # WebSocket has gone away; stop subscribing.
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logger.log_error("pubsub_loop", str(exc))

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _noop_send(self, message: dict) -> None:
        return

    def _wrap_send(self, send_callable: Callable) -> Callable:
        """Return an async wrapper that checks blocked_agents before sending."""
        async def wrapper(message_dict: dict):
            sender = message_dict.get("sender")
            if sender and sender in self.state.blocked_agents:
                blocked_iso = self.state.blocked_agents.get(sender)
                if blocked_iso:
                    try:
                        msg_time = datetime.fromisoformat(message_dict.get("timestamp", ""))
                        blocked_time = datetime.fromisoformat(blocked_iso)
                        if msg_time >= blocked_time:
                            return
                    except ValueError:
                        # Malformed timestamp — allow the send rather than silently dropping.
                        self.logger.log_error("block_timestamp_parse", f"Could not compare timestamps for sender '{sender}'")
            try:
                await send_callable(message_dict)
            except Exception as exc:
                self.logger.log_error("send", str(exc))

        return wrapper
