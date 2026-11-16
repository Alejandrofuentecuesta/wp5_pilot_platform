"""Validation of the NetQuest topic code in experimental configs.

Kept apart from test_config_repo.py, whose module-level fixture needs a live
PostgreSQL and skips every test there without one; these need no database.
"""
from __future__ import annotations

import pytest

from db.repositories import config_repo


def _minimal_exp() -> dict:
    return {
        "chatroom_context": "Discuss topic X",
        "incivility_framework": "",
        "ecological_validity_criteria": "Informal Reddit-like chatroom with short messages.",
        "groups": {
            "civil_support": {
                "internal_validity_criteria": "Be civil and supportive",
                "features": [],
            },
        },
    }


class TestNetquestTopicCode:
    @pytest.mark.parametrize("code", ["1", "2", " 2 ", 1])
    def test_netquest_topic_code_accepted_and_normalised(self, code):
        cfg = _minimal_exp()
        cfg["netquest_topic_code"] = code
        result = config_repo.validate_experimental_config(cfg, available_features=[])
        assert result["netquest_topic_code"] == str(code).strip()

    @pytest.mark.parametrize("code", [None, "", "  "])
    def test_netquest_topic_code_empty_means_none(self, code):
        cfg = _minimal_exp()
        cfg["netquest_topic_code"] = code
        result = config_repo.validate_experimental_config(cfg, available_features=[])
        assert result["netquest_topic_code"] is None

    def test_netquest_topic_code_absent_means_none(self):
        result = config_repo.validate_experimental_config(_minimal_exp(), available_features=[])
        assert result["netquest_topic_code"] is None

    @pytest.mark.parametrize("code", ["0", "3", "immigration", "12"])
    def test_netquest_topic_code_rejects_unknown_values(self, code):
        cfg = _minimal_exp()
        cfg["netquest_topic_code"] = code
        with pytest.raises(ValueError, match="netquest_topic_code"):
            config_repo.validate_experimental_config(cfg, available_features=[])
