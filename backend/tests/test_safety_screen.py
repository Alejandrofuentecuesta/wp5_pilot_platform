"""SafetyScreen policy: publish/withhold decisions and the flags they open.

safe        → publish, verdict on message, no flag
unsafe      → withheld and flagged until a reviewer approves publication
unavailable → agent turn withheld and flagged (no message_id); participant
              message flagged only
disabled    → nothing screened, nothing written
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.message import Message
from platforms.safety_screen import SafetyScreen
from utils.safety import DEFAULT_CATEGORIES, SafetyVerdict


class FakeClient:
    def __init__(self, verdict: SafetyVerdict, raise_exc: bool = False):
        self.verdict = verdict
        self.raise_exc = raise_exc
        self.prompts = []

    async def classify(self, prompt):
        self.prompts.append(prompt)
        if self.raise_exc:
            raise RuntimeError("boom")
        return self.verdict


class FakeChatClient:
    """Stands in for the anthropic_messages transport (system/user, not one raw prompt)."""

    transport = "anthropic_messages"

    def __init__(self, verdict: SafetyVerdict):
        self.verdict = verdict
        self.calls = []

    async def classify_chat(self, system, user):
        self.calls.append((system, user))
        return self.verdict

    async def classify(self, prompt):  # pragma: no cover - must never be used in chat mode
        raise AssertionError("classify() called instead of classify_chat() for anthropic_messages transport")


def _state(*messages):
    return SimpleNamespace(messages=list(messages), user_name="Paula")


def _screen(client, enabled=True, seed="Artículo de prueba", context_mode="always"):
    logger = MagicMock()
    return SafetyScreen(
        session_id="sess",
        experiment_id="exp",
        logger=logger,
        client=client,
        categories=list(DEFAULT_CATEGORIES),
        enabled=enabled,
        user_name="Paula",
        seed_text=seed,
        context_mode=context_mode,
    ), logger


@pytest.fixture
def repo():
    with patch("platforms.safety_screen.db_conn") as db, patch("platforms.safety_screen.safety_repo") as sr:
        db.get_pool.return_value = MagicMock()
        sr.insert_flag = AsyncMock()
        sr.set_message_safety_verdict = AsyncMock()
        sr.set_flag_seq = AsyncMock()
        yield sr


class TestAgentPath:
    async def test_safe_publishes_without_flag(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="safe")))
        msg = Message.create(sender="Carlos", content="Hola")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is True
        await screen.after_publish(msg, out)
        repo.set_message_safety_verdict.assert_awaited_once_with(repo.set_message_safety_verdict.call_args[0][0], msg.message_id, "safe")
        repo.insert_flag.assert_not_awaited()

    async def test_unsafe_hate_output_is_withheld_and_flagged(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="unsafe\nS10", model="g", prompt_hash="h")
        screen, logger = _screen(FakeClient(v))
        user = Message.create(sender="Paula", content="Los moros fuera")
        msg = Message.create(sender="Carlos", content="Eso, fuera todos")
        out = await screen.screen_agent(msg, _state(user))
        assert out.publish is False
        kw = repo.insert_flag.call_args.kwargs
        assert kw["sender_type"] == "agent"
        assert kw["message_id"] is None
        assert kw["verdict"] == "unsafe"
        assert kw["categories"] == ["S10"]
        assert kw["context_user_turn"] == "Los moros fuera"
        assert kw["displayed_at"] is None
        assert kw["prompt_hash"] == "h"
        assert logger.log_event.call_args[0][0] == "safety_turn_withheld"

    @pytest.mark.parametrize("category", ["S1", "S9"])
    async def test_violent_or_weapon_output_is_withheld(self, repo, category):
        v = SafetyVerdict(
            status="unsafe",
            categories=[category],
            raw=f"unsafe\n{category}",
            model="g",
            prompt_hash="h",
        )
        screen, logger = _screen(FakeClient(v))
        msg = Message.create(sender="Carlos", content="contenido violento")

        out = await screen.screen_agent(msg, _state())

        assert out.publish is False
        kw = repo.insert_flag.call_args.kwargs
        assert kw["verdict"] == "unsafe"
        assert kw["categories"] == [category]
        assert kw["message_id"] is None
        assert kw["displayed_at"] is None
        assert logger.log_event.call_args[0][0] == "safety_turn_withheld"

    async def test_unavailable_withholds_and_flags(self, repo):
        v = SafetyVerdict(status="unavailable", error="ConnectError: refused")
        screen, logger = _screen(FakeClient(v))
        msg = Message.create(sender="Carlos", content="texto retenido")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is False
        kw = repo.insert_flag.call_args.kwargs
        assert kw["verdict"] == "unavailable"
        assert kw["message_id"] is None
        assert kw["displayed_at"] is None
        assert kw["content"] == "texto retenido"
        assert kw["error"] == "ConnectError: refused"
        assert logger.log_event.call_args[0][0] == "safety_turn_withheld"
        repo.set_message_safety_verdict.assert_not_awaited()

    async def test_client_exception_withholds(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe"), raise_exc=True))
        msg = Message.create(sender="Carlos", content="x")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is False
        assert repo.insert_flag.call_args.kwargs["verdict"] == "unavailable"

    async def test_flag_persist_failure_still_withholds(self, repo):
        repo.insert_flag = AsyncMock(side_effect=RuntimeError("db down"))
        screen, logger = _screen(FakeClient(SafetyVerdict(status="unavailable", error="timeout")))
        out = await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())
        assert out.publish is False
        assert out.flag_id is None
        assert logger.log_error.called

    async def test_user_turn_is_latest_participant_message(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client)
        state = _state(
            Message.create(sender="Paula", content="primero"),
            Message.create(sender="Carlos", content="agente"),
            Message.create(sender="Paula", content="segundo"),
        )
        await screen.screen_agent(Message.create(sender="Carlos", content="resp"), state)
        assert "User: segundo\n\nAgent: resp\n\n" in client.prompts[0]
        assert "agente" not in client.prompts[0]

    async def test_seed_used_before_first_participant_message(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client, seed="Cuerpo del artículo")
        await screen.screen_agent(Message.create(sender="Carlos", content="resp"), _state())
        assert "User: Cuerpo del artículo\n\n" in client.prompts[0]

    async def test_context_none_uses_neutral_turn(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client, context_mode="none")
        state = _state(Message.create(sender="Paula", content="los moros fuera"))
        await screen.screen_agent(Message.create(sender="Carlos", content="resp"), state)
        assert "User: (no participant message)\n\nAgent: resp" in client.prompts[0]
        assert "moros" not in client.prompts[0]

    async def test_context_conditional_only_after_unsafe_participant_turn(self, repo):
        client = FakeClient(SafetyVerdict(status="unsafe", categories=["S10"], raw="unsafe\nS10"))
        screen, _ = _screen(client, context_mode="conditional")
        benign = Message.create(sender="Paula", content="hola a todos")
        hateful = Message.create(sender="Paula", content="los moros fuera")
        # Participant turn not yet screened -> neutral context.
        await screen.screen_agent(Message.create(sender="Carlos", content="r1"), _state(benign))
        assert "User: (no participant message)" in client.prompts[-1]
        # Participant turn screened safe -> still neutral.
        screen._participant_verdicts[benign.message_id] = "safe"
        await screen.screen_agent(Message.create(sender="Carlos", content="r2"), _state(benign))
        assert "User: (no participant message)" in client.prompts[-1]
        # Participant turn screened unsafe -> included.
        await screen.screen_participant(hateful)
        assert screen._participant_verdicts[hateful.message_id] == "unsafe"
        await screen.screen_agent(Message.create(sender="Carlos", content="r3"), _state(benign, hateful))
        assert "User: los moros fuera\n\nAgent: r3" in client.prompts[-1]

    async def test_context_conditional_includes_explicit_violence_even_after_safe_verdict(self, repo):
        client = FakeClient(SafetyVerdict(status="safe", raw="safe"))
        screen, _ = _screen(client, context_mode="conditional")
        violent = Message.create(sender="Paula", content="Habria que molerlos a palos")
        screen._participant_verdicts[violent.message_id] = "safe"

        await screen.screen_agent(Message.create(sender="Carlos", content="Exacto"), _state(violent))

        assert "User: Habria que molerlos a palos\n\nAgent: Exacto" in client.prompts[-1]

    def test_unknown_context_mode_rejected(self):
        with pytest.raises(ValueError):
            _screen(None, context_mode="sometimes")

    async def test_disabled_screen_publishes_and_writes_nothing(self, repo):
        screen, _ = _screen(None, enabled=False)
        msg = Message.create(sender="Carlos", content="x")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is True
        await screen.after_publish(msg, out)
        repo.set_message_safety_verdict.assert_not_awaited()
        repo.insert_flag.assert_not_awaited()

    async def test_enabled_without_client_is_disabled(self, repo):
        screen, _ = _screen(None, enabled=True)
        assert screen.enabled is False


class TestParticipantPath:
    async def test_safe_records_verdict_only(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe")))
        msg = Message.create(sender="Paula", content="hola")
        await screen.screen_participant(msg)
        repo.set_message_safety_verdict.assert_awaited_once()
        repo.insert_flag.assert_not_awaited()

    @pytest.mark.parametrize("content", [
        "A esos habría que molerlos a palos",
        "A cualquier cosa le llaman violencia, unos palos y calentitos pa casa",
        "Entonces estáis a favor de pegarles no?",
        "Di que sí, y si no dos tiros en la cabeza",
        "Estoy buscando gente para formar patrullas ciudadanas contra los inmigrantes",
    ])
    async def test_explicit_violence_cue_is_escalated_to_s1_when_model_says_safe(self, repo, content):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="safe")))
        msg = Message.create(sender="Paula", content=content)

        verdict = await screen.screen_participant(msg)

        assert verdict is not None
        assert verdict.status == "unsafe"
        assert "S1" in verdict.categories
        assert screen._participant_verdicts[msg.message_id] == "unsafe"
        assert repo.insert_flag.call_args.kwargs["categories"] == ["S1"]

    async def test_explicit_rejection_is_not_escalated(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="safe")))
        msg = Message.create(sender="Paula", content="La violencia nunca es una solución")

        verdict = await screen.screen_participant(msg)

        assert verdict is not None and verdict.status == "safe"
        repo.insert_flag.assert_not_awaited()

    async def test_do_not_hit_them_is_not_escalated(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="safe")))
        msg = Message.create(sender="Paula", content="No hay que pegarles, la violencia no sirve")

        verdict = await screen.screen_participant(msg)

        assert verdict is not None and verdict.status == "safe"
        repo.insert_flag.assert_not_awaited()

    async def test_unsafe_flags_as_participant(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S11"], raw="unsafe\nS11")
        client = FakeClient(v)
        screen, _ = _screen(client)
        msg = Message.create(sender="Paula", content="me quiero morir")
        await screen.screen_participant(msg)
        kw = repo.insert_flag.call_args.kwargs
        assert kw["sender_type"] == "participant"
        assert kw["categories"] == ["S11"]
        assert kw["message_id"] == msg.message_id
        assert kw["displayed_at"] == msg.timestamp
        assert "ONLY THE LAST User message" in client.prompts[0]

    async def test_unavailable_flags_but_message_stays(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="unavailable", error="timeout")))
        msg = Message.create(sender="Paula", content="x")
        v = await screen.screen_participant(msg)
        assert v.status == "unavailable"
        assert repo.insert_flag.call_args.kwargs["verdict"] == "unavailable"
        # Verdict column stays NULL: no verdict was obtained.
        assert repo.set_message_safety_verdict.call_args[0][2] is None

    async def test_disabled_does_nothing(self, repo):
        screen, _ = _screen(None, enabled=False)
        assert await screen.screen_participant(Message.create(sender="Paula", content="x")) is None
        repo.insert_flag.assert_not_awaited()


class TestAnthropicTransport:
    """SafetyScreen must route to classify_chat(), not classify(), for this transport."""

    async def test_safe_uses_classify_chat_not_classify(self, repo):
        client = FakeChatClient(SafetyVerdict(status="safe", raw="safe"))
        screen, _ = _screen(client)
        msg = Message.create(sender="Carlos", content="Hola")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is True
        assert len(client.calls) == 1
        system, user = client.calls[0]
        assert "safety classifier" in system.lower()
        assert "LAST Agent message" in user

    async def test_unsafe_rationale_reaches_the_flag(self, repo):
        v = SafetyVerdict(
            status="unsafe",
            categories=["S10"],
            raw="unsafe\nS10\nRationale: targets an identity group.",
            rationale="targets an identity group.",
        )
        screen, _ = _screen(FakeChatClient(v))
        msg = Message.create(sender="Carlos", content="x")
        out = await screen.screen_agent(msg, _state())
        await screen.after_publish(msg, out)
        kw = repo.insert_flag.call_args.kwargs
        assert kw["rationale"] == "targets an identity group."
