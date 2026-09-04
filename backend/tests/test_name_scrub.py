"""Tests for chatroom name helpers: folding, renames, alias picking.

The alias assigned by the backend is the participant's identity in every
record and is kept in the data on purpose. These helpers only compare and
rewrite names at session construction (collision renames in persona text).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from utils import name_scrub
from utils.name_scrub import (
    CANONICAL_NAME,
    fold,
    scrub_text,
)

from tests.test_chatroom import MINIMAL_CONFIG, _patch_externals


# ── Text scrubbing ────────────────────────────────────────────────────────────

class TestScrubText:
    def test_accent_insensitive_both_directions(self):
        text, changed = scrub_text("Lucía, eso no tiene sentido", "Lucia")
        assert changed and text == "participant, eso no tiene sentido"
        text, changed = scrub_text("Lucia dice tonterías", "Lucía")
        assert changed and text == "participant dice tonterías"

    def test_whole_word_only(self):
        text, changed = scrub_text("Los Lucianos no cuentan", "Lucia")
        assert not changed and "Lucianos" in text

    def test_diminutives_survive(self):
        # Known residual: a bot writing "Luci" is not matched.
        _, changed = scrub_text("Luci, ¿qué opinas?", "Lucia")
        assert not changed

    def test_multiple_occurrences_and_punctuation(self):
        text, changed = scrub_text("¿Lucia? ¡LUCIA! (lucía)", "Lucia")
        assert changed
        assert text == "¿participant? ¡participant! (participant)"

    def test_custom_replacement(self):
        text, _ = scrub_text("Lucia, 33, habla con calma.", "Lucia", replacement="Alba")
        assert text == "Alba, 33, habla con calma."

    def test_none_and_empty(self):
        assert scrub_text(None, "Lucia") == (None, False)
        assert scrub_text("", "Lucia") == ("", False)


# ── Collision rename at session construction ─────────────────────────────────

def _make_session(user_name, config=None):
    from platforms.chatroom import SimulationSession

    return SimulationSession(
        session_id="test-session",
        websocket_send=AsyncMock(),
        treatment_group="control",
        user_name=user_name,
        experiment_id="test-exp",
        _config=config or MINIMAL_CONFIG,
    )


class TestCollisionRename:
    def test_agent_sharing_participant_name_is_renamed(self):
        with _patch_externals():
            session = _make_session("alice")  # folds equal to roster "Alice"

            assert "Alice" not in session._agent_names
            assert len(session._agent_names) == 2
            assert "Bob" in session._agent_names

    def test_rename_updates_persona_text(self):
        config = json.loads(json.dumps(MINIMAL_CONFIG))
        config["simulation"]["agent_personas"] = [
            "Alice, 33, habla con calma.",
            "Bob es escéptico.",
        ]
        with _patch_externals():
            session = _make_session("Alice", config=config)

            renamed = next(n for n in session._agent_names if n != "Bob")
            persona = next(
                a.persona for a in session.state.agents if a.name == renamed
            )
            assert "Alice" not in persona
            assert persona.startswith(renamed)

    def test_no_rename_without_collision(self):
        with _patch_externals():
            session = _make_session("Rupert")

            assert session._agent_names == ["Alice", "Bob"]

    def test_gender_matched_alias_for_known_pool_name(self):
        config = json.loads(json.dumps(MINIMAL_CONFIG))
        config["simulation"]["agent_names"] = ["Lucia", "Carlos"]
        with _patch_externals():
            session = _make_session("Lucía", config=config)

            renamed = next(n for n in session._agent_names if n != "Carlos")
            # Lucia is a known female pool name; aliases alternate m/f with
            # Alba as the first female entry.
            assert renamed == "Alba"


# ── Participant alias assignment ─────────────────────────────────────────────

class TestPickParticipantAlias:
    def test_gender_matched(self):
        import random
        from platforms.chatroom import pick_participant_alias, _REPLACEMENT_AGENT_NAMES

        males = set(_REPLACEMENT_AGENT_NAMES[0::2])
        females = set(_REPLACEMENT_AGENT_NAMES[1::2])
        rng = random.Random(7)
        for _ in range(50):
            assert pick_participant_alias("m", rng) in males
            assert pick_participant_alias("f", rng) in females

    def test_unknown_gender_draws_from_full_list(self):
        import random
        from platforms.chatroom import pick_participant_alias, _REPLACEMENT_AGENT_NAMES

        rng = random.Random(7)
        drawn = {pick_participant_alias(None, rng) for _ in range(200)}
        assert drawn <= set(_REPLACEMENT_AGENT_NAMES)
        # Both genders appear when no preference is given.
        assert drawn & set(_REPLACEMENT_AGENT_NAMES[0::2])
        assert drawn & set(_REPLACEMENT_AGENT_NAMES[1::2])

    def test_alias_collision_with_roster_renames_the_agent(self):
        """End-to-end guard: an alias equal to a roster agent's name must
        trigger the construction-time rename, keeping the alias unique."""
        with _patch_externals():
            session = _make_session("Alice")  # alias role: user_name is the alias

            assert "Alice" not in session._agent_names
            assert session.state.user_name == "Alice"
