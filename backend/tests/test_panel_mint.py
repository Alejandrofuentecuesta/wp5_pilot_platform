"""Tests for panel (NetQuest) token minting on first arrival.

Covers `_try_panel_mint`, which admits an unknown token into the experiment
selected by the link's topic code ``e`` when the link is well-formed. The
cases below pin the order of its checks: link integrity is judged before
experiment availability, so a malformed link is always reported as an
invalid token rather than as a closed study.
"""
from __future__ import annotations

import contextlib
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import main


EXPERIMENT = "panel_experiment"
TOKEN = "9c3bfa22-1111-2222-3333-e4bc26c72c42_26cb4bbca562a83c"
GROUP = "incivil_like_minded"
G_PARAM = "7"  # PANEL_GROUP_MAP: 7 -> incivil_like_minded
E_PARAM = "1"  # immigration


def _hkey(token: str = TOKEN) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _config() -> dict:
    return {"experimental": {"netquest_topic_code": E_PARAM, "groups": {GROUP: {}}}}


@contextlib.contextmanager
def _patched(*, config=None, found=EXPERIMENT, availability=None, count=0):
    """Patch everything _try_panel_mint touches; yield the mocks."""
    mocks = SimpleNamespace(
        find=AsyncMock(return_value=found),
        avail=AsyncMock(return_value=availability),
        seed=AsyncMock(),
    )
    with patch.object(main.config_repo, "find_experiment_by_topic_code", mocks.find), \
         patch.object(main.config_repo, "get_experiment_config",
                      AsyncMock(return_value=config or _config())), \
         patch.object(main.config_repo, "check_experiment_availability", mocks.avail), \
         patch.object(main.token_repo, "count_tokens", AsyncMock(return_value=count)), \
         patch.object(main.token_repo, "get_token_status",
                      AsyncMock(return_value={"token": TOKEN,
                                              "experiment_id": EXPERIMENT,
                                              "treatment_group": GROUP,
                                              "used": False})), \
         patch.object(main.token_manager, "seed_tokens", mocks.seed):
        yield mocks


class TestTopicCodeRouting:
    @pytest.mark.asyncio
    async def test_e_selects_the_experiment_and_mints_into_it(self):
        with _patched() as m:
            row = await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

            m.find.assert_awaited_once_with(None, E_PARAM)
            m.seed.assert_awaited_once_with(None, EXPERIMENT, {GROUP: [TOKEN]})
            assert row["token"] == TOKEN
            assert row["treatment_group"] == GROUP

    @pytest.mark.asyncio
    async def test_e_is_stripped_before_lookup(self):
        with _patched() as m:
            await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, " 2 ")

            m.find.assert_awaited_once_with(None, "2")
            m.seed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_e_returns_none_without_lookup(self):
        with _patched() as m:
            assert await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, None) is None
            assert await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, "") is None

            m.find.assert_not_awaited()
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_e", ["0", "3", "12", "immigration", "x"])
    async def test_unknown_e_returns_none_without_lookup(self, bad_e):
        with _patched() as m:
            assert await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, bad_e) is None

            m.find.assert_not_awaited()
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_experiment_with_that_code_returns_none(self):
        """No experiment carries the code: an invalid link (401 upstream),
        not a closed study, and availability is never consulted."""
        with _patched(found=None) as m:
            assert await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM) is None

            m.avail.assert_not_awaited()
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_hkey_or_g_returns_none_without_lookup(self):
        with _patched() as m:
            assert await main._try_panel_mint(None, TOKEN, None, G_PARAM, E_PARAM) is None
            assert await main._try_panel_mint(None, TOKEN, _hkey(), None, E_PARAM) is None

            m.find.assert_not_awaited()
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_g_must_be_a_group_of_the_selected_experiment(self):
        """g=7 is a valid condition, but the selected experiment lacks that
        group (e.g. a test experiment with two groups): refused as invalid."""
        config = {"experimental": {"netquest_topic_code": E_PARAM,
                                   "groups": {"not_incivil_mix": {}}}}
        with _patched(config=config) as m:
            assert await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM) is None

            m.seed.assert_not_awaited()


