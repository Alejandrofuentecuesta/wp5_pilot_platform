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
from utils.safety import SafetyVerdict, load_policy


class FakeClient:
    def __init__(self, verdict: SafetyVerdict, raise_exc: bool = False):
        self.verdict = verdict
        self.raise_exc = raise_exc
        self.policies = []
        self.prompts = []

    async def classify(self, policy, excerpt):
        self.policies.append(policy)
        self.prompts.append(excerpt)
        if self.raise_exc:
            raise RuntimeError("boom")
        return self.verdict


def _state(*messages):
    return SimpleNamespace(messages=list(messages), user_name="Paula")


def _screen(client, enabled=True):
    logger = MagicMock()
    return SafetyScreen(
        session_id="sess",
        experiment_id="exp",
        logger=logger,
        client=client,
        enabled=enabled,
        user_name="Paula",
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
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="{}")))
        msg = Message.create(sender="Carlos", content="Hola")
        out = await screen.screen_agent(msg, _state())
        assert out.publish is True
        await screen.after_publish(msg, out)
        repo.set_message_safety_verdict.assert_awaited_once_with(repo.set_message_safety_verdict.call_args[0][0], msg.message_id, "safe")
        repo.insert_flag.assert_not_awaited()

    async def test_unsafe_hate_output_is_withheld_and_flagged(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="{}", model="g", prompt_hash="h")
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
        assert kw["context_user_turn"].startswith("User: Los moros fuera\n\nAgent 1: Eso, fuera todos\n\n")
        assert kw["policy_version"] == load_policy().version
        assert kw["displayed_at"] is None
        assert kw["prompt_hash"] == "h"
        assert logger.log_event.call_args[0][0] == "safety_turn_withheld"

    @pytest.mark.parametrize("category", ["S1", "S9"])
    async def test_violent_or_weapon_output_is_withheld(self, repo, category):
        v = SafetyVerdict(
            status="unsafe",
            categories=[category],
            raw="{}",
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

    async def test_policy_and_excerpt_are_sent(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client)
        state = _state(
            Message.create(sender="Paula", content="primero"),
            Message.create(sender="Carlos", content="agente"),
            Message.create(sender="Paula", content="segundo"),
        )
        await screen.screen_agent(Message.create(sender="Ana", content="resp"), state)
        assert client.policies[0] == load_policy().text
        assert client.prompts[0].startswith("Agent 1: agente\n\nUser: segundo\n\nAgent 2: resp\n\n")
        assert "primero" not in client.prompts[0]

    async def test_participant_message_outside_window_is_included(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client)
        state = _state(
            Message.create(sender="Paula", content="voy a por mi vecino"),
            Message.create(sender="Carlos", content="uno"),
            Message.create(sender="Ana", content="dos"),
            Message.create(sender="Luis", content="tres"),
        )
        await screen.screen_agent(Message.create(sender="Marta", content="hazlo"), state)
        assert client.prompts[0].startswith(
            "User: voy a por mi vecino\n\n[...]\n\nAgent 1: dos\n\nAgent 2: tres\n\nAgent 3: hazlo\n\n"
        )

    async def test_render_failure_withholds(self, repo):
        client = FakeClient(SafetyVerdict(status="safe"))
        screen, _ = _screen(client)
        out = await screen.screen_agent(Message.create(sender="Carlos", content="x"), SimpleNamespace(messages=[None]))
        assert out.publish is False
        assert repo.insert_flag.call_args.kwargs["verdict"] == "unavailable"
        assert client.prompts == []

    async def test_rationale_and_reasoning_reach_the_flag(self, repo):
        v = SafetyVerdict(
            status="unsafe", categories=["S10"], raw="{}", rationale="dehumanises a group", reasoning="The message ...",
        )
        screen, _ = _screen(FakeClient(v))
        await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())
        kw = repo.insert_flag.call_args.kwargs
        assert kw["rationale"] == "dehumanises a group"
        assert kw["reasoning"] == "The message ..."

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
        await screen.screen_participant(msg, _state(msg))
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
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="{}")))
        msg = Message.create(sender="Paula", content=content)

        verdict = await screen.screen_participant(msg, _state(msg))

        assert verdict is not None
        assert verdict.status == "unsafe"
        assert "S1" in verdict.categories
        assert repo.insert_flag.call_args.kwargs["categories"] == ["S1"]

    async def test_explicit_rejection_is_not_escalated(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="{}")))
        msg = Message.create(sender="Paula", content="La violencia nunca es una solución")

        verdict = await screen.screen_participant(msg, _state(msg))

        assert verdict is not None and verdict.status == "safe"
        repo.insert_flag.assert_not_awaited()

    async def test_do_not_hit_them_is_not_escalated(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe", raw="{}")))
        msg = Message.create(sender="Paula", content="No hay que pegarles, la violencia no sirve")

        verdict = await screen.screen_participant(msg, _state(msg))

        assert verdict is not None and verdict.status == "safe"
        repo.insert_flag.assert_not_awaited()

    async def test_unsafe_flags_as_participant(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S11"], raw="{}")
        client = FakeClient(v)
        screen, _ = _screen(client)
        msg = Message.create(sender="Paula", content="me quiero morir")
        await screen.screen_participant(msg, _state(msg))
        kw = repo.insert_flag.call_args.kwargs
        assert kw["sender_type"] == "participant"
        assert kw["categories"] == ["S11"]
        assert kw["message_id"] == msg.message_id
        assert kw["displayed_at"] == msg.timestamp
        assert client.prompts[0].startswith("User: me quiero morir\n\n[Assess the last message above, written by User.")

    async def test_unavailable_flags_but_message_stays(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="unavailable", error="timeout")))
        msg = Message.create(sender="Paula", content="x")
        v = await screen.screen_participant(msg, _state(msg))
        assert v.status == "unavailable"
        assert repo.insert_flag.call_args.kwargs["verdict"] == "unavailable"
        # Verdict column stays NULL: no verdict was obtained.
        assert repo.set_message_safety_verdict.call_args[0][2] is None

    async def test_disabled_does_nothing(self, repo):
        screen, _ = _screen(None, enabled=False)
        msg = Message.create(sender="Paula", content="x")
        assert await screen.screen_participant(msg, _state(msg)) is None
        repo.insert_flag.assert_not_awaited()


