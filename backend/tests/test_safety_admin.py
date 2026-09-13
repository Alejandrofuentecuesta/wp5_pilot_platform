"""Safety tab endpoints: admin-gated, reviewer name required, live-session actions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from db.repositories.config_repo import validate_safety_config

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
    ("post", "/admin/safety/flags/abc/review"),
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

    def test_review_requires_reviewer_name(self, client):
        with patch.object(main, "_get_pool", return_value=MagicMock()):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "concern", "reviewer": "  "})
        assert r.status_code == 422

    def test_review_unknown_flag_is_404(self, client):
        with patch.object(main, "_get_pool", return_value=MagicMock()), \
             patch("main.safety_repo.review_flag", new=AsyncMock(return_value=False)):
            r = client.post("/admin/safety/flags/f1/review", headers=HDR,
                            json={"verdict": "no_concern", "reviewer": "Laia"})
        assert r.status_code == 404

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


class TestSafetyConfigValidation:
    def test_absent_is_disabled(self):
        assert validate_safety_config(None) == {"enabled": False}

    def test_bad_transport_rejected(self):
        with pytest.raises(ValueError):
            validate_safety_config({"enabled": True, "transport": "grpc"})

    def test_categories_shape(self):
        with pytest.raises(ValueError):
            validate_safety_config({"categories": [{"code": "S1"}]})
        out = validate_safety_config({"categories": [{"code": "S10", "title": "Hate", "definition": "d"}]})
        assert out["categories"][0]["definition"] == "d"

    def test_timeout_positive_number(self):
        with pytest.raises(ValueError):
            validate_safety_config({"timeout_s": 0})
        assert validate_safety_config({"timeout_s": "5"})["timeout_s"] == 5.0
