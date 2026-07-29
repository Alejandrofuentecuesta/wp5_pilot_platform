"""Regression tests for the HTML session report renderer."""

from utils.log_viewer import render_session_start


def test_session_start_renders_lists_of_config_objects():
    event = {
        "timestamp": "2026-07-29T11:12:26.866389+00:00",
        "session_id": "68e45b42-0905-4233-8f07-054d1110864d",
        "data": {
            "treatment_group": "incivil_mix",
            "experiment_id": "final",
            "experimental_config": {},
            "simulation_config": {
                "agent_names": ["Candela", "Natalia"],
                "humanize_word_subs_list": [
                    {
                        "word": "que",
                        "replacement": "q",
                        "prob": 55,
                        "enabled": True,
                    }
                ],
            },
        },
    }

    rendered = render_session_start(event)

    assert "humanize_word_subs_list" in rendered
    assert "&quot;replacement&quot;: &quot;q&quot;" in rendered
