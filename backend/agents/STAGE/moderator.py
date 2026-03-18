"""Moderator module — extraction gate for Performer output.

Strips formatting artifacts and meta-commentary from the Performer's raw
output, returning only the clean chatroom message content.
"""
from pathlib import Path
from typing import Optional

# Sentinel value the Moderator returns when no valid message content is found
NO_CONTENT = "NO_CONTENT"

# Load unified Moderator prompt template at import time
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_UNIFIED_TEMPLATE = (_PROMPTS_DIR / "moderator_prompt.md").read_text(encoding="utf-8")

from agents.STAGE.prompts.prompt_renderer import render as _render_prompt


def build_moderator_system_prompt(chatroom_context: str = "", template: Optional[str] = None) -> str:
    """Build the Moderator system prompt (session-static)."""
    raw = template if (isinstance(template, str) and template.strip()) else _UNIFIED_TEMPLATE
    prompt = _render_prompt(raw, "system")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    return prompt


def build_moderator_user_prompt(performer_output: str, template: Optional[str] = None) -> str:
    """Build the per-turn user prompt with the Performer's raw output."""
    raw = template if (isinstance(template, str) and template.strip()) else _UNIFIED_TEMPLATE
    prompt = _render_prompt(raw, "user")
    prompt = prompt.replace("{PERFORMER_OUTPUT}", performer_output)
    return prompt


def parse_moderator_response(raw: str) -> Optional[str]:
    """Parse the Moderator's response.

    Returns the extracted message content as a string, or None if the
    Moderator signalled NO_CONTENT (meaning the performer output was unusable).
    """
    if not raw:
        return None

    cleaned = raw.strip()

    if cleaned == NO_CONTENT:
        return None

    if not cleaned:
        return None

    return cleaned
