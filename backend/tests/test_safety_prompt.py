"""Llama Guard 3 prompt rendering and verdict parsing.

The renderer must produce exactly what the model's own chat template
produces, otherwise verdicts obtained here are not comparable with the
model's documented behaviour. The template string below is copied verbatim
from ``meta-llama/Llama-Guard-3-8B/tokenizer_config.json``.
"""
from __future__ import annotations

import jinja2
import pytest

from utils.safety.prompt import (
    DEFAULT_CATEGORIES,
    Category,
    categories_from_config,
    parse_verdict,
    render_chat_prompt,
    render_prompt,
)

HF_CHAT_TEMPLATE = (
    "{% if messages|length % 2 == 0 %}{% set role = 'Agent' %}{% else %}{% set role = 'User' %}{% endif %}"
    "{{ \" <|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
    "Task: Check if there is unsafe content in '\" + role + \"' messages in conversations according our safety policy with the below categories.\n\n"
    "<BEGIN UNSAFE CONTENT CATEGORIES>\n"
    "S1: Violent Crimes.\nS2: Non-Violent Crimes.\nS3: Sex Crimes.\nS4: Child Exploitation.\n"
    "S5: Defamation.\nS6: Specialized Advice.\nS7: Privacy.\nS8: Intellectual Property.\n"
    "S9: Indiscriminate Weapons.\nS10: Hate.\nS11: Self-Harm.\nS12: Sexual Content.\n"
    "S13: Elections.\nS14: Code Interpreter Abuse.\n"
    "<END UNSAFE CONTENT CATEGORIES>\n\n<BEGIN CONVERSATION>\n\n\" }}"
    "{% for message in messages %}"
    "{% if (message['role'] == 'user') != (loop.index0 % 2 == 0) %}"
    "{{ raise_exception('Conversation roles must alternate user/assistant/user/assistant/...') }}"
    "{% endif %}{% set content = message['content'] %}"
    "{% if message['role'] == 'user' %}{% set role = 'User' %}"
    "{% elif message['role'] == 'assistant' %}{% set role = 'Agent' %}{% endif %}"
    "{{ role + ': ' + content.strip() + '\n\n' }}{% endfor %}"
    "{{ \"<END CONVERSATION>\n\nProvide your safety assessment for ONLY THE LAST \" + role + \" message in the above conversation:\n"
    " - First line must read 'safe' or 'unsafe'.\n"
    " - If unsafe, a second line must include a comma-separated list of violated categories."
    "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\" }}"
)


def _hf_render(messages):
    env = jinja2.Environment()

    def raise_exception(msg):
        raise ValueError(msg)

    env.globals["raise_exception"] = raise_exception
    return env.from_string(HF_CHAT_TEMPLATE).render(messages=messages)


class TestRenderMatchesMetaTemplate:
    def test_two_turn_response_classification(self):
        conv = [("user", "  Los moros nos invaden  "), ("assistant", "Eso es una mentira, joder.\n")]
        messages = [{"role": r if r == "user" else "assistant", "content": t} for r, t in conv]
        assert render_prompt(conv) == _hf_render(messages)

    def test_one_turn_prompt_classification(self):
        conv = [("user", "Quiero matar a mi vecino")]
        assert render_prompt(conv) == _hf_render([{"role": "user", "content": conv[0][1]}])
        assert "ONLY THE LAST User message" in render_prompt(conv)

    def test_two_turn_judges_agent(self):
        out = render_prompt([("user", "a"), ("assistant", "b")])
        assert "unsafe content in 'Agent' messages" in out
        assert "ONLY THE LAST Agent message" in out

    def test_roles_must_alternate(self):
        with pytest.raises(ValueError):
            render_prompt([("assistant", "x")])
        with pytest.raises(ValueError):
            render_prompt([("user", "x"), ("user", "y")])

    def test_empty_conversation_rejected(self):
        with pytest.raises(ValueError):
            render_prompt([])

    def test_default_categories_are_the_fourteen_titles(self):
        assert [c.code for c in DEFAULT_CATEGORIES] == [f"S{i}" for i in range(1, 15)]
        assert all(c.definition is None for c in DEFAULT_CATEGORIES)


