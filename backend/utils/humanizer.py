"""Post-processing humanizer for agent-generated chatroom messages.

Applies informal Spanish chatroom conventions to make LLM output look more
like a real user typed it: removes hashtags, drops inverted punctuation,
contracts common words, and introduces light orthographic errors.
"""
import random
import re
from typing import Optional


# ── Substitution tables ──────────────────────────────────────────────────────

# Word-level contractions/abbreviations (applied probabilistically)
_WORD_SUBS = [
    (r"\bque\b",      "q",    0.55),
    (r"\bpero\b",     "pero", 0.0),   # keep — too recognisable if changed
    (r"\btambién\b",  "tb",   0.40),
    (r"\bpara\b",     "para", 0.0),   # "pa" reads too dialectal/caricatured here
    (r"\bporque\b",   "xq",   0.45),
    (r"\bpor\b",      "x",    0.25),
    (r"\bcon\b",      "con",  0.0),
    (r"\bestoy\b",    "toy",  0.30),
    (r"\bno sé\b",    "ni idea", 0.25),
    (r"\bla verdad\b","la vd", 0.20),
]

# Accent removal (Spanish informal writing often drops accents)
_ACCENT_MAP = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _strip_hashtags(text: str) -> str:
    """Remove #hashtag tokens entirely."""
    return re.sub(r"\s*#\w+", "", text).strip()


def _strip_inverted_punctuation(text: str) -> str:
    """Remove opening ¿ and ¡ — informal Spanish writers skip them."""
    return text.replace("¿", "").replace("¡", "")


def _drop_spaces_after_comma(text: str, rng: random.Random, prob: float = 0.50) -> str:
    """Randomly remove the space after commas (informal typing)."""
    def _replace(m):
        return ",\u200b" if rng.random() < prob else m.group(0)
    result = re.sub(r",\s+", _replace, text)
    return result.replace(",\u200b", ",")


def _apply_word_subs(text: str, rng: random.Random, scale: float = 1.0) -> str:
    """Apply informal word contractions probabilistically.

    `scale` (0–1) multiplies every substitution probability; 0 disables all subs.
    """
    for pattern, replacement, prob in _WORD_SUBS:
        effective_prob = prob * scale
        if effective_prob <= 0.0:
            continue
        def _sub(m, rep=replacement, p=effective_prob):
            return rep if rng.random() < p else m.group(0)
        text = re.sub(pattern, _sub, text, flags=re.IGNORECASE)
    return text


def _drop_accents(text: str, rng: random.Random, prob: float = 0.40) -> str:
    """Randomly strip accents from the whole message."""
    if rng.random() < prob:
        return text.translate(_ACCENT_MAP)
    return text


def _strip_excess_emoji(text: str, rng: random.Random, max_emoji: int = 1) -> str:
    """Keep at most `max_emoji` individual emoji; remove the rest.

    Each emoji codepoint is matched separately (no + quantifier) so clusters
    like 😂😂😂 are counted and trimmed correctly.
    """
    # Match one emoji codepoint at a time (no trailing +)
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff"
        "\U00002702-\U000027B0"
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "]",
        flags=re.UNICODE,
    )
    emojis = emoji_pattern.findall(text)
    if len(emojis) <= max_emoji:
        return text
    kept = 0
    def _replacer(m):
        nonlocal kept
        if kept < max_emoji:
            kept += 1
            return m.group(0)
        return ""
    return emoji_pattern.sub(_replacer, text).strip()


def _lowercase_initial(text: str, rng: random.Random, prob: float = 0.15) -> str:
    """Sometimes lowercase a safe sentence-initial word."""
    if rng.random() >= prob:
        return text

    match = re.match(r"^([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü]*)", text)
    if not match:
        return text

    word = match.group(1)
    if len(word) <= 1 or word.isupper():
        return text

    protected = {
        "AEMET", "IPCC", "CSIC", "CIS", "PSOE", "PP", "Vox", "VOX",
        "España", "Moncloa", "Sánchez", "Ayuso", "Illa", "Madrid",
        "Barcelona",
    }
    if word in protected:
        return text

    safe_openers = {
        "Que", "Qué", "Vaya", "Menuda", "Menudo", "Pero", "No", "Si", "Sí",
        "Claro", "Pues", "Esto", "Esa", "Ese", "Esos", "Esas", "Otra",
        "Otro", "Madre", "Mira", "Vamos", "Tampoco", "Encima",
    }
    if word not in safe_openers:
        return text

    return word[:1].lower() + text[1:]


def _drop_final_punctuation(text: str, rng: random.Random, prob: float = 0.25) -> str:
    """Sometimes remove final sentence punctuation from short chat-like posts."""
    if rng.random() >= prob:
        return text
    if len(text) > 240:
        return text
    return re.sub(r"([.!?])+$", "", text).rstrip()


def humanize(
    text: str,
    seed: Optional[int] = None,
    strip_hashtags: int = 100,
    strip_inverted_punct: int = 100,
    word_subs: int = 80,
    drop_accents: int = 40,
    comma_spacing: int = 50,
    max_emoji: int = 1,
    lowercase_initial: int = 15,
    drop_final_punct: int = 25,
) -> str:
    """Apply informal chatroom humanization to a Spanish message.

    Each rule parameter is a probability percentage (0–100):
      - strip_hashtags: chance to remove all #hashtag tokens
      - strip_inverted_punct: chance to remove ¿ and ¡
      - word_subs: scales the base contraction probabilities (100 = full, 0 = off)
      - drop_accents: chance to remove accents from the whole message
      - comma_spacing: per-comma chance to drop the space after it
      - max_emoji: hard cap on number of emoji kept (not a probability)
      - lowercase_initial: chance to lowercase safe generic opening words
      - drop_final_punct: chance to remove final .!? from short messages

    All transformations are probabilistic (seeded for reproducibility if
    `seed` is provided) so each call produces slightly different output.
    """
    if not text or not text.strip():
        return text

    rng = random.Random(seed)

    if strip_hashtags > 0 and rng.random() < strip_hashtags / 100:
        text = _strip_hashtags(text)
    if strip_inverted_punct > 0 and rng.random() < strip_inverted_punct / 100:
        text = _strip_inverted_punctuation(text)
    if word_subs > 0:
        text = _apply_word_subs(text, rng, scale=word_subs / 100)
    if drop_accents > 0:
        text = _drop_accents(text, rng, prob=drop_accents / 100)
    if comma_spacing > 0:
        text = _drop_spaces_after_comma(text, rng, prob=comma_spacing / 100)
    if max_emoji >= 0:
        text = _strip_excess_emoji(text, rng, max_emoji=max_emoji)
    if lowercase_initial > 0:
        text = _lowercase_initial(text, rng, prob=lowercase_initial / 100)
    if drop_final_punct > 0:
        text = _drop_final_punctuation(text, rng, prob=drop_final_punct / 100)

    return text.strip()
