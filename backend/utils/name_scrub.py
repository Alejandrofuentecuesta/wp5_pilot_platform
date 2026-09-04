"""Name comparison and replacement helpers for chatroom identities.

Sessions run under a backend-assigned alias and the typed name never
leaves the browser, so stored records need no scrubbing; the alias is
kept in the data on purpose (it may carry bias effects worth analysing).
These helpers compare and rewrite names at session construction — folding
for collision checks, whole-word replacement when a colliding agent is
renamed in its persona text.

Matching is by whole word, case- and accent-insensitive, because bots and
participants are inconsistent about accents ("Lucia" vs "Lucía").
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

CANONICAL_NAME = "participant"

# Unicode-aware word tokens ("Lucía", "María-José"): [^\W\d_] is "any
# letter" in stdlib re, avoiding a dependency on the `regex` package.
_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|['’-])*", re.UNICODE)


def fold(value: str) -> str:
    """Casefold and strip accents, for name comparison."""
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def scrub_text(
    text: Optional[str],
    name: str,
    replacement: str = CANONICAL_NAME,
) -> Tuple[Optional[str], bool]:
    """Replace whole-word occurrences of ``name`` in free text.

    Tokens are compared accent- and case-insensitively, so "Lucía" matches
    a participant who typed "Lucia" and vice versa. "Lucianos" does not.
    Returns (new_text, changed).
    """
    if not text:
        return text, False
    target = fold(name)
    if not target:
        return text, False
    parts: List[str] = []
    last = 0
    changed = False
    for match in _WORD_RE.finditer(text):
        if fold(match.group()) == target:
            parts.append(text[last:match.start()])
            parts.append(replacement)
            last = match.end()
            changed = True
    if not changed:
        return text, False
    parts.append(text[last:])
    return "".join(parts), True