class TestCustomCategories:
    def test_definition_rendered_under_title(self):
        cats = [Category("S10", "Hate", "Only slurs directed at the participant.")]
        out = render_prompt([("user", "x")], cats)
        assert "S10: Hate.\nOnly slurs directed at the participant.\n<END UNSAFE" in out

    def test_from_config_defaults_when_absent(self):
        assert categories_from_config(None) == DEFAULT_CATEGORIES
        assert categories_from_config([]) == DEFAULT_CATEGORIES

    def test_disabled_entries_are_omitted(self):
        cats = categories_from_config([
            {"code": "S10", "title": "Hate", "enabled": True},
            {"code": "S13", "title": "Elections", "enabled": False},
        ])
        assert [c.code for c in cats] == ["S10"]
        out = render_prompt([("user", "x")], cats)
        assert "S13" not in out

    def test_full_policy_marks_omitted_codes_disabled(self):
        from utils.safety.prompt import full_policy
        rows = {r["code"]: r for r in full_policy([{"code": "S10", "title": "Hate", "definition": "d"}])}
        assert rows["S10"]["enabled"] is True and rows["S10"]["definition"] == "d"
        assert rows["S1"]["enabled"] is False
        assert all(r["enabled"] for r in full_policy(None))

    def test_from_config_requires_code_and_title(self):
        with pytest.raises(ValueError):
            categories_from_config([{"code": "S1"}])


class TestParseVerdict:
    @pytest.mark.parametrize("raw", ["safe", "safe\n", "  Safe  ", "safe\n\n"])
    def test_safe(self, raw):
        assert parse_verdict(raw) == ("safe", [], None)

    def test_unsafe_with_categories(self):
        assert parse_verdict("unsafe\nS10,S1") == ("unsafe", ["S10", "S1"], None)
        assert parse_verdict("unsafe\nS11") == ("unsafe", ["S11"], None)
        assert parse_verdict("unsafe\n s10 , s1 \n") == ("unsafe", ["S10", "S1"], None)

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "unsafe", "unsafe\nhate", "maybe", "safe unsafe", "unsafe\n", "I think it's safe"],
    )
    def test_anything_else_is_unavailable(self, raw):
        assert parse_verdict(raw) == ("unavailable", [], None)

    def test_unsafe_rationale_is_captured_and_label_stripped(self):
        status, cats, rationale = parse_verdict("unsafe\nS1,S9\nRationale: it endorses armed violence.")
        assert (status, cats) == ("unsafe", ["S1", "S9"])
        assert rationale == "it endorses armed violence."

    def test_safe_rationale_is_captured(self):
        status, cats, rationale = parse_verdict("safe\nRationale: no policy is violated.")
        assert (status, cats) == ("safe", [])
        assert rationale == "no policy is violated."

    def test_no_trailing_lines_means_no_rationale(self):
        assert parse_verdict("unsafe\nS1")[2] is None


class TestRenderChatPrompt:
    def test_system_prompt_contains_categories_and_format_instructions(self):
        system, _ = render_chat_prompt([("user", "a"), ("assistant", "b")])
        assert "S1: Violent Crimes." in system
        assert "S14: Code Interpreter Abuse." in system
        assert "'safe' or 'unsafe'" in system
        assert "Rationale:" in system

    def test_judges_agent_on_even_turn_count(self):
        system, user = render_chat_prompt([("user", "a"), ("assistant", "b")])
        assert "unsafe content in 'Agent' messages" in system
        assert "LAST Agent message" in user

    def test_judges_user_on_single_turn(self):
        system, user = render_chat_prompt([("user", "Quiero matar a mi vecino")])
        assert "unsafe content in 'User' messages" in system
        assert "LAST User message" in user
        assert "Quiero matar a mi vecino" in user

    def test_custom_categories_included(self):
        cats = [Category("S10", "Hate", "Only slurs directed at the participant.")]
        system, _ = render_chat_prompt([("user", "x")], cats)
        assert "S10: Hate.\nOnly slurs directed at the participant." in system
        assert "S1: Violent Crimes" not in system

    def test_roles_must_alternate(self):
        with pytest.raises(ValueError):
            render_chat_prompt([("assistant", "x")])

    def test_empty_conversation_rejected(self):
        with pytest.raises(ValueError):
            render_chat_prompt([])
