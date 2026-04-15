"""Tests for db/repositories/config_repo.py — validation and DB operations."""
from __future__ import annotations

import copy
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")
from db.repositories import config_repo


# ── helpers ──────────────────────────────────────────────────────────────────

def _minimal_sim() -> dict:
    return {
        "random_seed": 42,
        "session_duration_minutes": 15,
        "num_agents": 2,
        "agent_names": ["Alice", "Bob"],
        "messages_per_minute": 5,
        "director_llm_provider": "anthropic",
        "director_llm_model": "claude-3",
        "performer_llm_provider": "gemini",
        "performer_llm_model": "gemini-pro",
        "moderator_llm_provider": "anthropic",
        "moderator_llm_model": "claude-3-haiku",
        "evaluate_interval": 10,
    }


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


FULL_CONFIG = {
    "simulation": _minimal_sim(),
    "experimental": _minimal_exp(),
}


# ── validate_simulation_config ───────────────────────────────────────────────

class TestValidateSimulationConfig:
    def test_minimal_valid(self):
        result = config_repo.validate_simulation_config(_minimal_sim())
        assert result["random_seed"] == 42
        assert result["num_agents"] == 2

    def test_optional_defaults(self):
        result = config_repo.validate_simulation_config(_minimal_sim())
        assert "max_concurrent_agents" not in result
        assert result["director_temperature"] == 1.0
        assert result["performer_temperature"] == 1.0
        assert result["moderator_temperature"] == 1.0
        assert result["director_top_p"] == 1.0
        assert result["director_max_tokens"] == 1024
        assert result["performer_max_tokens"] == 384
        assert result["moderator_max_tokens"] == 512

    def test_explicit_values_preserved(self):
        cfg = _minimal_sim()
        cfg["director_temperature"] = 0.5
        cfg["performer_top_p"] = 0.9
        cfg["director_max_tokens"] = 2048
        result = config_repo.validate_simulation_config(cfg)
        assert result["director_temperature"] == 0.5
        assert result["performer_top_p"] == 0.9
        assert result["director_max_tokens"] == 2048

    @pytest.mark.parametrize("missing_key", [
        "random_seed", "session_duration_minutes", "num_agents", "agent_names",
        "messages_per_minute", "director_llm_provider", "director_llm_model",
        "performer_llm_provider", "performer_llm_model",
        "moderator_llm_provider", "moderator_llm_model",
        "evaluate_interval",
    ])
    def test_missing_required_key(self, missing_key):
        cfg = _minimal_sim()
        del cfg[missing_key]
        with pytest.raises(ValueError, match=missing_key):
            config_repo.validate_simulation_config(cfg)

    def test_negative_session_duration(self):
        cfg = _minimal_sim()
        cfg["session_duration_minutes"] = -1
        with pytest.raises(ValueError, match="session_duration_minutes"):
            config_repo.validate_simulation_config(cfg)

    def test_zero_session_duration(self):
        cfg = _minimal_sim()
        cfg["session_duration_minutes"] = 0
        with pytest.raises(ValueError, match="session_duration_minutes"):
            config_repo.validate_simulation_config(cfg)

    def test_negative_num_agents(self):
        cfg = _minimal_sim()
        cfg["num_agents"] = -1
        with pytest.raises(ValueError, match="num_agents"):
            config_repo.validate_simulation_config(cfg)

    def test_agent_names_length_mismatch(self):
        cfg = _minimal_sim()
        cfg["agent_names"] = ["Alice"]
        with pytest.raises(ValueError, match="agent_names"):
            config_repo.validate_simulation_config(cfg)

    def test_agent_names_not_list(self):
        cfg = _minimal_sim()
        cfg["agent_names"] = "Alice"
        with pytest.raises(ValueError, match="agent_names"):
            config_repo.validate_simulation_config(cfg)

    def test_temperature_out_of_range(self):
        cfg = _minimal_sim()
        cfg["director_temperature"] = 2.5
        with pytest.raises(ValueError, match="director_temperature"):
            config_repo.validate_simulation_config(cfg)

    def test_temperature_negative(self):
        cfg = _minimal_sim()
        cfg["performer_temperature"] = -0.1
        with pytest.raises(ValueError, match="performer_temperature"):
            config_repo.validate_simulation_config(cfg)

    def test_top_p_out_of_range(self):
        cfg = _minimal_sim()
        cfg["director_top_p"] = 1.5
        with pytest.raises(ValueError, match="director_top_p"):
            config_repo.validate_simulation_config(cfg)

    def test_empty_llm_provider(self):
        cfg = _minimal_sim()
        cfg["director_llm_provider"] = ""
        with pytest.raises(ValueError, match="director_llm_provider"):
            config_repo.validate_simulation_config(cfg)

    def test_zero_max_tokens(self):
        cfg = _minimal_sim()
        cfg["director_max_tokens"] = 0
        with pytest.raises(ValueError, match="director_max_tokens"):
            config_repo.validate_simulation_config(cfg)

    def test_zero_context_window(self):
        cfg = _minimal_sim()
        cfg["evaluate_interval"] = 0
        with pytest.raises(ValueError, match="evaluate_interval"):
            config_repo.validate_simulation_config(cfg)

    def test_max_concurrent_agents_stripped(self):
        """Legacy max_concurrent_agents should be silently removed."""
        cfg = _minimal_sim()
        cfg["max_concurrent_agents"] = 5
        result = config_repo.validate_simulation_config(cfg)
        assert "max_concurrent_agents" not in result

    # boundary values
    def test_temperature_at_zero(self):
        cfg = _minimal_sim()
        cfg["director_temperature"] = 0.0
        result = config_repo.validate_simulation_config(cfg)
        assert result["director_temperature"] == 0.0

    def test_temperature_at_two(self):
        cfg = _minimal_sim()
        cfg["director_temperature"] = 2.0
        result = config_repo.validate_simulation_config(cfg)
        assert result["director_temperature"] == 2.0

    def test_top_p_at_zero(self):
        cfg = _minimal_sim()
        cfg["director_top_p"] = 0.0
        result = config_repo.validate_simulation_config(cfg)
        assert result["director_top_p"] == 0.0

    def test_zero_agents_with_empty_names(self):
        cfg = _minimal_sim()
        cfg["num_agents"] = 0
        cfg["agent_names"] = []
        result = config_repo.validate_simulation_config(cfg)
        assert result["num_agents"] == 0

    def test_bsc_model_version_defaults_to_v2(self):
        result = config_repo.validate_simulation_config(_minimal_sim())
        assert result["bsc_model_version"] == "v2"

    def test_invalid_bsc_model_version(self):
        cfg = _minimal_sim()
        cfg["bsc_model_version"] = "v3"
        with pytest.raises(ValueError, match="bsc_model_version"):
            config_repo.validate_simulation_config(cfg)


