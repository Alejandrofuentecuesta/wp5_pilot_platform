"""Conservative, one-shot correction of the survey side from the first post."""
import re
import unicodedata
from typing import Optional


RESOLUTION_KEY = "participant_alignment_resolution"

# Match direct assertions, not mentions of a topic elsewhere in the message.
_PERSONAL = r"(?:(?:yo|personalmente)\s+)?"
_BELIEF = r"(?:(?:creo|pienso|considero) que\s+)?"
_IMMIGRATION = r"(?:la inmigracion|la acogida de (?:personas )?inmigrantes|la regularizacion de (?:personas )?inmigrantes)\b"
_CLIMATE_POLICY = r"(?:las energias renovables|la transicion (?:energetica|ecologica)|las (?:leyes|normativas|regulaciones) (?:medioambientales|ambientales)|la reduccion de emisiones)\b"
_RULES = {
    "immigration": {
        "pro_topic": [
            _PERSONAL + r"(?:estoy|soy) (?:claramente )?a favor de " + _IMMIGRATION,
            _PERSONAL + r"(?:apoyo|defiendo) " + _IMMIGRATION,
            _BELIEF + r"la inmigracion (?:es positiva|es beneficiosa|beneficia a nuestro pais)\b",
            _BELIEF + r"la inmigracion es un derecho\b",
            _BELIEF + r"(?:las personas inmigrantes|los inmigrantes) (?:se esfuerzan por integrarse|aportan a nuestra sociedad)\b",
        ],
        "anti_topic": [
            _PERSONAL + r"(?:estoy|soy) (?:claramente )?en contra de " + _IMMIGRATION,
            _PERSONAL + r"rechazo " + _IMMIGRATION,
            _BELIEF + r"(?:hay que|debemos) (?:restringir|frenar|reducir) la inmigracion\b",
            _BELIEF + r"(?:las personas inmigrantes|los inmigrantes) (?:reciben un trato de favor|no (?:hacen|hacen ningun) esfuerzo por integrarse)\b",
        ],
    },
    "climate_change": {
        "pro_topic": [
            _PERSONAL + r"(?:estoy|soy) (?:claramente )?a favor de " + _CLIMATE_POLICY,
            _PERSONAL + r"(?:apoyo|defiendo) " + _CLIMATE_POLICY,
            _BELIEF + r"(?:hay que|debemos) (?:priorizar (?:las energias renovables|la transicion energetica)|reducir las emisiones|cumplir los objetivos (?:internacionales )?de (?:emision de )?co2)\b",
        ],
        "anti_topic": [
            _PERSONAL + r"(?:estoy|soy) (?:claramente )?en contra de " + _CLIMATE_POLICY,
            _PERSONAL + r"(?:rechazo|no apoyo) " + _CLIMATE_POLICY,
            _BELIEF + r"(?:hay que|debemos) priorizar (?:las energias no renovables|el carbon|el gas)\b",
            _BELIEF + r"(?:el gobierno no deberia|no debemos) (?:dar prioridad al cumplimiento de los objetivos|priorizar los objetivos) de (?:emision de )?co2\b",
        ],
    },
}


def infer_clear_topic_stance(content: str, topic: str) -> tuple[Optional[str], list[str]]:
    """Abstain on ambiguity; generic approval of an article is not a topic side."""
    text = "".join(
        char for char in unicodedata.normalize("NFKD", content.lower())
        if not unicodedata.combining(char)
    )
    if re.search(r'["\u201c\u201d\u00ab\u00bb\u2018\u2019\x27?>]', text) or re.search(
        r"\b(?:pero|aunque|sin embargo|no obstante|quizas|tal vez|depende|"
        r"no se|no tengo claro|es broma|ironia|sarcasmo|no es verdad|"
        r"dice|dicen|dijo|segun|salvo|excepto|si|no digo|no pienso|no creo)\b", text,
    ):
        return None, []
    clauses = [" ".join(part.split()).strip() for part in re.split(r"[.!;\n]+", text)]
    evidence = []
    sides = set()
    for side, patterns in _RULES.get(topic, {}).items():
        for index, pattern in enumerate(patterns):
            if any(re.match(pattern, clause) for clause in clauses):
                sides.add(side)
                evidence.append(f"{topic}:{side}:{index + 1}")
    if len(sides) != 1:
        return None, []
    side = next(iter(sides))
    if side == "pro_topic" and re.search(r"\b(?:no|nunca|jamas|tampoco)\b", text):
        return None, []
    return side, evidence


def resolve_first_message_alignment(
    *, survey_stance: Optional[str], survey_cell: Optional[str], content: str,
    topic: str, message_id: str,
) -> dict:
    inferred_cell, evidence = infer_clear_topic_stance(content, topic)
    corrected = bool(survey_cell and inferred_cell and survey_cell != inferred_cell)
    return {
        "version": 1,
        "survey_stance": survey_stance,
        "survey_cell": survey_cell,
        "first_message_id": message_id,
        "topic": topic,
        "inferred_cell": inferred_cell,
        "effective_cell": inferred_cell if corrected or not survey_cell else survey_cell,
        "source": "first_message_correction" if corrected else (
            "survey" if survey_cell else "first_message" if inferred_cell else "unresolved"
        ),
        "evidence": evidence,
        "locked": True,
    }
