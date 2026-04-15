"""Performer module — simplified message generation.

The Performer receives:
  1. Chatroom context (topic/setting)
  2. Agent profile (accumulated track record from Director's assessments)
  3. Recent messages by this performer (so it avoids repetition)
  4. O/M/D instruction (Objective, Motivation, Directive from Director)
  5. Action type (message, message_targeted, reply, @mention)
  6. Target user / target message (for targeted actions; null for standalone)

It does NOT see the full chat log. The Director has already distilled what
matters into the instruction and agent profile, but it may receive a small
sample of recent room messages to avoid sounding structurally repetitive.
"""
from pathlib import Path
from typing import List, Optional

from models import Message
from agents.STAGE.prompts.prompt_renderer import render as _render_prompt
from agents.STAGE.prompts.prompt_renderer import render_action_type as _render_action_type


# Load unified Performer prompt template at import time
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_RAW_UNIFIED_TEMPLATE = (_PROMPTS_DIR / "performer_prompt.md").read_text(encoding="utf-8")


def format_recent_messages(messages: List[Message]) -> str:
    """Format the performer's recent messages for the prompt.

    Simple format: just the content of each message, most recent last.
    """
    if not messages:
        return "(You have not posted any messages yet.)"
    return "\n".join(f"- {m.content}" for m in messages)


def format_recent_room_messages(messages: List[Message]) -> str:
    """Format recent messages from other people in the room."""
    if not messages:
        return "(No recent messages from other people.)"
    return "\n".join(f"- {m.sender}: {m.content}" for m in messages)


def _format_target_message(target_message: Optional[Message]) -> str:
    """Format the target message for the performer prompt."""
    if target_message is None:
        return "(No target message)"
    return f"{target_message.sender}: {target_message.content}"


def _resolve_performer_action_type(action_type: str, target_user: Optional[str]) -> str:
    """Map Director action_type to performer prompt action type.

    The Director uses 'message' for both standalone and targeted messages.
    The performer prompt distinguishes these as 'message' vs 'message_targeted'.
    """
    if action_type == "message" and target_user:
        return "message_targeted"
    return action_type


def build_performer_system_prompt(
    chatroom_context: str = "",
    agent_name: str = "",
    participant_name: Optional[str] = None,
    agent_traits: Optional[dict] = None,
    template: Optional[str] = None,
) -> str:
    """Build the Performer system prompt with session-static data only."""
    raw = template if (isinstance(template, str) and template.strip()) else _RAW_UNIFIED_TEMPLATE
    prompt = _render_prompt(raw, "system")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{AGENT_NAME}", agent_name)
    participant_section = (
        f"The human participant's name is **{participant_name}** — use this to infer their gender when referring to them."
        if participant_name else ""
    )
    prompt = prompt.replace("{PARTICIPANT_NAME_SECTION}", participant_section)
    # Inject fixed ideological traits so the performer never contradicts its core position.
    if agent_traits:
        traits_lines = []
        if agent_traits.get("stance"):
            traits_lines.append(f"- **Stance on the topic**: {agent_traits['stance']}")
        if agent_traits.get("incivility"):
            traits_lines.append(f"- **Incivility level**: {agent_traits['incivility']}")
        if agent_traits.get("ideology"):
            traits_lines.append(f"- **Ideology**: {agent_traits['ideology']}")
        traits_block = (
            "\n\n## Your Fixed Position (never contradicts this):\n\n" + "\n".join(traits_lines)
            if traits_lines else ""
        )
    else:
        traits_block = ""
    prompt = prompt.replace("{AGENT_TRAITS_SECTION}", traits_block)
    return prompt


def build_performer_user_prompt(
    instruction: dict,
    agent_profile: str,
    action_type: str,
    persona: Optional[str] = None,
    target_user: Optional[str] = None,
    target_message: Optional[Message] = None,
    recent_messages: Optional[List[Message]] = None,
    recent_room_messages: Optional[List[Message]] = None,
    chatroom_context: str = "",
    template: Optional[str] = None,
) -> str:
    """Build the Performer user prompt from the Director's output."""
    objective = instruction.get("objective", "")
    motivation = instruction.get("motivation", "")
    directive = instruction.get("directive", "")
    # Persona section is optional: include heading + text only when a persona is defined.
    persona_section = f"## Your Character:\n\n{persona.strip()}\n\n" if (persona and persona.strip()) else ""
    profile_str = agent_profile or "(No behavioral history yet — this is the performer's first action.)"
    recent_str = format_recent_messages(recent_messages or [])
    recent_room_str = format_recent_room_messages(recent_room_messages or [])
    target_str = _format_target_message(target_message)
    target_user_str = target_user or ""
    # Guard: if action requires a target_user but none is set, fall back to plain message.
    if action_type == "@mention" and not target_user_str:
        action_type = "message"
    performer_action = _resolve_performer_action_type(action_type, target_user)
    raw = template if (isinstance(template, str) and template.strip()) else _RAW_UNIFIED_TEMPLATE
    prompt = _render_prompt(raw, "user")
    prompt = _render_action_type(prompt, performer_action)
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{AGENT_PERSONA_SECTION}", persona_section)
    prompt = prompt.replace("{AGENT_PROFILE}", profile_str)
    prompt = prompt.replace("{RECENT_MESSAGES}", recent_str)
    prompt = prompt.replace("{RECENT_ROOM_MESSAGES}", recent_room_str)
    prompt = prompt.replace("{OBJECTIVE}", objective)
    prompt = prompt.replace("{MOTIVATION}", motivation)
    prompt = prompt.replace("{DIRECTIVE}", directive)
    prompt = prompt.replace("{TARGET_USER}", target_user_str)
    prompt = prompt.replace("{TARGET_MESSAGE}", target_str)

    return prompt
