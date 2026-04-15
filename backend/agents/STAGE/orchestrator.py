"""Orchestrator — coordinates the three-call Director + Performer + Moderator pipeline.

Each turn:
  1. (Skip on first turn) Director Update: update last agent's profile
  2. Director Evaluate: assess validity criteria (every turn during warm-up,
     then every evaluate_interval turns once the first full interval completes)
  3. Director Action: select performer, action type, target, generate O/M/D
     — If the Director selects the human participant, the turn short-circuits
       here: Performer/Moderator are skipped, and the evaluate counter is
       not advanced (wait turns are not productive).
  4. Performer: generate message from agent profile + O/M/D + target message
  5. Moderator: extract clean content (retry up to 3 times)

Agent profiles accumulate over the session, updated by the Update call.
All names are anonymized before LLM calls and deanonymized in the output.
"""
import asyncio
import random
import re
from copy import copy
from dataclasses import dataclass
from typing import Optional, List, Dict, Set

from models import Message, Agent
from utils import Logger
from agents.STAGE.director import (
    build_update_system_prompt, build_update_user_prompt, parse_update_response,
    build_evaluate_system_prompt, build_evaluate_user_prompt, parse_evaluate_response,
    build_action_system_prompt, build_action_user_prompt, parse_action_response,
    format_treatment_fidelity_summary, format_participant_hint,
)
from agents.STAGE.performer import build_performer_system_prompt, build_performer_user_prompt
from agents.STAGE.moderator import build_moderator_system_prompt, build_moderator_user_prompt, parse_moderator_response
from agents.STAGE.classifier import (
    DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
    build_classifier_system_prompt,
    build_classifier_user_prompt,
    parse_classifier_response,
)


MAX_PERFORMER_RETRIES = 3


@dataclass
class TurnResult:
    """The result of a single Director->Performer turn.

    For 'like' actions, `message` will be None and `target_message_id`
    identifies the message to like.  For all other action types,
    `message` contains the generated Message ready to be added to state.
    """
    action_type: str
    agent_name: str
    message: Optional[Message] = None
    target_message_id: Optional[str] = None
    target_user: Optional[str] = None
    priority: Optional[str] = None
    performer_rationale: Optional[str] = None
    action_rationale: Optional[str] = None


# ── Anonymization helpers ────────────────────────────────────────────────────

def build_name_map(agent_names: List[str], user_name: str, rng: random.Random) -> Dict[str, str]:
    """Build a shuffled mapping from real names to anonymous labels.

    Agents are assigned "Performer 1", "Performer 2", … in a random order.
    The human participant keeps their real name so agents can infer gender
    and address them naturally.
    """
    shuffled = list(agent_names)
    rng.shuffle(shuffled)
    name_map = {name: f"Performer {i + 1}" for i, name in enumerate(shuffled)}
    # Participant maps to their own name — not anonymized.
    name_map[user_name] = user_name
    return name_map


def anonymize_message(msg: Message, name_map: Dict[str, str]) -> Message:
    """Return a shallow copy of a Message with sender/mentions/content anonymized."""
    anon = copy(msg)
    anon.sender = name_map.get(msg.sender, msg.sender)

    if msg.mentions:
        anon.mentions = [name_map.get(m, m) for m in msg.mentions]

    if msg.liked_by:
        anon.liked_by = {name_map.get(u, u) for u in msg.liked_by}

    anon.content = _replace_names_in_text(msg.content, name_map)

    if msg.quoted_text:
        anon.quoted_text = _replace_names_in_text(msg.quoted_text, name_map)

    return anon


def anonymize_agents(agents: List[Agent], name_map: Dict[str, str]) -> List[Agent]:
    """Return a list of Agents with anonymized names."""
    return [Agent(name=name_map.get(a.name, a.name), persona=a.persona) for a in agents]


def _replace_names_in_text(text: str, name_map: Dict[str, str]) -> str:
    """Replace all occurrences of real names in text with their anonymous labels."""
    if not text:
        return text
    for real, anon in sorted(name_map.items(), key=lambda x: -len(x[0])):
        text = text.replace(real, anon)
    return text


def deanonymize_text(text: str, reverse_map: Dict[str, str]) -> str:
    """Replace anonymous labels in text back to real names."""
    return _replace_names_in_text(text, reverse_map)


def _strip_target_quote_echo(content: str, target_message: Optional[Message]) -> str:
    """Remove a copied target message prefix when the moderator echoes quoted text."""
    if not content or not target_message or not target_message.content:
        return content

    cleaned = content.strip()
    target_text = target_message.content.strip()
    sender_prefix = f"{target_message.sender}:"

    for prefix in (
        target_text,
        f"> {target_text}",
        f"{sender_prefix} {target_text}",
    ):
        if cleaned.startswith(prefix):
            remainder = cleaned[len(prefix):].lstrip("\n\r\t :-")
            if remainder:
                return remainder.strip()

    return cleaned


