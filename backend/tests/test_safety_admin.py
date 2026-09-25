"""Safety tab endpoints: admin-gated, reviewer name required, live-session actions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from db.repositories.config_repo import validate_safety_config
from utils.safety import load_policy

KEY = "correct-passphrase"
HDR = {"X-Admin-Key": KEY}


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def admin():
    main._admin_failures.update(count=0, last_at=0.0)
    with patch.object(main, "ADMIN_PASSPHRASE", KEY):
        yield
    main._admin_failures.update(count=0, last_at=0.0)


@pytest.mark.parametrize("method,path", [
    ("get", "/admin/safety/summary"),
    ("get", "/admin/safety/flags"),
    ("get", "/admin/safety/flags/export?format=json"),
    ("post", "/admin/safety/flags/abc/review"),
    ("post", "/admin/safety/test"),
    ("post", "/admin/safety/sessions/abc/pause"),
    ("post", "/admin/safety/sessions/abc/resume"),
    ("post", "/admin/safety/sessions/abc/end"),
])
def test_all_safety_routes_require_admin(client, method, path):
    if method == "get":
        r = client.get(path)
    else:
        r = client.post(path, json={"reviewer": "x", "verdict": "concern"})
    assert r.status_code == 401


class TestFlags:
    def test_lists_open_flags_with_live_and_names(self, client):
        rows = [{
            "flag_id": "f1", "session_id": "s1", "session_status": "active",
            "categories": ["S10", "S11"], "verdict": "unsafe",
        }]
        with patch.object(main, "_get_pool", return_value=MagicMock()), \
             patch("main.safety_repo.list_flags", new=AsyncMock(return_value=rows)), \
             patch("main.session_manager.list_sessions", new=AsyncMock(return_value={"s1": MagicMock()})):
            r = client.get("/admin/safety/flags?status=open", headers=HDR)
        assert r.status_code == 200
        flag = r.json()["flags"][0]
        assert flag["live"] is True
        assert flag["category_names"] == ["Hate", "Suicide & Self-Harm"]
        assert "server_time" in r.json()

    @pytest.mark.parametrize("format,content_type", [("json", "application/json"), ("csv", "text/csv")])
    def test_exports_reviewed_flags(self, client, format, content_type):
        rows = [{
            "flag_id": "f1", "session_id": "s1", "experiment_id": "e1",
            "categories": ["S1"], "reviewed_by": "automatic_timeout",
            "review_verdict": "no_concern", "content": "message",
        }]
        with patch.object(main, "_get_pool", return_value=MagicMock()), \
             patch("main.safety_repo.list_flags", new=AsyncMock(return_value=rows)) as listed:
            r = client.get(f"/admin/safety/flags/export?format={format}", headers=HDR)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(content_type)
        assert "attachment" in r.headers["content-disposition"]
        assert "automatic_timeout" in r.text
        listed.assert_awaited_once()
        assert listed.call_args.kwargs["status"] == "reviewed"

    def test_review_requires_reviewer_name(self, client):
        with patch.object(main, "_get_pool", return_value=MagicMock()):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "concern", "reviewer": "  "})
        assert r.status_code == 422

    def test_review_unknown_flag_is_404(self, client):
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=False)) as review:
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "no_concern", "reviewer": "Laia"})
        assert r.status_code == 404
        review.assert_not_awaited()

    def test_review_records_and_logs(self, client):
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"session_id": "s1", "experiment_id": "e1"})
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=True)) as rv, \
             patch("main.event_repo.insert_event", new=AsyncMock()) as ev:
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "concern", "reviewer": "Laia", "note": "check"})
        assert r.status_code == 200
        assert rv.call_args.kwargs["verdict"] == "concern"
        assert ev.call_args.kwargs["event_type"] == "safety_flag_reviewed"
        assert ev.call_args.kwargs["data"]["by"] == "Laia"

    def test_no_concern_publishes_withheld_agent_message(self, client):
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "session_id": "s1",
            "experiment_id": "e1",
            "message_id": None,
            "displayed_at": None,
            "sender_type": "agent",
            "sender": "Carlos",
            "content": "mensaje revisado",
            "verdict": "unsafe",
            "categories": ["S10"],
        })
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.running = True
        session.operator_held = False
        session._turn_lock.__aenter__ = AsyncMock(return_value=None)
        session._turn_lock.__aexit__ = AsyncMock(return_value=False)
        session.agent_manager._handle_message = AsyncMock()
        # Real numbers (not a bare MagicMock) so the typing-delay math works;
        # sleep itself is mocked out below so the test doesn't actually wait.
        session._publish_typing = AsyncMock()
        session.TYPING_CHARS_PER_SECOND = 7.0
        session.TYPING_DELAY_MIN = 0.5
        session.TYPING_DELAY_MAX = 8.0

        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.session_manager.get_session", new=AsyncMock(return_value=session)), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=True)), \
             patch("main.safety_repo.set_message_safety_verdict", new=AsyncMock()) as set_verdict, \
             patch("main.safety_repo.mark_flag_published", new=AsyncMock()) as mark_published, \
             patch("main.event_repo.insert_event", new=AsyncMock()), \
             patch("main.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "no_concern", "reviewer": "Laia"})

        assert r.status_code == 200
        assert r.json()["published"] is True
        call = session.agent_manager._handle_message.call_args
        assert call.kwargs["skip_safety"] is True
        assert call.args[0].message.sender == "Carlos"
        assert call.args[0].message.content == "mensaje revisado"
        set_verdict.assert_awaited_once()
        mark_published.assert_awaited_once()
        # Published the same way a normal turn is: a typing indicator and a
        # length-based delay, not an instant insert.
        sleep_mock.assert_awaited_once()
        assert session._publish_typing.await_count == 2
        assert session._publish_typing.await_args_list[0].kwargs == {"started": True}
        assert session._publish_typing.await_args_list[1].kwargs == {"started": False}
        # And the agent must be unblocked so the Director can pick them again.
        session.safety_screen.resolve_flag.assert_called_once_with("f1", "Carlos")

    def test_concern_verdict_still_unblocks_the_agent_without_publishing(self, client):
        """Marking an agent's withheld message as 'concern' resolves the flag
        (so the agent can speak again) without ever publishing it."""
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "session_id": "s1",
            "experiment_id": "e1",
            "message_id": None,
            "displayed_at": None,
            "sender_type": "agent",
            "sender": "Carlos",
            "content": "mensaje retenido",
            "verdict": "unsafe",
            "categories": ["S10"],
        })
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.agent_manager._handle_message = AsyncMock()

        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.session_manager.get_session", new=AsyncMock(return_value=session)), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=True)), \
             patch("main.event_repo.insert_event", new=AsyncMock()):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "concern", "reviewer": "Laia"})

        assert r.status_code == 200
        assert r.json()["published"] is False
        session.agent_manager._handle_message.assert_not_awaited()
        session.safety_screen.resolve_flag.assert_called_once_with("f1", "Carlos")

    def test_unavailable_verdict_reviewed_unblocks_without_publish_path(self, client):
        """An 'unavailable' flag can never be published (no verdict to approve),
        but reviewing it must still unblock the agent."""
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "session_id": "s1",
            "experiment_id": "e1",
            "message_id": None,
            "displayed_at": None,
            "sender_type": "agent",
            "sender": "Carlos",
            "content": "mensaje retenido",
            "verdict": "unavailable",
            "categories": [],
        })
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.agent_manager._handle_message = AsyncMock()

        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.session_manager.get_session", new=AsyncMock(return_value=session)), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=True)), \
             patch("main.event_repo.insert_event", new=AsyncMock()):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "no_concern", "reviewer": "Laia"})

        assert r.status_code == 200
        assert r.json()["published"] is False
        session.agent_manager._handle_message.assert_not_awaited()
        session.safety_screen.resolve_flag.assert_called_once_with("f1", "Carlos")

    def test_participant_flag_review_does_not_touch_safety_screen(self, client):
        pool = MagicMock()
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "session_id": "s1",
            "experiment_id": "e1",
            "message_id": "m1",
            "displayed_at": "2026-01-01T00:00:00Z",
            "sender_type": "participant",
            "sender": "Paula",
            "content": "mensaje del participante",
            "verdict": "unsafe",
            "categories": ["S11"],
        })
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(main, "_get_pool", return_value=pool), \
             patch("main.session_manager.get_session", new=AsyncMock()) as get_session, \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=True)), \
             patch("main.event_repo.insert_event", new=AsyncMock()):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "no_concern", "reviewer": "Laia"})

        assert r.status_code == 200
        get_session.assert_not_awaited()


class TestSessionActions:
    def test_pause_unknown_session_is_404(self, client):
        with patch("main.session_manager.get_session", new=AsyncMock(return_value=None)):
            r = client.post("/admin/safety/sessions/s1/pause", headers=HDR, json={"reviewer": "Laia"})
        assert r.status_code == 404

    def test_pause_resume_end_delegate_to_session(self, client):
        session = MagicMock()
        session.running = True
        session.pause_for_safety = AsyncMock(return_value=True)
        session.resume_from_safety = AsyncMock(return_value=12.0)
        session.end_for_safety = AsyncMock()
        with patch("main.session_manager.get_session", new=AsyncMock(return_value=session)):
            assert client.post("/admin/safety/sessions/s1/pause", headers=HDR,
                               json={"reviewer": "Laia"}).json()["status"] == "paused"
            assert client.post("/admin/safety/sessions/s1/resume", headers=HDR,
                               json={"reviewer": "Laia"}).json()["credited_seconds"] == 12.0
            assert client.post("/admin/safety/sessions/s1/end", headers=HDR,
                               json={"reviewer": "Laia"}).json()["status"] == "ended"
        session.pause_for_safety.assert_awaited_once_with("Laia")
        session.resume_from_safety.assert_awaited_once_with("Laia")
        session.end_for_safety.assert_awaited_once_with("Laia")


class TestPolicyEndpoints:
    def _cfg(self, locked=False):
        return {"simulation": {}, "experimental": {"safety": {
            "enabled": True, "locked": locked}}}

    def test_draft_classifier_config_can_be_tested_without_saving(self, client):
        result = {"ok": True, "transport": "anthropic_messages", "model": "claude-haiku"}
        with patch.object(main, "_test_safety_classifier_config", new=AsyncMock(return_value=result)) as test:
            r = client.post("/admin/safety/test", headers=HDR, json={
                "enabled": True,
                "transport": "anthropic_messages",
                "model": "claude-haiku",
                "timeout_s": 10,
            })
        assert r.status_code == 200
        assert r.json() == result
        safety = test.await_args.args[0]
        assert safety["transport"] == "anthropic_messages"
        assert safety["model"] == "claude-haiku"
        assert safety["timeout_s"] == 10

    def test_get_shows_settings_and_fixed_policy(self, client):
        with patch.object(main, "_get_pool", return_value=MagicMock()), \
             patch("main.config_repo.get_experiment_config", new=AsyncMock(return_value=self._cfg())):
            r = client.get("/admin/safety/policy/e1", headers=HDR)
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True and body["locked"] is False
        assert "categories" not in body and "context_mode" not in body
        policy = load_policy()
        assert body["policy"] == {"name": policy.name, "version": policy.version, "text": policy.text}

    def test_policy_cannot_be_edited_through_the_api(self, client):
        r = client.put("/admin/safety/policy/e1", headers=HDR, json={"categories": []})
        assert r.status_code == 405

    def test_lock_endpoint(self, client):
        with patch.object(main, "_get_pool", return_value=MagicMock()), \
             patch("main.config_repo.get_experiment_config", new=AsyncMock(return_value=self._cfg())), \
             patch("main.config_repo.update_safety_block", new=AsyncMock()) as upd:
            r = client.post("/admin/safety/policy/e1/lock", headers=HDR, json={"locked": True})
        assert r.status_code == 200 and r.json()["locked"] is True
        assert upd.call_args[0][2]["locked"] is True


class TestSafetyConfigValidation:
    def test_absent_is_disabled(self):
        assert validate_safety_config(None) == {"enabled": False, "locked": False}

    def test_legacy_llama_guard_settings_fall_back_to_safeguard_defaults(self):
        out = validate_safety_config({
            "enabled": True, "locked": True, "transport": "openai_completions",
            "model": "meta-llama/Llama-Guard-3-8B", "timeout_s": 8,
            "base_url": "https://whatif.inf.uni-konstanz.de", "context_mode": "always",
            "categories": [{"code": "S10", "title": "Hate"}], "num_ctx": 4096,
        })
        assert out == {"enabled": True, "locked": True, "base_url": "https://whatif.inf.uni-konstanz.de"}

    def test_current_settings_are_kept(self):
        cfg = {"enabled": True, "locked": False, "transport": "anthropic_messages",
               "model": "claude-haiku-4-5-20251001", "timeout_s": 15.0}
        assert validate_safety_config(cfg) == cfg

    def test_bad_transport_rejected(self):
        with pytest.raises(ValueError):
            validate_safety_config({"enabled": True, "transport": "grpc"})

    def test_timeout_positive_number(self):
        with pytest.raises(ValueError):
            validate_safety_config({"timeout_s": 0})
        assert validate_safety_config({"timeout_s": "5"})["timeout_s"] == 5.0
