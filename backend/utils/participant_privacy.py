"""Detect direct personal contact details without retaining matched values."""

import re
import unicodedata
from typing import Optional


_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_CONTACT_CUE = re.compile(r"\b(?:telefono|movil|whatsapp|llamame|contactame|mi numero)\b")
_PHONE = re.compile(r"(?<!\d)(?:\+34[ .-]*)?[6789](?:[ .-]*\d){8}(?!\d)")
_ID_CUE = re.compile(r"\b(?:dni|nie|nif|documento de identidad)\b")
_ID_NUMBER = re.compile(r"\b(?:\d{8}|[XYZ]\d{7})[ -]?[A-Z]\b", re.IGNORECASE)
_IBAN = re.compile(r"\bES\d{2}(?:[ -]?\d{4}){5}\b", re.IGNORECASE)


def personal_information_category(content: str) -> Optional[str]:
    """Conservative format checks, not a guarantee against all possible PII.

    A phone/identity cue is required to avoid interpreting ordinary political
    statistics as personal data. Names and postal addresses need no invented
    heuristic here: political discussion routinely names public figures/places.
    """
    normalized = unicodedata.normalize("NFKC", content or "")
    email_text = re.sub(r"\s*(?:\[at\]|\(at\)|\[arroba\]|\(arroba\))\s*", "@", normalized, flags=re.I)
    email_text = re.sub(r"\s*(?:\[dot\]|\(dot\)|\[punto\]|\(punto\))\s*", ".", email_text, flags=re.I)
    if _EMAIL.search(email_text):
        return "email"
    folded = "".join(c for c in unicodedata.normalize("NFD", normalized.lower())
                     if not unicodedata.combining(c))
    for match in _PHONE.finditer(folded):
        if _CONTACT_CUE.search(folded[max(0, match.start() - 60):match.end() + 30]):
            return "phone"
    for match in _ID_NUMBER.finditer(normalized):
        if _ID_CUE.search(folded[max(0, match.start() - 60):match.end() + 30]):
            return "identity_document"
    if _IBAN.search(normalized):
        return "bank_account"
    return None