def _looks_truncated_response(text: Optional[str]) -> bool:
    """Heuristic guard for obviously cut-off long generations."""
    if not text:
        return False

    cleaned = text.strip()
    if len(cleaned) < 200:
        return False

    if re.search(r"[.!?…)\]\"'»”]\s*$", cleaned):
        return False

    if cleaned.endswith(("😂", "🤣", "😭", "😡", "😤", "💸", "🔥", "🙏", "❤️", "♥")):
        return False

    if cleaned.endswith((",", ";", ":", "-", "—", "(", "[", "{", "¿", "¡")):
        return True

    if re.search(r"\b(?:y|o|pero|porque|que|si|aunque|cuando|donde|mientras|como)\s*$", cleaned, re.IGNORECASE):
        return True

    # If the message already contains sentence endings but stops on a bare
    # word, it is usually a length cut rather than an intentional style choice.
    return bool(re.search(r"[.!?…].*[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]\s*$", cleaned, re.DOTALL))


def _merge_prompt_context(chatroom_context: str = "", incivility_framework: str = "") -> str:
    """Combine shared experiment context blocks for prompt injection."""
    parts = []
    if chatroom_context.strip():
        parts.append(chatroom_context.strip())
    if incivility_framework.strip():
        parts.append(f"Incivility framework:\n{incivility_framework.strip()}")
    return "\n\n".join(parts)