# ── validate_experimental_config ─────────────────────────────────────────────

class TestValidateExperimentalConfig:
    def test_valid(self):
        result = config_repo.validate_experimental_config(
            _minimal_exp(), available_features=[]
        )
        assert "groups" in result
        assert result["incivility_framework"] == ""

    def test_missing_incivility_framework_defaults_to_empty(self):
        cfg = _minimal_exp()
        del cfg["incivility_framework"]
        result = config_repo.validate_experimental_config(cfg, available_features=[])
        assert result["incivility_framework"] == ""

    def test_no_groups(self):
        with pytest.raises(ValueError, match="treatment group"):
            config_repo.validate_experimental_config(
                {"chatroom_context": "x", "ecological_validity_criteria": "realistic", "groups": {}},
                available_features=[],
            )

    def test_missing_ecological_validity(self):
        cfg = {"chatroom_context": "x", "groups": {"g1": {"internal_validity_criteria": "t", "features": []}}}
        with pytest.raises(ValueError, match="ecological_validity_criteria"):
            config_repo.validate_experimental_config(cfg, available_features=[])

    def test_missing_internal_validity_criteria(self):
        cfg = {"groups": {"g1": {"internal_validity_criteria": "", "features": []}}}
        with pytest.raises(ValueError, match="missing an internal_validity_criteria"):
            config_repo.validate_experimental_config(cfg, available_features=[])

    def test_unknown_feature(self):
        cfg = {"groups": {"g1": {"internal_validity_criteria": "be nice", "features": ["nonexistent"]}}}
        with pytest.raises(ValueError, match="unknown feature"):
            config_repo.validate_experimental_config(
                cfg, available_features=["news_article"]
            )

    def test_valid_feature(self):
        cfg = {"groups": {"g1": {"internal_validity_criteria": "be nice", "features": ["news_article"]}}}
        result = config_repo.validate_experimental_config(
            cfg, available_features=["news_article", "gate_until_user_post"]
        )
        assert result["groups"]["g1"]["features"] == ["news_article"]


# ── validate_token_groups ────────────────────────────────────────────────────

class TestValidateTokenGroups:
    def test_valid(self):
        config_repo.validate_token_groups(
            {"civil_support": ["t1"], "civil_oppose": ["t2"]},
            {"civil_support": {}, "civil_oppose": {}},
        )

    def test_no_tokens(self):
        with pytest.raises(ValueError, match="No tokens"):
            config_repo.validate_token_groups({}, {"g1": {}})

    def test_token_group_references_undefined(self):
        with pytest.raises(ValueError, match="undefined treatment groups"):
            config_repo.validate_token_groups(
                {"unknown_group": ["t1"]},
                {"civil_support": {}},
            )

    def test_treatment_group_missing_tokens(self):
        with pytest.raises(ValueError, match="missing tokens"):
            config_repo.validate_token_groups(
                {"civil_support": ["t1"]},
                {"civil_support": {}, "civil_oppose": {}},
            )


# ── DB operations (require PostgreSQL) ───────────────────────────────────────

@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean(db_pool, clean_tables):
    """Clean DB before each test."""
    yield


async def test_save_and_get_config(db_pool):
    config = copy.deepcopy(FULL_CONFIG)
    await config_repo.save_experiment_config(db_pool, "exp_save_test", config, description="test desc")

    result = await config_repo.get_experiment_config(db_pool, "exp_save_test")
    assert result is not None
    assert result["simulation"]["random_seed"] == 42
    assert result["experimental"]["groups"]["civil_support"]["internal_validity_criteria"] == "Be civil and supportive"


async def test_save_duplicate_raises(db_pool):
    config = copy.deepcopy(FULL_CONFIG)
    await config_repo.save_experiment_config(db_pool, "exp_dup_test", config)
    with pytest.raises(ValueError, match="already exists"):
        await config_repo.save_experiment_config(db_pool, "exp_dup_test", config)


async def test_get_nonexistent_returns_none(db_pool):
    result = await config_repo.get_experiment_config(db_pool, "nonexistent")
    assert result is None


async def test_get_experiment_full_row(db_pool):
    config = copy.deepcopy(FULL_CONFIG)
    await config_repo.save_experiment_config(db_pool, "exp_row_test", config, description="my desc")

    row = await config_repo.get_experiment(db_pool, "exp_row_test")
    assert row is not None
    assert row["experiment_id"] == "exp_row_test"
    assert row["description"] == "my desc"
    assert row["config"]["simulation"]["num_agents"] == 2
    assert row["created_at"] is not None
