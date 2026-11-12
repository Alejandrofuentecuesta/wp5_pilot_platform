"""PersonalDataFilter: replaces flagged text in values about to be written."""
from __future__ import annotations

import json

from utils.personal_data_filter import (
    MIN_SUBSTRING_LENGTH,
    PERSONAL_DATA_PLACEHOLDER,
    PersonalDataFilter,
)

SECRET = 'Me llamo Ana García Pérez, "vivo" en Vallecas'


def _filter(*texts):
    data_filter = PersonalDataFilter()
    for text in texts:
        data_filter.add(text)
    return data_filter


def test_inactive_filter_returns_the_value_itself():
    data_filter = PersonalDataFilter()
    value = {"content": SECRET}
    assert data_filter.active is False
    assert data_filter.apply(value) is value


def test_replaces_the_text_in_nested_string_values_and_leaves_keys():
    data_filter = _filter(SECRET)
    value = {SECRET: [SECRET, {"prompt": f"antes {SECRET} después"}], "n": 3, "ok": True, "none": None}

    result = data_filter.apply(value)

    assert result == {
        SECRET: [PERSONAL_DATA_PLACEHOLDER, {"prompt": f"antes {PERSONAL_DATA_PLACEHOLDER} después"}],
        "n": 3, "ok": True, "none": None,
    }


def test_replaces_the_json_escaped_form_inside_a_prompt():
    data_filter = _filter(SECRET)
    prompt = "Chat data (JSON):\n" + json.dumps({"latest_participant_message": SECRET}, ensure_ascii=False)

    result = data_filter.apply(prompt)

    assert "García" not in result
    assert json.loads(result.split("\n", 1)[1]) == {"latest_participant_message": PERSONAL_DATA_PLACEHOLDER}


def test_does_not_mutate_the_original():
    data_filter = _filter(SECRET)
    value = {"content": SECRET, "items": [SECRET]}

    data_filter.apply(value)

    assert value == {"content": SECRET, "items": [SECRET]}


def test_short_text_is_replaced_only_as_a_whole_value():
    short = "Ana Gil"
    assert len(short) < MIN_SUBSTRING_LENGTH
    data_filter = _filter(short)

    assert data_filter.apply(short) == PERSONAL_DATA_PLACEHOLDER
    assert data_filter.apply("Ana Gil dice que sí") == "Ana Gil dice que sí"


def test_longer_flagged_text_is_replaced_whole_before_a_shorter_one():
    longer = "Soy Ana García Pérez y mi teléfono es 612345678"
    inner = "Ana García Pérez"
    data_filter = _filter(inner, longer)

    assert data_filter.apply(longer) == PERSONAL_DATA_PLACEHOLDER
    assert data_filter.apply(f"Cita: {inner}") == f"Cita: {PERSONAL_DATA_PLACEHOLDER}"


def test_blank_and_duplicate_texts_are_ignored():
    data_filter = _filter("", "   ", SECRET, SECRET)
    assert data_filter.texts == [SECRET]
