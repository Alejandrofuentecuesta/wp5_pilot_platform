"""Tests for making an experiment live.

Several experiments may be live at once: each receives the panel arrivals
carrying its NetQuest topic code, so activating one leaves the others as
they are. What activation refuses is a second live experiment with the same
code, which would make an arrival ambiguous. The target's own sessions
frozen by an earlier pause are unfrozen, which is what lets resume recover
from an emergency pause. Resume goes through the same routine.

The module-level default (``_experiment_id``) is only the admin views'
default experiment, recomputed as the newest unpaused one after every
activate, pause and delete.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import main


CURRENT = "live_experiment"
TARGET = "other_experiment"


@contextlib.contextmanager
def _patched(*, config=None, config_found=True, clash=None, unfrozen=0, newest=TARGET):
    """Patch everything _make_experiment_live touches; yield the mocks."""
    cfg = config if config is not None else {"experimental": {}}
    mocks = SimpleNamespace(
        clash=AsyncMock(return_value=clash),
        set_paused=AsyncMock(),
        unfreeze=AsyncMock(return_value=unfrozen),
        newest=AsyncMock(return_value=newest),
    )
    with patch.object(main, "_require_admin", lambda key: None), \
         patch.object(main, "_experiment_id", CURRENT), \
         patch.object(main, "_get_pool", lambda: None), \
         patch.object(main.config_repo, "get_experiment_config",
                      AsyncMock(return_value=cfg if config_found else None)), \
         patch.object(main.config_repo, "find_live_experiment_with_code", mocks.clash), \
         patch.object(main.config_repo, "set_paused", mocks.set_paused), \
         patch.object(main.config_repo, "newest_unpaused_experiment_id", mocks.newest), \
         patch.object(main.session_manager, "set_experiment_paused", mocks.unfreeze):
        yield mocks


def _coded(code, redirect_url=""):
    return {"experimental": {"netquest_topic_code": code, "redirect_url": redirect_url}}


class TestActivateExperiment:
    @pytest.mark.asyncio
    async def test_activation_unpauses_only_the_target(self):
        with _patched() as m:
            result = await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.set_paused.assert_awaited_once_with(None, TARGET, False)
            assert result == {
                "status": "activated",
                "experiment_id": TARGET,
                "sessions_resumed": 0,
                "warning": None,
            }

    @pytest.mark.asyncio
    async def test_other_live_experiments_are_left_alone(self):
        """Two topics run as two live experiments: activating the second must
        not pause the first, and sessions elsewhere never block it."""
        with _patched(config=_coded("2")) as m:
            await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.set_paused.assert_awaited_once_with(None, TARGET, False)

    @pytest.mark.asyncio
    async def test_same_topic_code_live_elsewhere_is_refused(self):
        with _patched(config=_coded("1"), clash=CURRENT) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            assert exc.value.detail["reason"] == "topic_code_in_use"
            assert exc.value.detail["experiment_id"] == CURRENT
            assert exc.value.detail["topic_code"] == "1"
            m.clash.assert_awaited_once_with(None, "1", excluding_experiment_id=TARGET)
            m.set_paused.assert_not_awaited()
            m.unfreeze.assert_not_called()

    @pytest.mark.asyncio
    async def test_experiment_without_code_skips_the_clash_check(self):
        with _patched(config={"experimental": {}}) as m:
            await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.clash.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redirect_url_without_code_warns(self):
        """A return URL means panel participants are expected, but without a
        topic code none can be routed here: the operator is warned."""
        with _patched(config=_coded(None, "https://panel.example/return")):
            result = await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert result["warning"] == main.NO_TOPIC_CODE_WARNING

    @pytest.mark.asyncio
    async def test_redirect_url_with_code_does_not_warn(self):
        with _patched(config=_coded("2", "https://panel.example/return")):
            result = await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert result["warning"] is None

    @pytest.mark.asyncio
    async def test_admin_default_is_recomputed(self):
        with _patched(newest="newest_live") as m:
            await main.admin_activate_experiment(TARGET, x_admin_key="k")

            m.newest.assert_awaited_once()
            assert main._experiment_id == "newest_live"

    @pytest.mark.asyncio
    async def test_activation_unfreezes_the_targets_sessions(self):
        """Recovering from an emergency pause: activating the same experiment
        again must unfreeze its in-memory sessions."""
        with _patched(unfrozen=4) as m:
            result = await main.admin_activate_experiment(CURRENT, x_admin_key="k")

            m.unfreeze.assert_called_once_with(CURRENT, False)
            assert result["sessions_resumed"] == 4

    @pytest.mark.asyncio
    async def test_unknown_experiment_is_404(self):
        with _patched(config_found=False) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment("nope", x_admin_key="k")

            assert exc.value.status_code == 404
            m.set_paused.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_synthetic_experiment_is_refused(self):
        with _patched(config={"experimental": {}, "synthetic": {"batch_id": "b"}}) as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_activate_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            m.set_paused.assert_not_awaited()


class TestResumeExperiment:
    @pytest.mark.asyncio
    async def test_resume_is_activation(self):
        with _patched(unfrozen=2) as m:
            result = await main.admin_resume_experiment(TARGET, x_admin_key="k")

            m.set_paused.assert_awaited_once_with(None, TARGET, False)
            m.unfreeze.assert_called_once_with(TARGET, False)
            assert result == {
                "status": "resumed",
                "experiment_id": TARGET,
                "sessions_resumed": 2,
                "warning": None,
            }

    @pytest.mark.asyncio
    async def test_resume_is_refused_on_a_topic_code_clash(self):
        with _patched(config=_coded("2"), clash="third") as m:
            with pytest.raises(HTTPException) as exc:
                await main.admin_resume_experiment(TARGET, x_admin_key="k")

            assert exc.value.status_code == 409
            m.set_paused.assert_not_awaited()
            m.unfreeze.assert_not_called()


class TestPauseExperiment:
    @pytest.mark.asyncio
    async def test_pause_recomputes_the_admin_default(self):
        with patch.object(main, "_require_admin", lambda key: None), \
             patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.session_manager, "count_running", lambda eid: 0), \
             patch.object(main.config_repo, "set_paused", AsyncMock()) as set_paused, \
             patch.object(main.config_repo, "newest_unpaused_experiment_id",
                          AsyncMock(return_value=None)), \
             patch.object(main.session_manager, "set_experiment_paused", AsyncMock(return_value=0)):
            result = await main.admin_pause_experiment(CURRENT, x_admin_key="k")

            set_paused.assert_awaited_once_with(None, CURRENT, True)
            assert result["status"] == "paused"
            assert main._experiment_id == ""


class TestStartupDefault:
    @pytest.mark.asyncio
    async def test_refresh_sets_newest_unpaused_or_empty(self):
        with patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main.config_repo, "newest_unpaused_experiment_id",
                          AsyncMock(return_value="fresh")):
            await main._refresh_default_experiment(None)
            assert main._experiment_id == "fresh"
        with patch.object(main, "_experiment_id", CURRENT), \
             patch.object(main.config_repo, "newest_unpaused_experiment_id",
                          AsyncMock(return_value=None)):
            await main._refresh_default_experiment(None)
            assert main._experiment_id == ""


class TestUpdateConfigTopicCodeGuard:
    """Editing a live experiment into another live experiment's topic code
    is refused, mirroring the activation check."""

    @contextlib.contextmanager
    def _patched(self, *, paused, clash):
        update = AsyncMock()
        with patch.object(main, "_require_admin", lambda key: None), \
             patch.object(main, "_get_pool", lambda: None), \
             patch.object(main.config_repo, "validate_simulation_config", lambda sim: sim), \
             patch.object(main.config_repo, "validate_experimental_config", lambda exp, feats: exp), \
             patch.object(main.config_repo, "get_experiment",
                          AsyncMock(return_value={"experiment_id": TARGET, "paused": paused})), \
             patch.object(main.config_repo, "find_live_experiment_with_code",
                          AsyncMock(return_value=clash)), \
             patch.object(main.config_repo, "update_experiment_config", update):
            yield update

    @pytest.mark.asyncio
    async def test_live_experiment_cannot_take_a_code_in_use(self):
        body = {"simulation": {"k": 1}, "experimental": {"netquest_topic_code": "1"}}
        with self._patched(paused=False, clash=CURRENT) as update:
            with pytest.raises(HTTPException) as exc:
                await main.admin_update_config(TARGET, body, x_admin_key="k")

            assert exc.value.status_code == 422
            assert CURRENT in exc.value.detail
            update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_paused_experiment_may_take_the_code(self):
        """The clash is caught later, at activation."""
        body = {"simulation": {"k": 1}, "experimental": {"netquest_topic_code": "1"}}
        with self._patched(paused=True, clash=CURRENT) as update:
            result = await main.admin_update_config(TARGET, body, x_admin_key="k")

            assert result["status"] == "updated"
            update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_code_skips_the_check(self):
        body = {"simulation": {"k": 1}, "experimental": {"netquest_topic_code": None}}
        with self._patched(paused=False, clash=CURRENT) as update:
            await main.admin_update_config(TARGET, body, x_admin_key="k")

            main.config_repo.find_live_experiment_with_code.assert_not_awaited()
            update.assert_awaited_once()
