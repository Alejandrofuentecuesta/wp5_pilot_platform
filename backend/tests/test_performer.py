"""Unit tests for agents/STAGE/performer.py — simplified prompt building."""
from datetime import datetime, timezone

from models.message import Message
from agents.STAGE.performer import (
    _format_target_message,
    _resolve_performer_action_type,
    build_performer_user_prompt,
    build_performer_system_prompt,
)


def _msg(sender="Alice", content="Hello", msg_id="m1", **kwargs):
    return Message(
        sender=sender,
        content=content,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        message_id=msg_id,
        **kwargs,
    )


# ── _resolve_performer_action_type ─────────────────────────────────────────

class TestResolvePerformerActionType:
    def test_message_without_target(self):
        assert _resolve_performer_action_type("message", None) == "message"

    def test_message_with_target(self):
        assert _resolve_performer_action_type("message", "Bob") == "message_targeted"

    def test_reply_passthrough(self):
        assert _resolve_performer_action_type("reply", None) == "reply"

    def test_mention_passthrough(self):
        assert _resolve_performer_action_type("@mention", "Bob") == "@mention"


# ── _format_target_message ─────────────────────────────────────────────────

class TestFormatTargetMessage:
    def test_none_target(self):
        result = _format_target_message(None)
        assert "no target" in result.lower()

    def test_with_target(self):
        msg = _msg(sender="Bob", content="What do you think?")
        result = _format_target_message(msg)
        assert "Bob: What do you think?" in result


# ── build_performer_system_prompt ──────────────────────────────────────────

class TestBuildPerformerSystemPrompt:
    def test_returns_string(self):
        result = build_performer_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_system_prompt_is_concise(self):
        """The unified template injects chatroom context into the system prompt."""
        result = build_performer_system_prompt(chatroom_context="Climate debate")
        assert "chatroom" in result.lower()
        assert "Climate debate" in result

    def test_system_prompt_limits_message_length(self):
        result = build_performer_system_prompt()
        assert "default to 2-3 short sentences" in result
        assert "do not go beyond 3 sentences" in result


# ── build_performer_user_prompt ────────────────────────────────────────────

class TestBuildPerformerUserPrompt:
    def _instruction(self):
        return {"objective": "greet everyone", "motivation": "warmth", "directive": "be casual"}

    def test_contains_individual_fields(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Friendly and active participant.",
            action_type="message",
        )
        assert "greet everyone" in result
        assert "warmth" in result
        assert "be casual" in result

    def test_contains_agent_profile(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Has been sceptical throughout.",
            action_type="message",
        )
        assert "Has been sceptical throughout." in result

    def test_empty_profile_shows_placeholder(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="",
            action_type="message",
        )
        assert "first action" in result.lower()

    def test_message_standalone(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="message",
        )
        assert "not responding to anyone" in result.lower()

    def test_message_targeted(self):
        target = _msg(sender="Bob", content="Interesting point")
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="message",
            target_user="Bob",
            target_message=target,
        )
        assert "Bob" in result
        assert "Interesting point" in result

    def test_reply_includes_target(self):
        target = _msg(sender="Bob", content="Interesting point")
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="reply",
            target_message=target,
        )
        assert "Bob: Interesting point" in result
        assert "quoted above" in result.lower()

    def test_mention_includes_target_user(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="@mention",
            target_user="Charlie",
        )
        assert "Charlie" in result
        assert "@mention" in result.lower() or "directed at" in result.lower()

    def test_chatroom_context_in_user_prompt(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="",
            action_type="message",
            chatroom_context="Climate debate",
        )
        assert "Climate debate" in result

    def test_renders_action_type_block(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="reply",
            target_message=_msg(sender="Bob", content="Earlier message"),
            chatroom_context="Test room",
        )
        # Should include the reply block content
        assert "quoted above" in result.lower()
        # Should NOT include other action type blocks
        assert "not responding to anyone" not in result.lower()

    def test_message_targeted_with_context(self):
        result = build_performer_user_prompt(
            instruction=self._instruction(),
            agent_profile="Active user.",
            action_type="message",
            target_user="Bob",
            target_message=_msg(sender="Bob", content="Hey there"),
            chatroom_context="Test room",
        )
        assert "Bob" in result
        assert "Hey there" in result
        # Should NOT include standalone message block
        assert "not responding to anyone" not in result.lower()
