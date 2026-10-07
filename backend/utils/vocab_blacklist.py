"""Session-wide vocabulary blacklist for agent messages.

Once a distinctive political label, slang term, or contempt formula has
appeared anywhere in the chat, agents must not use it again for the rest of
the session, unless they are answering the very message that used it.
Matching is accent- and case-insensitive because the humanizer drops accents.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional

# label -> pattern over accent-stripped, lowercased text.
BLACKLIST_TERMS: Dict[str, str] = {
    "buenismo / buenista": r"\bbuenis(?:mo|tas?)\b",
    "facha": r"\bfachas?\b",
    "negacionista": r"\bnegacionistas?\b",
    "chiringuito": r"\bchiringuitos?\b",
    "paguita": r"\bpaguitas?\b",
    "menas": r"\bmenas\b",
    "zurdo": r"\bzurd(?:o|a|os|as|itos?)\b",
    "progre": r"\bprogres?\b",
    "perroflauta": r"\bperroflautas?\b",
    "cuñao / cuñado": r"\b(?:neo)?cun(?:ao|aos|ado|ados|adismo)\b",
    "vendehumos": r"\bvendehumos\b",
    "señoro": r"\bsenoros?\b",
    "conspiranoico": r"\bconspiranoic[oa]s?\b",
    "lamebotas": r"\blame\s*botas\b",
    "jovenlandes": r"\bjovenlandes(?:es)?\b",
    "abraza árboles": r"\babraza\s*arboles\b",
    "ecologista de salón": r"\becologistas?\s+de\s+salon\b",
    "sanchismo": r"\bsanchis(?:mo|tas?)\b",
    "perro sanchez": r"\bperro\s+sanchez\b",
    "efecto llamada": r"\befecto\s+llamada\b",
    "fronteras abiertas": r"\bfronteras\s+abiertas\b",
    "disfrutad lo votado": r"\bdisfruta\w*\s+lo\s+votado\b",
    "ingenuidad": r"\bingenuidad\b",
    "sentimentalismo": r"\bsentimentalismo\b",
    "demagogia": r"\bdemagogi(?:a|co|ca)s?\b",
    "qué nivel": r"\bque\s+nivel\b",
    "qué cansinos": r"\bque\s+cansin[oa]s?\b",
    # Contempt openers: "menudo X" / "menuda X" (not "a menudo") and "vaya X".
    "menudo/menuda ...": r"(?<!\ba\s)\bmenud[oa]s?\b",
    "vaya ...": r"(?:^|[.!?,;:]\s*)vaya\s+(?!a\b|al\b|de\b|con\b|por\b|usted\b)\w+",
}

_COMPILED = {label: re.compile(pattern) for label, pattern in BLACKLIST_TERMS.items()}


def _plain(text: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


def find_terms(text: str | None) -> List[str]:
    """Return the blacklist labels that appear in ``text``."""
    value = _plain(text)
    if not value:
        return []
    return [label for label, rx in _COMPILED.items() if rx.search(value)]


def used_terms(contents: Iterable[str | None]) -> List[str]:
    """Return the labels used anywhere in ``contents``, in blacklist order."""
    seen = set()
    for content in contents:
        seen.update(find_terms(content))
    return [label for label in BLACKLIST_TERMS if label in seen]


def violations(
    candidate: str | None,
    banned: Iterable[str],
    responding_to: Optional[str] = None,
) -> List[str]:
    """Banned labels in ``candidate``, excluding ones the answered message used."""
    banned_set = set(banned)
    exempt = set(find_terms(responding_to)) if responding_to else set()
    return [t for t in find_terms(candidate) if t in banned_set and t not in exempt]


def format_blacklist_block(banned: List[str]) -> str:
    """Prompt block listing the vocabulary already burned in this session."""
    if not banned:
        return ""
    return (
        "**Session vocabulary blacklist (already used in this chat, do not reuse):** "
        + ", ".join(f'"{t}"' for t in banned)
        + ". These labels, slang terms and contempt formulas (including close variants and "
        "spelling variants) are permanently banned for the rest of the session. Only exception: "
        "when directly answering the exact message that used the term. Use fresh wording instead, "
        "or make the point without a label."
    )
