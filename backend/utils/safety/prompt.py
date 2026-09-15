"""Llama Guard 3 prompt rendering and verdict parsing.

The prompt is rendered here, byte for byte as the model's own chat template
(``tokenizer_config.json`` of ``meta-llama/Llama-Guard-3-8B``) renders it, and
sent raw to whichever host serves the model. Rendering locally means both the
development host (Ollama) and the production host (vLLM) receive identical
input, so verdicts are comparable across them.

Llama Guard judges only the last turn of a strictly alternating User/Agent
conversation. Callers build that conversation; this module only renders it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Category:
    code: str
    title: str
    definition: Optional[str] = None

    def render(self) -> str:
        line = f"{self.code}: {self.title}."
        if self.definition:
            line += f"\n{self.definition.strip()}"
        return line


# Exactly the titles in the model's default chat template.
DEFAULT_CATEGORIES: List[Category] = [
    Category("S1", "Violent Crimes"),
    Category("S2", "Non-Violent Crimes"),
    Category("S3", "Sex Crimes"),
    Category("S4", "Child Exploitation"),
    Category("S5", "Defamation"),
    Category("S6", "Specialized Advice"),
    Category("S7", "Privacy"),
    Category("S8", "Intellectual Property"),
    Category("S9", "Indiscriminate Weapons"),
    Category("S10", "Hate"),
    Category("S11", "Self-Harm"),
    Category("S12", "Sexual Content"),
    Category("S13", "Elections"),
    Category("S14", "Code Interpreter Abuse"),
]

# Human-readable names for the dashboard (the model card's long titles).
CATEGORY_NAMES = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex-Related Crimes",
    "S4": "Child Sexual Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
    "S14": "Code Interpreter Abuse",
}

_ROLE_LABEL = {"user": "User", "assistant": "Agent"}

# Stands in for the participant turn when the policy excludes context.
NEUTRAL_USER_TURN = "(no participant message)"


def full_policy(raw: Optional[Sequence[dict]]) -> List[dict]:
    """All 14 categories with their enabled flag and description, for the admin panel."""
    by_code = {str(e.get("code", "")).strip(): e for e in (raw or [])}
    rows = []
    for c in DEFAULT_CATEGORIES:
        e = by_code.get(c.code, {})
        rows.append({
            "code": c.code,
            "title": c.title,
            "name": CATEGORY_NAMES.get(c.code, c.title),
            "enabled": bool(e.get("enabled", True)) if raw else True,
            "definition": e.get("definition") or "",
        })
    if raw:
        # Codes omitted from a saved policy count as disabled.
        saved = set(by_code)
        for r in rows:
            if r["code"] not in saved:
                r["enabled"] = False
    return rows


def categories_from_config(raw: Optional[Sequence[dict]]) -> List[Category]:
    """Build the category list from experiment config; default when absent.

    Entries with ``enabled: false`` are omitted from the prompt entirely, so
    the model can neither see nor return that code.
    """
    if not raw:
        return list(DEFAULT_CATEGORIES)
    out: List[Category] = []
    for entry in raw:
        if entry.get("enabled", True) is False:
            continue
        code = str(entry.get("code", "")).strip()
        title = str(entry.get("title", "")).strip()
        if not code or not title:
            raise ValueError(f"safety category needs code and title: {entry!r}")
        definition = entry.get("definition")
        out.append(Category(code, title, definition.strip() if definition else None))
    return out


def render_prompt(
    conversation: Sequence[Tuple[str, str]],
    categories: Optional[Sequence[Category]] = None,
) -> str:
    """Render the Llama Guard 3 prompt for ``conversation``.

    ``conversation`` is a sequence of ``(role, text)`` with roles ``"user"``
    and ``"assistant"``, alternating and starting with ``"user"``. The last
    turn is the one judged.
    """
    if not conversation:
        raise ValueError("conversation must have at least one turn")
    cats = list(categories) if categories is not None else DEFAULT_CATEGORIES
    for i, (role, _) in enumerate(conversation):
        expected = "user" if i % 2 == 0 else "assistant"
        if role != expected:
            raise ValueError("Conversation roles must alternate user/assistant/user/assistant/...")

    judged = "Agent" if len(conversation) % 2 == 0 else "User"
    category_block = "\n".join(c.render() for c in cats)

    parts = [
        # The leading space is part of the model's template.
        " <|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        f"Task: Check if there is unsafe content in '{judged}' messages in conversations "
        "according our safety policy with the below categories.\n\n"
        "<BEGIN UNSAFE CONTENT CATEGORIES>\n"
        f"{category_block}\n"
        "<END UNSAFE CONTENT CATEGORIES>\n\n"
        "<BEGIN CONVERSATION>\n\n"
    ]
    for role, text in conversation:
        parts.append(f"{_ROLE_LABEL[role]}: {text.strip()}\n\n")
    parts.append(
        "<END CONVERSATION>\n\n"
        f"Provide your safety assessment for ONLY THE LAST {judged} message in the above conversation:\n"
        " - First line must read 'safe' or 'unsafe'.\n"
        " - If unsafe, a second line must include a comma-separated list of violated categories."
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )
    return "".join(parts)


def parse_verdict(raw: Optional[str]) -> Tuple[str, List[str]]:
    """Parse the model output into ``(status, categories)``.

    Accepts only the documented shape: first line ``safe`` or ``unsafe``,
    and for ``unsafe`` a second line of comma-separated category codes.
    Anything else is ``("unavailable", [])`` so the caller withholds.
    """
    if not raw or not raw.strip():
        return "unavailable", []
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    head = lines[0].lower()
    if head == "safe":
        return "safe", []
    if head == "unsafe":
        if len(lines) < 2:
            return "unavailable", []
        codes = [c.strip().upper() for c in lines[1].split(",") if c.strip()]
        if not codes or not all(c.startswith("S") and c[1:].isdigit() for c in codes):
            return "unavailable", []
        return "unsafe", codes
    return "unavailable", []
