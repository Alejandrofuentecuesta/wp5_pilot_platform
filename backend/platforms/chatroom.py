import asyncio
import random
import re
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
from db.repositories import session_repo, message_repo, config_repo
from cache import redis_client


def _parse_target_percentage(criteria: str, label: str, default: int) -> int:
    match = re.search(rf"{label}\s*=\s*(\d+)", criteria or "")
    return int(match.group(1)) if match else default


def _incivility_order(target: int) -> List[str]:
    if target >= 67:
        return ["uncivil", "moderate", "civil"]
    if target <= 33:
        return ["civil", "moderate", "uncivil"]
    return ["moderate", "civil", "uncivil"]


def _non_uncivil_order(target: int) -> List[str]:
    return [level for level in _incivility_order(target) if level != "uncivil"]


def _participant_stance_preferences(participant_stance: Optional[str]) -> tuple[List[str], List[str], List[str], List[str]]:
    stance = (participant_stance or "").strip().lower()
    if stance == "against":
        return (["disagree"], ["agree", "neutral"], ["right", "center", "left"], ["left", "center", "right"])
    if stance == "skeptical":
        return (["neutral"], ["agree", "disagree"], ["center", "left", "right"], ["center", "right", "left"])
    # Default to "favor" and any unknown value.
    return (["agree"], ["disagree", "neutral"], ["left", "center", "right"], ["right", "center", "left"])


def _rank_pool_agents(
    agents: List[dict],
    *,
    stance_order: List[str],
    ideology_order: List[str],
    incivility_order: List[str],
) -> List[dict]:
    stance_rank = {value: i for i, value in enumerate(stance_order)}
    ideology_rank = {value: i for i, value in enumerate(ideology_order)}
    incivility_rank = {value: i for i, value in enumerate(incivility_order)}

    def _key(agent: dict) -> tuple[int, int, int, str]:
        stance = str(agent.get("stance", "neutral"))
        ideology = str(agent.get("ideology", "center"))
        incivility = str(agent.get("incivility", "civil"))
        return (
            stance_rank.get(stance, len(stance_order)),
            ideology_rank.get(ideology, len(ideology_order)),
            incivility_rank.get(incivility, len(incivility_order)),
            str(agent.get("name", "")),
        )

    return sorted(agents, key=_key)


def _take_ranked_agents(
    candidates: List[dict],
    *,
    count: int,
    used_ids: set[str],
    stance_order: List[str],
    ideology_order: List[str],
    incivility_order: List[str],
    allowed_incivilities: Optional[List[str]] = None,
) -> List[dict]:
    if count <= 0:
        return []

    filtered = [
        agent
        for agent in candidates
        if str(agent.get("id", "")) not in used_ids
        and (
            allowed_incivilities is None
            or str(agent.get("incivility", "civil")) in allowed_incivilities
        )
    ]
    ranked = _rank_pool_agents(
        filtered,
        stance_order=stance_order,
        ideology_order=ideology_order,
        incivility_order=incivility_order,
    )
    selected = ranked[:count]
    used_ids.update(str(agent.get("id", "")) for agent in selected)
    return selected


