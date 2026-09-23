"""Safety policy, conversation excerpt and verdict parsing for gpt-oss-safeguard.

The classifier receives two texts: the policy (a fixed file in ``policies/``,
sent as the system message) and an excerpt of the chat ending with the message
under assessment (sent as the user message). The policy is not configurable
per experiment; changing it means adding a new file and pointing
``ACTIVE_POLICY`` at it, so every verdict can be traced to the exact text
through ``Policy.version``.

The excerpt keeps the line between the human and the LLMs and nothing else:
the participant is ``User``, every agent is ``Agent <n>`` numbered by order of
appearance in the excerpt. It holds the message under assessment and the two
messages before it, plus the participant's latest message and the message
being replied to when either falls outside those three.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Protocol, Sequence, Tuple

POLICY_DIR = Path(__file__).parent / "policies"
# The policy in use. policies/ also holds lg3-taxonomy_wp5_v1.md, the same
# policy with Meta's original S10 (Hate) definition, kept for reference.
ACTIVE_POLICY = "lg3-taxonomy_s10-revised_wp5_v1"

# The message under assessment plus the two before it.
WINDOW = 3
GAP_MARKER = "[...]"

# Human-readable names for the dashboard (the hazard taxonomy's titles).
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


@dataclass(frozen=True)
class Policy:
    name: str
    text: str
    sha256: str

    @property
    def version(self) -> str:
        return f"{self.name}@{self.sha256[:12]}"


@lru_cache(maxsize=None)
def load_policy(name: str = ACTIVE_POLICY) -> Policy:
    """Read a policy file. Raises if it is missing, so a bad name fails early."""
    text = (POLICY_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    return Policy(name=name, text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


class ChatMessage(Protocol):
    message_id: str
    sender: str
    content: str
    reply_to: Optional[str]


def render_excerpt(target: ChatMessage, history: Sequence[ChatMessage], user_name: str) -> str:
    """Render the excerpt the classifier judges; ``target`` is its last message.

    ``history`` is the chat before ``target`` in chronological order and must
    not contain ``target`` itself.
    """
    history = [m for m in history if (m.content or "").strip()]
    picked = set(range(max(0, len(history) - (WINDOW - 1)), len(history)))

    if target.reply_to:
        for i, m in enumerate(history):
            if m.message_id == target.reply_to:
                picked.add(i)
                break

    if target.sender != user_name and not any(history[i].sender == user_name for i in picked):
        for i in range(len(history) - 1, -1, -1):
            if history[i].sender == user_name:
                picked.add(i)
                break

    rows: List[Tuple[int, ChatMessage]] = [(i, history[i]) for i in sorted(picked)]
    rows.append((len(history), target))

    labels = {user_name: "User"}
    agents = 0
    lines: List[str] = []
    previous = None
    for i, m in rows:
        if previous is not None and i > previous + 1:
            lines.append(GAP_MARKER)
        previous = i
        if m.sender not in labels:
            agents += 1
            labels[m.sender] = f"Agent {agents}"
        lines.append(f"{labels[m.sender]}: {m.content.strip()}")

    lines.append(
        f"[Assess the last message above, written by {labels[target.sender]}. "
        "The earlier messages are context only.]"
    )
    return "\n\n".join(lines)


_CODE = re.compile(r"S(\d{1,2})\b")


def parse_verdict(raw: Optional[str]) -> Tuple[str, List[str], Optional[str]]:
    """Parse the classifier's JSON answer into ``(status, categories, rationale)``.

    Expects the first JSON object in the output to be
    ``{"violation": 0|1, "categories": [...], "rationale": "..."}``.
    Anything else, including a ``violation`` of 0 that still lists
    categories, is ``unavailable`` so the caller withholds the message.
    """
    if not raw or "{" not in raw:
        return "unavailable", [], None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[raw.index("{"):])
    except ValueError:
        return "unavailable", [], None
    if not isinstance(obj, dict):
        return "unavailable", [], None

    violation = obj.get("violation")
    if isinstance(violation, bool):
        violation = int(violation)
    if violation not in (0, 1):
        return "unavailable", [], None

    raw_codes = obj.get("categories") or []
    if not isinstance(raw_codes, list):
        return "unavailable", [], None
    codes: List[str] = []
    for c in raw_codes:
        match = _CODE.match(str(c).strip().upper())
        if not match or not 1 <= int(match.group(1)) <= 14:
            return "unavailable", [], None
        code = f"S{int(match.group(1))}"
        if code not in codes:
            codes.append(code)

    rationale = obj.get("rationale")
    rationale = (rationale.strip() or None) if isinstance(rationale, str) else None

    if violation == 0:
        if codes:
            return "unavailable", [], None
        return "safe", [], rationale
    return "unsafe", codes, rationale
