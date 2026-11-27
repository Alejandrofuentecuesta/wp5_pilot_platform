"""Keeps a participant message that disclosed personal data out of storage.

When the participant safety classifier finds personal data in a message, the
session goes on (the participant is paused and reminded, see
``SimulationSession.pause_for_privacy``) and the message stays in the room and
in the agents' context. Every later database write of the session would then
carry the text again: agent replies quote it, and every logged model prompt
contains it. This filter sits at the session's write paths and replaces the
flagged text with a placeholder before anything is written.

Replacement only ever touches string values, never dictionary keys or the
structure around them, and it returns new objects so in-memory state is left
as it is. A flagged text shorter than ``MIN_SUBSTRING_LENGTH`` is only replaced
where a whole value equals it: as a substring, a short text could match
unrelated words.
"""
from __future__ import annotations

import json
from typing import Any, List

PERSONAL_DATA_PLACEHOLDER = "[mensaje eliminado: datos personales]"

# Below this length a flagged text is replaced only where a whole value equals
# it, never inside longer text.
MIN_SUBSTRING_LENGTH = 8


def json_escaped(text: str) -> str:
    """``text`` as it appears inside a JSON string, without the quotes."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


class PersonalDataFilter:
    """The flagged texts of one session and the replacement applied to writes."""

    def __init__(self) -> None:
        self._texts: List[str] = []

    @property
    def active(self) -> bool:
        return bool(self._texts)

    @property
    def texts(self) -> List[str]:
        return list(self._texts)

    def add(self, text: str) -> None:
        """Register a flagged text. Longest first, so a text that contains
        another flagged text is replaced as a whole."""
        if not text or not text.strip() or text in self._texts:
            return
        self._texts.append(text)
        self._texts.sort(key=len, reverse=True)

    def scrub_text(self, value: str) -> str:
        """Replace every flagged text in one string."""
        for text in self._texts:
            if value == text:
                return PERSONAL_DATA_PLACEHOLDER
            if len(text) < MIN_SUBSTRING_LENGTH:
                continue
            value = value.replace(text, PERSONAL_DATA_PLACEHOLDER)
            # Text embedded in a JSON payload inside a prompt string.
            escaped = json_escaped(text)
            if escaped != text:
                value = value.replace(escaped, PERSONAL_DATA_PLACEHOLDER)
        return value

    def apply(self, value: Any) -> Any:
        """Return ``value`` with every flagged text replaced in its string values.

        Dictionaries and lists are rebuilt, keys are left as they are, and any
        other type passes through unchanged. With no flagged text the value is
        returned as it is.
        """
        if not self._texts:
            return value
        return self._apply(value)

    def _apply(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {key: self._apply(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._apply(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._apply(item) for item in value)
        return value
