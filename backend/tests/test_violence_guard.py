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
        "A que habría que salir con bates a enseñarles qué es lo que pasa",
        "Habría que darles con el bate",
        "Vamos con los bates y arreglamos esto",
        "Hay que ir con machetes a por ellos",
        "Salir con los bates es la única solución",
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


@pytest.mark.parametrize(
    "text",
    [
        "Le compré un bate de béisbol a mi hijo por su cumpleaños",
        "Los bates de aluminio son más ligeros que los de madera",
        "Vamos a ver el partido de béisbol el sábado",
        "Con los bates que tenemos en el equipo podemos ganar la liga",
    ],
)
def test_bare_bat_mention_without_violent_verb_is_not_a_cue(text):
    """'un bate'/'los bates' alone is overwhelmingly literal (baseball, a gift)
    in Spanish, unlike 'unos palos' which is a standalone beating idiom — so
    only the verb/preposition-anchored patterns should fire for bats."""
    assert not contains_explicit_violence_cue(text)
