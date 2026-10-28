import pytest

from utils.participant_alignment import infer_clear_topic_stance, resolve_first_message_alignment


@pytest.mark.parametrize("topic,text,expected", [
    ("immigration", "Estoy a favor de la inmigracion.", "pro_topic"),
    ("immigration", "Personalmente apoyo la inmigraci\u00f3n", "pro_topic"),
    ("immigration", "La inmigracion es un derecho.", "pro_topic"),
    ("immigration", "Creo que la inmigracion es positiva para nuestro pais.", "pro_topic"),
    ("immigration", "Estoy en contra de la inmigracion.", "anti_topic"),
    ("immigration", "Hay que restringir la inmigracion", "anti_topic"),
    ("immigration", "Los inmigrantes reciben un trato de favor del Estado", "anti_topic"),
    ("immigration", "Los inmigrantes no hacen ningun esfuerzo por integrarse", "anti_topic"),
    ("climate_change", "Estoy a favor de las energias renovables", "pro_topic"),
    ("climate_change", "Debemos priorizar las energias renovables", "pro_topic"),
    ("climate_change", "Apoyo las leyes medioambientales mas estrictas", "pro_topic"),
    ("climate_change", "Hay que cumplir los objetivos internacionales de CO2", "pro_topic"),
    ("climate_change", "Estoy en contra de las energias renovables", "anti_topic"),
    ("climate_change", "No apoyo las normativas medioambientales mas estrictas", "anti_topic"),
    ("climate_change", "Debemos priorizar el gas para reducir costes", "anti_topic"),
    ("climate_change", "El Gobierno no deberia dar prioridad al cumplimiento de los objetivos de emision de CO2", "anti_topic"),
])
def test_explicit_topic_statements(topic, text, expected):
    side, evidence = infer_clear_topic_stance(text, topic)
    assert side == expected
    assert evidence


@pytest.mark.parametrize("text", [
    "Hola a todos, ya he leido la noticia.",
    "Estoy a favor de esta medida", "Estoy en contra de esta medida",
    "La medida esta mal planteada", "No estoy a favor de la inmigracion",
    "No creo que la inmigracion es positiva", "Quizas apoyo la inmigracion",
    "Estoy a favor de la inmigracion pero tengo dudas",
    "Estoy a favor de la inmigracion. Estoy en contra de la inmigracion.",
    'Dice: "Estoy en contra de la inmigracion"',
    "'Estoy en contra de la inmigracion' es una frase ajena",
    "Segun Pedro, la inmigracion es positiva",
    "Estoy en contra de la inmigracion, dice Pedro",
    "Si estoy en contra de la inmigracion, me cambiariais de grupo",
    "Estoy en contra de la inmigracion?",
    "Estoy a favor de la inmigracion. Es broma.",
    "Estoy a favor de la inmigracion. No es lo que pienso.",
    "No se. Estoy en contra de la inmigracion.",
    "El cambio climatico es real", "El cambio climatico es una farsa",
])
def test_ambiguous_generic_quoted_and_unrelated_statements_do_not_override(text):
    for topic in ("immigration", "climate_change", "unknown"):
        assert infer_clear_topic_stance(text, topic) == (None, [])


@pytest.mark.parametrize("survey,inferred", [("pro_topic", "anti_topic"), ("anti_topic", "pro_topic")])
def test_only_a_clear_opposite_side_corrects_the_survey(survey, inferred):
    text = "Estoy en contra de la inmigracion" if inferred == "anti_topic" else "Apoyo la inmigracion"
    result = resolve_first_message_alignment(
        survey_stance=survey, survey_cell=survey, content=text,
        topic="immigration", message_id="first",
    )
    assert result["survey_stance"] == survey
    assert result["effective_cell"] == inferred
    assert result["source"] == "first_message_correction"
    assert result["locked"] is True
    assert result["first_message_id"] == "first"


@pytest.mark.parametrize("text", ["Hola", "Apoyo la inmigracion", "Estoy en contra de esta medida"])
def test_no_contradiction_keeps_survey(text):
    result = resolve_first_message_alignment(
        survey_stance="favor", survey_cell="pro_topic", content=text,
        topic="immigration", message_id="first",
    )
    assert result["survey_stance"] == "favor"
    assert result["effective_cell"] == "pro_topic"
    assert result["source"] == "survey"
