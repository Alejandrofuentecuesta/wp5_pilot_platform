"""The safety gate between the simulation and the participant.

Every agent message passes through ``screen_agent`` before it is persisted or
broadcast, and every participant message passes through ``screen_participant``
after it is posted. The policy:

* ``safe``        — publish; verdict recorded on the message.
* ``unsafe``      — agent turns are withheld and flagged for human review.
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
from typing import Dict, List, Optional, Tuple

from db import connection as db_conn
from db.repositories import safety_repo
from models.message import Message
from utils.safety import NEUTRAL_USER_TURN, Category, SafetyClient, SafetyVerdict, render_prompt

CONTEXT_MODES = ("none", "conditional", "always")


@dataclass
class ScreenOutcome:
    publish: bool
    verdict: SafetyVerdict
    user_turn: str
    flag_id: Optional[str] = None


class SafetyScreen:
    def __init__(
        self,
        *,
        session_id: str,
        experiment_id: str,
        logger,
        client: Optional[SafetyClient],
        categories: List[Category],
        enabled: bool,
        user_name: str,
        seed_text: str = "",
        context_mode: str = "conditional",
    ) -> None:
        self.session_id = session_id
        self.experiment_id = experiment_id
        self.logger = logger
        self.client = client
        self.categories = categories
        self.enabled = bool(enabled and client is not None)
        self.user_name = user_name
        self.seed_text = (seed_text or "").strip()
        if context_mode not in CONTEXT_MODES:
            raise ValueError(f"unknown safety context_mode {context_mode!r}")
        # How much of the participant's side the agent screen sees:
        #   none         – never; the agent message is judged on its own
        #   conditional  – only when the participant's last message was itself
        #                  flagged (the case where endorsement matters)
        #   always       – the participant's last message every time
        self.context_mode = context_mode
        # message_id -> verdict status of participant messages screened here.
        self._participant_verdicts: Dict[str, str] = {}

    # ── conversation mapping ──────────────────────────────────────────────

    def _latest_participant(self, state) -> Optional[Message]:
        for m in reversed(getattr(state, "messages", []) or []):
            if m.sender == self.user_name and (m.content or "").strip():
                return m
        return None

    def _agent_conversation(self, message: Message, state) -> Tuple[List[Tuple[str, str]], str]:
        last = self._latest_participant(state)
        if self.context_mode == "always":
            user_turn = last.content if last else (self.seed_text or NEUTRAL_USER_TURN)
        elif self.context_mode == "conditional" and last is not None \
                and self._participant_verdicts.get(last.message_id) == "unsafe":
            user_turn = last.content
        else:
            user_turn = NEUTRAL_USER_TURN
        return [("user", user_turn), ("assistant", message.content)], user_turn

    # ── classification ────────────────────────────────────────────────────

    async def _classify(self, conversation: List[Tuple[str, str]]) -> SafetyVerdict:
        try:
            prompt = render_prompt(conversation, self.categories)
        except Exception as exc:
            return SafetyVerdict(status="unavailable", error=f"render: {exc}")
        try:
            verdict = await self.client.classify(prompt)
        except Exception as exc:  # the client should never raise; belt and braces
            verdict = SafetyVerdict(status="unavailable", error=f"client: {exc}")
        try:
            self.logger.log_llm_call(
                agent_name="__safety__",
                prompt=prompt,
                response=verdict.raw or None,
                error=verdict.error,
            )
        except Exception:
            pass
        return verdict

    # ── agent path ────────────────────────────────────────────────────────

    async def screen_agent(self, message: Message, state) -> ScreenOutcome:
        """Decide whether an agent message may be published.

        Returns ``publish=False`` when no verdict was obtained or when the
        agent output falls under any unsafe safety category. The
        withheld text is retained in a flag for review but never published.
        """
        if not self.enabled:
            return ScreenOutcome(publish=True, verdict=SafetyVerdict(status="unscreened"), user_turn="")
        try:
            conversation, user_turn = self._agent_conversation(message, state)
            verdict = await self._classify(conversation)
        except Exception as exc:
            verdict = SafetyVerdict(status="unavailable", error=f"screen: {exc}")
            user_turn = ""

        blocked_categories = set(verdict.categories) if verdict.status == "unsafe" else set()
        if verdict.status in {"unsafe", "unavailable"}:
            flag_id = await self._flag(
                sender_type="agent",
                sender=message.sender,
                content=message.content,
                user_turn=user_turn,
                verdict=verdict,
                message_id=None,
                displayed_at=None,
            )
            self._event(
                "safety_turn_withheld",
                {
                    "sender": message.sender,
                    "error": verdict.error,
                    "categories": sorted(blocked_categories),
                },
            )
            return ScreenOutcome(publish=False, verdict=verdict, user_turn=user_turn, flag_id=flag_id)

        return ScreenOutcome(publish=True, verdict=verdict, user_turn=user_turn)

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
                user_turn=outcome.user_turn,
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

    async def screen_participant(self, message: Message) -> Optional[SafetyVerdict]:
        """Classify a participant message that is already in the room. Flag only."""
        if not self.enabled:
            return None
        try:
            verdict = await self._classify([("user", message.content)])
        except Exception as exc:
            verdict = SafetyVerdict(status="unavailable", error=f"screen: {exc}")
        self._participant_verdicts[message.message_id] = verdict.status
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
                user_turn="",
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
        user_turn: str,
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
                context_user_turn=user_turn,
                verdict=verdict.status,
                categories=verdict.categories,
                raw_output=verdict.raw or None,
                model=verdict.model or None,
                prompt_hash=verdict.prompt_hash,
                unsafe_prob=verdict.unsafe_prob,
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
