"""Policy loading, conversation excerpt and verdict parsing."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from utils.safety.prompt import ACTIVE_POLICY, GAP_MARKER, load_policy, parse_verdict, render_excerpt

USER = "Paula"


def m(sender, content, reply_to=None, mid=None):
    m.n += 1
    return SimpleNamespace(message_id=mid or f"m{m.n}", sender=sender, content=content, reply_to=reply_to)


m.n = 0


def _lines(excerpt):
    return excerpt.split("\n\n")


class TestPolicy:
    def test_active_policy_loads_and_is_versioned(self):
        p = load_policy()
        assert p.name == ACTIVE_POLICY
        assert p.version == f"{ACTIVE_POLICY}@{p.sha256[:12]}"
        assert "## INSTRUCTIONS" in p.text and "## VIOLATES (1)" in p.text and "## SAFE (0)" in p.text
        for code in range(1, 15):
            assert f"S{code} - " in p.text

    def test_reference_policy_differs_only_in_s10(self):
        active, reference = load_policy(), load_policy("lg3-taxonomy_wp5_v1")
        assert "demean or dehumanize people" in reference.text
        assert "not S10" not in reference.text
        strip = lambda t: t[:t.index("S10 - Hate")] + t[t.index("S11 - Suicide"):t.index("## SAFE (0)")]
        assert strip(active.text).splitlines()[1:] == strip(reference.text).splitlines()[1:]

    def test_missing_policy_raises(self):
        with pytest.raises(FileNotFoundError):
            load_policy("no_such_policy")


class TestExcerpt:
    def test_window_is_target_plus_two_before(self):
        history = [m(USER, "uno"), m("Carlos", "dos"), m("Ana", "tres"), m(USER, "cuatro")]
        out = _lines(render_excerpt(m("Carlos", "cinco"), history, USER))
        assert out[:3] == ["Agent 1: tres", "User: cuatro", "Agent 2: cinco"]
        assert out[3] == "[Assess the last message above, written by Agent 2. The earlier messages are context only.]"

    def test_agents_numbered_by_appearance_and_same_agent_same_number(self):
        history = [m("Carlos", "a"), m("Ana", "b")]
        out = _lines(render_excerpt(m("Carlos", "c"), history, USER))
        assert out[:3] == ["Agent 1: a", "Agent 2: b", "Agent 1: c"]

    def test_latest_user_message_added_when_outside_window(self):
        history = [m(USER, "viejo"), m(USER, "voy a por él"), m("Carlos", "x"), m("Ana", "y"), m("Luis", "z")]
        out = _lines(render_excerpt(m("Marta", "hazlo"), history, USER))
        assert out[:6] == ["User: voy a por él", GAP_MARKER, "Agent 1: y", "Agent 2: z", "Agent 3: hazlo", out[5]]
        assert "viejo" not in "".join(out)

    def test_no_gap_marker_when_user_message_is_adjacent(self):
        history = [m(USER, "u"), m("Carlos", "x"), m("Ana", "y")]
        out = _lines(render_excerpt(m("Luis", "z"), history, USER))
        assert out[:4] == ["User: u", "Agent 1: x", "Agent 2: y", "Agent 3: z"]

    def test_quoted_message_added_when_outside_window(self):
        quoted = m("Carlos", "hay que echarlos a todos", mid="q1")
        history = [quoted, m("Ana", "otra cosa"), m(USER, "a"), m("Luis", "b"), m("Marta", "c")]
        out = _lines(render_excerpt(m("Jorge", "exacto", reply_to="q1"), history, USER))
        # The quoted message and the user's latest message are both outside
        # the window; each is added, with a gap marker where messages are left out.
        assert out[:7] == [
            "Agent 1: hay que echarlos a todos",
            GAP_MARKER,
            "User: a",
            "Agent 2: b",
            "Agent 3: c",
            "Agent 4: exacto",
            out[6],
        ]
        assert "otra cosa" not in "".join(out)

    def test_participant_target_gets_no_extra_user_message(self):
        history = [m(USER, "antes"), m("Carlos", "x"), m("Ana", "y"), m("Luis", "z")]
        out = _lines(render_excerpt(m(USER, "me quiero morir"), history, USER))
        assert out[:3] == ["Agent 1: y", "Agent 2: z", "User: me quiero morir"]
        assert out[3].startswith("[Assess the last message above, written by User.")

    def test_first_message_of_session(self):
        out = _lines(render_excerpt(m("Carlos", "hola"), [], USER))
        assert out == ["Agent 1: hola", "[Assess the last message above, written by Agent 1. The earlier messages are context only.]"]

    def test_empty_messages_are_skipped(self):
        history = [m("Carlos", "a"), m("Ana", "   "), m("Luis", "b")]
        out = _lines(render_excerpt(m("Marta", "c"), history, USER))
        assert out[:3] == ["Agent 1: a", "Agent 2: b", "Agent 3: c"]


class TestParseVerdict:
    def test_safe(self):
        assert parse_verdict('{"violation": 0, "categories": [], "rationale": "ok"}') == ("safe", [], "ok")

    def test_unsafe_multiple_categories(self):
        raw = '{"violation": 1, "categories": ["S1", "S10"], "rationale": "calls for violence"}'
        assert parse_verdict(raw) == ("unsafe", ["S1", "S10"], "calls for violence")

    def test_json_surrounded_by_text(self):
        raw = 'Here is my answer:\n```json\n{"violation": 1, "categories": ["S11"], "rationale": "x"}\n```'
        assert parse_verdict(raw) == ("unsafe", ["S11"], "x")

    def test_category_codes_are_normalised(self):
        raw = '{"violation": 1, "categories": ["s10", "S10 - Hate", "S01"], "rationale": "x"}'
        assert parse_verdict(raw) == ("unsafe", ["S10", "S1"], "x")

    def test_boolean_violation_accepted(self):
        assert parse_verdict('{"violation": true, "categories": ["S1"]}') == ("unsafe", ["S1"], None)

    def test_unsafe_without_categories_is_still_unsafe(self):
        assert parse_verdict('{"violation": 1, "categories": [], "rationale": "x"}') == ("unsafe", [], "x")

    @pytest.mark.parametrize("raw", [
        None,
        "",
        "safe",
        "unsafe\nS10",
        '{"violation": 2, "categories": []}',
        '{"violation": "1", "categories": []}',
        '{"categories": ["S1"]}',
        '{"violation": 1, "categories": "S1"}',
        '{"violation": 1, "categories": ["S15"]}',
        '{"violation": 1, "categories": ["hate"]}',
        '{"violation": 0, "categories": ["S10"]}',
        '{"violation": 1, "categories": [',
    ])
    def test_anything_else_is_unavailable(self, raw):
        assert parse_verdict(raw) == ("unavailable", [], None)
