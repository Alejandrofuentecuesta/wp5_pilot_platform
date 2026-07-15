"""Orchestrator â€” coordinates the three-call Director + Performer + Moderator pipeline.

Each turn:
  1. (Skip on first turn) Director Update: update last agent's profile
  2. Director Evaluate: assess validity criteria (every turn during warm-up,
     then every evaluate_interval turns once the first full interval completes)
  3. Director Action: select performer, action type, target, generate O/M/D
     â€” If the Director selects the human participant, the turn short-circuits
       here: Performer/Moderator are skipped, and the evaluate counter is
       not advanced (wait turns are not productive).
  4. Performer: generate message from agent profile + O/M/D + target message
  5. Moderator: extract clean content (retry up to 3 times)

Agent profiles accumulate over the session, updated by the Update call.
Performer labels stay fixed for the full session and now use the agents' real names.
"""
import asyncio
import random
import re
import unicodedata
from copy import copy
from dataclasses import dataclass
from typing import Optional, List, Dict, Set

from models import Message, Agent
from utils import Logger
from agents.STAGE.director import (
    build_update_system_prompt, build_update_user_prompt, parse_update_response,
    build_evaluate_system_prompt, build_evaluate_user_prompt, parse_evaluate_response,
    build_action_system_prompt, build_action_user_prompt, parse_action_response,
    format_participant_hint, format_participant_alignment_cell,
    format_target_constraints_by_speaker,
)
from agents.STAGE.performer import (
    build_performer_system_prompt,
    build_performer_user_prompt,
    build_incivility_instruction_block,
)
from agents.STAGE.moderator import build_moderator_system_prompt, build_moderator_user_prompt, parse_moderator_response
from agents.STAGE.classifier import (
    DEFAULT_CLASSIFIER_PROMPT_TEMPLATE,
    build_classifier_system_prompt,
    build_classifier_user_prompt,
    parse_classifier_response,
)


MAX_PERFORMER_RETRIES = 3
MAX_STANCE_RETRIES = 1
MAX_ROOM_WIDE_OPENERS = 3
TARGET_ELIGIBLE_SPEAKER_COUNT = 4
DEFAULT_UNCIVIL_LENGTH_RANGE = (2, 45)
DEFAULT_CIVIL_LENGTH_RANGE = (18, 95)


@dataclass
class TurnResult:
    """The result of a single Director->Performer turn.

    For 'like' actions, `message` will be None and `target_message_id`
    identifies the message to like.  For all other action types,
    `message` contains the generated Message ready to be added to state.
    """
    action_type: str
    agent_name: str
    message: Optional[Message] = None
    target_message_id: Optional[str] = None
    target_user: Optional[str] = None
    priority: Optional[str] = None
    performer_rationale: Optional[str] = None
    action_rationale: Optional[str] = None


# Ã¢â€â‚¬Ã¢â€â‚¬ Anonymization helpers Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def build_name_map(agent_names: List[str], user_name: str, rng: random.Random) -> Dict[str, str]:
    """Build a stable identity map for the session."""
    del rng
    all_names = list(agent_names) + [user_name]
    return {name: name for name in all_names}



def anonymize_message(msg: Message, name_map: Dict[str, str]) -> Message:
    """Return a shallow copy of a Message with sender/mentions/content anonymized."""
    anon = copy(msg)
    anon.sender = name_map.get(msg.sender, msg.sender)

    if msg.mentions:
        anon.mentions = [name_map.get(m, m) for m in msg.mentions]

    if msg.liked_by:
        anon.liked_by = {name_map.get(u, u) for u in msg.liked_by}

    anon.content = _replace_names_in_text(msg.content, name_map)

    if msg.quoted_text:
        anon.quoted_text = _replace_names_in_text(msg.quoted_text, name_map)

    return anon


def anonymize_agents(agents: List[Agent], name_map: Dict[str, str]) -> List[Agent]:
    """Return a list of Agents with anonymized names."""
    return [Agent(name=name_map.get(a.name, a.name), persona=a.persona) for a in agents]


def _replace_names_in_text(text: str, name_map: Dict[str, str]) -> str:
    """Replace all occurrences of real names in text with their anonymous labels."""
    if not text:
        return text
    for real, anon in sorted(name_map.items(), key=lambda x: -len(x[0])):
        text = text.replace(real, anon)
    return text


def deanonymize_text(text: str, reverse_map: Dict[str, str]) -> str:
    """Replace anonymous labels in text back to real names."""
    return _replace_names_in_text(text, reverse_map)


def _strip_target_quote_echo(content: str, target_message: Optional[Message]) -> str:
    """Remove a copied target message prefix when the moderator echoes quoted text."""
    if not content or not target_message or not target_message.content:
        return content

    cleaned = content.strip()
    target_text = target_message.content.strip()
    sender_prefix = f"{target_message.sender}:"

    for prefix in (
        target_text,
        f"> {target_text}",
        f"{sender_prefix} {target_text}",
    ):
        if cleaned.startswith(prefix):
            remainder = cleaned[len(prefix):].lstrip("\n\r\t :-")
            if remainder:
                return remainder.strip()

    return cleaned


def _looks_truncated_response(text: Optional[str]) -> bool:
    """Heuristic guard for obviously cut-off long generations."""
    if not text:
        return False

    cleaned = text.strip()
    if len(cleaned) < 200:
        return False

    # Repeated or stitched-together generations can end in a bare word while
    # still being clearly broken, e.g. "... convivenciaPrimera frase ...".
    if re.search(r"[a-záéíóúüñ][A-ZÁÉÍÓÚÜÑ]", cleaned):
        return True

    if re.search(r"[.!?â€¦)\]\"'Â»â€]\s*$", cleaned):
        return False

    if cleaned.endswith(("ðŸ˜‚", "ðŸ¤£", "ðŸ˜­", "ðŸ˜¡", "ðŸ˜¤", "ðŸ’¸", "ðŸ”¥", "ðŸ™", "â¤ï¸", "â™¥")):
        return False

    if cleaned.endswith((",", ";", ":", "-", "â€”", "(", "[", "{", "Â¿", "Â¡")):
        return True

    if re.search(r"\b(?:y|o|pero|porque|que|si|aunque|cuando|donde|mientras|como)\s*$", cleaned, re.IGNORECASE):
        return True

    # A bare-word ending is common in chat, especially when surface realism
    # asks for missing final punctuation. Do not treat that as truncation by
    # itself; only strong cut-off markers above should trigger retries.
    return False


def _merge_prompt_context(chatroom_context: str = "", incivility_framework: str = "") -> str:
    """Combine shared experiment context blocks for prompt injection."""
    parts = []
    if chatroom_context.strip():
        parts.append(chatroom_context.strip())
    if incivility_framework.strip():
        parts.append(f"Incivility framework:\n{incivility_framework.strip()}")
    return "\n\n".join(parts)


def select_incivility_dimensions(rng: random.Random) -> List[str]:
    """Select incivility dimensions based on target probabilities.

    Target rates: 70% Impoliteness, 60% Hate Speech, 40% Democratic Threats.
    Ensures at least one dimension is always selected.
    """
    selected = []
    if rng.random() < 0.70:
        selected.append("impoliteness")
    if rng.random() < 0.60:
        selected.append("hate_speech")
    if rng.random() < 0.40:
        selected.append("democratic_threats")

    # Fallback to make sure at least one is selected
    if not selected:
        r = rng.random() * 1.70
        if r < 0.70:
            selected.append("impoliteness")
        elif r < 1.30:
            selected.append("hate_speech")
        else:
            selected.append("democratic_threats")

    return selected


def default_message_length_range(incivility_bucket: Optional[str]) -> tuple[int, int]:
    """Return broad default word-count ranges by civility style."""
    if incivility_bucket == "uncivil":
        return DEFAULT_UNCIVIL_LENGTH_RANGE
    return DEFAULT_CIVIL_LENGTH_RANGE



