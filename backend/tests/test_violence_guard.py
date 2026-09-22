import pytest

from utils.violence_guard import (
    contains_explicit_violence_cue,
    explicitly_rejects_violence,
    signals_violence_endorsement,
)


@pytest.mark.parametrize(
    "text",
    [
        "Habría que hacer justicia por mano propia",
        "Yo digo de organizarnos para golpearlos",
        "Hay que darles un escarmiento",
        "Podríamos darles un buen susto",
        "Toca ir a por ellos",
        "Que aprendan por las malas",
    ],
)
def test_detects_explicit_and_euphemistic_violence(text):
    assert contains_explicit_violence_cue(text)


@pytest.mark.parametrize(
    "text",
    [
        "Dale caña a esos tíos",
        "La verdad es que ya no queda otra",
        "Hay que hacerles pagar",
        "Que aprendan por las malas",
        "Se lo merecen",
    ],
)
def test_detects_contextual_violence_endorsement(text):
    assert signals_violence_endorsement(text)


def test_clear_rejection_is_recognised_without_endorsement():
    text = "La violencia nunca es una solución y no se puede justificar"
    assert explicitly_rejects_violence(text)
    assert not signals_violence_endorsement(text)
