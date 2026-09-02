"""Tests for switching the live experiment.

Exactly one experiment accepts participants at a time, which is what makes
an unknown panel token unambiguous. Switching pauses the outgoing
experiment, and pausing freezes that experiment's participants
mid-conversation, so a switch is refused outright while any session is
still running.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import main


CURRENT = "live_experiment"
TARGET = "other_experiment"


def _patch_admin():
    return patch.object(main, "_require_admin", lambda key: None)


class TestActivateExperiment:
    @pytest.mark.asyncio
    async def test_switch_pauses_others_when_nothing_is_running(self):
        with _patch_admin(), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value={"experimental": {}})), \
             patch.object(main.session_repo, "count_live_sessions_by_experiment",
                          AsyncMock(return_value=[])), \
             patch.object(main.config_repo, "activate_exclusively", AsyncMock()) as activate:
            result = await main.admin_activate_experiment(TARGET, x_admin_key="k")

            activate.assert_awaited_once_with(None, TARGET)
            assert result == {"status": "activated", "experiment_id": TARGET}
            assert main._experiment_id == TARGET

    @pytest.mark.asyncio
    async def test_live_session_blocks_the_switch(self):
        with _patch_admin(), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value={"experimental": {}})), \
             patch.object(main.session_repo, "count_live_sessions_by_experiment",
                          AsyncMock(return_value=[{"experiment_id": CURRENT, "live": 3}])), \
             patch.object(main.config_repo, "activate_exclusively", AsyncMock()) as activate:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            assert exc.value.detail["reason"] == "sessions_in_progress"
            assert exc.value.detail["total"] == 3
            assert exc.value.detail["live_sessions"] == [
                {"experiment_id": CURRENT, "count": 3}
            ]
            activate.assert_not_awaited()
            assert main._experiment_id == CURRENT

    @pytest.mark.asyncio
    async def test_pending_sessions_count_as_live(self):
        """A pending row means a token is already spent on a participant who
        is on their way in, so it must block just as an active one does."""
        with _patch_admin(), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value={"experimental": {}})), \
             patch.object(main.session_repo, "count_live_sessions_by_experiment",
                          AsyncMock(return_value=[{"experiment_id": "third", "live": 1}])), \
             patch.object(main.config_repo, "activate_exclusively", AsyncMock()) as activate:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            activate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reselecting_the_live_experiment_is_allowed_while_running(self):
        """Re-selecting changes nothing, so it must not trip the block."""
        counter = AsyncMock(return_value=[{"experiment_id": CURRENT, "live": 5}])
        with _patch_admin(), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value={"experimental": {}})), \
             patch.object(main.session_repo, "count_live_sessions_by_experiment", counter), \
             patch.object(main.config_repo, "activate_exclusively", AsyncMock()) as activate:
            result = await main.admin_activate_experiment(CURRENT, x_admin_key="k")

            assert result["experiment_id"] == CURRENT
            counter.assert_not_awaited()
            activate.assert_awaited_once_with(None, CURRENT)

    @pytest.mark.asyncio
    async def test_unknown_experiment_is_404(self):
        with _patch_admin(), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "get_experiment_config",
                          AsyncMock(return_value=None)), \
             patch.object(main.config_repo, "activate_exclusively", AsyncMock()) as activate:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment("nope", x_admin_key="k")

            assert exc.value.status_code == 404
            activate.assert_not_awaited()