class Orchestrator:
    """Coordinates the three-call Director + Performer + Moderator pipeline.

    Maintains agent profiles that accumulate over the session via the
    Director's Update call. Performer labels stay fixed for the full
    session and use the agents' real names.
    """

    def __init__(
        self,
        director_llm,
        performer_llm,
        moderator_llm,
        classifier_llm,
        state,
        logger: Logger,
        evaluate_interval: int = 5,
        action_window_size: int = 10,
        performer_memory_size: int = 3,
        chatroom_context: str = "",
        incivility_framework: str = "",
        ecological_criteria: str = "",
        agent_traits: Optional[Dict[str, Dict[str, str]]] = None,
        classifier_prompt_template: Optional[str] = None,
        performer_prompt_template: Optional[str] = None,
        director_action_prompt_template: Optional[str] = None,
        director_evaluate_prompt_template: Optional[str] = None,
        moderator_prompt_template: Optional[str] = None,
        humanize_output: bool = False,
        humanize_rules: Optional[Dict] = None,
        humanize_mode: str = "general",
        humanize_per_agent: Optional[Dict[str, Dict]] = None,
        boost_replies_mentions: bool = False,
        ten_messages_mode: bool = False,
        rng: Optional[random.Random] = None,
        narrative_pool: Optional[List[Dict[str, str]]] = None,
    ):
        self.director_llm = director_llm
        self.narrative_pool = narrative_pool or []
        self.performer_llm = performer_llm
        self.moderator_llm = moderator_llm
        self.classifier_llm = classifier_llm
        self.state = state
        self.logger = logger
        self.evaluate_interval = evaluate_interval
        self.action_window_size = action_window_size
        self.performer_memory_size = performer_memory_size
        self.chatroom_context = chatroom_context
        self.incivility_framework = incivility_framework
        self.ecological_criteria = ecological_criteria
        self._agent_traits = agent_traits or {}
        self.participant_stance_hint = getattr(state, "participant_stance_hint", None)
        self._participant_hint_text = format_participant_hint(self.participant_stance_hint)
        self.classifier_prompt_template = (
            classifier_prompt_template
            if isinstance(classifier_prompt_template, str) and classifier_prompt_template.strip()
            else DEFAULT_CLASSIFIER_PROMPT_TEMPLATE
        )
        self.performer_prompt_template = (
            performer_prompt_template
            if isinstance(performer_prompt_template, str) and performer_prompt_template.strip()
            else None
        )
        self.director_action_prompt_template = (
            director_action_prompt_template
            if isinstance(director_action_prompt_template, str) and director_action_prompt_template.strip()
            else None
        )
        self.director_evaluate_prompt_template = (
            director_evaluate_prompt_template
            if isinstance(director_evaluate_prompt_template, str) and director_evaluate_prompt_template.strip()
            else None
        )
        self.moderator_prompt_template = (
            moderator_prompt_template
            if isinstance(moderator_prompt_template, str) and moderator_prompt_template.strip()
            else None
        )
        self.humanize_output = humanize_output
        self.humanize_rules = humanize_rules or {}
        self.humanize_mode = humanize_mode
        self.humanize_per_agent = humanize_per_agent or {}
        self.boost_replies_mentions = boost_replies_mentions
        self.ten_messages_mode = ten_messages_mode

        # Build the shuffled name mapping (stable for the session lifetime).
        _rng = rng or random.Random()
        self._rng = _rng
        agent_names = [a.name for a in state.agents]
        self._name_map = build_name_map(agent_names, state.user_name, _rng)
        self._reverse_map = {v: k for k, v in self._name_map.items()}
        self._anon_user = self._name_map[state.user_name]

        # Performer profiles: keyed by anonymous name, values are free-form text.
        # Includes both agents and the human â€” the Director treats all as equal performers.
        # Seeded with each agent's persona (anonymized) so the Director knows their character
        # from turn 1; further accumulated via Director Update calls.
        self.agent_profiles: Dict[str, str] = {}
        for a in state.agents:
            anon_name = self._name_map[a.name]
            if a.persona and a.persona.strip():
                persona_text = _replace_names_in_text(a.persona, self._name_map)
                self.agent_profiles[anon_name] = f"Character persona: {persona_text}"
            else:
                self.agent_profiles[anon_name] = ""
        self.agent_profiles[self._anon_user] = ""

        # Track the last agent that acted (anonymous name) and their action type, for Update calls.
        self._last_agent: Optional[str] = None
        self._last_action_type: Optional[str] = None

        # Running action counts for the Evaluate prompt.
        self._action_counts: Dict[str, int] = {
            "message": 0, "reply": 0, "@mention": 0, "like": 0,
        }

        # Probabilistic like injection: probability that a turn becomes an
        # automatic random like (resolved locally, never sent to the LLM).
        # How many of the most recent messages are eligible targets.
        self.auto_like_probability: float = 0.15
        self.auto_like_recency_window: int = 5

        # Per-performer action counts (keyed by anonymous name).
        self._performer_counts: Dict[str, int] = {
            self._name_map[name]: 0 for name in agent_names
        }
        self._performer_counts[self._anon_user] = 0

        # Carry forward validity evaluations between turns.
        self._internal_validity_summary: str = ""
        self._ecological_validity_summary: str = ""

        # Participant alignment cell â€” computed after name_map and agent_traits are ready.
        self._participant_alignment_cell_text = format_participant_alignment_cell(
            self._participant_alignment_cell_live()
        )

        # Evaluate fires every evaluate_interval turns, so each call sees a
        # full window of new messages.  Counter tracks turns since last evaluate.
        # During warm-up (before the first full interval), evaluate fires every turn.
        self._turns_since_evaluate: int = 0
        self._has_completed_first_interval: bool = False

        # Evaluate and Action system prompts deferred until first execute_turn (need internal_validity_criteria).
        self._evaluate_system_prompt: Optional[str] = None
        self._action_system_prompt: Optional[str] = None

        prompt_context = _merge_prompt_context(
            chatroom_context=chatroom_context,
            incivility_framework=incivility_framework,
        )

        # Cached session-static system prompts.
        self._update_system_prompt = build_update_system_prompt(
            chatroom_context=prompt_context,
        )
        # Performer system prompt is per-agent (each agent has their own name).
        # Cached lazily on first use per agent name.
        self._performer_system_prompts: Dict[str, str] = {}
        
        # Only send the news article to the Performer, stripping all legacy rules and the trailing incivility framework
        if "The following news article has been shown to the participant:" in prompt_context:
            article_part = prompt_context.split("The following news article has been shown to the participant:")[1]
            if "Incivility framework:" in article_part:
                article_part = article_part.split("Incivility framework:")[0]
            self._performer_prompt_context = "The following news article has been shown to the participant:\n" + article_part.strip()
        else:
            self._performer_prompt_context = ""
        self._moderator_system_prompt = build_moderator_system_prompt(
            chatroom_context=prompt_context,
            template=self.moderator_prompt_template,
        )
        self._classifier_system_prompt = build_classifier_system_prompt(
            chatroom_context=prompt_context,
        )

    def _should_boost_replies_mentions(self) -> bool:
        import os
        env_val = os.getenv("BOOST_REPLIES_MENTIONS", "false").lower() in ("true", "1")
        return env_val or getattr(self, "boost_replies_mentions", False)

    @staticmethod
    def _normalize_agent_ideology(raw_ideology: Optional[str]) -> Optional[str]:
        """Collapse ideology labels to left/right/center buckets."""
        if not raw_ideology:
            return None
        ideology = str(raw_ideology).strip().lower()
        if ideology in {"left", "pro", "favor", "favour", "support", "agree"}:
            return "left"
        if ideology in {"right", "anti", "against", "oppose", "disagree"}:
            return "right"
        if ideology in {"center", "centre", "neutral", "mixed", "skeptical"}:
            return "center"
        return None

    def _agents_share_alignment_cell(self, actor_name: Optional[str], target_name: Optional[str]) -> bool:
        """Return True when both agents belong to the same fixed alignment cell."""
        if not actor_name or not target_name or actor_name == target_name:
            return False

        actor_traits = self._agent_traits.get(actor_name) or {}
        target_traits = self._agent_traits.get(target_name) or {}
        actor_cell = self._agent_alignment_cell_from_traits(actor_traits)
        target_cell = self._agent_alignment_cell_from_traits(target_traits)
        return actor_cell is not None and actor_cell == target_cell

    def _agents_have_different_alignment_cells(self, actor_name: Optional[str], target_name: Optional[str]) -> bool:
        """Return True when both agents have known alignment cells and they differ."""
        if not actor_name or not target_name or actor_name == target_name:
            return False

        actor_traits = self._agent_traits.get(actor_name) or {}
        target_traits = self._agent_traits.get(target_name) or {}
        actor_cell = self._agent_alignment_cell_from_traits(actor_traits)
        target_cell = self._agent_alignment_cell_from_traits(target_traits)
        return actor_cell is not None and target_cell is not None and actor_cell != target_cell

    @staticmethod
    def _looks_like_agent_validation(content: Optional[str]) -> bool:
        """Heuristic guard for explicit agreement language between agents."""
        if not content:
            return False
        normalized = " ".join(str(content).lower().split())
        return bool(re.search(
            r"\b("
            r"exacto|exactamente|tal cual|totalmente de acuerdo|"
            r"estoy de acuerdo|coincido|tienes raz[oÃ³]n|llevas raz[oÃ³]n|"
            r"muy de acuerdo|completamente de acuerdo|"
            r"eso mismo|justo eso|pienso igual|opino igual"
            r")\b",
            normalized,
        ))

    @staticmethod
    def _looks_like_attack_on_participant(content: Optional[str]) -> bool:
        """Heuristic guard for direct, adversarial language aimed at the participant."""
        if not content:
            return False
        normalized = " ".join(str(content).lower().split())
        return bool(re.search(
            r"\b("
            r"deja de|no digas|no vayas|calla|"
            r"eres|es pat[eÃ©]tico|pat[eÃ©]tico|rid[iÃ­]culo|"
            r"estupideces|tonter[iÃ­]as|gilipolleces|mierda|"
            r"imb[eÃ©]cil|idiota|analfabeta|ignorante|ingenuo"
            r")\b",
            normalized,
        ))

    @staticmethod
    def _performer_output_needs_moderator(content: Optional[str]) -> bool:
        """Return True only when performer output looks too messy to publish directly."""
        if not content:
            return True
        text = str(content).strip()
        if not text or text == "NO_CONTENT":
            return True
        if "```" in text:
            return True
        if text.startswith("{") or text.startswith("["):
            return True
        if re.search(
            r"^\s*(mensaje|respuesta|message|objective|motivation|directive)\s*:",
            text,
            re.IGNORECASE | re.MULTILINE,
        ):
            return True
        if re.search(r"^\s*[-*]\s+", text, re.MULTILINE):
            return True
        if text.count("\n") > 0:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) > 1:
                return True
        return False

    @staticmethod
    def _normalize_participant_stance_hint(raw_stance: Optional[str]) -> Optional[str]:
        """Collapse participant stance hints to comparable buckets."""
        if not raw_stance:
            return None

        stance = str(raw_stance).strip().lower()
        if stance in {"pro_topic", "column_i", "column_1", "column 1", "column i"}:
            return "pro_topic"
        if stance in {"anti_topic", "column_ii", "column_2", "column 2", "column ii"}:
            return "anti_topic"
        if stance in {"qualified_favor", "qualified_against"}:
            return "pro_topic"
        if stance in {"favor", "favour", "in favor", "in favour", "support", "pro", "agree"}:
            return "pro_topic"
        if stance in {"against", "oppose", "anti", "disagree"}:
            return "anti_topic"
        if stance in {"skeptical", "skeptic", "unsure", "neutral", "mixed"}:
            return "skeptical"

        # Classifier summaries are free text ("supports regularization but..."),
        # not canonical enum values, so fall back to simple keyword heuristics.
        normalized = stance.replace("_", " ").replace("-", " ")
        favor_match = bool(re.search(
            r"\b("
            r"favor|favour|in favor|in favour|support|supports|supported|supportive|"
            r"pro|agree|agrees|agreed|backs?|backed|apoya|apoya la|a favor|"
            r"regulari[sz]ation"
            r")\b",
            normalized,
        ))
        against_match = bool(re.search(
            r"\b("
            r"against|oppose|opposes|opposed|opposition|anti|disagree|disagrees|"
            r"reject|rejects|rejected|critical of|criticizes|criticises|"
            r"en contra|se opone|opone|rechaza"
            r")\b",
            normalized,
        ))
        skeptical_match = bool(re.search(
            r"\b("
            r"skeptical|skeptic|unsure|unclear|mixed|neutral|ambivalent|"
            r"doubt|doubts|doubtful|uncertain|concerned|reservations?|"
            r"esc[eÃ©]ptic|duda|dudas|reservas?"
            r")\b",
            normalized,
        ))

        if favor_match and against_match:
            return "skeptical"
        if favor_match:
            return "pro_topic"
        if against_match:
            return "anti_topic"
        if skeptical_match:
            return "skeptical"
        return None

    @classmethod
    def _participant_alignment_cell_from_hint(cls, raw_stance: Optional[str]) -> Optional[str]:
        """Map participant self-report to the experiment's topic-only sides."""
        stance = cls._normalize_participant_stance_hint(raw_stance)
        if stance == "pro_topic":
            return "pro_topic"
        if stance == "anti_topic":
            return "anti_topic"
        return None

    @staticmethod
    def _is_substantive_participant_message(content: Optional[str]) -> bool:
        """Return True for participant messages that contain an actual stance signal."""
        if not content:
            return False
        cleaned = " ".join(str(content).split()).strip()
        if len(cleaned) < 12:
            return False
        return bool(re.search(r"[A-Za-zÃÃ‰ÃÃ“ÃšÃ¡Ã©Ã­Ã³ÃºÃ‘Ã±]", cleaned))

    @classmethod
    def _participant_alignment_cell_from_message(
        cls,
        message_text: Optional[str],
    ) -> Optional[str]:
        """Infer a participant alignment cell from one clear participant message.

        This is intentionally conservative: it only returns a cell when the
        message contains a strong enough cue to correct or refine the self-report.
        Otherwise it returns None and the self-report remains in force.
        """
        if not message_text:
            return None

        text = " " .join(str(message_text).lower().split())

        # Fast-path for common unaccented phrasings so we can still refine the
        # participant cell even when the incoming text loses diacritics.
        if (
            "la inmigracion es un derecho" in text
            and ("esta mal planteado" in text or "es una mala medida" in text)
        ):
            return "pro_topic"

        pro_policy_patterns = [
            r"\bestoy a favor\b",
            r"\bme parece bien\b",
            r"\bme parece una buena medida\b",
            r"\bestoy de acuerdo\b",
            r"\bes un buen paso\b",
            r"\bapoyo (?:el|la|esta|este)\b",
            r"\bhay que apoyar\b",
            r"\bbeneficia\b",
        ]
        anti_policy_patterns = [
            r"\bestoy en contra\b",
            r"\bno me convence\b",
            r"\bme parece mal\b",
            r"\bes una mala medida\b",
            r"\bestÃ¡ mal plantead[oa]\b",
            r"\bes insuficiente\b",
            r"\bse queda corto\b",
            r"\bes una verg[Ã¼u]enza\b",
            r"\bes una locura\b",
            r"\bno funciona\b",
        ]
        pro_topic_patterns = [
            r"\bla inmigraci[oÃ³]n es un derecho\b",
            r"\bhay que regularizar\b",
            r"\bsoy pro inmigraci[oÃ³]n\b",
            r"\bcombatir el cambio clim[aÃ¡]tico\b",
            r"\bhay que actuar contra el cambio clim[aÃ¡]tico\b",
            r"\bel cambio clim[aÃ¡]tico es real\b",
            r"\bhay que reducir emisiones\b",
        ]
        anti_topic_patterns = [
            r"\bsobran inmigrantes\b",
            r"\bdevolvedlos\b",
            r"\bno necesitamos inmigraci[oÃ³]n\b",
            r"\befecto llamada\b",
            r"\bel cambio clim[aÃ¡]tico es una farsa\b",
            r"\bel cambio clim[aÃ¡]tico es un enga[Ã±n]o\b",
            r"\bel cambio clim[aÃ¡]tico est[aÃ¡] exagerado\b",
        ]

        def _matches(patterns: List[str]) -> bool:
            return any(re.search(pattern, text) for pattern in patterns)

        pro_policy = _matches(pro_policy_patterns)
        anti_policy = _matches(anti_policy_patterns)
        pro_topic = _matches(pro_topic_patterns)
        anti_topic = _matches(anti_topic_patterns)

        if pro_policy and not anti_policy:
            return "pro_topic"
        if anti_policy and pro_topic and not anti_topic:
            return "pro_topic"
        if anti_policy and anti_topic and not pro_topic:
            return "anti_topic"
        return None

    def _participant_alignment_cell_live(self) -> Optional[str]:
        """Resolve participant cell, treating the pre-chat survey as authoritative when present."""
        hint_cell = self._participant_alignment_cell_from_hint(self.participant_stance_hint)
        if hint_cell is not None:
            return hint_cell

        participant_messages = [
            message
            for message in self.state.messages
            if message.sender == self.state.user_name
            and self._is_substantive_participant_message(message.content)
        ]
        if not participant_messages:
            return hint_cell

        first_message_cell = self._participant_alignment_cell_from_message(
            participant_messages[0].content
        )
        return first_message_cell or hint_cell

    @staticmethod
    def _agent_alignment_cell_from_traits(traits: Dict[str, str]) -> Optional[str]:
        """Return the agent's topic-only alignment side from fixed traits."""
        explicit = str(traits.get("alignment_cell", "")).strip().lower()
        if explicit in {"pro_topic", "anti_topic"}:
            return explicit
        if explicit in {"pro_policy_pro_topic", "anti_policy_pro_topic"}:
            return "pro_topic"
        if explicit == "anti_policy_anti_topic":
            return "anti_topic"

        policy_stance = str(traits.get("policy_stance", "")).strip().lower()
        topic_stance = str(traits.get("topic_stance", "")).strip().lower()
        stance = str(traits.get("stance", "")).strip().lower()
        ideology = str(traits.get("ideology", "")).strip().lower()

        if not policy_stance:
            if stance in {"agree", "support", "favor", "pro"}:
                policy_stance = "pro_policy"
            elif stance in {"disagree", "oppose", "against", "anti"}:
                policy_stance = "anti_policy"
            elif ideology == "left":
                policy_stance = "pro_policy"
            elif ideology == "right":
                policy_stance = "anti_policy"

        if topic_stance in {"pro_topic", "anti_topic"}:
            return topic_stance
        if policy_stance == "pro_policy":
            return "pro_topic"
        if policy_stance == "anti_policy":
            return "anti_topic"
        return None

    def _expected_like_minded_for_agent(self, agent_name: str) -> Optional[bool]:
        """Infer expected alignment from the participant cell and the agent cell."""
        participant_cell = self._participant_alignment_cell_live()
        if participant_cell is None:
            return None

        traits = self._agent_traits.get(agent_name) or {}
        agent_cell = self._agent_alignment_cell_from_traits(traits)
        if agent_cell is None:
            return None
        return agent_cell == participant_cell

    @staticmethod
    def _extract_target_percent(criteria: str, key: str) -> Optional[int]:
        """Extract an integer percentage target from the internal validity criteria text."""
        if not criteria:
            return None
        match = re.search(rf"{re.escape(key)}\s*=\s*(\d+)", criteria)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _agent_civility_bucket(self, agent_name: str) -> Optional[str]:
        """Return the fixed civility bucket of an agent, if known."""
        traits = self._agent_traits.get(agent_name) or {}
        value = str(traits.get("incivility", "")).strip().lower()
        if value in {"civil", "uncivil"}:
            return value
        return None

    def _was_interpellated_last_turn(self, agent_real_name: str) -> bool:
        """Return True if the very last message in the chat interpellated this agent."""
        if not self.state.messages:
            return False
        last_message = self.state.messages[-1]

        # 1. Check if it's a quote-reply targeting a message sent by this agent
        if last_message.reply_to:
            for m in self.state.messages:
                if m.message_id == last_message.reply_to and m.sender == agent_real_name:
                    return True

        # 2. Check if the agent is mentioned in the last message
        anon_name = self._name_map.get(agent_real_name)
        if anon_name and last_message.mentions and anon_name in last_message.mentions:
            return True

        # 3. Check if the last message was sent immediately after a message from this agent (adjacency)
        if len(self.state.messages) >= 2:
            second_last = self.state.messages[-2]
            if second_last.sender == agent_real_name:
                return True

        return False

    def _filter_candidate_agents_for_targets(
        self,
        internal_validity_criteria: str,
        candidate_agent_names: Set[str],
    ) -> Set[str]:
        """Return a ranked subset of candidates, preserving some flexibility.

        We still prioritize the side/tone currently needed most, but we avoid
        collapsing the visible set to 1-2 names whenever possible. This gives
        the Director a realistic choice set and reduces retry loops caused by
        global speaker memory mentioning agents that are technically valid but
        not in an over-tight exact-match subset.
        """
        candidates = {
            name for name in candidate_agent_names
            if any(agent.name == name for agent in self.state.agents)
        }
        if not candidates:
            return candidate_agent_names

        like_target = self._extract_target_percent(internal_validity_criteria, "LIKEMINDED_TARGET")
        not_like_target = self._extract_target_percent(internal_validity_criteria, "NOT_LIKEMINDED_TARGET")
        incivil_target = self._extract_target_percent(internal_validity_criteria, "INCIVILITY_TARGET")

        agent_messages = [
            message for message in self.state.messages
            if message.sender != self.state.user_name
        ]
        total_messages = len(agent_messages)

        if len(candidates) <= TARGET_ELIGIBLE_SPEAKER_COUNT:
            return candidates

        preferred_like_value: Optional[bool] = None
        preferred_civility: Optional[str] = None
        preferred_uncivil_ideology: Optional[str] = None

        if self.ten_messages_mode:
            # 10 Messages Mode Solver
            target_uncivil = round(10 * (incivil_target or 50) / 100)
            target_civil = 10 - target_uncivil

            target_like_minded = round(10 * (like_target or 50) / 100)
            target_not_like_minded = 10 - target_like_minded

            if target_uncivil == 2:
                target_uncivil_left = 1
                target_uncivil_right = 1
            elif target_uncivil == 8:
                target_uncivil_left = 4
                target_uncivil_right = 4
            elif target_uncivil == 5:
                target_uncivil_left = 3
                target_uncivil_right = 3
            else:
                target_uncivil_left = target_uncivil // 2
                target_uncivil_right = target_uncivil - target_uncivil_left

            # Current counts
            uncivil_sent = sum(1 for m in agent_messages if m.is_incivil is True)
            civil_sent = sum(1 for m in agent_messages if m.is_incivil is False)

            like_minded_sent = sum(1 for m in agent_messages if self._expected_like_minded_for_agent(m.sender) is True)
            not_like_minded_sent = sum(1 for m in agent_messages if self._expected_like_minded_for_agent(m.sender) is False)

            uncivil_left_sent = 0
            uncivil_right_sent = 0
            for m in agent_messages:
                if m.is_incivil is True:
                    traits = self._agent_traits.get(m.sender) or {}
                    sender_ideology = self._normalize_agent_ideology(traits.get("ideology"))
                    if sender_ideology == "left":
                        uncivil_left_sent += 1
                    elif sender_ideology == "right":
                        uncivil_right_sent += 1

            needed_uncivil = max(0, target_uncivil - uncivil_sent)
            needed_civil = max(0, target_civil - civil_sent)
            needed_like_minded = max(0, target_like_minded - like_minded_sent)
            needed_not_like_minded = max(0, target_not_like_minded - not_like_minded_sent)
            needed_uncivil_left = max(0, target_uncivil_left - uncivil_left_sent)
            needed_uncivil_right = max(0, target_uncivil_right - uncivil_right_sent)

            # Apply hard filtering
            filtered_candidates = set()
            for name in candidates:
                # Civility target filter
                agent_civility = self._agent_civility_bucket(name)
                if agent_civility == "uncivil" and needed_uncivil == 0:
                    continue
                if agent_civility == "civil" and needed_civil == 0:
                    continue

                # Stance target filter
                agent_like = self._expected_like_minded_for_agent(name)
                if agent_like is True and needed_like_minded == 0:
                    continue
                if agent_like is False and needed_not_like_minded == 0:
                    continue

                # Ideology filter for uncivil turns (exclude center, enforce left/right targets)
                if agent_civility == "uncivil":
                    traits = self._agent_traits.get(name) or {}
                    agent_ideology = self._normalize_agent_ideology(traits.get("ideology"))
                    if agent_ideology not in {"left", "right"}:
                        continue
                    if agent_ideology == "left" and needed_uncivil_left == 0:
                        continue
                    if agent_ideology == "right" and needed_uncivil_right == 0:
                        continue

                filtered_candidates.add(name)

            if filtered_candidates:
                candidates = filtered_candidates

            # Set preferred target values based on remaining gaps
            if needed_like_minded > 0 or needed_not_like_minded > 0:
                preferred_like_value = True if needed_like_minded >= needed_not_like_minded else False
            if needed_uncivil > 0 or needed_civil > 0:
                preferred_civility = "uncivil" if needed_uncivil >= needed_civil else "civil"
            if preferred_civility == "uncivil":
                if needed_uncivil_left > 0 or needed_uncivil_right > 0:
                    preferred_uncivil_ideology = "left" if needed_uncivil_left >= needed_uncivil_right else "right"

        else:
            # Normal Session Targets logic
            if total_messages > 0 and like_target is not None and not_like_target is not None:
                like_count = sum(
                    1 for message in agent_messages
                    if self._expected_like_minded_for_agent(message.sender) is True
                )
                not_like_count = sum(
                    1 for message in agent_messages
                    if self._expected_like_minded_for_agent(message.sender) is False
                )
                current_like_pct = (100.0 * like_count / total_messages)
                current_not_like_pct = (100.0 * not_like_count / total_messages)
                like_gap = like_target - current_like_pct
                not_like_gap = not_like_target - current_not_like_pct

                if like_gap > 0 or not_like_gap > 0:
                    preferred_like_value = True if like_gap >= not_like_gap else False

            classified_incivility = [message for message in agent_messages if message.is_incivil is not None]
            if classified_incivility and incivil_target is not None:
                incivil_count = sum(1 for message in classified_incivility if message.is_incivil)
                civil_count = sum(1 for message in classified_incivility if message.is_incivil is False)
                current_incivil_pct = 100.0 * incivil_count / len(classified_incivility)
                current_civil_pct = 100.0 * civil_count / len(classified_incivility)
                civil_target = max(0, 100 - incivil_target)
                incivil_gap = incivil_target - current_incivil_pct
                civil_gap = civil_target - current_civil_pct

                if incivil_gap > 0 or civil_gap > 0:
                    preferred_civility = "uncivil" if incivil_gap >= civil_gap else "civil"

            if preferred_civility == "uncivil":
                uncivil_left_count = 0
                uncivil_right_count = 0
                for message in classified_incivility:
                    if message.is_incivil is True:
                        traits = self._agent_traits.get(message.sender) or {}
                        sender_ideology = self._normalize_agent_ideology(traits.get("ideology"))
                        if sender_ideology == "left":
                            uncivil_left_count += 1
                        elif sender_ideology == "right":
                            uncivil_right_count += 1

                if uncivil_left_count < uncivil_right_count:
                    preferred_uncivil_ideology = "left"
                elif uncivil_right_count < uncivil_left_count:
                    preferred_uncivil_ideology = "right"
                else:
                    preferred_uncivil_ideology = self._rng.choice(["left", "right"])

        last_index_by_real: Dict[str, int] = {}
        count_by_real: Dict[str, int] = {}
        for idx, message in enumerate(agent_messages):
            count_by_real[message.sender] = count_by_real.get(message.sender, 0) + 1
            last_index_by_real[message.sender] = idx

        def _rank_key(name: str) -> tuple[int, int, int, int, str]:
            score = 0

            if preferred_like_value is not None and self._expected_like_minded_for_agent(name) is preferred_like_value:
                score += 4
            if preferred_civility is not None and self._agent_civility_bucket(name) == preferred_civility:
                if preferred_civility == "uncivil" and preferred_uncivil_ideology is not None:
                    traits = self._agent_traits.get(name) or {}
                    raw_ideology = traits.get("ideology")
                    if self._normalize_agent_ideology(raw_ideology) == preferred_uncivil_ideology:
                        score += 5
                    else:
                        score += 1
                else:
                    score += 3

            if self.ten_messages_mode and self._was_interpellated_last_turn(name):
                score += 20

            message_count = count_by_real.get(name, 0)
            if self.ten_messages_mode:
                turns_ago = len(agent_messages) - 1 - last_index_by_real.get(name, -1)
                never_spoken = 1 if message_count == 0 else 0
                return (score, never_spoken, turns_ago, -message_count, name)
            else:
                if message_count == 0:
                    score += 2
                else:
                    last_index = last_index_by_real.get(name)
                    turns_ago = len(agent_messages) - 1 - last_index if last_index is not None else 0
                    if turns_ago >= 3:
                        score += 1

                last_index = last_index_by_real.get(name)
                turns_ago = len(agent_messages) - 1 - last_index if last_index is not None else 10_000
                never_spoken = 1 if message_count == 0 else 0
                return (score, never_spoken, turns_ago, -message_count, name)

        ranked = sorted(candidates, key=_rank_key, reverse=True)
        return set(ranked[:TARGET_ELIGIBLE_SPEAKER_COUNT]) or candidates

    def _sanitize_summary_for_eligible_agents(
        self,
        summary: str,
        eligible_anon_names: Set[str],
    ) -> str:
        """Remove concrete agent-name suggestions that are not eligible this turn."""
        if not summary:
            return summary

        eligible = {name for name in eligible_anon_names if name != self._anon_user}
        if not eligible:
            return summary

        all_agent_names = {
            anon_name
            for anon_name in self._performer_counts.keys()
            if anon_name != self._anon_user
        }
        ineligible = sorted(all_agent_names - eligible, key=len, reverse=True)

        sanitized = summary
        for anon_name in ineligible:
            sanitized = re.sub(rf"\b{re.escape(anon_name)}\b", "another eligible agent", sanitized)

        sanitized = re.sub(
            r"another eligible agent(?:\s*/\s*another eligible agent)+",
            "another eligible agent",
            sanitized,
        )
        sanitized = re.sub(
            r"another eligible agent(?:,\s*another eligible agent)+",
            "eligible agents",
            sanitized,
        )
        sanitized = re.sub(
            r"\(\s*e\.g\.,\s*another eligible agent(?:\s+or\s+another eligible agent)?\s*\)",
            "(e.g., an eligible agent)",
            sanitized,
            flags=re.IGNORECASE,
        )
        return sanitized

    def _message_contradicts_fixed_stance(
        self,
        agent_name: str,
        classification: Dict[str, Optional[object]],
    ) -> bool:
        """Return True when classifier output clearly conflicts with fixed stance."""
        expected_like_minded = self._expected_like_minded_for_agent(agent_name)
        actual_like_minded = classification.get("is_like_minded")
        stance_confidence = classification.get("stance_confidence")
        inferred_participant_stance = self._normalize_participant_stance_hint(
            classification.get("inferred_participant_stance")
        )
        expected_participant_stance = self._normalize_participant_stance_hint(
            self.participant_stance_hint
        )

        # Treat the classifier as a soft signal unless it is both explicit
        # and highly confident. This avoids skipping fluent turns because of
        # noisy like-mindedness judgments on aggressive or indirect messages.
        if (
            expected_like_minded is None
            or actual_like_minded is None
            or stance_confidence != "high"
        ):
            return False

        if (
            inferred_participant_stance is not None
            and expected_participant_stance is not None
            and inferred_participant_stance != expected_participant_stance
        ):
            return False
        return bool(actual_like_minded) != expected_like_minded

    @staticmethod
    def _is_room_wide_opener_message(message: Message) -> bool:
        """Return True when a published message is a non-targeted room-wide opener."""
        return (
            bool(message.content)
            and not message.reply_to
            and not message.mentions
            and message.sender != "[news]"
        )

    def _agent_has_spoken_before(self, agent_name: str) -> bool:
        """Return True if the agent has already posted a message in this session."""
        return any(message.sender == agent_name for message in self.state.messages)

    def _agent_messages_so_far(self) -> List[Message]:
        """Return published agent messages, excluding the human participant."""
        agent_names = {agent.name for agent in self.state.agents if agent.name != self.state.user_name}
        return [
            message
            for message in self.state.messages
            if message.sender in agent_names
        ]

    @staticmethod
    def _format_turns_ago(distance: Optional[int]) -> str:
        """Render a compact recency label for agent speaking turns."""
        if distance is None:
            return "never"
        if distance == 0:
            return "latest agent message"
        if distance == 1:
            return "1 agent message ago"
        return f"{distance} agent messages ago"

    def _format_participation_memory(
        self,
        eligible_anon_names: Optional[Set[str]] = None,
    ) -> str:
        """Build an explicit memory of who has spoken and how recently.

        The Director needs two separate views:
        - global speaker memory across all agents, to avoid false claims like
          "has not spoken yet"
        - eligible speakers this turn, so treatment filtering stays intact
        """
        agent_messages = self._agent_messages_so_far()
        all_anon_agents = sorted(
            anon_name
            for anon_name in self._performer_counts.keys()
            if anon_name != self._anon_user
        )

        last_index_by_real: Dict[str, int] = {}
        count_by_real: Dict[str, int] = {}
        for idx, message in enumerate(agent_messages):
            count_by_real[message.sender] = count_by_real.get(message.sender, 0) + 1
            last_index_by_real[message.sender] = idx

        def _section(title: str, anon_names: List[str]) -> str:
            lines = [title]
            for anon_name in anon_names:
                real_name = self._deanon_name(anon_name)
                message_count = count_by_real.get(real_name, 0)
                last_index = last_index_by_real.get(real_name)
                last_spoke = self._format_turns_ago(
                    None if last_index is None else len(agent_messages) - 1 - last_index
                )
                spoken = "yes" if message_count > 0 else "no"
                lines.append(
                    f"- {anon_name}: spoken={spoken}, messages={message_count}, last_spoke={last_spoke}"
                )
            return "\n".join(lines)

        sections = [_section("Global speaker memory:", all_anon_agents)]

        if eligible_anon_names is not None:
            eligible_only = sorted(
                anon_name
                for anon_name in eligible_anon_names
                if anon_name != self._anon_user
            )
            if eligible_only:
                sections.append(_section("Eligible speakers this turn:", eligible_only))

        return "\n\n".join(sections)

    def _count_room_wide_openers(self, agent_names: Set[str]) -> int:
        """Count first-turn room-wide opener messages already present in the session."""
        seen_speakers: Set[str] = set()
        count = 0
        for message in self.state.messages:
            if message.sender not in agent_names or message.sender in seen_speakers:
                continue
            seen_speakers.add(message.sender)
            if self._is_room_wide_opener_message(message):
                count += 1
        return count

    def _last_message_was_room_wide_opener(self, agent_names: Set[str]) -> bool:
        """Return True when the latest agent message was a room-wide opener."""
        for message in reversed(self.state.messages):
            if message.sender in agent_names:
                return self._is_room_wide_opener_message(message)
        return False

    def _find_room_wide_anchor_message(self, agent_name: str) -> Optional[Message]:
        """Pick a recent non-self message to anchor a redirected opener to."""
        for message in reversed(self.state.messages):
            if message.sender == agent_name or message.sender == "[news]":
                continue
            return message
        return None

    def _can_directly_target_message(self, actor_name: str, message: Message) -> bool:
        """Return True when a message is a coherent direct target for this actor."""
        if not message or message.sender in {actor_name, "[news]"}:
            return False
        if message.sender == self.state.user_name:
            return True
        return not self._agents_share_alignment_cell(actor_name, message.sender)

    def _find_best_direct_target_message(
        self,
        actor_name: str,
        recent_messages: List[Message],
        exclude_senders: Optional[Set[str]] = None,
        exclude_message_ids: Optional[Set[str]] = None,
    ) -> Optional[Message]:
        """Pick the best recent message this actor can target directly."""
        excluded = exclude_senders or set()
        excluded_ids = exclude_message_ids or set()

        if self._should_boost_replies_mentions():
            eligible_msgs = []
            seen_ids = set()
            for message in reversed(recent_messages):
                if message.sender in excluded or message.message_id in excluded_ids:
                    continue
                if message.message_id in seen_ids:
                    continue
                if self._can_directly_target_message(actor_name, message):
                    eligible_msgs.append(message)
                    seen_ids.add(message.message_id)
            for message in reversed(self.state.messages):
                if message.sender in excluded or message.message_id in excluded_ids:
                    continue
                if message.message_id in seen_ids:
                    continue
                if self._can_directly_target_message(actor_name, message):
                    eligible_msgs.append(message)
                    seen_ids.add(message.message_id)
            
            if not eligible_msgs:
                return None
            
            # Weighted random choice using geometric decay (factor 0.7)
            # More recent eligible messages have higher probability
            decay = 0.7
            weights = [decay ** i for i in range(len(eligible_msgs))]
            return self._rng.choices(eligible_msgs, weights=weights, k=1)[0]
        else:
            for message in reversed(recent_messages):
                if message.sender in excluded or message.message_id in excluded_ids:
                    continue
                if self._can_directly_target_message(actor_name, message):
                    return message
            for message in reversed(self.state.messages):
                if message.sender in excluded or message.message_id in excluded_ids:
                    continue
                if self._can_directly_target_message(actor_name, message):
                    return message
            return None

    def _find_latest_message_anchor(
        self,
        actor_name: str,
        recent_messages: List[Message],
    ) -> Optional[Message]:
        """Return the latest coherent message a plain `message` could naturally answer."""
        if recent_messages:
            latest = recent_messages[-1]
            if self._can_directly_target_message(actor_name, latest):
                return latest
        return None

    def _can_like_message(self, actor_name: str, message: Message) -> bool:
        """Return True when a like would be coherent with cell-based validation rules."""
        if not message or message.sender in {actor_name, "[news]"}:
            return False
        if message.sender == self.state.user_name:
            return self._expected_like_minded_for_agent(actor_name) is True
        return self._agents_share_alignment_cell(actor_name, message.sender)

    def _make_accent_insensitive_regex(self, name: str) -> str:
        # Maps Spanish/Catalan/common vowels to character classes
        mapping = {
            'a': '[aÃ¡Ã Ã¢Ã¤]', 'Ã¡': '[aÃ¡Ã Ã¢Ã¤]', 'Ã ': '[aÃ¡Ã Ã¢Ã¤]', 'Ã¢': '[aÃ¡Ã Ã¢Ã¤]', 'Ã¤': '[aÃ¡Ã Ã¢Ã¤]',
            'e': '[eÃ©Ã¨ÃªÃ«]', 'Ã©': '[eÃ©Ã¨ÃªÃ«]', 'Ã¨': '[eÃ©Ã¨ÃªÃ«]', 'Ãª': '[eÃ©Ã¨ÃªÃ«]', 'Ã«': '[eÃ©Ã¨ÃªÃ«]',
            'i': '[iÃ­Ã¬Ã®Ã¯]', 'Ã­': '[iÃ­Ã¬Ã®Ã¯]', 'Ã¬': '[iÃ­Ã¬Ã®Ã¯]', 'Ã®': '[iÃ­Ã¬Ã®Ã¯]', 'Ã¯': '[iÃ­Ã¬Ã®Ã¯]',
            'o': '[oÃ³Ã²Ã´Ã¶]', 'Ã³': '[oÃ³Ã²Ã´Ã¶]', 'Ã²': '[oÃ³Ã²Ã´Ã¶]', 'Ã´': '[oÃ³Ã²Ã´Ã¶]', 'Ã¶': '[oÃ³Ã²Ã´Ã¶]',
            'u': '[uÃºÃ¹Ã»Ã¼]', 'Ãº': '[uÃºÃ¹Ã»Ã¼]', 'Ã¹': '[uÃºÃ¹Ã»Ã¼]', 'Ã»': '[uÃºÃ¹Ã»Ã¼]', 'Ã¼': '[uÃºÃ¹Ã»Ã¼]',
        }
        pattern_parts = []
        for char in name.lower():
            if char in mapping:
                pattern_parts.append(mapping[char])
            else:
                pattern_parts.append(re.escape(char))
        return "".join(pattern_parts)

    @staticmethod
    def _strip_accents(text: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(char)
        )

    def _strip_vocative_prefix(self, text: str) -> str:
        if not text:
            return text
        names = list(self._name_map.keys())
        if not names:
            return text
        # Sort names by length descending to prevent greedy matching on substrings
        names.sort(key=len, reverse=True)

        normalized_text = self._strip_accents(text)
        for name in names:
            normalized_name = re.escape(self._strip_accents(name))
            pattern = (
                r"^([\u00bf\u00a1]*)\s*@?"
                + normalized_name
                + r"\s*(?:,|\.{3}|\u2026|[:\-\u2014!?])\s*(.*)$"
            )
            match = re.match(pattern, normalized_text, re.IGNORECASE)
            if match:
                leading_punct = text[match.start(1):match.end(1)] if match.group(1) else ""
                remaining_text = text[match.start(2):].strip()
                if remaining_text:
                    remaining_text = remaining_text[0].upper() + remaining_text[1:]
                return leading_punct + remaining_text
        return text

    def _format_target_constraints_by_speaker(
        self,
        eligible_anon_names: Set[str],
        recent_messages: List[Message],
    ) -> str:
        """Describe valid direct targets and best reply anchors per eligible speaker."""
        visible_speakers = sorted(
            anon_name for anon_name in eligible_anon_names
            if anon_name != self._anon_user
        )
        if not visible_speakers:
            return "(No speaker-specific target constraints available.)"

        constraints: Dict[str, Dict[str, object]] = {}
        all_agent_targets = sorted(
            anon_name
            for anon_name in self._performer_counts.keys()
            if anon_name != self._anon_user
        )
        spoken_agent_reals = {
            m.sender for m in self.state.messages
            if m.sender != self.state.user_name and m.sender != "[news]"
        }
        spoken_agent_anons = {
            self._name_map.get(real, real) for real in spoken_agent_reals
        }

        for speaker_anon in visible_speakers:
            speaker_real = self._deanon_name(speaker_anon)
            valid_targets: List[str] = []
            forbidden_targets: List[str] = []
            for target_anon in all_agent_targets:
                if target_anon == speaker_anon:
                    continue
                if target_anon not in spoken_agent_anons:
                    continue
                target_real = self._deanon_name(target_anon)
                if self._agents_share_alignment_cell(speaker_real, target_real):
                    forbidden_targets.append(target_anon)
                else:
                    valid_targets.append(target_anon)

            exclude_senders = None
            exclude_ids = None
            if self._should_boost_replies_mentions() and self.state.messages:
                last_msg = self.state.messages[-1]
                exclude_senders = {last_msg.sender}
                exclude_ids = {last_msg.message_id}

            best_anchor = self._find_best_direct_target_message(
                speaker_real,
                recent_messages,
                exclude_senders=exclude_senders,
                exclude_message_ids=exclude_ids,
            )
            best_anchor_text = None
            if best_anchor is not None:
                best_anchor_text = f"{best_anchor.sender} [{best_anchor.message_id}]"
            participant_target_mode = (
                "support-only"
                if self._expected_like_minded_for_agent(speaker_real) is True
                else "allowed"
            )

            constraints[speaker_anon] = {
                "valid_targets": valid_targets,
                "forbidden_targets": forbidden_targets,
                "best_reply_anchor": best_anchor_text,
                "participant_target_mode": participant_target_mode,
            }

        return format_target_constraints_by_speaker(constraints)

    @staticmethod
    def _trailing_speaker_streak(messages: List[Message], agent_names: Set[str]) -> tuple[Optional[str], int]:
        """Return the trailing consecutive speaking streak for agent messages."""
        speaker = None
        count = 0
        for msg in reversed(messages):
            if msg.sender not in agent_names:
                break
            if speaker is None:
                speaker = msg.sender
                count = 1
                continue
            if msg.sender != speaker:
                break
            count += 1
        return speaker, count

    def set_participant_stance_hint(self, participant_stance_hint: Optional[str]) -> None:
        """Refresh the participant's fixed survey-based side in prompts and summaries."""
        self.participant_stance_hint = participant_stance_hint
        self._participant_hint_text = format_participant_hint(participant_stance_hint)
        self._participant_alignment_cell_text = format_participant_alignment_cell(
            self._participant_alignment_cell_live()
        )

    def _format_treatment_fidelity_summary(self) -> str:
        """Summarise structural alignment plus observed incivility as simple percentages."""
        agent_messages = self._agent_messages_so_far()
        if not agent_messages:
            return "(No agent messages yet.)"

        total = len(agent_messages)
        expected_like = sum(
            1
            for message in agent_messages
            if self._expected_like_minded_for_agent(message.sender) is True
        )
        expected_not_like = sum(
            1
            for message in agent_messages
            if self._expected_like_minded_for_agent(message.sender) is False
        )

        classified_incivility = [message for message in agent_messages if message.is_incivil is not None]
        incivil_count = sum(1 for message in classified_incivility if message.is_incivil)
        civil_count = sum(1 for message in classified_incivility if message.is_incivil is False)
        cell_order = ["pro_topic", "anti_topic"]
        cell_counts: Dict[str, int] = {cell: 0 for cell in cell_order}
        unknown_cell_count = 0
        for message in agent_messages:
            traits = self._agent_traits.get(message.sender) or {}
            cell = self._agent_alignment_cell_from_traits(traits)
            if cell in cell_counts:
                cell_counts[cell] += 1
            else:
                unknown_cell_count += 1

        def _pct(count: int, base: int) -> str:
            return f"{round((count / base) * 100)}%" if base > 0 else "0%"

        lines = [
            f"- Agent messages published: {total}",
            f"- Like-minded messages so far: {expected_like}/{total} ({_pct(expected_like, total)})",
            f"- Not-like-minded messages so far: {expected_not_like}/{total} ({_pct(expected_not_like, total)})",
            "- Messages by alignment cell so far: "
            + ", ".join(
                f"{cell}={cell_counts[cell]}/{total} ({_pct(cell_counts[cell], total)})"
                for cell in cell_order
            )
            + (f", unknown={unknown_cell_count}/{total} ({_pct(unknown_cell_count, total)})" if unknown_cell_count else ""),
        ]
        if classified_incivility:
            uncivil_left = 0
            uncivil_right = 0
            for message in classified_incivility:
                if message.is_incivil is True:
                    traits = self._agent_traits.get(message.sender) or {}
                    sender_ideology = self._normalize_agent_ideology(traits.get("ideology"))
                    if sender_ideology == "left":
                        uncivil_left += 1
                    elif sender_ideology == "right":
                        uncivil_right += 1
            lines.append(
                f"- Incivil messages so far: {incivil_count}/{len(classified_incivility)} ({_pct(incivil_count, len(classified_incivility))}) [left={uncivil_left}, right={uncivil_right}]"
            )
            lines.append(
                f"- Civil messages so far: {civil_count}/{len(classified_incivility)} ({_pct(civil_count, len(classified_incivility))})"
            )
        else:
            lines.append("- Incivil messages so far: no classifier output yet")
            lines.append("- Civil messages so far: no classifier output yet")
        if total < 5:
            lines.append("- Early window note: fewer than 5 agent messages have been published, so do not treat temporary imbalance as a serious failure yet.")
        return "\n".join(lines)

    async def _classify_message(self, agent_message: str, agent_name: Optional[str] = None) -> Dict[str, Optional[object]]:
        """Run the post-moderation classifier stage for a generated message."""
        participant_messages = [
            message for message in self.state.messages if message.sender == self.state.user_name
        ]
        recent_context = self.state.messages[-3:] if self.state.messages else []

        agent_ideology = None
        if agent_name and self._agent_traits:
            traits = self._agent_traits.get(agent_name) or {}
            agent_ideology = traits.get("ideology")

        classifier_user_prompt = build_classifier_user_prompt(
            participant_messages=participant_messages,
            agent_message=agent_message,
            prompt_template=self.classifier_prompt_template,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            agent_ideology=agent_ideology,
            participant_name=self.state.user_name,
            agent_name=agent_name,
            recent_context=recent_context,
        )

        classifier_raw = None
        try:
            classifier_raw = await self.classifier_llm.generate_response(
                classifier_user_prompt,
                max_retries=1,
                system_prompt=self._classifier_system_prompt,
            )
        except Exception as exc:
            self.logger.log_error("classifier_llm_call", str(exc))

        self.logger.log_llm_call(
            agent_name="__classifier__",
            prompt=f"[SYSTEM]\n{self._classifier_system_prompt}\n\n[USER]\n{classifier_user_prompt}",
            response=classifier_raw,
            error=None if classifier_raw else "Classifier LLM returned no response",
        )

        if not classifier_raw:
            return {}

        try:
            return parse_classifier_response(classifier_raw)
        except ValueError as exc:
            self.logger.log_error("classifier_parse", str(exc))
            return {}

    def _deanon_name(self, anon_name: str) -> str:
        """Map an anonymous label back to the real name."""
        return self._reverse_map.get(anon_name, anon_name)

    def _try_auto_like(
        self,
        allowed_performers: Optional[Set[str]],
        rng: random.Random,
    ) -> Optional[TurnResult]:
        """Attempt to inject a probabilistic like without calling the LLM.

        Picks a random eligible agent and the most recent message that agent
        has not already liked.  Returns a ready TurnResult, or None if no
        valid target exists or the RNG roll fails.
        """
        if rng.random() >= self.auto_like_probability:
            return None

        agents = [a.name for a in self.state.agents if a.name != self.state.user_name]
        if allowed_performers is not None:
            agents = [n for n in agents if n in allowed_performers]
        if not agents:
            return None

        # Candidate messages: N most recent, from anyone.
        recent = self.state.messages[-self.auto_like_recency_window:]
        if not recent:
            return None

        rng.shuffle(agents)
        for agent_name in agents:
            likeable = [
                m for m in reversed(recent)
                if agent_name not in (m.liked_by or set())
                and m.sender != agent_name
                and self._can_like_message(agent_name, m)
            ]
            if not likeable:
                continue

            target = likeable[0]
            self._action_counts["like"] += 1
            anon_name = self._name_map.get(agent_name, agent_name)
            self._performer_counts[anon_name] = self._performer_counts.get(anon_name, 0) + 1
            self._last_agent = anon_name
            self._last_action_type = "like"
            self.logger.log_error(
                "auto_like",
                f"Auto-like: '{agent_name}' -> {target.message_id} ({target.sender})",
            )
            return TurnResult(
                action_type="like",
                agent_name=agent_name,
                target_message_id=target.message_id,
                priority="low",
                performer_rationale="auto",
                action_rationale="probabilistic like injection",
            )

        return None

    async def execute_turn(
        self,
        internal_validity_criteria: str,
        allowed_performers: Optional[Set[str]] = None,
    ) -> Optional[TurnResult]:
        """Run one full Update Ã¢â€ â€™ Evaluate Ã¢â€ â€™ Action Ã¢â€ â€™ Performer Ã¢â€ â€™ Moderator cycle.

        ``allowed_performers`` (real agent names) restricts which agents the
        Director can select in parallel mode, preventing duplicate picks.
        When ``None``, all agents are eligible (sequential mode).

        Returns a TurnResult on success, or None if the cycle fails.
        """
        self._participant_alignment_cell_text = format_participant_alignment_cell(
            self._participant_alignment_cell_live()
        )

        # 1. Gather recent messages, then anonymize.
        #    Action and Evaluate use separate window sizes; Update and human
        #    detection use the Action window (which contains the most recent message).
        recent_action = self.state.get_recent_messages(self.action_window_size)
        agents = self.state.agents

        anon_recent_action = [anonymize_message(m, self._name_map) for m in recent_action]

        # 1b. Detect if the human posted since the last orchestrator turn.
        #     Do NOT treat the participant as a performer for Update purposes â€”
        #     the Director cannot instruct the human, and running Update on their
        #     message causes the Director to try to "correct" them in Action.
        if anon_recent_action and anon_recent_action[-1].sender == self._anon_user:
            self._last_action_type = "message"
            # Leave _last_agent unchanged so Update still targets the previous agent.

        # 2. Director Update (skip on first turn â€” nothing to assess)
        if anon_recent_action and self._last_agent and self._last_agent != self._anon_user:
            # Skip Update for likes â€” they aren't significant enough for a profile revision.
            if self._last_action_type != "like":
                await self._director_update(anon_recent_action)

        # 2b. Director Evaluate
        #     Before the first full interval fires, evaluate every turn so the
        #     Director has validity guidance from the very start.  Once the first
        #     full window completes, switch to the regular cadence.
        #     Save counter state so we can restore it if the Director yields (wait turn).
        _saved_counter = self._turns_since_evaluate
        _saved_first_interval = self._has_completed_first_interval
        self._turns_since_evaluate += 1
        should_evaluate = (
            not self._has_completed_first_interval          # warm-up: every turn
            or self._turns_since_evaluate >= self.evaluate_interval  # steady-state
        )
        if should_evaluate:
            recent_eval = self.state.get_recent_messages(self.evaluate_interval)
            anon_recent_eval = [anonymize_message(m, self._name_map) for m in recent_eval]
            await self._director_evaluate(internal_validity_criteria, anon_recent_eval)
            if self._turns_since_evaluate >= self.evaluate_interval:
                self._has_completed_first_interval = True
                self._turns_since_evaluate = 0

        # 3. Director Action
        #    The Director selects from all performers visible in profiles/chat log.
        #    If it picks the human participant, the turn becomes a 'wait'.
        #    In parallel mode, only show profiles for the allowed agent subset
        #    so each pipeline's Director picks from its own pool.
        action_profiles = self.agent_profiles
        action_perf_counts = self._performer_counts
        speaking_agent_names = {a.name for a in agents if a.name != self.state.user_name}
        capped_speaker, capped_streak = self._trailing_speaker_streak(recent_action, speaking_agent_names)
        disallowed_speaker = capped_speaker if capped_streak >= 2 else None
        base_allowed_real = (
            set(allowed_performers)
            if allowed_performers is not None
            else {a.name for a in agents if a.name != self.state.user_name}
        )
        if disallowed_speaker:
            base_allowed_real.discard(disallowed_speaker)
        filtered_allowed_real = self._filter_candidate_agents_for_targets(
            internal_validity_criteria,
            base_allowed_real,
        )
        allowed_anon = {self._name_map[n] for n in filtered_allowed_real if n in self._name_map}
        # Always include the human so the Director can still yield ('wait').
        allowed_anon.add(self._anon_user)
        action_profiles = {k: v for k, v in self.agent_profiles.items() if k in allowed_anon}
        action_perf_counts = {k: v for k, v in self._performer_counts.items() if k in allowed_anon}

        # Probabilistic like: resolve locally before calling the LLM.
        auto_like = self._try_auto_like(base_allowed_real, self._rng)
        if auto_like is not None:
            return auto_like

        action_data = await self._director_action(
            anon_recent_action,
            real_recent=recent_action,
            override_profiles=action_profiles,
            override_perf_counts=action_perf_counts,
        )
        if action_data is None:
            return None

        action_type = action_data["action_type"]
        agent_name = self._deanon_name(action_data["next_performer"])
        target_user = action_data.get("target_user")
        if target_user:
            target_user = self._deanon_name(target_user)
        target_message_id = action_data.get("target_message_id")
        priority = action_data.get("priority")
        performer_rationale = action_data.get("performer_rationale")
        action_rationale = action_data.get("action_rationale")

        # Upgrade out-of-turn targeted message to a reply
        if action_type == "message" and target_user:
            target_msg = None
            for m in reversed(self.state.messages):
                if m.sender == target_user:
                    target_msg = m
                    break
            if target_msg and self.state.messages and target_msg.message_id != self.state.messages[-1].message_id:
                action_type = "reply"
                action_data["action_type"] = "reply"
                target_message_id = target_msg.message_id
                action_data["target_message_id"] = target_message_id
                target_user = None
                action_data["target_user"] = None

        # 3a. If the participant's most recent message in the window @mentions or
        #     addresses a specific agent that has NOT yet replied to it, force
        #     that agent to reply.  We scan backwards through the window to find
        #     the latest participant message, then check whether any agent has
        #     already responded after it â€” if so, the obligation is discharged.
        addressed_agent = None
        pending_human_msg = None
        agent_names = {a.name for a in agents if a.name != self.state.user_name}

        for msg in reversed(recent_action):
            if msg.sender == self.state.user_name:
                pending_human_msg = msg
                break
            # An agent replied after the participant's message â€” obligation discharged.
            if msg.sender in agent_names:
                break

        if pending_human_msg:
            # Check explicit @mentions first
            if pending_human_msg.mentions:
                for m in pending_human_msg.mentions:
                    if m in agent_names:
                        addressed_agent = m
                        break

            # Fallback: message starts with or contains @agentname
            if addressed_agent is None:
                content_lower = (pending_human_msg.content or "").lower()
                for name in agent_names:
                    if content_lower.startswith(name.lower()) or f"@{name.lower()}" in content_lower:
                        addressed_agent = name
                        break

        if addressed_agent and addressed_agent != agent_name:
            self.logger.log_error(
                "director_override_participant_mention",
                f"Participant addressed '{addressed_agent}'; overriding Director choice '{agent_name}'",
            )
            agent_name = addressed_agent
            action_data["next_performer"] = self._name_map.get(addressed_agent, addressed_agent)

        if addressed_agent:
            # Force a reply to the participant's message and reset the instruction
            # so the performer gets a coherent brief (original instruction was for a different agent/action).
            action_type = "reply"
            action_data["action_type"] = "reply"
            target_message_id = pending_human_msg.message_id
            action_data["target_message_id"] = target_message_id
            target_user = None
            action_data["target_user"] = None
            action_data["performer_instruction"] = {
                "objective": f"Reply directly to {self.state.user_name}'s message addressed to you.",
                "motivation": f"{self.state.user_name} addressed you specifically â€” not replying would feel rude and unnatural.",
                "directive": "Keep it conversational and on-topic; stay true to your fixed stance and character.",
            }

        latest_message_anchor = self._find_latest_message_anchor(agent_name, recent_action)
        is_true_room_wide_opener = (
            action_type == "message"
            and not target_user
            and not target_message_id
            and latest_message_anchor is None
        )
        if is_true_room_wide_opener and not (disallowed_speaker and agent_name == disallowed_speaker):
            is_first_turn_for_agent = not self._agent_has_spoken_before(agent_name)
            existing_room_wide_openers = self._count_room_wide_openers(agent_names)
            previous_was_room_wide_opener = self._last_message_was_room_wide_opener(agent_names)
            room_wide_violation = (
                not is_first_turn_for_agent
                or existing_room_wide_openers >= MAX_ROOM_WIDE_OPENERS
                or previous_was_room_wide_opener
            )
            if room_wide_violation:
                anchor_message = self._find_best_direct_target_message(agent_name, recent_action)
                if anchor_message is None:
                    anchor_message = self._find_room_wide_anchor_message(agent_name)
                if anchor_message is None:
                    self.logger.log_error(
                        "director_room_wide_opener_blocked",
                        f"Blocked room-wide opener for '{agent_name}' but found no anchor message; skipping turn",
                    )
                    self._turns_since_evaluate = _saved_counter
                    self._has_completed_first_interval = _saved_first_interval
                    return TurnResult(
                        action_type="wait",
                        agent_name=agent_name,
                        priority=priority,
                        performer_rationale=performer_rationale,
                        action_rationale=action_rationale,
                    )

                self.logger.log_error(
                    "director_room_wide_opener_redirected",
                    f"Redirected room-wide opener for '{agent_name}' to reply to '{anchor_message.sender}'",
                )
                action_type = "reply"
                action_data["action_type"] = "reply"
                target_message_id = anchor_message.message_id
                action_data["target_message_id"] = target_message_id
                target_user = None
                action_data["target_user"] = None
                action_data["performer_instruction"] = {
                    "objective": f"Join the ongoing thread by responding to {anchor_message.sender}'s recent message.",
                    "motivation": "A fresh room-wide statement here would make the chat feel disjointed, so anchor yourself to the existing conversation.",
                    "directive": "Reply directly and conversationally to the quoted message instead of posting a general statement to the room. Keep the target coherent with your alignment cell.",
                }

        if disallowed_speaker and agent_name == disallowed_speaker:
            self.logger.log_error(
                "director_consecutive_speaker_limit",
                f"Agent '{agent_name}' already spoke {capped_streak} turns in a row; skipping a third consecutive speaking turn",
            )
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            return TurnResult(
                action_type="wait",
                agent_name=agent_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # 3b. Fix self-mention: if Director told an agent to @mention itself,
        #     downgrade to a regular message (no target_user).
        if action_type == "@mention" and target_user and target_user == agent_name:
            self.logger.log_error(
                "director_self_mention",
                f"Director told '{agent_name}' to @mention itself; converting to message",
            )
            action_type = "message"
            action_data["action_type"] = "message"
            target_user = None
            # Clear the @mention instruction â€” the performer now posts a standalone message.
            if action_data.get("performer_instruction"):
                action_data["performer_instruction"] = {
                    "objective": action_data["performer_instruction"].get("objective", "Post a message to the chatroom."),
                    "motivation": action_data["performer_instruction"].get("motivation", ""),
                    "directive": action_data["performer_instruction"].get("directive", "Stay true to your fixed stance and character."),
                }

        cross_cell_target = None

        # 3c. Prevent direct infighting between agents in the same alignment cell.
        if action_type in {"reply", "@mention", "message"}:
            same_side_target = None
            if target_user and self._agents_share_alignment_cell(agent_name, target_user):
                same_side_target = target_user
            elif target_message_id:
                target_msg_for_guard = next(
                    (m for m in self.state.messages if m.message_id == target_message_id),
                    None,
                )
                if target_msg_for_guard and self._agents_share_alignment_cell(agent_name, target_msg_for_guard.sender):
                    same_side_target = target_msg_for_guard.sender

            if same_side_target:
                retarget_message = self._find_best_direct_target_message(
                    agent_name,
                    recent_action,
                    exclude_senders={same_side_target, agent_name},
                )
                if retarget_message is not None:
                    self.logger.log_error(
                        "director_same_side_target",
                        f"Director targeted same-cell agents '{agent_name}' -> '{same_side_target}'; redirecting to reply to '{retarget_message.sender}'",
                    )
                    action_type = "reply"
                    action_data["action_type"] = "reply"
                    target_user = None
                    action_data["target_user"] = None
                    target_message_id = retarget_message.message_id
                    action_data["target_message_id"] = target_message_id
                    action_data["performer_instruction"] = {
                        "objective": f"Push your cell's position by responding to {retarget_message.sender} instead of attacking an allied same-cell agent.",
                        "motivation": "You share a fixed alignment cell with the originally targeted agent, so infighting would be incoherent; redirect your energy toward a valid opposing or participant message.",
                        "directive": "Reply directly to the quoted message. Do not criticize, mock, or challenge agents who share your alignment cell.",
                    }
                else:
                    self.logger.log_error(
                        "director_same_side_target",
                        f"Director targeted same-cell agents '{agent_name}' -> '{same_side_target}'; converting to a non-targeted message",
                    )
                    action_type = "message"
                    action_data["action_type"] = "message"
                    target_user = None
                    action_data["target_user"] = None
                    target_message_id = None
                    action_data["target_message_id"] = None
                    action_data["performer_instruction"] = {
                        "objective": "Reinforce your cell's position without attacking allied agents.",
                        "motivation": "You occupy the same alignment cell, so infighting would feel incoherent and weaken the discussion.",
                        "directive": "Sound supportive or additive; do not criticize, mock, or challenge agents who share your alignment cell.",
                    }
            else:
                if target_user and self._agents_have_different_alignment_cells(agent_name, target_user):
                    cross_cell_target = target_user
                elif target_message_id:
                    target_msg_for_guard = next(
                        (m for m in self.state.messages if m.message_id == target_message_id),
                        None,
                    )
                    if (
                        target_msg_for_guard
                        and self._agents_have_different_alignment_cells(agent_name, target_msg_for_guard.sender)
                    ):
                        cross_cell_target = target_msg_for_guard.sender

                if cross_cell_target:
                    existing_instruction = dict(action_data.get("performer_instruction") or {})
                    directive = (existing_instruction.get("directive") or "").strip()
                    contrastive_clause = (
                        "You are addressing an agent from a different alignment cell: do not agree with, praise, "
                        "validate, echo, or pile on in support of them. If you engage, make the contrast between "
                        "your cell and theirs explicit."
                    )
                    existing_instruction["directive"] = (
                        f"{directive} {contrastive_clause}".strip()
                        if directive else contrastive_clause
                    )
                    action_data["performer_instruction"] = existing_instruction

        participant_targeted_message = None
        if action_type in {"reply", "@mention", "message"}:
            if target_user == self.state.user_name:
                participant_targeted_message = next(
                    (
                        m for m in self.state.messages
                        if m.sender == self.state.user_name
                        and (not target_message_id or m.message_id == target_message_id)
                    ),
                    None,
                )
            elif target_message_id:
                participant_targeted_message = next(
                    (
                        m for m in self.state.messages
                        if m.message_id == target_message_id and m.sender == self.state.user_name
                    ),
                    None,
                )

        if participant_targeted_message is not None and self._expected_like_minded_for_agent(agent_name) is True:
            existing_instruction = dict(action_data.get("performer_instruction") or {})
            directive = (existing_instruction.get("directive") or "").strip()
            support_clause = (
                "Your alignment cell matches the participant's current cell: do not attack, blame, mock, or "
                "undermine the participant. You may defend them, reinforce them, or sharpen their shared case."
            )
            existing_instruction["directive"] = (
                f"{directive} {support_clause}".strip()
                if directive else support_clause
            )
            action_data["performer_instruction"] = existing_instruction

        # Guard: Downgrade replies/mentions targeting agents who haven't spoken yet
        spoken_senders = {m.sender for m in self.state.messages if m.sender != "[news]"}
        # The participant is always considered active
        spoken_senders.add(self.state.user_name)

        target_inactive = False
        inactive_reason = ""
        if target_user and target_user not in spoken_senders:
            target_inactive = True
            inactive_reason = f"target_user '{target_user}' has not spoken yet"
        elif target_message_id:
            target_msg = next(
                (m for m in self.state.messages if m.message_id == target_message_id),
                None,
            )
            if not target_msg:
                target_inactive = True
                inactive_reason = f"target_message_id '{target_message_id}' not found"
            elif target_msg.sender not in spoken_senders:
                target_inactive = True
                inactive_reason = f"sender '{target_msg.sender}' of targeted message has not spoken yet"

        if target_inactive and action_type in {"reply", "@mention"}:
            self.logger.log_error(
                "downgrade_inactive_target",
                f"Downgrading {action_type} for '{agent_name}' to message because {inactive_reason}",
            )
            action_type = "message"
            action_data["action_type"] = "message"
            target_user = None
            action_data["target_user"] = None
            target_message_id = None
            action_data["target_message_id"] = None
            if action_data.get("performer_instruction"):
                action_data["performer_instruction"] = {
                    "objective": "Post a message responding to the conversation.",
                    "motivation": action_data["performer_instruction"].get("motivation", ""),
                    "directive": action_data["performer_instruction"].get("directive", "Stay true to your fixed stance and character."),
                }
        elif action_type == "message" and target_user and target_user not in spoken_senders:
            self.logger.log_error(
                "remove_inactive_target",
                f"Removing target_user for '{agent_name}' because target_user '{target_user}' has not spoken yet",
            )
            target_user = None
            action_data["target_user"] = None
            target_message_id = None
            action_data["target_message_id"] = None

        # Downgrade replies/mentions that target the immediately preceding message/sender to plain messages
        if self.state.messages:
            last_msg = self.state.messages[-1]
            if action_type == "reply" and target_message_id == last_msg.message_id:
                self.logger.log_event("action_normalization", {
                    "normalization_type": "downgrade_immediate_reply",
                    "agent_name": agent_name,
                    "message": f"Downgrading reply to message because it targets the immediately preceding message {target_message_id}",
                    "target_message_id": target_message_id,
                })
                action_type = "message"
                action_data["action_type"] = "message"
                target_message_id = None
                action_data["target_message_id"] = None
                target_user = None
                action_data["target_user"] = None
                if action_data.get("performer_instruction"):
                    original_objective = action_data["performer_instruction"].get("objective", "")
                    original_directive = action_data["performer_instruction"].get("directive", "Stay true to your fixed stance and character.")
                    action_data["performer_instruction"] = {
                        "objective": original_objective or "Respond directly to the immediately preceding turn as a plain message.",
                        "motivation": action_data["performer_instruction"].get("motivation", ""),
                        "directive": f"{original_directive} Treat this as a direct continuation of the immediately preceding message, without using reply metadata or naming the target in the body.",
                    }
            elif action_type == "@mention" and target_user == last_msg.sender:
                self.logger.log_event("action_normalization", {
                    "normalization_type": "downgrade_immediate_mention",
                    "agent_name": agent_name,
                    "message": f"Downgrading mention to message because it targets the sender of the immediately preceding message '{target_user}'",
                    "target_user": target_user,
                })
                action_type = "message"
                action_data["action_type"] = "message"
                target_user = None
                action_data["target_user"] = None
                target_message_id = None
                action_data["target_message_id"] = None
                if action_data.get("performer_instruction"):
                    original_objective = action_data["performer_instruction"].get("objective", "")
                    original_directive = action_data["performer_instruction"].get("directive", "Stay true to your fixed stance and character.")
                    action_data["performer_instruction"] = {
                        "objective": original_objective or "Respond directly to the immediately preceding turn as a plain message.",
                        "motivation": action_data["performer_instruction"].get("motivation", ""),
                        "directive": f"{original_directive} Treat this as a direct continuation of the immediately preceding message, without using @mention metadata or naming the target in the body.",
                    }
            elif action_type == "message" and target_user == last_msg.sender:
                self.logger.log_error(
                    "downgrade_immediate_targeted_message",
                    f"Removing target_user for '{agent_name}' because it targets the sender of the immediately preceding message '{target_user}'",
                )
                target_user = None
                action_data["target_user"] = None
                target_message_id = None
                action_data["target_message_id"] = None

        # 3b. Handle 'wait' â€” Director selected the human participant.
        #     Skip Performer/Moderator and restore evaluate counter
        #     (wait turns are not productive turns).
        if agent_name == self.state.user_name:
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            return TurnResult(
                action_type="wait",
                agent_name=agent_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # Validate that the chosen agent exists; fall back to a random valid agent.
        if not agents:
            self.logger.log_error("director_agent", "No agents available for this session")
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            return TurnResult(
                action_type="wait",
                agent_name=self.state.user_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )
        if not any(a.name == agent_name for a in agents):
            pool = list(filtered_allowed_real) if filtered_allowed_real else [a.name for a in agents]
            fallback = random.choice(pool)
            self.logger.log_error(
                "director_agent",
                f"Director chose unknown agent '{agent_name}'; falling back to '{fallback}'",
            )
            agent_name = fallback

        # Enforce the filtered subset used for this Director call.
        if filtered_allowed_real and agent_name not in filtered_allowed_real:
            pool = list(filtered_allowed_real)
            fallback = random.choice(pool)
            self.logger.log_error(
                "director_agent_restricted",
                f"Director chose '{agent_name}' outside its filtered treatment subset; "
                f"falling back to '{fallback}'",
            )
            agent_name = fallback

        # Track last agent and action type for next turn's Update call (use anonymous name).
        # Save previous values so we can restore on performer failure (silent skip).
        _saved_last_agent = self._last_agent
        _saved_last_action_type = self._last_action_type
        self._last_agent = self._name_map.get(agent_name, action_data["next_performer"])
        self._last_action_type = action_type

        # 4. Handle 'like' actions (no Performer call needed)
        if action_type == "like":
            # Guard: skip duplicate likes (agent already liked this message).
            if target_message_id:
                target_msg = next(
                    (m for m in self.state.messages if m.message_id == target_message_id),
                    None,
                )
                if target_msg and agent_name in (target_msg.liked_by or set()):
                    self.logger.log_error(
                        "director_duplicate_like",
                        f"'{agent_name}' already liked message {target_message_id}; skipping as wait",
                    )
                    self._turns_since_evaluate = _saved_counter
                    self._has_completed_first_interval = _saved_first_interval
                    self._last_agent = _saved_last_agent
                    self._last_action_type = _saved_last_action_type
                    return TurnResult(
                        action_type="wait",
                        agent_name=agent_name,
                        priority=priority,
                        performer_rationale=performer_rationale,
                        action_rationale=action_rationale,
                    )

            self._action_counts["like"] += 1
            anon_name = self._name_map.get(agent_name, agent_name)
            self._performer_counts[anon_name] = self._performer_counts.get(anon_name, 0) + 1
            return TurnResult(
                action_type="like",
                agent_name=agent_name,
                target_message_id=target_message_id,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )

        # 5. Performer Ã¢â€ â€™ Moderator loop (max MAX_PERFORMER_RETRIES attempts)
        performer_instruction = action_data.get("performer_instruction", {})

        # Get the selected agent's profile and restore real names for the performer.
        anon_agent_name = self._name_map.get(agent_name, agent_name)
        agent_profile = deanonymize_text(
            self.agent_profiles.get(anon_agent_name, ""),
            self._reverse_map,
        )

        # Look up target message if needed.
        # For 'message' with a target_user (targeted response), find the
        # target user's most recent message so the Performer has context.
        target_message = None
        if target_message_id:
            target_message = next(
                (m for m in self.state.messages if m.message_id == target_message_id),
                None,
            )
        elif action_type == "message" and target_user:
            # Director chose a targeted message but no explicit message_id â€”
            # resolve the target user's most recent message.
            for m in reversed(self.state.messages):
                if m.sender == target_user:
                    target_message = m
                    break

        # Gather this performer's recent messages with real names so it can avoid repetition
        # while still knowing who it has interacted with.
        recent_by_agent = []
        if self.performer_memory_size > 0:
            for m in reversed(self.state.messages):
                if m.sender == agent_name:
                    recent_by_agent.append(m)
                    if len(recent_by_agent) >= self.performer_memory_size:
                        break
            recent_by_agent.reverse()

        recent_by_others = []
        if self.performer_memory_size > 0:
            for m in reversed(self.state.messages):
                if m.sender != agent_name:
                    recent_by_others.append(m)
                    if len(recent_by_others) >= self.performer_memory_size:
                        break
            recent_by_others.reverse()

        # Get agent's raw persona for the performer (not anonymized â€” performer knows their own character)
        agent_obj = next((a for a in agents if a.name == agent_name), None)
        agent_persona = (agent_obj.persona or None) if agent_obj else None

        agent_length_traits = (self._agent_traits.get(agent_name) or {}) if self._agent_traits else {}
        _len_min = agent_length_traits.get("message_length_min")
        _len_max = agent_length_traits.get("message_length_max")
        target_word_count: Optional[int] = None
        if _len_min is None or _len_max is None:
            _len_min, _len_max = default_message_length_range(
                self._agent_civility_bucket(agent_name)
            )
        if _len_min is not None and _len_max is not None:
            try:
                target_word_count = random.randint(int(_len_min), max(int(_len_min), int(_len_max)))
            except (ValueError, TypeError):
                pass

        # Extract narratives for this agent's cell
        narratives_str = None
        if self.narrative_pool and self._agent_traits:
            traits = self._agent_traits.get(agent_name) or {}
            alignment_cell = traits.get("alignment_cell")
            ideology = traits.get("ideology")
            if alignment_cell and ideology:
                # Find matching cell in the list of narrative cells
                matching_cell = next(
                    (
                        cell for cell in self.narrative_pool
                        if cell.get("alignment_cell") == alignment_cell and cell.get("ideology") == ideology
                    ),
                    None
                )
                if matching_cell and matching_cell.get("narratives"):
                    # Split by newline and format as bullet points
                    raw_narratives = matching_cell["narratives"]
                    lines = [line.strip() for line in raw_narratives.split("\n") if line.strip()]
                    if lines:
                        # Limit to a random subset of 5 narratives to avoid overwhelming the Performer LLM
                        sampled_lines = self._rng.sample(lines, min(5, len(lines)))
                        narratives_str = "\n".join(f"- {line}" for line in sampled_lines)

        base_performer_user_prompt = build_performer_user_prompt(
            instruction=performer_instruction,
            agent_profile=agent_profile,
            action_type=action_type,
            persona=agent_persona,
            target_user=target_user,
            target_message=target_message,
            recent_messages=recent_by_agent,
            recent_room_messages=recent_by_others,
            chatroom_context=self._performer_prompt_context,
            target_word_count=target_word_count,
            template=self.performer_prompt_template,
            narratives=narratives_str,
        )
        performer_user_prompt = base_performer_user_prompt

        if self._agent_civility_bucket(agent_name) == "uncivil":
            selected_dims = select_incivility_dimensions(self._rng)
            incivility_instructions = build_incivility_instruction_block(selected_dims)
            if incivility_instructions:
                performer_user_prompt = performer_user_prompt.rstrip() + "\n\n" + incivility_instructions


        content = None
        classification = {}
        mentions = None
        reply_to = None
        quoted_text = None

        # Build (or retrieve cached) per-agent performer system prompt.
        if agent_name not in self._performer_system_prompts:
            self._performer_system_prompts[agent_name] = build_performer_system_prompt(
                chatroom_context=self._performer_prompt_context,
                agent_name=agent_name,
                participant_name=self.state.user_name,
                agent_traits=self._agent_traits.get(agent_name) if self._agent_traits else None,
                template=self.performer_prompt_template,
            )
        performer_system_prompt = self._performer_system_prompts[agent_name]

        for attempt in range(1, MAX_PERFORMER_RETRIES + 1):
            # 5a. Call the Performer
            performer_raw = None
            try:
                performer_raw = await self.performer_llm.generate_response(
                    performer_user_prompt, max_retries=1,
                    system_prompt=performer_system_prompt,
                )
            except Exception as e:
                self.logger.log_error("performer_llm_call", str(e))

            self.logger.log_llm_call(
                agent_name=agent_name,
                prompt=f"[SYSTEM]\n{performer_system_prompt}\n\n[USER]\n{performer_user_prompt}",
                response=performer_raw,
                error=None if performer_raw else f"Performer LLM returned no response (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
            )

            if not performer_raw:
                continue

            if _looks_truncated_response(performer_raw):
                self.logger.log_error(
                    "performer_output_truncated",
                    f"Performer output appears truncated (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                    context={"agent_name": agent_name, "action_type": action_type},
                )
                continue

            # 5b. Only call the Moderator when the performer output looks messy.
            if self._performer_output_needs_moderator(performer_raw):
                moderator_user_prompt = build_moderator_user_prompt(
                    performer_output=performer_raw,
                    template=self.moderator_prompt_template,
                )

                moderator_raw = None
                try:
                    moderator_raw = await self.moderator_llm.generate_response(
                        moderator_user_prompt, max_retries=1,
                        system_prompt=self._moderator_system_prompt,
                    )
                except Exception as e:
                    self.logger.log_error("moderator_llm_call", str(e))

                self.logger.log_llm_call(
                    agent_name="__moderator__",
                    prompt=f"[SYSTEM]\n{self._moderator_system_prompt}\n\n[USER]\n{moderator_user_prompt}",
                    response=moderator_raw,
                    error=None if moderator_raw else f"Moderator LLM returned no response (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                )

                content = parse_moderator_response(moderator_raw)

                if content is None:
                    self.logger.log_error(
                        "moderator_no_content",
                        f"Moderator could not extract content from performer output (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                    )
                    continue

                if _looks_truncated_response(content):
                    self.logger.log_error(
                        "moderator_output_truncated",
                        f"Moderator output appears truncated (attempt {attempt}/{MAX_PERFORMER_RETRIES})",
                        context={"agent_name": agent_name, "action_type": action_type},
                    )
                    content = None
                    continue
            else:
                content = performer_raw.strip()

            candidate_content = deanonymize_text(content, self._reverse_map)
            candidate_content = self._strip_vocative_prefix(candidate_content)

            # Post-process ellipsis: replace with a space at the end of the message (which gets stripped), and a dot in the middle.
            candidate_content = re.sub(r"(?:\.{3,}|…+)\s*$", " ", candidate_content)
            candidate_content = re.sub(r"(?:\.{3,}|…+)", ".", candidate_content)
            candidate_content = candidate_content.strip()

            if action_type == "reply" and target_message:
                candidate_content = _strip_target_quote_echo(candidate_content, target_message)

            if action_type == "@mention" and target_user:
                candidate_content = re.sub(
                    r"^@?" + re.escape(target_user) + r"\s*",
                    "",
                    candidate_content,
                ).strip()

            if self.humanize_output:
                from utils.humanizer import humanize as _humanize
                if agent_name in self.humanize_per_agent:
                    r = self.humanize_per_agent[agent_name]
                else:
                    r = self.humanize_rules
                candidate_content = _humanize(
                    candidate_content,
                    strip_hashtags=int(r.get("strip_hashtags", 100)),
                    strip_inverted_punct=int(r.get("strip_inverted_punct", 100)),
                    word_subs=int(r.get("word_subs", 80)),
                    drop_accents=int(r.get("drop_accents", 40)),
                    comma_spacing=int(r.get("comma_spacing", 50)),
                    max_emoji=int(r.get("max_emoji", 1)),
                    lowercase_initial=int(r.get("lowercase_initial", 15)),
                    drop_final_punct=int(r.get("drop_final_punct", 25)),
                )

            candidate_mentions = None
            candidate_reply_to = None
            candidate_quoted_text = None

            if action_type == "@mention" and target_user:
                candidate_content = f"@{target_user} {candidate_content}"
                candidate_mentions = [target_user]
            elif action_type == "reply" and target_message_id:
                candidate_reply_to = target_message_id
                if target_message:
                    candidate_quoted_text = target_message.content

            target_agent_for_validation = None
            if target_user and target_user != self.state.user_name:
                target_agent_for_validation = target_user
            elif target_message and target_message.sender != self.state.user_name:
                target_agent_for_validation = target_message.sender

            if (
                target_agent_for_validation
                and self._agents_have_different_alignment_cells(agent_name, target_agent_for_validation)
                and self._looks_like_agent_validation(candidate_content)
            ):
                self.logger.log_error(
                    "performer_cross_cell_validation_retry",
                    f"Generated message for '{agent_name}' validated '{target_agent_for_validation}' across alignment cells; retrying",
                    context={"action_type": action_type},
                )
                performer_user_prompt = (
                    f"{base_performer_user_prompt}\n\n"
                    "Important correction:\n"
                    "Your last draft sounded validating toward an agent from a different alignment cell.\n"
                    "Rewrite it so you stay clearly inside your own cell. You may attack the same opponent or "
                    "respond to the same topic, but do not agree with, praise, echo, or pile on in support of the target."
                )
                content = None
                continue

            participant_target_for_validation = None
            if target_user == self.state.user_name:
                participant_target_for_validation = self.state.user_name
            elif target_message and target_message.sender == self.state.user_name:
                participant_target_for_validation = self.state.user_name



            if (
                participant_target_for_validation
                and self._expected_like_minded_for_agent(agent_name) is True
                and self._looks_like_attack_on_participant(candidate_content)
            ):
                self.logger.log_error(
                    "performer_like_minded_participant_attack_retry",
                    f"Generated message for '{agent_name}' attacked same-cell participant '{self.state.user_name}'; retrying",
                    context={"action_type": action_type},
                )
                performer_user_prompt = (
                    f"{base_performer_user_prompt}\n\n"
                    "Important correction:\n"
                    "Your last draft turned against the participant even though your exact alignment cell matches theirs.\n"
                    "Rewrite it so you support, defend, or sharpen the participant's case. Do not scold them, call them names, "
                    "or frame them as the problem."
                )
                content = None
                continue

            content = candidate_content
            mentions = candidate_mentions
            reply_to = candidate_reply_to
            quoted_text = candidate_quoted_text
            break

        # Classify the final approved message once, outside the retry loop.
        if content is not None:
            classification = await self._classify_message(agent_message=content, agent_name=agent_name)

        if content is None:
            self.logger.log_error(
                "performer_retries_exhausted",
                f"Failed to get valid performer content after {MAX_PERFORMER_RETRIES} attempts",
            )
            # Treat exhausted retries like a wait turn: restore evaluate
            # counter and clear last-agent so the failed turn is invisible
            # to subsequent Director calls.
            self._turns_since_evaluate = _saved_counter
            self._has_completed_first_interval = _saved_first_interval
            self._last_agent = _saved_last_agent
            self._last_action_type = _saved_last_action_type
            return TurnResult(
                action_type="wait",
                agent_name=agent_name,
                priority=priority,
                performer_rationale=performer_rationale,
                action_rationale=action_rationale,
            )


        message = Message.create(
            sender=agent_name,
            content=content,
            reply_to=reply_to,
            quoted_text=quoted_text,
            mentions=mentions,
            is_incivil=classification.get("is_incivil"),
            is_like_minded=classification.get("is_like_minded"),
            inferred_participant_stance=classification.get("inferred_participant_stance"),
            classification_rationale=classification.get("classification_rationale"),
        )
        stance_confidence = classification.get("stance_confidence")
        if stance_confidence:
            message.metadata["stance_confidence"] = stance_confidence

        self._action_counts[action_type] = self._action_counts.get(action_type, 0) + 1
        anon_name = self._name_map.get(agent_name, agent_name)
        self._performer_counts[anon_name] = self._performer_counts.get(anon_name, 0) + 1

        return TurnResult(
            action_type=action_type,
            agent_name=agent_name,
            message=message,
            target_message_id=target_message_id,
            target_user=target_user,
            priority=priority,
            performer_rationale=performer_rationale,
            action_rationale=action_rationale,
        )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Director Update (Call 1) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    async def _director_update(self, anon_recent: List[Message]) -> None:
        """Run Director Update call: update last agent's profile.

        Updates agent profile in place. On failure, carries forward unchanged.
        """
        last_agent_profile = self.agent_profiles.get(self._last_agent, "")

        # Find the most recent message by the last-acting agent.
        last_action = None
        for msg in reversed(anon_recent):
            if msg.sender == self._last_agent:
                last_action = msg
                break

        # Resolve the last agent's fixed traits (keyed by real name, looked up via reverse map)
        last_agent_real_name = self._reverse_map.get(self._last_agent, self._last_agent)
        last_agent_traits = self._agent_traits.get(last_agent_real_name) if self._agent_traits else None

        update_user = build_update_user_prompt(
            last_action=last_action,
            last_agent=self._last_agent or "",
            last_agent_profile=last_agent_profile,
            last_agent_traits=last_agent_traits,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
        )

        update_raw = None
        try:
            update_raw = await self.director_llm.generate_response(
                update_user, max_retries=1,
                system_prompt=self._update_system_prompt,
            )
        except Exception as e:
            self.logger.log_error("director_update_llm_call", str(e))
            return

        self.logger.log_llm_call(
            agent_name="__director_update__",
            prompt=f"[SYSTEM]\n{self._update_system_prompt}\n\n[USER]\n{update_user}",
            response=update_raw,
            error=None if update_raw else "Director Update LLM returned no response",
        )

        if not update_raw:
            return

        try:
            update_data = parse_update_response(update_raw)
        except ValueError as e:
            self.logger.log_error("director_update_parse", str(e))
            return

        # Update the last-acting agent's profile
        if self._last_agent and self._last_agent in self.agent_profiles:
            self.agent_profiles[self._last_agent] = update_data["performer_profile_update"]

    # Ã¢â€â‚¬Ã¢â€â‚¬ Director Evaluate (Call 2) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    async def _director_evaluate(self, internal_validity_criteria: str, anon_recent: List[Message]) -> None:
        """Run Director Evaluate call: revise validity evaluations.

        Updates validity evaluations in place. On failure, carries forward unchanged.
        """
        # Cache Evaluate system prompt (session-static once criteria are known)
        if self._evaluate_system_prompt is None:
            self._evaluate_system_prompt = build_evaluate_system_prompt(
                internal_validity_criteria=internal_validity_criteria,
                ecological_criteria=self.ecological_criteria,
                chatroom_context=_merge_prompt_context(
                    chatroom_context=self.chatroom_context,
                    incivility_framework=self.incivility_framework,
                ),
                participant_stance_hint=self._participant_hint_text,
                participant_alignment_cell=self._participant_alignment_cell_text,
                participant_name=self.state.user_name,
                template=self.director_evaluate_prompt_template,
            )

        evaluate_user = build_evaluate_user_prompt(
            messages=anon_recent,
            previous_internal=self._internal_validity_summary,
            previous_ecological=self._ecological_validity_summary,
            internal_validity_criteria=internal_validity_criteria,
            ecological_criteria=self.ecological_criteria,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            participant_stance_hint=self._participant_hint_text,
            participant_alignment_cell=self._participant_alignment_cell_text,
            treatment_fidelity_summary=self._format_treatment_fidelity_summary(),
            action_counts=self._action_counts,
            performer_counts=self._performer_counts,
            participation_summary=self._format_participation_memory(),
            exclude_performer=self._anon_user,
            template=self.director_evaluate_prompt_template,
        )

        evaluate_raw = None
        try:
            evaluate_raw = await self.director_llm.generate_response(
                evaluate_user, max_retries=1,
                system_prompt=self._evaluate_system_prompt,
            )
        except Exception as e:
            self.logger.log_error("director_evaluate_llm_call", str(e))
            return

        self.logger.log_llm_call(
            agent_name="__director_evaluate__",
            prompt=f"[SYSTEM]\n{self._evaluate_system_prompt}\n\n[USER]\n{evaluate_user}",
            response=evaluate_raw,
            error=None if evaluate_raw else "Director Evaluate LLM returned no response",
        )

        if not evaluate_raw:
            return

        try:
            evaluate_data = parse_evaluate_response(evaluate_raw)
        except ValueError as e:
            self.logger.log_error("director_evaluate_parse", str(e))
            return

        # Update validity evaluations
        self._internal_validity_summary = evaluate_data["internal_validity_evaluation"]
        self._ecological_validity_summary = evaluate_data["ecological_validity_evaluation"]

    # Ã¢â€â‚¬Ã¢â€â‚¬ Director Action (Call 3) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    async def _director_action(
        self,
        anon_recent: List[Message],
        real_recent: Optional[List[Message]] = None,
        override_profiles: Optional[Dict[str, str]] = None,
        override_perf_counts: Optional[Dict[str, int]] = None,
    ) -> Optional[dict]:
        """Run Director Action call: select performer, action type, O/M/D.

        The Director selects from all performers visible in profiles and
        chat log.  If it picks the human participant, the orchestrator
        will treat this as a 'wait' (handled by the caller).

        ``override_profiles`` / ``override_perf_counts`` allow the caller
        to restrict the agent pool (used in parallel pipeline mode).

        Returns parsed action response dict, or None on failure.
        """
        # Cache Action system prompt (session-static)
        if self._action_system_prompt is None:
            action_template = self.director_action_prompt_template
            if self._should_boost_replies_mentions() and not action_template:
                from agents.STAGE.director import _BOOSTED_ACTION_TEMPLATE
                action_template = _BOOSTED_ACTION_TEMPLATE
            self._action_system_prompt = build_action_system_prompt(
                chatroom_context=_merge_prompt_context(
                    chatroom_context=self.chatroom_context,
                    incivility_framework=self.incivility_framework,
                ),
                participant_stance_hint=self._participant_hint_text,
                participant_alignment_cell=self._participant_alignment_cell_text,
                participant_name=self.state.user_name,
                template=action_template,
            )

        profiles = override_profiles if override_profiles is not None else self.agent_profiles
        perf_counts = override_perf_counts if override_perf_counts is not None else self._performer_counts
        eligible_anon_names = set(profiles.keys())
        visible_target_labels = set(self.agent_profiles.keys())
        recent_messages = real_recent if real_recent is not None else self.state.get_recent_messages(len(anon_recent))
        sanitized_internal_summary = self._sanitize_summary_for_eligible_agents(
            self._internal_validity_summary or "No actions have occurred yet. No assessment available.",
            eligible_anon_names,
        )
        sanitized_ecological_summary = self._sanitize_summary_for_eligible_agents(
            self._ecological_validity_summary or "No actions have occurred yet. No assessment available.",
            eligible_anon_names,
        )
        anon_traits = None
        if self._agent_traits:
            anon_traits = {
                self._name_map.get(real_name, real_name): traits
                for real_name, traits in self._agent_traits.items()
                if self._name_map.get(real_name, real_name) in profiles
            }

        action_template = self.director_action_prompt_template
        if self._should_boost_replies_mentions() and not action_template:
            from agents.STAGE.director import _BOOSTED_ACTION_TEMPLATE
            action_template = _BOOSTED_ACTION_TEMPLATE

        action_user = build_action_user_prompt(
            messages=anon_recent,
            agent_profiles=profiles,
            internal_validity_summary=sanitized_internal_summary,
            ecological_validity_summary=sanitized_ecological_summary,
            chatroom_context=_merge_prompt_context(
                chatroom_context=self.chatroom_context,
                incivility_framework=self.incivility_framework,
            ),
            participant_stance_hint=self._participant_hint_text,
            participant_alignment_cell=self._participant_alignment_cell_text,
            treatment_fidelity_summary=self._format_treatment_fidelity_summary(),
            performer_counts=perf_counts,
            participation_summary=self._format_participation_memory(
                eligible_anon_names=eligible_anon_names,
            ),
            target_constraints_by_speaker=self._format_target_constraints_by_speaker(
                eligible_anon_names=eligible_anon_names,
                recent_messages=recent_messages,
            ),
            action_counts=self._action_counts,
            exclude_performer=self._anon_user,
            agent_traits=anon_traits,
            template=action_template,
        )

        valid_direct_targets_by_speaker: Dict[str, Set[str]] = {}
        all_agent_target_labels = {
            anon_name
            for anon_name in self._performer_counts.keys()
            if anon_name != self._anon_user
        }
        for speaker_anon in eligible_anon_names:
            if speaker_anon == self._anon_user:
                continue
            speaker_real = self._deanon_name(speaker_anon)
            valid_targets = {
                target_anon
                for target_anon in all_agent_target_labels
                if target_anon != speaker_anon
                and not self._agents_share_alignment_cell(speaker_real, self._deanon_name(target_anon))
            }
            valid_direct_targets_by_speaker[speaker_anon] = valid_targets

        # Retry loop: Director Action is the most critical call in the pipeline.
        # On empty response or unparseable JSON, retry with short exponential backoff
        # before giving up â€” this handles cold-start timeouts and transient API errors
        # that are especially common at session start.
        MAX_ACTION_ATTEMPTS = 3
        BACKOFF_SECONDS = [0, 2, 5]  # delay before attempt 1, 2, 3

        for attempt in range(MAX_ACTION_ATTEMPTS):
            if BACKOFF_SECONDS[attempt] > 0:
                await asyncio.sleep(BACKOFF_SECONDS[attempt])

            action_raw = None
            try:
                action_raw = await self.director_llm.generate_response(
                    action_user, max_retries=1,
                    system_prompt=self._action_system_prompt,
                )
            except Exception as e:
                self.logger.log_error(
                    "director_action_llm_call",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: {e}",
                )
                continue

            self.logger.log_llm_call(
                agent_name="__director_action__",
                prompt=f"[SYSTEM]\n{self._action_system_prompt}\n\n[USER]\n{action_user}",
                response=action_raw,
                error=None if action_raw else f"Director Action LLM returned no response (attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS})",
            )

            if not action_raw:
                continue

            try:
                action_data = parse_action_response(action_raw)
            except ValueError as e:
                self.logger.log_error(
                    "director_action_parse",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: {e}",
                )
                continue

            selected_performer = action_data.get("next_performer")
            if selected_performer not in profiles:
                self.logger.log_error(
                    "director_action_unknown_performer_label",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: Director returned next_performer '{selected_performer}', "
                    "which is not one of the visible performer labels in AGENT_PROFILES",
                )
                continue

            selected_target_user = action_data.get("target_user")
            if selected_target_user and selected_target_user not in visible_target_labels:
                self.logger.log_error(
                    "director_action_unknown_target_label",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: Director returned target_user '{selected_target_user}', "
                    "which is not one of the visible session-member labels for this turn",
                )
                continue

            if (
                selected_target_user
                and selected_performer != self._anon_user
                and selected_target_user != self._anon_user
                and selected_target_user not in valid_direct_targets_by_speaker.get(selected_performer, set())
            ):
                self.logger.log_error(
                    "director_action_invalid_target_for_speaker",
                    f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: Director returned target_user '{selected_target_user}' "
                    f"for '{selected_performer}', but that target is not valid for the chosen speaker",
                )
                if attempt < MAX_ACTION_ATTEMPTS - 1:
                    continue

            if action_data.get("action_type") == "reply" and action_data.get("target_message_id"):
                speaker_real = self._deanon_name(selected_performer)
                reply_target = next(
                    (message for message in self.state.messages if message.message_id == action_data["target_message_id"]),
                    None,
                )
                if reply_target is not None and not self._can_directly_target_message(speaker_real, reply_target):
                    self.logger.log_error(
                        "director_action_invalid_reply_target",
                        f"attempt {attempt + 1}/{MAX_ACTION_ATTEMPTS}: Director returned reply target "
                        f"'{action_data['target_message_id']}' for '{selected_performer}', but that message is not "
                        "a valid reply target for the chosen speaker",
                    )
                    if attempt < MAX_ACTION_ATTEMPTS - 1:
                        continue

            return action_data

        self.logger.log_error(
            "director_action_failed",
            f"Director Action gave no valid response after {MAX_ACTION_ATTEMPTS} attempts â€” skipping turn",
        )
        return None