class Orchestrator:
    """Coordinates the three-call Director + Performer + Moderator pipeline.

    Maintains agent profiles that accumulate over the session via the
    Director's Update call. All names are anonymized before LLM calls.
    """

    def __init__(
        self,
        director_llm,
        performer_llm,
        moderator_llm,
        classifier_llm,
        state,
        logger: Logger,
        evaluate_interval: int = 5,
        action_window_size: int = 10,
        performer_memory_size: int = 3,
        chatroom_context: str = "",
        incivility_framework: str = "",
        ecological_criteria: str = "",
        agent_traits: Optional[Dict[str, Dict[str, str]]] = None,
        classifier_prompt_template: Optional[str] = None,
        performer_prompt_template: Optional[str] = None,
        director_action_prompt_template: Optional[str] = None,
        director_evaluate_prompt_template: Optional[str] = None,
        moderator_prompt_template: Optional[str] = None,
        humanize_output: bool = False,
        humanize_rules: Optional[Dict] = None,
        humanize_mode: str = "general",
        humanize_per_agent: Optional[Dict[str, Dict]] = None,
        rng: Optional[random.Random] = None,
    ):
        self.director_llm = director_llm
        self.performer_llm = performer_llm
        self.moderator_llm = moderator_llm
        self.classifier_llm = classifier_llm
        self.state = state
        self.logger = logger
        self.evaluate_interval = evaluate_interval
        self.action_window_size = action_window_size
        self.performer_memory_size = performer_memory_size
        self.chatroom_context = chatroom_context
        self.incivility_framework = incivility_framework
        self.ecological_criteria = ecological_criteria
        self._agent_traits = agent_traits or {}
        self.participant_stance_hint = getattr(state, "participant_stance_hint", None)
        self._participant_hint_text = format_participant_hint(self.participant_stance_hint)
        self.classifier_prompt_template = (
            classifier_prompt_template
            if isinstance(classifier_prompt_template, str) and classifier_prompt_template.strip()
            else DEFAULT_CLASSIFIER_PROMPT_TEMPLATE
        )
        self.performer_prompt_template = (
            performer_prompt_template
            if isinstance(performer_prompt_template, str) and performer_prompt_template.strip()
            else None
        )
        self.director_action_prompt_template = (
            director_action_prompt_template
            if isinstance(director_action_prompt_template, str) and director_action_prompt_template.strip()
            else None
        )
        self.director_evaluate_prompt_template = (
            director_evaluate_prompt_template
            if isinstance(director_evaluate_prompt_template, str) and director_evaluate_prompt_template.strip()
            else None
        )
        self.moderator_prompt_template = (
            moderator_prompt_template
            if isinstance(moderator_prompt_template, str) and moderator_prompt_template.strip()
            else None
        )
        self.humanize_output = humanize_output
        self.humanize_rules = humanize_rules or {}
        self.humanize_mode = humanize_mode
        self.humanize_per_agent = humanize_per_agent or {}

        # Build the shuffled name mapping (stable for the session lifetime).
        _rng = rng or random.Random()
        agent_names = [a.name for a in state.agents]
        self._name_map = build_name_map(agent_names, state.user_name, _rng)
        self._reverse_map = {v: k for k, v in self._name_map.items()}
        self._anon_user = self._name_map[state.user_name]

        # Performer profiles: keyed by anonymous name, values are free-form text.
        # Includes both agents and the human — the Director treats all as equal performers.
        # Seeded with each agent's persona (anonymized) so the Director knows their character
        # from turn 1; further accumulated via Director Update calls.
        self.agent_profiles: Dict[str, str] = {}
        for a in state.agents:
            anon_name = self._name_map[a.name]
            if a.persona and a.persona.strip():
                persona_text = _replace_names_in_text(a.persona, self._name_map)
                self.agent_profiles[anon_name] = f"Character persona: {persona_text}"
            else:
                self.agent_profiles[anon_name] = ""
        self.agent_profiles[self._anon_user] = ""

        # Track the last agent that acted (anonymous name) and their action type, for Update calls.
        self._last_agent: Optional[str] = None
        self._last_action_type: Optional[str] = None

        # Running action counts for the Evaluate prompt.
        self._action_counts: Dict[str, int] = {
            "message": 0, "reply": 0, "@mention": 0, "like": 0,
        }

        # Per-performer action counts (keyed by anonymous name).
        self._performer_counts: Dict[str, int] = {
            self._name_map[name]: 0 for name in agent_names
        }
        self._performer_counts[self._anon_user] = 0

        # Carry forward validity evaluations between turns.
        self._internal_validity_summary: str = ""
        self._ecological_validity_summary: str = ""

        # Evaluate fires every evaluate_interval turns, so each call sees a
        # full window of new messages.  Counter tracks turns since last evaluate.
        # During warm-up (before the first full interval), evaluate fires every turn.
        self._turns_since_evaluate: int = 0
        self._has_completed_first_interval: bool = False

        prompt_context = _merge_prompt_context(
            chatroom_context=chatroom_context,
            incivility_framework=incivility_framework,
        )

        # Cached session-static system prompts.
        self._update_system_prompt = build_update_system_prompt(
            chatroom_context=prompt_context,
        )
        # Performer system prompt is per-agent (each agent has their own name).
        # Cached lazily on first use per agent name.
        self._performer_system_prompts: Dict[str, str] = {}
        self._performer_prompt_context = prompt_context
        self._moderator_system_prompt = build_moderator_system_prompt(
            chatroom_context=prompt_context,
            template=self.moderator_prompt_template,
        )
        self._classifier_system_prompt = build_classifier_system_prompt(
            chatroom_context=prompt_context,
        )
        # Evaluate and Action system prompts deferred until first execute_turn (need internal_validity_criteria).
        self._evaluate_system_prompt: Optional[str] = None
        self._action_system_prompt: Optional[str] = None

    @staticmethod
    def _normalize_agent_stance(raw_stance: Optional[str]) -> Optional[str]:
        """Collapse stance labels to comparable buckets for anti-infighting rules."""
        if not raw_stance:
            return None
        stance = str(raw_stance).strip().lower()
        if stance in {"agree", "favor", "favour", "support", "pro"}:
            return "agree"
        if stance in {"disagree", "against", "oppose", "anti"}:
            return "disagree"
        return None

    def _agents_share_measure_side(self, actor_name: Optional[str], target_name: Optional[str]) -> bool:
        """Return True when both agents hold the same non-neutral stance on the measure."""
        if not actor_name or not target_name or actor_name == target_name:
            return False

        actor_traits = self._agent_traits.get(actor_name) or {}
        target_traits = self._agent_traits.get(target_name) or {}
        actor_stance = self._normalize_agent_stance(actor_traits.get("stance"))
        target_stance = self._normalize_agent_stance(target_traits.get("stance"))
        return actor_stance is not None and actor_stance == target_stance

    def set_participant_stance_hint(self, participant_stance_hint: Optional[str]) -> None:
        """Refresh the soft prior used in prompts and report summaries."""
        self.participant_stance_hint = participant_stance_hint
        self._participant_hint_text = format_participant_hint(participant_stance_hint)

    def _format_treatment_fidelity_summary(self) -> str:
        """Summarise classifier-derived treatment fidelity across the session."""
        agent_messages = [
            message
            for message in self.state.messages
            if message.sender != self.state.user_name
        ]
        return format_treatment_fidelity_summary(agent_messages)

    async def _classify_message(self, agent_message: str) -> Dict[str, Optional[object]]:
        """Run the post-moderation classifier stage for a generated message."""
        participant_messages = [
            message for message in self.state.messages if message.sender == self.state.user_name
        ]

        classifier_user_prompt = build_classifier_user_prompt(
            participant_messages=participant_messages,
            agent_message=agent_message,
            prompt_template=self.classifier_prompt_template,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
        )

        classifier_raw = None
        try:
            classifier_raw = await self.classifier_llm.generate_response(
                classifier_user_prompt,
                max_retries=1,
                system_prompt=self._classifier_system_prompt,
            )
        except Exception as exc:
            self.logger.log_error("classifier_llm_call", str(exc))

        self.logger.log_llm_call(
            agent_name="__classifier__",
            prompt=f"[SYSTEM]\n{self._classifier_system_prompt}\n\n[USER]\n{classifier_user_prompt}",
            response=classifier_raw,
            error=None if classifier_raw else "Classifier LLM returned no response",
        )

        if not classifier_raw:
            return {}

        try:
            return parse_classifier_response(classifier_raw)
        except ValueError as exc:
            self.logger.log_error("classifier_parse", str(exc))
            return {}

    def _deanon_name(self, anon_name: str) -> str:
        """Map an anonymous label back to the real name."""
        return self._reverse_map.get(anon_name, anon_name)

    async def execute_turn(
        self,
        internal_validity_criteria: str,
        allowed_performers: Optional[Set[str]] = None,
    ) -> Optional[TurnResult]:
        """Run one full Update → Evaluate → Action → Performer → Moderator cycle.

        ``allowed_performers`` (real agent names) restricts which agents the
        Director can select in parallel mode, preventing duplicate picks.
        When ``None``, all agents are eligible (sequential mode).

        Returns a TurnResult on success, or None if the cycle fails.
        """
        # 1. Gather recent messages, then anonymize.
        #    Action and Evaluate use separate window sizes; Update and human
        #    detection use the Action window (which contains the most recent message).
        recent_action = self.state.get_recent_messages(self.action_window_size)
        agents = self.state.agents

        anon_recent_action = [anonymize_message(m, self._name_map) for m in recent_action]

        # 1b. Detect if the human posted since the last orchestrator turn.
        #     Do NOT treat the participant as a performer for Update purposes —
        #     the Director cannot instruct the human, and running Update on their
        #     message causes the Director to try to "correct" them in Action.
        if anon_recent_action and anon_recent_action[-1].sender == self._anon_user:
            self._last_action_type = "message"
            # Leave _last_agent unchanged so Update still targets the previous agent.

        # 2. Director Update (skip on first turn — nothing to assess)
        if anon_recent_action and self._last_agent and self._last_agent != self._anon_user:
            # Skip Update for likes — they aren't significant enough for a profile revision.
            if self._last_action_type != "like":
                await self._director_update(anon_recent_action)

        # 2b. Director Evaluate
        #     Before the first full interval fires, evaluate every turn so the
        #     Director has validity guidance from the very start.  Once the first
        #     full window completes, switch to the regular cadence.
        #     Save counter state so we can restore it if the Director yields (wait turn).
        _saved_counter = self._turns_since_evaluate
        _saved_first_interval = self._has_completed_first_interval
        self._turns_since_evaluate += 1
        should_evaluate = (
            not self._has_completed_first_interval          # warm-up: every turn
            or self._turns_since_evaluate >= self.evaluate_interval  # steady-state
        )
        if should_evaluate:
            recent_eval = self.state.get_recent_messages(self.evaluate_interval)
            anon_recent_eval = [anonymize_message(m, self._name_map) for m in recent_eval]
            await self._director_evaluate(internal_validity_criteria, anon_recent_eval)
            if self._turns_since_evaluate >= self.evaluate_interval:
                self._has_completed_first_interval = True
                self._turns_since_evaluate = 0

        # 3. Director Action
        #    The Director selects from all performers visible in profiles/chat log.
        #    If it picks the human participant, the turn becomes a 'wait'.
        #    In parallel mode, only show profiles for the allowed agent subset
        #    so each pipeline's Director picks from its own pool.
        action_profiles = self.agent_profiles
        action_perf_counts = self._performer_counts
        if allowed_performers is not None:
            allowed_anon = {self._name_map[n] for n in allowed_performers if n in self._name_map}
            # Always include the human so the Director can still yield ('wait').
            allowed_anon.add(self._anon_user)
            action_profiles = {k: v for k, v in self.agent_profiles.items() if k in allowed_anon}
            action_perf_counts = {k: v for k, v in self._performer_counts.items() if k in allowed_anon}

        action_data = await self._director_action(
            anon_recent_action,
            override_profiles=action_profiles,
            override_perf_counts=action_perf_counts,
        )
        if action_data is None:
            return None

        action_type = action_data["action_type"]
        agent_name = self._deanon_name(action_data["next_performer"])
        target_user = action_data.get("target_user")
        if target_user:
            target_user = self._deanon_name(target_user)
        target_message_id = action_data.get("target_message_id")
        priority = action_data.get("priority")
        performer_rationale = action_data.get("performer_rationale")
        action_rationale = action_data.get("action_rationale")

        # 3a. If the participant's most recent message in the window @mentions or
        #     addresses a specific agent that has NOT yet replied to it, force
        #     that agent to reply.  We scan backwards through the window to find
        #     the latest participant message, then check whether any agent has
        #     already responded after it — if so, the obligation is discharged.
        addressed_agent = None
        pending_human_msg = None
        agent_names = {a.name for a in agents if a.name != self.state.user_name}

        for msg in reversed(recent_action):
            if msg.sender == self.state.user_name:
                pending_human_msg = msg
                break
            # An agent replied after the participant's message — obligation discharged.
            if msg.sender in agent_names:
                break

        if pending_human_msg:
            # Check explicit @mentions first
            if pending_human_msg.mentions:
                for m in pending_human_msg.mentions:
                    if m in agent_names:
                        addressed_agent = m
                        break

            # Fallback: message starts with or contains @agentname
            if addressed_agent is None:
                content_lower = (pending_human_msg.content or "").lower()
                for name in agent_names:
                    if content_lower.startswith(name.lower()) or f"@{name.lower()}" in content_lower:
                        addressed_agent = name
                        break

        if addressed_agent and addressed_agent != agent_name:
            self.logger.log_error(
                "director_override_participant_mention",
                f"Participant addressed '{addressed_agent}'; overriding Director choice '{agent_name}'",
            )
            agent_name = addressed_agent
            action_data["next_performer"] = self._name_map.get(addressed_agent, addressed_agent)

        if addressed_agent:
            # Force a reply to the participant's message and reset the instruction
            # so the performer gets a coherent brief (original instruction was for a different agent/action).
            action_type = "reply"
            action_data["action_type"] = "reply"
            target_message_id = pending_human_msg.message_id
            action_data["target_message_id"] = target_message_id
            target_user = None
            action_data["target_user"] = None
            action_data["performer_instruction"] = {
                "objective": f"Reply directly to {self.state.user_name}'s message addressed to you.",
                "motivation": f"{self.state.user_name} addressed you specifically — not replying would feel rude and unnatural.",
                "directive": "Keep it conversational and on-topic; stay true to your fixed stance and character.",
            }

        # 3b. Fix self-mention: if Director told an agent to @mention itself,
        #     downgrade to a regular message (no target_user).
        if action_type == "@mention" and target_user and target_user == agent_name:
            self.logger.log_error(
                "director_self_mention",
                f"Director told '{agent_name}' to @mention itself; converting to message",
            )
            action_type = "message"
            action_data["action_type"] = "message"
            target_user = None
            # Clear the @mention instruction — the performer now posts a standalone message.
            if action_data.get("performer_instruction"):
                action_data["performer_instruction"] = {
                    "objective": action_data["performer_instruction"].get("objective", "Post a message to the chatroom."),
                    "motivation": action_data["performer_instruction"].get("motivation", ""),
                    "directive": action_data["performer_instruction"].get("directive", "Stay true to your fixed stance and character."),
                }

        # 3c. Prevent direct infighting between agents on the same side of the measure.
        if action_type in {"reply", "@mention", "message"}:
            same_side_target = None
            if target_user and self._agents_share_measure_side(agent_name, target_user):
                same_side_target = target_user
            elif target_message_id and target_message_id:
                target_msg_for_guard = next(
                    (m for m in self.state.messages if m.message_id == target_message_id),
                    None,
                )
                if target_msg_for_guard and self._agents_share_measure_side(agent_name, target_msg_for_guard.sender):
                    same_side_target = target_msg_for_guard.sender

            if same_side_target:
                self.logger.log_error(
                    "director_same_side_target",
                    f"Director targeted same-side agents '{agent_name}' -> '{same_side_target}'; converting to a non-targeted message",
                )
                action_type = "message"
                action_data["action_type"] = "message"
                target_user = None
                action_data["target_user"] = None
                target_message_id = None
                action_data["target_message_id"] = None
                action_data["performer_instruction"] = {
                    "objective": "Reinforce your side's position without attacking allied agents.",
                    "motivation": "You agree on the measure, so infighting would feel incoherent and weaken the discussion.",
                    "directive": "Sound supportive or additive; do not criticize, mock, or challenge agents who share your stance.",
                }

        # 3b. Handle 'wait' — Director selected the human participant.
        #     Skip Performer/Moderator and restore evaluate counter
        #     (wait turns are not productive turns).
        if agent_name == self.state.user_name:
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            return TurnResult(
                action_type="wait",
                agent_name=agent_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # Validate that the chosen agent exists; fall back to a random valid agent.
        if not agents:
            self.logger.log_error("director_agent", "No agents available for this session")
            return None
        if not any(a.name == agent_name for a in agents):
            pool = list(allowed_performers) if allowed_performers else [a.name for a in agents]
            fallback = random.choice(pool)
            self.logger.log_error(
                "director_agent",
                f"Director chose unknown agent '{agent_name}'; falling back to '{fallback}'",
            )
            agent_name = fallback

        # In parallel mode, enforce the allowed subset.
        if allowed_performers and agent_name not in allowed_performers:
            pool = list(allowed_performers)
            fallback = random.choice(pool)
            self.logger.log_error(
                "director_agent_restricted",
                f"Director chose '{agent_name}' outside its pipeline subset; "
                f"falling back to '{fallback}'",
            )
            agent_name = fallback

        # Track last agent and action type for next turn's Update call (use anonymous name).
        # Save previous values so we can restore on performer failure (silent skip).
        _saved_last_agent = self._last_agent
        _saved_last_action_type = self._last_action_type
        self._last_agent = self._name_map.get(agent_name, action_data["next_performer"])
        self._last_action_type = action_type

        # 4. Handle 'like' actions (no Performer call needed)
        if action_type == "like":
            # Guard: skip duplicate likes (agent already liked this message).
            if target_message_id:
                target_msg = next(
                    (m for m in self.state.messages if m.message_id == target_message_id),
                    None,
                )
                if target_msg and agent_name in (target_msg.liked_by or set()):
                    self.logger.log_error(
                        "director_duplicate_like",
                        f"'{agent_name}' already liked message {target_message_id}; skipping as wait",
                    )
                    self._turns_since_evaluate = _saved_counter
                    self._has_completed_first_interval = _saved_first_interval
                    self._last_agent = _saved_last_agent
                    self._last_action_type = _saved_last_action_type
                    return TurnResult(
                        action_type="wait",
                        agent_name=agent_name,
                        priority=priority,
                        performer_rationale=performer_rationale,
                        action_rationale=action_rationale,
                    )

            self._action_counts["like"] += 1
            anon_name = self._name_map.get(agent_name, agent_name)
            self._performer_counts[anon_name] = self._performer_counts.get(anon_name, 0) + 1
            return TurnResult(
                action_type="like",
                agent_name=agent_name,
                target_message_id=target_message_id,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # 5. Performer → Moderator loop (max MAX_PERFORMER_RETRIES attempts)
        performer_instruction = action_data.get("performer_instruction", {})

        # Get the selected agent's profile and restore real names for the performer.
        anon_agent_name = self._name_map.get(agent_name, agent_name)
        agent_profile = deanonymize_text(
            self.agent_profiles.get(anon_agent_name, ""),
            self._reverse_map,
        )

        # Look up target message if needed.
        # For 'message' with a target_user (targeted response), find the
        # target user's most recent message so the Performer has context.
        target_message = None
        if target_message_id:
            target_message = next(
                (m for m in self.state.messages if m.message_id == target_message_id),
                None,
            )
        elif action_type == "message" and target_user:
            # Director chose a targeted message but no explicit message_id —
            # resolve the target user's most recent message.
            for m in reversed(self.state.messages):
                if m.sender == target_user:
                    target_message = m
                    break

        # Gather this performer's recent messages with real names so it can avoid repetition
        # while still knowing who it has interacted with.
        recent_by_agent = []
        if self.performer_memory_size > 0:
            for m in reversed(self.state.messages):
                if m.sender == agent_name:
                    recent_by_agent.append(m)
                    if len(recent_by_agent) >= self.performer_memory_size:
                        break
            recent_by_agent.reverse()

        # Get agent's raw persona for the performer (not anonymized — performer knows their own character)
        agent_obj = next((a for a in agents if a.name == agent_name), None)
        agent_persona = (agent_obj.persona or None) if agent_obj else None

        performer_user_prompt = build_performer_user_prompt(
            instruction=performer_instruction,
            agent_profile=agent_profile,
            action_type=action_type,
            persona=agent_persona,
            target_user=target_user,
            target_message=target_message,
            recent_messages=recent_by_agent,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            template=self.performer_prompt_template,
        )

        content = None

        # Build (or retrieve cached) per-agent performer system prompt.
        if agent_name not in self._performer_system_prompts:
            self._performer_system_prompts[agent_name] = build_performer_system_prompt(
                chatroom_context=self._performer_prompt_context,
                agent_name=agent_name,
                participant_name=self.state.user_name,
                agent_traits=self._agent_traits.get(agent_name) if self._agent_traits else None,
                template=self.performer_prompt_template,
            )
        performer_system_prompt = self._performer_system_prompts[agent_name]

        for attempt in range(1, MAX_PERFORMER_RETRIES + 1):
            # 5a. Call the Performer
            performer_raw = None
            try:
                performer_raw = await self.performer_llm.generate_response(
                    performer_user_prompt, max_retries=1,
                    system_prompt=performer_system_prompt,
                )
            except Exception as e:
                self.logger.log_error("performer_llm_call", str(e))

            self.logger.log_llm_call(
                agent_name=agent_name,
                prompt=f"[SYSTEM]\n{performer_system_prompt}\n\n[USER]\n{performer_user_prompt}",
                response=performer_raw,
                error=None if performer_raw else f"Performer LLM returned no response (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
            )

            if not performer_raw:
                continue

            if _looks_truncated_response(performer_raw):
                self.logger.log_error(
                    "performer_output_truncated",
                    f"Performer output appears truncated (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                    context={"agent_name": agent_name, "action_type": action_type},
                )
                continue

            # 5b. Call the Moderator to extract clean content
            moderator_user_prompt = build_moderator_user_prompt(
                performer_output=performer_raw,
                template=self.moderator_prompt_template,
            )

            moderator_raw = None
            try:
                moderator_raw = await self.moderator_llm.generate_response(
                    moderator_user_prompt, max_retries=1,
                    system_prompt=self._moderator_system_prompt,
                )
            except Exception as e:
                self.logger.log_error("moderator_llm_call", str(e))

            self.logger.log_llm_call(
                agent_name="__moderator__",
                prompt=f"[SYSTEM]\n{self._moderator_system_prompt}\n\n[USER]\n{moderator_user_prompt}",
                response=moderator_raw,
                error=None if moderator_raw else f"Moderator LLM returned no response (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
            )

            content = parse_moderator_response(moderator_raw)

            if content is not None:
                if _looks_truncated_response(content):
                    self.logger.log_error(
                        "moderator_output_truncated",
                        f"Moderator output appears truncated (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                        context={"agent_name": agent_name, "action_type": action_type},
                    )
                    content = None
                    continue
                break
            else:
                self.logger.log_error(
                    "moderator_no_content",
                    f"Moderator could not extract content from performer output (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                )

        if content is None:
            self.logger.log_error(
                "performer_retries_exhausted",
                f"Failed to get valid performer content after {MAX_PERFORMER_RETRIES} attempts",
            )
            # Treat exhausted retries like a wait turn: restore evaluate
            # counter and clear last-agent so the failed turn is invisible
            # to subsequent Director calls.
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            self._last_agent = _saved_last_agent
            self._last_action_type = _saved_last_action_type
            return TurnResult(
                action_type="wait",
                agent_name=agent_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # 6. Deanonymize any anonymous labels in the generated content.
        content = deanonymize_text(content, self._reverse_map)

        if action_type == "reply" and target_message:
            content = _strip_target_quote_echo(content, target_message)

        # 6b. Strip any @mention prefix the Performer included — the
        #     Orchestrator adds it canonically below, so duplicates must go.
        if action_type == "@mention" and target_user:
            content = re.sub(
                r"^@?" + re.escape(target_user) + r"\s*",
                "",
                content,
            ).strip()

        # 6c. Optional post-processing humanization (informal typos, no hashtags…)
        if self.humanize_output:
            from utils.humanizer import humanize as _humanize
            # Use per-agent rules if an override exists for this agent, regardless of humanize_mode.
            if agent_name in self.humanize_per_agent:
                r = self.humanize_per_agent[agent_name]
            else:
                r = self.humanize_rules
            content = _humanize(
                content,
                strip_hashtags=int(r.get("strip_hashtags", 100)),
                strip_inverted_punct=int(r.get("strip_inverted_punct", 100)),
                word_subs=int(r.get("word_subs", 80)),
                drop_accents=int(r.get("drop_accents", 40)),
                comma_spacing=int(r.get("comma_spacing", 50)),
                max_emoji=int(r.get("max_emoji", 1)),
            )

        # 7. Format the output into a Message
        mentions = None
        reply_to = None
        quoted_text = None

        if action_type == "@mention" and target_user:
            content = f"@{target_user} {content}"
            mentions = [target_user]
        elif action_type == "reply" and target_message_id:
            reply_to = target_message_id
            if target_message:
                quoted_text = target_message.content

        classification = await self._classify_message(agent_message=content)

        message = Message.create(
            sender=agent_name,
            content=content,
            reply_to=reply_to,
            quoted_text=quoted_text,
            mentions=mentions,
            is_incivil=classification.get("is_incivil"),
            is_like_minded=classification.get("is_like_minded"),
            inferred_participant_stance=classification.get("inferred_participant_stance"),
            classification_rationale=classification.get("classification_rationale"),
        )
        stance_confidence = classification.get("stance_confidence")
        if stance_confidence:
            message.metadata["stance_confidence"] = stance_confidence

        self._action_counts[action_type] = self._action_counts.get(action_type, 0) + 1
        anon_name = self._name_map.get(agent_name, agent_name)
        self._performer_counts[anon_name] = self._performer_counts.get(anon_name, 0) + 1

        return TurnResult(
            action_type=action_type,
            agent_name=agent_name,
            message=message,
            target_message_id=target_message_id,
            target_user=target_user,
            priority=priority,
            performer_rationale=performer_rationale,
            action_rationale=action_rationale,
        )

    # ── Director Update (Call 1) ──────────────────────────────────────────────

    async def _director_update(self, anon_recent: List[Message]) -> None:
        """Run Director Update call: update last agent's profile.

        Updates agent profile in place. On failure, carries forward unchanged.
        """
        last_agent_profile = self.agent_profiles.get(self._last_agent, "")

        # Find the most recent message by the last-acting agent.
        last_action = None
        for msg in reversed(anon_recent):
            if msg.sender == self._last_agent:
                last_action = msg
                break

        # Resolve the last agent's fixed traits (keyed by real name, looked up via reverse map)
        last_agent_real_name = self._reverse_map.get(self._last_agent, self._last_agent)
        last_agent_traits = self._agent_traits.get(last_agent_real_name) if self._agent_traits else None

        update_user = build_update_user_prompt(
            last_action=last_action,
            last_agent=self._last_agent or "",
            last_agent_profile=last_agent_profile,
            last_agent_traits=last_agent_traits,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
        )

        update_raw = None
        try:
            update_raw = await self.director_llm.generate_response(
                update_user, max_retries=1,
                system_prompt=self._update_system_prompt,
            )
        except Exception as e:
            self.logger.log_error("director_update_llm_call", str(e))
            return

        self.logger.log_llm_call(
            agent_name="__director_update__",
            prompt=f"[SYSTEM]\n{self._update_system_prompt}\n\n[USER]\n{update_user}",
            response=update_raw,
            error=None if update_raw else "Director Update LLM returned no response",
        )

        if not update_raw:
            return

        try:
            update_data = parse_update_response(update_raw)
        except ValueError as e:
            self.logger.log_error("director_update_parse", str(e))
            return

        # Update the last-acting agent's profile
        if self._last_agent and self._last_agent in self.agent_profiles:
            self.agent_profiles[self._last_agent] = update_data["performer_profile_update"]

    # ── Director Evaluate (Call 2) ────────────────────────────────────────────

    async def _director_evaluate(self, internal_validity_criteria: str, anon_recent: List[Message]) -> None:
        """Run Director Evaluate call: revise validity evaluations.

        Updates validity evaluations in place. On failure, carries forward unchanged.
        """
        # Cache Evaluate system prompt (session-static once criteria are known)
        if self._evaluate_system_prompt is None:
            self._evaluate_system_prompt = build_evaluate_system_prompt(
                internal_validity_criteria=internal_validity_criteria,
                ecological_criteria=self.ecological_criteria,
                chatroom_context=_merge_prompt_context(
                    chatroom_context=self.chatroom_context,
                    incivility_framework=self.incivility_framework,
                ),
                participant_stance_hint=self._participant_hint_text,
                participant_name=self.state.user_name,
                template=self.director_evaluate_prompt_template,
            )

        evaluate_user = build_evaluate_user_prompt(
            messages=anon_recent,
            previous_internal=self._internal_validity_summary,
            previous_ecological=self._ecological_validity_summary,
            internal_validity_criteria=internal_validity_criteria,
            ecological_criteria=self.ecological_criteria,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            participant_stance_hint=self._participant_hint_text,
            treatment_fidelity_summary=self._format_treatment_fidelity_summary(),
            action_counts=self._action_counts,
            performer_counts=self._performer_counts,
            exclude_performer=self._anon_user,
            template=self.director_evaluate_prompt_template,
        )

        evaluate_raw = None
        try:
            evaluate_raw = await self.director_llm.generate_response(
                evaluate_user, max_retries=1,
                system_prompt=self._evaluate_system_prompt,
            )
        except Exception as e:
            self.logger.log_error("director_evaluate_llm_call", str(e))
            return

        self.logger.log_llm_call(
            agent_name="__director_evaluate__",
            prompt=f"[SYSTEM]\n{self._evaluate_system_prompt}\n\n[USER]\n{evaluate_user}",
            response=evaluate_raw,
            error=None if evaluate_raw else "Director Evaluate LLM returned no response",
        )

        if not evaluate_raw:
            return

        try:
            evaluate_data = parse_evaluate_response(evaluate_raw)
        except ValueError as e:
            self.logger.log_error("director_evaluate_parse", str(e))
            return

        # Update validity evaluations
        self._internal_validity_summary = evaluate_data["internal_validity_evaluation"]
        self._ecological_validity_summary = evaluate_data["ecological_validity_evaluation"]

    # ── Director Action (Call 3) ──────────────────────────────────────────────

    async def _director_action(
        self,
        anon_recent: List[Message],
        override_profiles: Optional[Dict[str, str]] = None,
        override_perf_counts: Optional[Dict[str, int]] = None,
    ) -> Optional[dict]:
        """Run Director Action call: select performer, action type, O/M/D.

        The Director selects from all performers visible in profiles and
        chat log.  If it picks the human participant, the orchestrator
        will treat this as a 'wait' (handled by the caller).

        ``override_profiles`` / ``override_perf_counts`` allow the caller
        to restrict the agent pool (used in parallel pipeline mode).

        Returns parsed action response dict, or None on failure.
        """
        # Cache Action system prompt (session-static)
        if self._action_system_prompt is None:
            self._action_system_prompt = build_action_system_prompt(
                chatroom_context=_merge_prompt_context(
                    chatroom_context=self.chatroom_context,
                    incivility_framework=self.incivility_framework,
                ),
                participant_stance_hint=self._participant_hint_text,
                participant_name=self.state.user_name,
                template=self.director_action_prompt_template,
            )

        profiles = override_profiles if override_profiles is not None else self.agent_profiles
        perf_counts = override_perf_counts if override_perf_counts is not None else self._performer_counts
        anon_traits = None
        if self._agent_traits:
            anon_traits = {
                self._name_map.get(real_name, real_name): traits
                for real_name, traits in self._agent_traits.items()
                if self._name_map.get(real_name, real_name) in profiles
            }

        action_user = build_action_user_prompt(
            messages=anon_recent,
            agent_profiles=profiles,
            internal_validity_summary=self._internal_validity_summary or "No actions have occurred yet. No assessment available.",
            ecological_validity_summary=self._ecological_validity_summary or "No actions have occurred yet. No assessment available.",
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            participant_stance_hint=self._participant_hint_text,
            treatment_fidelity_summary=self._format_treatment_fidelity_summary(),
            performer_counts=perf_counts,
            action_counts=self._action_counts,
            exclude_performer=self._anon_user,
            agent_traits=anon_traits,
            template=self.director_action_prompt_template,
        )

        # Retry loop: Director Action is the most critical call in the pipeline.
        # On empty response or unparseable JSON, retry with short exponential backoff
        # before giving up — this handles cold-start timeouts and transient API errors
        # that are especially common at session start.
        MAX_ACTION_ATTEMPTS = 3
        BACKOFF_SECONDS = [0, 2, 5]  # delay before attempt 1, 2, 3

        for attempt in range(MAX_ACTION_ATTEMPTS):
            if BACKOFF_SECONDS[attempt] > 0:
                await asyncio.sleep(BACKOFF_SECONDS[attempt])

            action_raw = None
            try:
                action_raw = await self.director_llm.generate_response(
                    action_user, max_retries=1,
                    system_prompt=self._action_system_prompt,
                )
            except Exception as e:
                self.logger.log_error(
                    "director_action_llm_call",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: {e}",
                )
                continue

            self.logger.log_llm_call(
                agent_name="__director_action__",
                prompt=f"[SYSTEM]\n{self._action_system_prompt}\n\n[USER]\n{action_user}",
                response=action_raw,
                error=None if action_raw else f"Director Action LLM returned no response (attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS})",
            )

            if not action_raw:
                continue

            try:
                return parse_action_response(action_raw)
            except ValueError as e:
                self.logger.log_error(
                    "director_action_parse",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: {e}",
                )
                continue

        self.logger.log_error(
            "director_action_failed",
            f"Director Action gave no valid response after {MAX_ACTION_ATTEMPTS} attempts — skipping turn",
        )
        return None
