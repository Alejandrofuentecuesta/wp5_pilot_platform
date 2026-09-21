"""Narrow deterministic checks for explicit physical-violence handling."""
from __future__ import annotations

import re
import unicodedata


def _plain(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


def contains_explicit_violence_cue(text: str | None) -> bool:
    """Detect a deliberately small set of unambiguous physical-violence cues."""
    value = _plain(text)
    return bool(re.search(
        r"\b(?:"
        r"moler(?:los|las|le|les)?\s+a\s+palos|"
        r"hinchar(?:los|las|le|les)?\s+a\s+hostias|"
        r"echar(?:los|las|le|les)?\s+a\s+palos|"
        r"(?:dar|pegar)(?:les|le|los|las)?\s+(?:de\s+)?(?:palos|hostias)|"
        r"pegar(?:les|le|los|las)\b|"
        r"(?:a|con)\s+(?:palos|hostias)\b|"
        r"un(?:os)?\s+palos\b|"
        r"dos\s+tiros|tiro\s+en\s+la\s+cabeza|"
        r"(?:disparar|matar|asesinar)(?:los|las|le|les)?|"
        r"poner\s+(?:una\s+)?bomba|violencia\s+armada|"
        r"patrullas?\s+ciudadanas?\s+contra"
        r")\b",
        value,
    ))


def explicitly_rejects_violence(text: str | None) -> bool:
    """Require an unmistakable rejection, not merely a topic change or hedge."""
    value = _plain(text)
    return bool(re.search(
        r"(?:"
        r"\bla\s+violencia\s+(?:nunca\s+)?(?:no\s+)?(?:es|sirve|lleva|soluciona)|"
        r"\bviolencia\s+(?:nunca|jamas)\b|"
        r"\bviolencia\s+(?:es\s+)?(?:inaceptable|inadmisible)|"
        r"\b(?:rechazo|rechazamos|condeno|condenamos)\s+(?:la\s+)?violencia|"
        r"\b(?:nunca|jamas)\s+(?:es|sera)\s+(?:una\s+)?solucion|"
        r"\bno\s+(?:hay\s+que|se\s+debe|debemos)\s+pegar(?:les|le|los|las)?|"
        r"\bno\s+(?:se\s+)?(?:puede|debe)\s+(?:aceptar|justificar)\s+la\s+violencia"
        r")",
        value,
    ))


def signals_violence_endorsement(text: str | None) -> bool:
    """Catch short approvals and coercive wording when violent context is active."""
    value = _plain(text)
    if contains_explicit_violence_cue(value):
        return True
    return bool(re.search(
        r"\b(?:exacto|claro\s+que\s+si|totalmente|eso\s+es|di\s+que\s+si)\b|"
        r"\bmano\s+dura\b",
        value,
    ))
