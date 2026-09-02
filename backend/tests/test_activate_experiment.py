"""Tests for switching the live experiment.

Exactly one experiment accepts participants at a time, which is what makes
an unknown panel token unambiguous. Making an experiment live pauses every
other one, and pausing freezes participants mid-conversation, so a switch
is refused while any OTHER experiment still has sessions running. The
target's own sessions never block it — activation unpauses and unfreezes
them — which is also what lets resume recover from an emergency pause.

The resume endpoint goes through the same routine: before this, resume was
a side door that could leave two experiments unpaused at once.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import main


CURRENT = "live_experiment"
TARGET = "other_experiment"


@contextlib.contextmanager
def _patched(*, live_rows, config_found=True, unfrozen=0):
    """Patch everything _make_experiment_live touches; yield the mocks."""
    mocks = SimpleNamespace(
        counter=AsyncMock(return_value=live_rows),
        activate=AsyncMock(),
        unfreeze=MagicMock(return_value=unfrozen),
    )
    with patch.object(main, "_require_admin", lambda key: None), \
         patch.object(main, "_experiment_id", CURRENT), \
         patch.object(main, "_get_pool", lambda: None), \
         patch.object(main.config_repo, "get_experiment_config",
                      AsyncMock(return_value={"experimental": {}} if config_found else None)), \
         patch.object(main.session_repo, "count_live_sessions_by_experiment", mocks.counter), \
         patch.object(main.config_repo, "activate_exclusively", mocks.activate), \
         patch.object(main.session_manager, "set_experiment_paused", mocks.unfreeze):
        yield mocks


class TestActivateExperiment:
    @pytest.mark.asyncio
    async def test_switch_pauses_others_when_nothing_is_running(self):
        with _patched(live_rows=[]) as m:
            result = await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.activate.assert_awaited_once_with(None, TARGET)
            assert result == {
                "status": "activated",
                "experiment_id": TARGET,
                "sessions_resumed": 0,
            }
            assert main._experiment_id == TARGET

    @pytest.mark.asyncio
    async def test_guard_excludes_the_target_experiment(self):
        """The target's own sessions are helped by activation, never harmed,
        so the count must exclude them."""
        with _patched(live_rows=[]) as m:
            await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.counter.assert_awaited_once_with(None, excluding_experiment_id=TARGET)

    @pytest.mark.asyncio
    async def test_live_session_elsewhere_blocks_the_switch(self):
        with _patched(live_rows=[{"experiment_id": CURRENT, "live": 3}]) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            assert exc.value.detail["reason"] == "sessions_in_progress"
            assert exc.value.detail["total"] == 3
            assert exc.value.detail["live_sessions"] == [
                {"experiment_id": CURRENT, "count": 3}
            ]
            m.activate.assert_not_awaited()
            assert main._experiment_id == CURRENT

    @pytest.mark.asyncio
    async def test_activation_unfreezes_the_targets_sessions(self):
        """Recovering from an emergency pause: activating the same experiment
        again must unfreeze its in-memory sessions."""
        with _patched(live_rows=[], unfrozen=4) as m:
            result = await main.admin_activate_experiment(CURRENT, x_admin_key="k")

            m.unfreeze.assert_called_once_with(CURRENT, False)
            assert result["sessions_resumed"] == 4

    @pytest.mark.asyncio
    async def test_unknown_experiment_is_404(self):
        with _patched(live_rows=[], config_found=False) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment("nope", x_admin_key="k")

            assert exc.value.status_code == 404
            m.activate.assert_not_awaited()


class TestResumeExperiment:
    @pytest.mark.asyncio
    async def test_resume_is_exclusive_activation(self):
        """Resume must pause every other experiment, not just unpause one."""
        with _patched(live_rows=[], unfrozen=2) as m:
            result = await main.admin_resume_experiment(TARGET, x_admin_key="k")

            m.activate.assert_awaited_once_with(None, TARGET)
            m.unfreeze.assert_called_once_with(TARGET, False)
            assert result == {
                "status": "resumed",
                "experiment_id": TARGET,
                "sessions_resumed": 2,
            }
            assert main._experiment_id == TARGET

    @pytest.mark.asyncio
    async def test_resume_is_blocked_by_sessions_elsewhere(self):
        with _patched(live_rows=[{"experiment_id": "third", "live": 1}]) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_resume_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            m.activate.assert_not_awaited()
            m.unfreeze.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_of_paused_live_experiment_skips_its_own_sessions(self):
        """Pause the live experiment mid-session, then resume it: its own
        frozen sessions are excluded from the guard, so resume succeeds and
        unfreezes them rather than deadlocking."""
        with _patched(live_rows=[], unfrozen=3) as m:
            result = await main.admin_resume_experiment(CURRENT, x_admin_key="k")

            m.counter.assert_awaited_once_with(None, excluding_experiment_id=CURRENT)
            assert result["sessions_resumed"] == 3
