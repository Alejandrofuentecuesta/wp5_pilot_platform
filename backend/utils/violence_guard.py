"""Narrow deterministic checks for explicit physical-violence handling."""
from __future__ import annotations

import re
import unicodedata


def _plain(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


def contains_explicit_violence_cue(text: str | None) -> bool:
    """Detect explicit violence and common Spanish euphemisms for it."""
    value = _plain(text)
    return bool(re.search(
        r"\b(?:"
        r"moler(?:los|las|le|les)?\s+a\s+palos|"
        r"hinchar(?:los|las|le|les)?\s+a\s+hostias|"
        r"echar(?:los|las|le|les)?\s+a\s+palos|"
        r"(?:dar|pegar)(?:les|le|los|las)?\s+(?:de\s+|con\s+(?:el\s+|los\s+|un\s+|unos\s+)?)?"
        r"(?:palos|hostias|bate|bates|machetazos)|"
        r"pegar(?:les|le|los|las)\b|"
        r"golpear(?:les|le|los|las)?\b|"
        r"(?:apalear|linchar|reventar|machacar)(?:les|le|los|las)?\b|"
        r"partir(?:les|le)?\s+(?:la\s+)?cara|romper(?:les|le)?\s+(?:las?\s+)?piernas?|"
        r"(?:a|con)\s+(?:palos|hostias|bates?|machetes?|navajas?|cadenas?)\b|"
        r"(?:salir|ir|salgamos|vamos|coger|cojamos|armarse|armarnos)\s+con\s+(?:el\s+|los\s+|un\s+|unos\s+)?"
        r"(?:bates?|machetes?|navajas?|cadenas?)|"
        r"un(?:os)?\s+palos\b|"
        r"dos\s+tiros|tiro\s+en\s+la\s+cabeza|"
        r"(?:disparar|matar|asesinar)(?:los|las|le|les)?|"
        r"poner\s+(?:una\s+)?bomba|violencia\s+armada|"
        r"patrullas?\s+ciudadanas?\s+contra|"
        r"(?:hacer|tomar(?:se)?)\s+(?:la\s+)?justicia\s+por\s+(?:su|nuestra|mi)?\s*mano\s+propia|"
        r"justicia\s+por\s+(?:su|nuestra|mi)?\s*mano\s+propia|"
        r"dar(?:les|le)?\s+(?:un\s+)?(?:escarmiento|buen\s+susto)|"
        r"ajustar\s+cuentas\s+con|ir\s+a\s+por\s+(?:ellos|ellas)|"
        r"que\s+aprendan\s+por\s+las\s+malas|"
        r"poner(?:les|los|las)?\s+en\s+su\s+sitio|"
        r"cazar(?:los|las|le|les)\b|"
        r"(?:salir|ir|salimos|vamos)(?:emos)?\s+de\s+caza\s+de\s+"
        r"(?:moros|inmigrantes|musulmanes|magrebies|extranjeros|sudacas|negros|gitanos|menas)\b"
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
        r"\b(?:yo\s+)?me\s+apunto\b|\bcuenta\s+conmigo\b|\bahi\s+estare\b|"
        r"\b(?:ya\s+)?no\s+queda\s+otra\b|"
        r"\b(?:dale|darles?|darle)\s+cana\b|"
        r"\b(?:a\s+por\s+ellos|se\s+lo\s+merecen|que\s+aprendan\s+por\s+las\s+malas)\b|"
        r"\b(?:hacerles?|hacerlos?)\s+pagar\b|"
        r"\bponer(?:les|los|las)?\s+en\s+su\s+sitio\b|"
        r"\bmano\s+dura\b",
        value,
    ))