class TestPendingReviewBlocking:
    """An agent with an unreviewed withheld flag must not be selectable again
    until that flag is resolved — otherwise a second, unrelated turn from the
    same agent can publish while the first is still awaiting review."""

    async def test_withheld_agent_turn_blocks_the_agent(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="{}")
        screen, _ = _screen(FakeClient(v))
        assert screen.pending_review_agents() == set()

        msg = Message.create(sender="Carlos", content="x")
        out = await screen.screen_agent(msg, _state())

        assert out.publish is False
        assert screen.pending_review_agents() == {"Carlos"}

    async def test_unavailable_agent_turn_also_blocks(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="unavailable", error="timeout")))
        await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())
        assert screen.pending_review_agents() == {"Carlos"}

    async def test_safe_agent_turn_does_not_block(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe")))
        await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())
        assert screen.pending_review_agents() == set()

    async def test_participant_flag_does_not_block_any_agent(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="unsafe", categories=["S11"])))
        msg = Message.create(sender="Paula", content="x")
        await screen.screen_participant(msg, _state(msg))
        assert screen.pending_review_agents() == set()

    async def test_resolve_flag_unblocks_the_agent(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="{}")
        screen, _ = _screen(FakeClient(v))
        out = await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())

        screen.resolve_flag(out.flag_id, "Carlos")

        assert screen.pending_review_agents() == set()

    async def test_resolve_flag_without_agent_name_scans_all(self, repo):
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="{}")
        screen, _ = _screen(FakeClient(v))
        out = await screen.screen_agent(Message.create(sender="Carlos", content="x"), _state())

        screen.resolve_flag(out.flag_id)

        assert screen.pending_review_agents() == set()

    async def test_two_pending_flags_for_same_agent_both_must_resolve(self, repo):
        """Defensive: an agent blocked twice stays blocked until every flag clears."""
        v = SafetyVerdict(status="unsafe", categories=["S10"], raw="{}")
        screen, _ = _screen(FakeClient(v))
        first = await screen.screen_agent(Message.create(sender="Carlos", content="a"), _state())
        # Second withheld flag injected directly (the agent should already be
        # excluded from selection by the caller, but the bookkeeping must
        # still be correct if it somehow happens).
        screen._pending_review_agents["Carlos"].add("extra-flag")

        screen.resolve_flag(first.flag_id, "Carlos")
        assert screen.pending_review_agents() == {"Carlos"}

        screen.resolve_flag("extra-flag", "Carlos")
        assert screen.pending_review_agents() == set()

    async def test_resolving_unknown_flag_is_a_noop(self, repo):
        screen, _ = _screen(FakeClient(SafetyVerdict(status="safe")))
        screen.resolve_flag("does-not-exist", "Nobody")
        screen.resolve_flag("does-not-exist")
        assert screen.pending_review_agents() == set()
