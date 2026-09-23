"""The safety gate between the simulation and the participant.

Every agent message passes through ``screen_agent`` before it is persisted or
broadcast, and every participant message passes through ``screen_participant``
after it is posted. The policy:

* ``safe``        — publish; verdict recorded on the message.
* ``unsafe``      — agent turns are withheld until a human marks them as
                    ``no_concern``; ``concern`` keeps them out of the chat.
* ``unavailable`` — the classifier gave no verdict. An agent turn is withheld
                    (never published) and a flag records the withheld text; a
                    participant message is already in the room, so only a flag
                    is opened.

The screen catches every exception internally and treats it as
``unavailable``. It never raises into the turn loop and never publishes
anything itself.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

from db import connection as db_conn
from db.repositories import safety_repo
from models.message import Message
from utils.safety import Policy, SafetyClient, SafetyVerdict, load_policy, render_excerpt
from utils.violence_guard import contains_explicit_violence_cue, explicitly_rejects_violence


@dataclass
class ScreenOutcome:
    publish: bool
    verdict: SafetyVerdict
    # The conversation excerpt the classifier judged (stored on the flag).
    context: str
    flag_id: Optional[str] = None


class SafetyScreen:
    def __init__(
        self,
        *,
        session_id: str,
        experiment_id: str,
        logger,
        client: Optional[SafetyClient],
        enabled: bool,
        user_name: str,
        policy: Optional[Policy] = None,
    ) -> None:
        self.session_id = session_id
        self.experiment_id = experiment_id
        self.logger = logger
        self.client = client
        self.enabled = bool(enabled and client is not None)
        self.user_name = user_name
        self.policy = policy or load_policy()
        # agent_name -> open flag_ids blocking them. While an agent has any
        # unreviewed withheld message, the Director must not pick them again —
        # otherwise a second turn from the same agent can publish before the
        # first one is reviewed, and approving the first afterwards makes two
        # messages from that agent appear back-to-back with no explanation.
        self._pending_review_agents: Dict[str, Set[str]] = {}

    # ── pending-review blocking ──────────────────────────────────────────

    def pending_review_agents(self) -> Set[str]:
        """Agent names that currently have at least one unreviewed withheld flag."""
        return {name for name, flags in self._pending_review_agents.items() if flags}

    def resolve_flag(self, flag_id: str, agent_name: Optional[str] = None) -> None:
        """Unblock the agent once a withheld flag has been reviewed (or auto-resolved).

        Call this from wherever a flag transitions out of the open/unreviewed
        state: the reviewer approval endpoint and the 2-minute auto-concern
        timeout. ``agent_name`` is an optional shortcut; without it every
        pending agent is scanned for the flag_id.
        """
        if agent_name is not None:
            flags = self._pending_review_agents.get(agent_name)
            if flags is not None:
                flags.discard(flag_id)
                if not flags:
                    del self._pending_review_agents[agent_name]
            return
        for name, flags in list(self._pending_review_agents.items()):
            if flag_id in flags:
                flags.discard(flag_id)
                if not flags:
                    del self._pending_review_agents[name]

    # ── classification ────────────────────────────────────────────────────

    def _excerpt(self, message: Message, state) -> str:
        """The excerpt ending in ``message``, built from the chat before it."""
        messages = list(getattr(state, "messages", []) or [])
        end = next((i for i, m in enumerate(messages) if m.message_id == message.message_id), len(messages))
        return render_excerpt(message, messages[:end], self.user_name)

    async def _classify(self, message: Message, state) -> Tuple[SafetyVerdict, str]:
        """Classify ``message`` in context. Never raises; failures are ``unavailable``."""
        try:
            excerpt = self._excerpt(message, state)
        except Exception as exc:
            return SafetyVerdict(status="unavailable", error=f"render: {exc}"), ""
        try:
            verdict = await self.client.classify(self.policy.text, excerpt)
        except Exception as exc:  # the client should never raise; belt and braces
            verdict = SafetyVerdict(status="unavailable", error=f"client: {exc}")
        verdict.policy_version = self.policy.version
        try:
            self.logger.log_llm_call(
                agent_name="__safety__",
                prompt=excerpt,
                response=verdict.raw or None,
                error=verdict.error,
            )
        except Exception:
            pass
        return verdict, excerpt

    # ── agent path ────────────────────────────────────────────────────────

    async def screen_agent(self, message: Message, state) -> ScreenOutcome:
        """Decide whether an agent message may be published.

        Returns ``publish=False`` when no verdict was obtained or the output
        is unsafe. The withheld text is retained in a flag for review.
        """
        if not self.enabled:
            return ScreenOutcome(publish=True, verdict=SafetyVerdict(status="unscreened"), context="")
        verdict, context = await self._classify(message, state)

        if verdict.status in ("unsafe", "unavailable"):
            flag_id = await self._flag(
                sender_type="agent",
                sender=message.sender,
                content=message.content,
                context=context,
                verdict=verdict,
                message_id=None,
                displayed_at=None,
            )
            if flag_id:
                self._pending_review_agents.setdefault(message.sender, set()).add(flag_id)
            self._event(
                "safety_turn_withheld",
                {
                    "sender": message.sender,
                    "error": verdict.error,
                    "categories": verdict.categories,
                },
            )
            return ScreenOutcome(publish=False, verdict=verdict, context=context, flag_id=flag_id)

        return ScreenOutcome(publish=True, verdict=verdict, context=context)

    async def after_publish(self, message: Message, outcome: ScreenOutcome) -> None:
        """Record the verdict on the published message and open a flag if unsafe."""
        if not self.enabled or outcome.verdict.status == "unscreened":
            return
        try:
            pool = db_conn.get_pool()
            await safety_repo.set_message_safety_verdict(pool, message.message_id, outcome.verdict.status)
        except Exception as exc:
            self._error("safety_verdict_persist", str(exc))
        if outcome.verdict.status == "unsafe":
            flag_id = await self._flag(
                sender_type="agent",
                sender=message.sender,
                content=message.content,
                context=outcome.context,
                verdict=outcome.verdict,
                message_id=message.message_id,
                displayed_at=datetime.now(timezone.utc),
            )
            outcome.flag_id = flag_id
            self._event(
                "safety_flag_opened",
                {"flag_id": flag_id, "sender": message.sender, "categories": outcome.verdict.categories},
            )

    # ── participant path ──────────────────────────────────────────────────

    async def screen_participant(self, message: Message, state) -> Optional[SafetyVerdict]:
        """Classify a participant message that is already in the room. Flag only."""
        if not self.enabled:
            return None
        verdict, context = await self._classify(message, state)
        if contains_explicit_violence_cue(message.content) and not explicitly_rejects_violence(message.content):
            categories = list(dict.fromkeys([*verdict.categories, "S1"]))
            verdict = SafetyVerdict(
                status="unsafe",
                categories=categories,
                raw=verdict.raw,
                model=verdict.model,
                latency_ms=verdict.latency_ms,
                error=verdict.error,
                prompt_hash=verdict.prompt_hash,
                rationale=verdict.rationale,
                reasoning=verdict.reasoning,
                policy_version=verdict.policy_version,
            )
        try:
            pool = db_conn.get_pool()
            await safety_repo.set_message_safety_verdict(
                pool,
                message.message_id,
                verdict.status if verdict.status in ("safe", "unsafe") else None,
            )
        except Exception as exc:
            self._error("safety_verdict_persist", str(exc))
        if verdict.status in ("unsafe", "unavailable"):
            flag_id = await self._flag(
                sender_type="participant",
                sender=message.sender,
                content=message.content,
                context=context,
                verdict=verdict,
                message_id=message.message_id,
                displayed_at=message.timestamp,
            )
            self._event(
                "safety_flag_opened",
                {"flag_id": flag_id, "sender": message.sender, "categories": verdict.categories,
                 "verdict": verdict.status},
            )
        return verdict

    # ── persistence helpers ───────────────────────────────────────────────

    async def _flag(
        self,
        *,
        sender_type: str,
        sender: str,
        content: str,
        context: str,
        verdict: SafetyVerdict,
        message_id: Optional[str],
        displayed_at: Optional[datetime],
    ) -> Optional[str]:
        flag_id = str(uuid.uuid4())
        try:
            pool = db_conn.get_pool()
            await safety_repo.insert_flag(
                pool,
                flag_id=flag_id,
                session_id=self.session_id,
                experiment_id=self.experiment_id,
                message_id=message_id,
                sender_type=sender_type,
                sender=sender,
                content=content,
                context_user_turn=context,
                verdict=verdict.status,
                categories=verdict.categories,
                raw_output=verdict.raw or None,
                rationale=verdict.rationale,
                reasoning=verdict.reasoning,
                policy_version=verdict.policy_version,
                model=verdict.model or None,
                prompt_hash=verdict.prompt_hash,
                latency_ms=verdict.latency_ms,
                error=verdict.error,
                displayed_at=displayed_at,
            )
            if message_id:
                await safety_repo.set_flag_seq(pool, flag_id, message_id)
            return flag_id
        except Exception as exc:
            self._error("safety_flag_persist", str(exc))
            return None

    def _event(self, name: str, data: dict) -> None:
        try:
            self.logger.log_event(name, data)
        except Exception:
            pass

    def _error(self, name: str, msg: str) -> None:
        try:
            self.logger.log_error(name, msg)
        except Exception:
            pass
