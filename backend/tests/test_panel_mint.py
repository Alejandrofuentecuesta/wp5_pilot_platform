"""Tests for panel (NetQuest) token minting on first arrival.

Covers `_try_panel_mint`, which admits an unknown token into the active
experiment when the link is well-formed. The cases below pin the order of
its checks: link integrity is judged before experiment availability, so a
malformed link is always reported as an invalid token rather than as a
closed study.
"""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import main


EXPERIMENT = "panel_experiment"
TOKEN = "9c3bfa22-1111-2222-3333-e4bc26c72c42_26cb4bbca562a83c"
GROUP = "incivil_like_minded"
G_PARAM = "7"  # PANEL_GROUP_MAP: 7 -> incivil_like_minded


def _hkey(token: str = TOKEN) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _config() -> dict:
    return {"experimental": {"panel_entry": True, "groups": {GROUP: {}}}}


class TestPanelMintAvailability:
    @pytest.mark.asyncio
    async def test_open_experiment_mints_token(self):
        with patch.object(main, "_experiment_id", EXPERIMENT), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value=_config())), \
             patch.object(main.config_repo, "check_experiment_availability",
                          AsyncMock(return_value=None)), \
             patch.object(main.token_manager, "seed_tokens", AsyncMock()) as seed, \
             patch.object(main.token_repo, "get_token_status",
                          AsyncMock(return_value={"token": TOKEN,
                                                  "experiment_id": EXPERIMENT,
                                                  "treatment_group": GROUP,
                                                  "used": False})):
            row = await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM)

            seed.assert_awaited_once_with(None, EXPERIMENT, {GROUP: [TOKEN]})
            assert row["token"] == TOKEN
            assert row["treatment_group"] == GROUP

    @pytest.mark.asyncio
    async def test_closed_experiment_raises_403_without_minting(self):
        """The regression this guards: a closed study used to mint a token
        row and only then reject the arrival, leaving orphans behind."""
        message = "This study has ended and is no longer accepting participants."
        with patch.object(main, "_experiment_id", EXPERIMENT), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value=_config())), \
             patch.object(main.config_repo, "check_experiment_availability",
                          AsyncMock(return_value=message)), \
             patch.object(main.token_manager, "seed_tokens", AsyncMock()) as seed:
            with pytest.raises(HTTPException) as exc:
                await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM)

            assert exc.value.status_code == 403
            assert exc.value.detail == message
            seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_hkey_returns_none_before_availability_is_consulted(self):
        """A malformed link must read as an invalid token (401 upstream),
        never as a closed study, whatever the experiment's state."""
        with patch.object(main, "_experiment_id", EXPERIMENT), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value=_config())), \
             patch.object(main.config_repo, "check_experiment_availability",
                          AsyncMock(return_value="This study has ended.")) as avail, \
             patch.object(main.token_manager, "seed_tokens", AsyncMock()) as seed:
            row = await main._try_panel_mint(None, TOKEN, "not-a-real-hash", G_PARAM)

            assert row is None
            seed.assert_not_awaited()
            avail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_group_returns_none_before_availability_is_consulted(self):
        with patch.object(main, "_experiment_id", EXPERIMENT), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value=_config())), \
             patch.object(main.config_repo, "check_experiment_availability",
                          AsyncMock(return_value="This study has ended.")) as avail, \
             patch.object(main.token_manager, "seed_tokens", AsyncMock()) as seed:
            row = await main._try_panel_mint(None, TOKEN, _hkey(), "99")

            assert row is None
            seed.assert_not_awaited()
            avail.assert_not_awaited()
