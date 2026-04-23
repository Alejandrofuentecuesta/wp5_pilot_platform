"""Unit tests for agents/STAGE/director.py — parsing and formatting (Update + Evaluate + Action)."""
import json
import pytest
from datetime import datetime, timezone

from models.message import Message
from models.agent import Agent
from agents.STAGE.director import (
    format_chat_log,
    format_agent_profiles,
    format_participant_hint,
    format_treatment_fidelity_summary,
    build_action_system_prompt,
    parse_update_response,
    parse_evaluate_response,
    parse_action_response,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _msg(sender="Alice", content="Hello", msg_id="msg-1", **kwargs):
    return Message(
        sender=sender,
        content=content,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        message_id=msg_id,
        **kwargs,
    )


# ── format_chat_log ─────────────────────────────────────────────────────────

class TestFormatChatLog:
    def test_empty_messages(self):
        assert format_chat_log([]) == "(No messages yet)"

    def test_single_message(self):
        result = format_chat_log([_msg()])
        assert "[msg-1] Alice: Hello" in result

    def test_multiple_messages_each_on_own_line(self):
        msgs = [
            _msg(sender="Alice", content="Hi", msg_id="m1"),
            _msg(sender="Bob", content="Hey", msg_id="m2"),
        ]
        result = format_chat_log(msgs)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "[m1] Alice: Hi" in lines[0]
        assert "[m2] Bob: Hey" in lines[1]

    def test_reply_metadata(self):
        msg = _msg(reply_to="m0")
        result = format_chat_log([msg])
        assert "replying to m0" in result

    def test_mention_metadata(self):
        msg = _msg(mentions=["Bob", "Carol"])
        result = format_chat_log([msg])
        assert "@mentions Bob, Carol" in result

    def test_liked_by_metadata(self):
        msg = _msg(liked_by={"Bob", "Carol"})
        result = format_chat_log([msg])
        assert "liked by" in result
        assert "Bob" in result
        assert "Carol" in result

    def test_multiple_metadata_separated_by_semicolons(self):
        msg = _msg(reply_to="m0", mentions=["Bob"], liked_by={"Carol"})
        result = format_chat_log([msg])
        assert ";" in result

    def test_news_message_uses_headline_instead_of_full_body(self):
        msg = _msg(
            sender="[news]",
            content="Headline here\n\nVery long article body that should not be copied into the director chat log.",
            metadata={"headline": "Headline here"},
        )
        result = format_chat_log([msg])
        assert "Headline shared earlier: Headline here" in result
        assert "Very long article body" not in result


# ── format_agent_profiles ──────────────────────────────────────────────────

class TestFormatAgentProfiles:
    def test_empty_profiles(self):
        result = format_agent_profiles({})
        assert "No performer profiles yet" in result

    def test_profiles_with_content(self):
        profiles = {"Performer 1": "Took a sceptical stance", "Performer 2": ""}
        result = format_agent_profiles(profiles)
        assert "**Performer 1**: Took a sceptical stance" in result
        assert "**Performer 2**: (This performer has not acted yet.)" in result

    def test_profiles_with_traits(self):
        profiles = {"Performer 1": "Took a sceptical stance"}
        traits = {"Performer 1": {"stance": "disagree", "incivility": "uncivil", "ideology": "right"}}
        result = format_agent_profiles(profiles, traits=traits)
        assert "Fixed traits" in result
        assert "stance=disagree" in result
        assert "incivility=uncivil" in result
        assert "ideology=right" in result


class TestFormatParticipantHint:
    def test_empty_hint(self):
        assert "No pre-session stance survey" in format_participant_hint(None)

    def test_favor_hint(self):
        result = format_participant_hint("favor")
        assert "in favor" in result

    def test_qualified_favor_hint(self):
        result = format_participant_hint("qualified_favor")
        assert "broadly in favor" in result
        assert "specific measure" in result


class TestFormatTreatmentFidelitySummary:
    def test_empty_messages(self):
        assert "No classifier-derived treatment metrics yet" in format_treatment_fidelity_summary([])

    def test_summary_with_messages(self):
        msgs = [
            _msg(
                sender="Alice",
                content="Hi",
                is_incivil=False,
                is_like_minded=True,
                inferred_participant_stance="pro social spending",
                metadata={"stance_confidence": "high"},
            ),
            _msg(
                sender="Bob",
                content="Rude",
                is_incivil=True,
                is_like_minded=False,
            ),
        ]
        result = format_treatment_fidelity_summary(msgs)
        assert "Incivil messages: 1/2" in result
        assert "Like-minded messages: 1/2" in result
        assert "confidence=high" in result


class TestBuildActionSystemPrompt:
    def test_clarifies_stance_is_relative_to_participant(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate climatico",
            participant_stance_hint="participant self-report: against the article",
            participant_name="Martin",
        )
        assert "relative to the participant's stance in this session" in prompt
        assert "If the participant is against the article" in prompt
        assert "Always reason from alignment with the participant first" in prompt

    def test_handles_qualified_participant_stances_without_changing_agent_fixed_sides(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate climatico",
            participant_stance_hint="participant self-report: broadly in favor of the article's direction, but with important reservations about the specific measure",
            participant_name="Martin",
        )
        assert "Qualified participant stances" in prompt
        assert "`qualified_favor` counts with favor" in prompt
        assert "prefer disagreement that is close to the participant's frame" in prompt
        assert "adequacy, realism, or design of the measure" in prompt

    def test_adds_secondary_topic_stance_selector_without_redefining_like_minded(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate migratorio",
            participant_stance_hint="participant self-report: against the article",
            participant_name="Martin",
        )
        assert "Secondary topic-stance selector" in prompt
        assert "Do **not** redefine `like-minded` or `not-like-minded` with it" in prompt
        assert "The participant's stance on the **measure** still decides" in prompt
        assert "what **kind** of support or opposition will feel most natural" in prompt

    def test_topic_stance_rules_cover_pro_topic_against_measure_case(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate migratorio",
            participant_stance_hint="participant self-report: broadly against the measure as framed, but not necessarily aligned with the opposite ideological camp",
            participant_name="Martin",
        )
        assert "If `participant_topic_stance = pro_topic`" in prompt
        assert "prefer `like-minded` performers who are still broadly `pro_topic` but criticize this specific measure" in prompt
        assert "performers who are broadly `pro_topic` but defend the measure" in prompt
        assert "performers who are broadly `anti_topic` and oppose the participant from a harder ideological position" in prompt

    def test_requires_targeted_room_messages_to_name_opposition_and_non_validation(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate migratorio",
            participant_stance_hint="participant self-report: against the article",
            participant_name="Martin",
        )
        assert "Targeted room messages" in prompt
        assert "must not validate or echo" in prompt
        assert "When using `message`, make the contrast explicit" in prompt
        assert "not to agree with, praise, or echo the participant" in prompt

    def test_discourages_room_wide_openers_when_recent_anchor_exists(self):
        prompt = build_action_system_prompt(
            chatroom_context="Debate migratorio",
            participant_stance_hint="participant self-report: against the article",
            participant_name="Martin",
        )
        assert "Non-targeted room messages are exceptional" in prompt
        assert "Treat this as a last resort, not a default action" in prompt
        assert "If the latest message already gives you a natural anchor, use it" in prompt
        assert "treat a new room-wide opener as the wrong choice" in prompt


# ── parse_update_response — valid inputs ─────────────────────────────────────

class TestParseUpdateResponseValid:
    def test_plain_json(self):
        raw = json.dumps({"performer_profile_update": "Active and friendly."})
        data = parse_update_response(raw)
        assert data["performer_profile_update"] == "Active and friendly."

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"performer_profile_update":"neutral"}\n```'
        data = parse_update_response(raw)
        assert data["performer_profile_update"] == "neutral"


# ── parse_update_response — invalid inputs ───────────────────────────────────

class TestParseUpdateResponseInvalid:
    def test_not_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_update_response("this is not json")

    def test_missing_performer_profile_update(self):
        raw = json.dumps({"something_else": "ok"})
        with pytest.raises(ValueError, match="performer_profile_update"):
            parse_update_response(raw)


# ── parse_evaluate_response — valid inputs ───────────────────────────────────

class TestParseEvaluateResponseValid:
    def test_plain_json(self):
        raw = json.dumps({
            "internal_validity_evaluation": "Good",
            "ecological_validity_evaluation": "Natural",
        })
        data = parse_evaluate_response(raw)
        assert data["internal_validity_evaluation"] == "Good"
        assert data["ecological_validity_evaluation"] == "Natural"

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"internal_validity_evaluation":"ok","ecological_validity_evaluation":"fine"}\n```'
        data = parse_evaluate_response(raw)
        assert data["internal_validity_evaluation"] == "ok"


