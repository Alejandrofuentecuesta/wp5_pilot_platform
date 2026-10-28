"""Regression tests for the HTML session report renderer."""

from utils.log_viewer import render_agent_impressions, render_llm_call, render_session_start


def _impressions_event(survey):
    return {
        "timestamp": "2026-09-25T11:12:26.866389+00:00",
        "event_type": "agent_impressions",
        "data": {"ratings": [], "skipped": True, "report_block_survey": survey},
    }


def test_agent_impressions_shows_block_and_report_separately():
    rendered = render_agent_impressions(_impressions_event({
        "tempted_to_block": True,
        "tempted_block_agent_names": ["Candela"],
        "block_reasons": ["Porque me resulta molesto o incómodo"],
        "tempted_to_report": True,
        "tempted_report_agent_names": ["Diego"],
        "report_reasons": ["Porque difundía información falsa"],
        "report_other": None,
        "blocked_agent_names": [],
    }))

    assert "Tentado/a de bloquear a:</strong> Candela" in rendered
    assert "Motivos (bloquear):</strong> Porque me resulta molesto o incómodo" in rendered
    assert "Tentado/a de reportar a:</strong> Diego" in rendered
    assert "Motivos (reportar):</strong> Porque difundía información falsa" in rendered


def test_agent_impressions_shows_nobody_when_not_tempted():
    rendered = render_agent_impressions(_impressions_event({
        "tempted_to_block": False,
        "tempted_block_agent_names": [],
        "tempted_to_report": False,
        "tempted_report_agent_names": [],
        "blocked_agent_names": [],
    }))

    assert "Tentado/a de bloquear a:</strong> Nadie" in rendered
    assert "Tentado/a de reportar a:</strong> Nadie" in rendered


def test_agent_impressions_shows_actual_blocks():
    rendered = render_agent_impressions(_impressions_event({
        "blocked_agent_names": ["Diego"],
        "block_reasons": ["Porque me resulta molesto o incómodo"],
        "block_other": "Muy pesado",
        "tempted_report_agent_names": [],
    }))

    assert "Bloqueó a:</strong> Diego" in rendered
    assert "Otros: Muy pesado" in rendered


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
    assert "Timeline — started at 11:12:26.866 on 29/07/2026" in rendered


def test_render_llm_call_classifier_labels():
    alignment_call = {
        "timestamp": "2026-10-28T12:20:27.368369+00:00",
        "data": {
            "agent_name": "__participant_alignment_classifier__",
            "prompt": "prompt text",
            "response": '{"stance": "neutral"}',
        },
    }
    rendered = render_llm_call(alignment_call)
    assert "Classifier → Alignment" in rendered
    assert "llm-agent classifier" in rendered
    assert "Performer" not in rendered

    safety_call = {
        "timestamp": "2026-10-28T12:20:28.000000+00:00",
        "data": {
            "agent_name": "__participant_safety_classifier__",
            "prompt": "prompt text",
            "response": '{"status": "ok"}',
        },
    }
    rendered_safety = render_llm_call(safety_call)
    assert "Classifier → Safety" in rendered_safety
    assert "llm-agent classifier" in rendered_safety