class SimulationSession:
    """Core platform logic for a chatroom session (STAGE framework).

    Responsibilities:
    - manages platform event loop with tick-based pacing
    - delegates all agent decisions to the Director->Performer pipeline
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
        participant_stance_hint: Optional[str] = None,
        *,
        _preloaded_messages: Optional[List[dict]] = None,
        _preloaded_blocks: Optional[dict] = None,
        _config: Optional[Dict] = None,
        _started_at: Optional[datetime] = None,
    ):
        self.session_id = session_id
        self.experiment_id = experiment_id
        self.logger = Logger(session_id, experiment_id)
        self._paused = False

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

        self.internal_validity_criteria = self.experimental_config.get("internal_validity_criteria", "")
        if not self.internal_validity_criteria:
            raise RuntimeError(f"treatment_group '{treatment_group}' has no 'internal_validity_criteria' description")

        self.chatroom_context = experimental_full.get("chatroom_context", "")
        self.incivility_framework = experimental_full.get("incivility_framework", "")
        self.ecological_criteria = experimental_full.get("ecological_validity_criteria", "")
        self.redirect_url = experimental_full.get("redirect_url", "")
        self.participant_stance_hint = participant_stance_hint

        # Optionally inject the seed article summary into chatroom_context so agents know the article content.
        if self.experimental_config.get("agents_see_article"):
            seed = self.experimental_config.get("seed") or {}
            headline = seed.get("headline", "").strip()
            summary = seed.get("agent_summary", "").strip()
            if headline or summary:
                article_block = "\n\nThe following news article has been shown to the participant:"
                if headline:
                    article_block += f"\nHeadline: {headline}"
                if summary:
                    article_block += f"\n\n{summary}"
                self.chatroom_context = (self.chatroom_context.rstrip() + article_block)

        # Create LLM managers for each pipeline stage
        self.director_llm = LLMManager.from_simulation_config(self.simulation_config, role="director")
        self.performer_llm = LLMManager.from_simulation_config(self.simulation_config, role="performer")
        self.moderator_llm = LLMManager.from_simulation_config(self.simulation_config, role="moderator")
        self.classifier_llm = LLMManager.from_simulation_config(self.simulation_config, role="classifier")

        self._rng = random.Random(int(self.simulation_config["random_seed"]))

        # Initialise session state — pool mode overrides agent list.
        # The participant self-report is a prior, not ground truth.
        self._agent_mode = self.simulation_config.get("agent_mode", "prompt")
        self._agent_traits: Dict[str, Dict[str, str]] = {}  # name → {stance, incivility, ideology}

        if self._agent_mode == "pool":
            agent_names, agent_personas, self._agent_traits = self._select_pool_agents(
                experimental_full=experimental_full,
                participant_stance_hint=participant_stance_hint,
            )
        else:
            agent_names = self.simulation_config["agent_names"]
            agent_personas = self.simulation_config.get("agent_personas", [""] * len(agent_names))

        self._agent_names = agent_names

        agents = [
            Agent(name=name, persona=agent_personas[i] if i < len(agent_personas) else "")
            for i, name in enumerate(agent_names)
        ]

        self.state = SessionState(
            session_id=session_id,
            agents=agents,
            duration_minutes=self.simulation_config["session_duration_minutes"],
            participant_stance_hint=participant_stance_hint,
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
            evaluate_interval=int(self.simulation_config["evaluate_interval"]),
            action_window_size=int(self.simulation_config.get("action_window_size", 10)),
            performer_memory_size=int(self.simulation_config.get("performer_memory_size", 3)),
            chatroom_context=self.chatroom_context,
            incivility_framework=self.incivility_framework,
            ecological_criteria=self.ecological_criteria,
            classifier_prompt_template=self.simulation_config.get(
                "classifier_prompt_template",
                DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
            ),
            performer_prompt_template=self.simulation_config.get("performer_prompt_template") or None,
            director_action_prompt_template=self.simulation_config.get("director_action_prompt_template") or None,
            director_evaluate_prompt_template=self.simulation_config.get("director_evaluate_prompt_template") or None,
            moderator_prompt_template=self.simulation_config.get("moderator_prompt_template") or None,
            humanize_output=bool(self.simulation_config.get("humanize_output", False)),
            humanize_rules={
                "strip_hashtags":       int(self.simulation_config.get("humanize_strip_hashtags", 100)),
                "strip_inverted_punct": int(self.simulation_config.get("humanize_strip_inverted_punct", 100)),
                "word_subs":            int(self.simulation_config.get("humanize_word_subs", 80)),
                "drop_accents":         int(self.simulation_config.get("humanize_drop_accents", 40)),
                "comma_spacing":        int(self.simulation_config.get("humanize_comma_spacing", 50)),
                "max_emoji":            int(self.simulation_config.get("humanize_max_emoji", 1)),
            },
            agent_traits=self._agent_traits if self._agent_mode == "pool" else None,
            rng=self._rng,
        )
        orchestrator.set_participant_stance_hint(self.participant_stance_hint)

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
        self._turn_lock = asyncio.Lock()   # serialises the persist+broadcast phase
        self._director_lock = asyncio.Lock()  # serialises the Director phase so each pipeline reads fresh state
        self._parallel_turns = max(1, int(self.simulation_config.get("parallel_turns", 1)))
        self._active_turn_tasks: set = set()  # track fire-and-forget parallel tasks
        self._next_pipeline_id = 0  # cycles 1..N for parallel pipeline tagging

        # Pre-split agents across pipeline slots so each director only picks
        # from its own subset, avoiding duplicate agent selection.
        if self._parallel_turns > 1:
            self._pipeline_agents: List[List[str]] = [[] for _ in range(self._parallel_turns)]
            for i, name in enumerate(self._agent_names):
                self._pipeline_agents[i % self._parallel_turns].append(name)
        else:
            self._pipeline_agents = []

    def _select_pool_agents(
        self,
        *,
        experimental_full: Dict,
        participant_stance_hint: Optional[str],
    ) -> tuple[List[str], List[str], Dict[str, Dict[str, str]]]:
        """Pick a stable pool roster for the current treatment.

        The participant self-report acts as a soft prior: it biases which
        agents enter the room, but the treatment targets still control the
        overall stance/incivility mix.
        """
        full_pool = experimental_full.get("agent_pool", [])
        selected_ids = [str(agent_id) for agent_id in self.experimental_config.get("pool_agent_ids", []) if str(agent_id).strip()]
        candidate_pool = [a for a in full_pool if not selected_ids or a.get("id") in set(selected_ids)]
        if not candidate_pool:
            candidate_pool = list(full_pool)

        target_count = int(self.simulation_config.get("num_agents", len(candidate_pool)) or len(candidate_pool))
        target_count = max(0, min(target_count, len(candidate_pool)))
        if target_count == 0:
            return [], [], {}

        like_target = _parse_target_percentage(self.internal_validity_criteria, "LIKEMINDED_TARGET", 50)
        incivility_target = _parse_target_percentage(self.internal_validity_criteria, "INCIVILITY_TARGET", 50)
        like_count = round(target_count * like_target / 100)
        opposite_count = max(0, target_count - like_count)
        uncivil_count = round(target_count * incivility_target / 100)
        like_uncivil_count = round(uncivil_count * like_count / target_count) if target_count > 0 else 0
        opposite_uncivil_count = max(0, uncivil_count - like_uncivil_count)
        like_non_uncivil_count = max(0, like_count - like_uncivil_count)
        opposite_non_uncivil_count = max(0, opposite_count - opposite_uncivil_count)

        like_stances, opposite_stances, like_ideologies, opposite_ideologies = _participant_stance_preferences(
            participant_stance_hint
        )
        incivility_order = _incivility_order(incivility_target)
        non_uncivil_order = _non_uncivil_order(incivility_target)

        like_candidates = [a for a in candidate_pool if str(a.get("stance", "neutral")) in like_stances]
        if not like_candidates:
            like_candidates = list(candidate_pool)
        opposite_candidates = [a for a in candidate_pool if str(a.get("stance", "neutral")) in opposite_stances]
        if not opposite_candidates:
            opposite_candidates = list(candidate_pool)

        used_ids: set[str] = set()
        pool_agents: List[dict] = []

        # Hard quotas first: side (like/opposite) x incivility (uncivil/non-uncivil).
        pool_agents.extend(_take_ranked_agents(
            like_candidates,
            count=like_uncivil_count,
            used_ids=used_ids,
            stance_order=like_stances,
            ideology_order=like_ideologies,
            incivility_order=["uncivil"],
            allowed_incivilities=["uncivil"],
        ))
        pool_agents.extend(_take_ranked_agents(
            opposite_candidates,
            count=opposite_uncivil_count,
            used_ids=used_ids,
            stance_order=opposite_stances,
            ideology_order=opposite_ideologies,
            incivility_order=["uncivil"],
            allowed_incivilities=["uncivil"],
        ))
        pool_agents.extend(_take_ranked_agents(
            like_candidates,
            count=like_non_uncivil_count,
            used_ids=used_ids,
            stance_order=like_stances,
            ideology_order=like_ideologies,
            incivility_order=non_uncivil_order,
            allowed_incivilities=non_uncivil_order,
        ))
        pool_agents.extend(_take_ranked_agents(
            opposite_candidates,
            count=opposite_non_uncivil_count,
            used_ids=used_ids,
            stance_order=opposite_stances,
            ideology_order=opposite_ideologies,
            incivility_order=non_uncivil_order,
            allowed_incivilities=non_uncivil_order,
        ))

        # If a hard cell is under-filled, preserve the side quota before relaxing
        # the incivility requirement.
        remaining_like = max(
            0,
            like_count - sum(1 for agent in pool_agents if agent in like_candidates)
        )
        if remaining_like > 0:
            pool_agents.extend(_take_ranked_agents(
                like_candidates,
                count=remaining_like,
                used_ids=used_ids,
                stance_order=like_stances,
                ideology_order=like_ideologies,
                incivility_order=incivility_order,
            ))

        remaining_opposite = max(
            0,
            opposite_count - sum(1 for agent in pool_agents if agent in opposite_candidates)
        )
        if remaining_opposite > 0:
            pool_agents.extend(_take_ranked_agents(
                opposite_candidates,
                count=remaining_opposite,
                used_ids=used_ids,
                stance_order=opposite_stances,
                ideology_order=opposite_ideologies,
                incivility_order=incivility_order,
            ))

        # Final fallback only if the pool cannot satisfy the exact quota structure.
        remaining_total = max(0, target_count - len(pool_agents))
        if remaining_total > 0:
            pool_agents.extend(_take_ranked_agents(
                candidate_pool,
                count=remaining_total,
                used_ids=used_ids,
                stance_order=like_stances + opposite_stances,
                ideology_order=like_ideologies + [i for i in opposite_ideologies if i not in like_ideologies],
                incivility_order=incivility_order,
            ))

        agent_names = [a["name"] for a in pool_agents]
        agent_personas = [a.get("persona", "") for a in pool_agents]
        traits: Dict[str, Dict[str, str]] = {}
        for a in pool_agents:
            traits[a["name"]] = {
                "stance": a.get("stance", "neutral"),
                "incivility": a.get("incivility", "civil"),
                "ideology": a.get("ideology", "center"),
            }
        return agent_names, agent_personas, traits

    def _apply_agent_roster(
        self,
        agent_names: List[str],
        agent_personas: List[str],
        agent_traits: Dict[str, Dict[str, str]],
    ) -> None:
        """Rebuild the in-memory roster and dependent orchestrator structures."""
        self._agent_names = agent_names
        self._agent_traits = agent_traits

        agents = [
            Agent(name=name, persona=agent_personas[i] if i < len(agent_personas) else "")
            for i, name in enumerate(agent_names)
        ]
        self.state.agents = agents

        orchestrator = Orchestrator(
            director_llm=self.director_llm,
            performer_llm=self.performer_llm,
            moderator_llm=self.moderator_llm,
            classifier_llm=self.classifier_llm,
            state=self.state,
            logger=self.logger,
            evaluate_interval=int(self.simulation_config["evaluate_interval"]),
            action_window_size=int(self.simulation_config.get("action_window_size", 10)),
            performer_memory_size=int(self.simulation_config.get("performer_memory_size", 3)),
            chatroom_context=self.chatroom_context,
            incivility_framework=self.incivility_framework,
            ecological_criteria=self.ecological_criteria,
            classifier_prompt_template=self.simulation_config.get(
                "classifier_prompt_template",
                DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
            ),
            performer_prompt_template=self.simulation_config.get("performer_prompt_template") or None,
            director_action_prompt_template=self.simulation_config.get("director_action_prompt_template") or None,
            director_evaluate_prompt_template=self.simulation_config.get("director_evaluate_prompt_template") or None,
            moderator_prompt_template=self.simulation_config.get("moderator_prompt_template") or None,
            humanize_output=bool(self.simulation_config.get("humanize_output", False)),
            humanize_rules={
                "strip_hashtags":       int(self.simulation_config.get("humanize_strip_hashtags", 100)),
                "strip_inverted_punct": int(self.simulation_config.get("humanize_strip_inverted_punct", 100)),
                "word_subs":            int(self.simulation_config.get("humanize_word_subs", 80)),
                "drop_accents":         int(self.simulation_config.get("humanize_drop_accents", 40)),
                "comma_spacing":        int(self.simulation_config.get("humanize_comma_spacing", 50)),
                "max_emoji":            int(self.simulation_config.get("humanize_max_emoji", 1)),
            },
            agent_traits=self._agent_traits if self._agent_mode == "pool" else None,
            rng=self._rng,
        )
        orchestrator.set_participant_stance_hint(self.participant_stance_hint)
        self.agent_manager.orchestrator = orchestrator

        if self._parallel_turns > 1:
            self._pipeline_agents = [[] for _ in range(self._parallel_turns)]
            for i, name in enumerate(self._agent_names):
                self._pipeline_agents[i % self._parallel_turns].append(name)
        else:
            self._pipeline_agents = []

    async def set_participant_stance_hint(self, participant_stance_hint: Optional[str]) -> None:
        """Update the participant self-report and, in pool mode, refresh the roster."""
        self.participant_stance_hint = participant_stance_hint
        self.state.participant_stance_hint = participant_stance_hint
        self.agent_manager.orchestrator.set_participant_stance_hint(participant_stance_hint)

        if self._agent_mode == "pool":
            pool = db_conn.get_pool()
            config = await config_repo.get_experiment_config(pool, self.experiment_id)
            if not config:
                return
            experimental_full = config.get("experimental", {})
            agent_names, agent_personas, agent_traits = self._select_pool_agents(
                experimental_full=experimental_full,
                participant_stance_hint=participant_stance_hint,
            )
            self._apply_agent_roster(agent_names, agent_personas, agent_traits)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start a fresh session (seed scenario + launch clock loop)."""
        self.running = True
        self.logger.log_session_start(
            self.experimental_config, self.simulation_config,
            self.treatment_group,
            chatroom_context=self.chatroom_context,
            incivility_framework=self.incivility_framework,
            participant_stance_hint=self.participant_stance_hint or "",
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
        # Cancel any in-flight parallel turn tasks.
        for task in list(self._active_turn_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._active_turn_tasks.clear()

        self.logger.log_session_end(reason)
        # Flush any pending fire-and-forget log tasks before closing DB connection.
        await self.logger.drain()

        try:
            from utils.session_csv_exporter import export_session_messages_csv
            csv_path = export_session_messages_csv(self.session_id, self.state.messages)
            print(f"[Session {self.session_id}] CSV exported: {csv_path}")
        except Exception as exc:
            print(f"[Session {self.session_id}] CSV export failed: {exc}")

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

        Turns are executed sequentially (awaited under a lock) so that each
        Director→Performer→Moderator cycle sees the messages produced by the
        previous turn.
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

                # Do not let the chat begin until the participant has read
                # the article and provided the self-report used by the study.
                if not self.participant_stance_hint:
                    await asyncio.sleep(tick_interval)
                    continue

                if not self.features.agents_active(self.state):
                    await asyncio.sleep(tick_interval)
                    continue

                if self._paused:
                    await asyncio.sleep(tick_interval)
                    continue

                if self._rng.random() < post_probability:
                    if self._parallel_turns > 1:
                        # Fire turn as background task, capped by parallel_turns.
                        # No stagger needed — _director_lock in _parallel_turn already
                        # sequences Directors so each reads fresh chat state.
                        if len(self._active_turn_tasks) < self._parallel_turns:
                            self._next_pipeline_id = (self._next_pipeline_id % self._parallel_turns) + 1
                            pid = self._next_pipeline_id
                            allowed = self._pipeline_agents[pid - 1]  # 0-indexed
                            task = asyncio.create_task(
                                self._parallel_turn(pid, allowed)
                            )
                            self._active_turn_tasks.add(task)
                            task.add_done_callback(self._active_turn_tasks.discard)
                    else:
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
                    self.internal_validity_criteria,
                )

                if result is None or result.action_type == "wait":
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

    async def _parallel_turn(self, pid: int, allowed_agents: List[str], stagger_delay: float = 0.0) -> None:
        """Execute a single agent turn in parallel-friendly mode.

        Pipelines are serialised through the Director phase (_director_lock) so
        each one reads the chat state *after* the previous pipeline has persisted
        its message.  This prevents multiple Directors from seeing the same
        conversation and producing redundant replies.

        The Performer call (the slowest part) runs outside both locks so multiple
        agents can generate their messages concurrently.

        ``pid`` tags log events for the report.
        ``allowed_agents`` restricts which agents this pipeline's Director can pick.
        """
        from utils.logger import pipeline_id_var
        pipeline_id_var.set(pid)
        try:
            if stagger_delay > 0:
                await asyncio.sleep(stagger_delay)

            await self._publish_typing(started=True)

            # ── Phase 1: Director (serialised so each sees fresh state) ───────
            async with self._director_lock:
                result = await self.agent_manager.orchestrator.execute_turn(
                    self.internal_validity_criteria,
                    allowed_performers=set(allowed_agents),
                )

            if result is None or result.action_type == "wait":
                return

            # ── Phase 2: Likes need no typing delay — persist immediately ─────
            if result.action_type == "like":
                async with self._turn_lock:
                    await self.agent_manager._handle_like(result)
                return

            # ── Phase 3: Typing delay (outside lock — Performers run in parallel)
            if result.message and result.message.content:
                delay = len(result.message.content) / self.TYPING_CHARS_PER_SECOND
                delay = max(self.TYPING_DELAY_MIN, min(delay, self.TYPING_DELAY_MAX))
                await asyncio.sleep(delay)

            # ── Phase 4: Persist + broadcast (serialised for ordering) ────────
            async with self._turn_lock:
                await self.agent_manager._handle_message(result)

        except Exception as e:
            self.logger.log_error("parallel_turn", str(e))
        finally:
            await self._publish_typing(started=False)

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

    # ── User message handling ─────────────────────────────────────────────────

    async def handle_user_message(
        self,
        content: str,
        reply_to: Optional[str] = None,
        quoted_text: Optional[str] = None,
        mentions: Optional[list] = None,
    ) -> None:
        """Handle an incoming user message — persist to DB and broadcast."""
        if not self.running:
            return  # session has ended; silently drop
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
