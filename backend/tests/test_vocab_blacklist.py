"""Tests for the session-wide vocabulary blacklist detector."""

from utils.vocab_blacklist import find_terms, format_blacklist_block, used_terms, violations


def test_matches_ignore_accents_case_and_inflection():
    assert find_terms("Típico de ZURDOS buenistas") == ["buenismo / buenista", "zurdo"]
    assert find_terms("eso es de cuñaos") == ["cuñao / cuñado"]


def test_contempt_openers_do_not_match_ordinary_usage():
    assert find_terms("Menuda risa") == ["menudo/menuda ..."]
    assert find_terms("Vaya ingenuidad") == ["ingenuidad", "vaya ..."]
    assert find_terms("eso pasa a menudo") == []
    assert find_terms("que se vaya a votar") == []


def test_used_terms_accumulates_across_messages():
    assert used_terms(["Menudo buenismo", None, "fachas"]) == [
        "buenismo / buenista", "facha", "menudo/menuda ...",
    ]


def test_violations_exempt_terms_from_the_answered_message():
    banned = ["buenismo / buenista", "zurdo"]
    assert violations("puro buenismo de zurdo", banned) == ["buenismo / buenista", "zurdo"]
    assert violations("puro buenismo de zurdo", banned, responding_to="Menudo buenismo") == ["zurdo"]
    assert violations("sin etiquetas", banned) == []


def test_block_is_empty_without_banned_terms():
    assert format_blacklist_block([]) == ""
    assert '"facha"' in format_blacklist_block(["facha"])