class TestPanelMintAvailability:
    @pytest.mark.asyncio
    async def test_closed_experiment_raises_403_without_minting(self):
        """The regression this guards: a closed study used to mint a token
        row and only then reject the arrival, leaving orphans behind."""
        message = "This study has ended and is no longer accepting participants."
        with _patched(availability=message) as m:
            with pytest.raises(HTTPException) as exc:
                await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

            assert exc.value.status_code == 403
            assert exc.value.detail == message
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_hkey_returns_none_before_availability_is_consulted(self):
        """A malformed link must read as an invalid token (401 upstream),
        never as a closed study, whatever the experiment's state."""
        with _patched(availability="This study has ended.") as m:
            row = await main._try_panel_mint(None, TOKEN, "not-a-real-hash", G_PARAM, E_PARAM)

            assert row is None
            m.seed.assert_not_awaited()
            m.avail.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_group_returns_none_before_availability_is_consulted(self):
        with _patched(availability="This study has ended.") as m:
            row = await main._try_panel_mint(None, TOKEN, _hkey(), "99", E_PARAM)

            assert row is None
            m.seed.assert_not_awaited()
            m.avail.assert_not_awaited()


class TestPanelMintCeiling:
    @pytest.mark.asyncio
    async def test_limit_reached_refuses_with_study_closed(self):
        config = _config()
        config["experimental"]["panel_mint_limit"] = 100
        with _patched(config=config, count=100) as m:
            with pytest.raises(HTTPException) as exc:
                await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

            assert exc.value.status_code == 403
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backstop_limit_applies_when_config_is_silent(self):
        """No panel_mint_limit in the config must still mean bounded minting."""
        with _patched(count=main._PANEL_MINT_DEFAULT_LIMIT) as m:
            with pytest.raises(HTTPException) as exc:
                await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

            assert exc.value.status_code == 403
            m.seed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_below_limit_still_mints(self):
        config = _config()
        config["experimental"]["panel_mint_limit"] = 100
        with _patched(config=config, count=99) as m:
            row = await main._try_panel_mint(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

            m.seed.assert_awaited_once()
            assert row["token"] == TOKEN


def _http_request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


class TestIntakeEndpoint:
    @pytest.mark.asyncio
    async def test_intake_passes_e_to_the_minter_for_unknown_tokens(self):
        request = main.SessionIntakeRequest(token=TOKEN, hkey=_hkey(), g=G_PARAM, e=E_PARAM)
        with patch.object(main, "_enforce_entry_rate_limit", lambda r: None), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.token_repo, "get_token_status", AsyncMock(return_value=None)), \
             patch.object(main, "_try_panel_mint", AsyncMock(return_value=None)) as mint:
            with pytest.raises(HTTPException) as exc:
                await main.preview_session_intake(request, _http_request())

            assert exc.value.status_code == 401
            mint.assert_awaited_once_with(None, TOKEN, _hkey(), G_PARAM, E_PARAM)

    @pytest.mark.asyncio
    async def test_existing_token_ignores_e_and_keeps_its_experiment(self):
        """A re-clicked link with a different e must not re-route a token that
        already belongs to an experiment: minting is never attempted."""
        request = main.SessionIntakeRequest(token=TOKEN, hkey=_hkey(), g=G_PARAM, e="2")
        token_row = {"token": TOKEN, "experiment_id": EXPERIMENT,
                     "treatment_group": GROUP, "used": False}
        config = {"experimental": {"groups": {GROUP: {"seed": {"template_id": "immigration"}}}}}
        with patch.object(main, "_enforce_entry_rate_limit", lambda r: None), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.token_repo, "get_token_status", AsyncMock(return_value=token_row)), \
             patch.object(main, "_try_panel_mint", AsyncMock()) as mint, \
             patch.object(main.config_repo, "check_experiment_availability", AsyncMock(return_value=None)), \
             patch.object(main.config_repo, "get_experiment_config", AsyncMock(return_value=config)):
            resp = await main.preview_session_intake(request, _http_request())

            mint.assert_not_awaited()
            assert resp.topic_template_id == "immigration"
            assert resp.rejoin_session_id is None