# ── parse_evaluate_response — invalid inputs ─────────────────────────────────

class TestParseEvaluateResponseInvalid:
    def test_not_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_evaluate_response("this is not json")

    def test_missing_internal_validity(self):
        raw = json.dumps({"ecological_validity_evaluation": "ok"})
        with pytest.raises(ValueError, match="internal_validity_evaluation"):
            parse_evaluate_response(raw)

    def test_missing_ecological_validity(self):
        raw = json.dumps({"internal_validity_evaluation": "ok"})
        with pytest.raises(ValueError, match="ecological_validity_evaluation"):
            parse_evaluate_response(raw)


# ── parse_action_response — valid inputs ────────────────────────────────────────

class TestParseActionResponseValid:
    def test_plain_json(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "message",
            "performer_instruction": {
                "objective": "say hi",
                "motivation": "join the conversation",
                "directive": "keep it short",
            },
        })
        data = parse_action_response(raw)
        assert data["next_performer"] == "Alice"
        assert data["action_type"] == "message"

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"next_performer":"Alice","action_type":"message","performer_instruction":{"objective":"greet","motivation":"be social","directive":"sound casual"}}\n```'
        data = parse_action_response(raw)
        assert data["next_performer"] == "Alice"

    def test_reply_action(self):
        raw = json.dumps({
            "next_performer": "Bob",
            "action_type": "reply",
            "target_message_id": "msg-42",
            "performer_instruction": {
                "objective": "agree",
                "motivation": "support the point",
                "directive": "be concise",
            },
        })
        data = parse_action_response(raw)
        assert data["action_type"] == "reply"
        assert data["target_message_id"] == "msg-42"

    def test_like_action(self):
        raw = json.dumps({
            "next_performer": "Bob",
            "action_type": "like",
            "target_message_id": "msg-42",
        })
        data = parse_action_response(raw)
        assert data["action_type"] == "like"

    def test_mention_action(self):
        raw = json.dumps({
            "next_performer": "Carol",
            "action_type": "@mention",
            "target_user": "Dave",
            "performer_instruction": {
                "objective": "ask question",
                "motivation": "bring them back in",
                "directive": "make it friendly",
            },
        })
        data = parse_action_response(raw)
        assert data["target_user"] == "Dave"

    def test_like_does_not_require_performer_instruction(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "like",
            "target_message_id": "msg-1",
        })
        data = parse_action_response(raw)
        assert "performer_instruction" not in data


# ── parse_action_response — invalid inputs ──────────────────────────────────────

class TestParseActionResponseInvalid:
    def test_not_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_action_response("this is not json at all")

    def test_missing_next_performer(self):
        raw = json.dumps({"action_type": "message", "performer_instruction": {}})
        with pytest.raises(ValueError, match="next_performer"):
            parse_action_response(raw)

    def test_missing_action_type(self):
        raw = json.dumps({"next_performer": "Alice", "performer_instruction": {}})
        with pytest.raises(ValueError, match="action_type"):
            parse_action_response(raw)

    def test_invalid_action_type(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "shout",
            "performer_instruction": {},
        })
        with pytest.raises(ValueError, match="invalid action_type"):
            parse_action_response(raw)

    def test_reply_missing_target_message_id(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "reply",
            "performer_instruction": {"objective": "agree"},
        })
        with pytest.raises(ValueError, match="target_message_id"):
            parse_action_response(raw)

    def test_like_missing_target_message_id(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "like",
        })
        with pytest.raises(ValueError, match="target_message_id"):
            parse_action_response(raw)

    def test_mention_missing_target_user(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "@mention",
            "performer_instruction": {"objective": "greet"},
        })
        with pytest.raises(ValueError, match="target_user"):
            parse_action_response(raw)

    def test_message_missing_performer_instruction(self):
        raw = json.dumps({
            "next_performer": "Alice",
            "action_type": "message",
        })
        with pytest.raises(ValueError, match="performer_instruction"):
            parse_action_response(raw)
