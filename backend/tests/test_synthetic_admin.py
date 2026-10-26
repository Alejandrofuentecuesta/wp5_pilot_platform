from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main

KEY = "synthetic-test-key"
HEADERS = {"X-Admin-Key": KEY}
BODY = {
    "source_experiment_id": "study", "groups": ["low"],
    "participant_provider": "konstanz", "participant_model": "model",
    "confirm_api_usage": True,
}


@pytest.fixture(autouse=True)
def admin():
    main._admin_failures.update(count=0, last_at=0.0)
    with patch.object(main, "ADMIN_PASSPHRASE", KEY):
        yield
    main._admin_failures.update(count=0, last_at=0.0)


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("method,path", [
    ("get", "/admin/synthetic-batches"),
    ("post", "/admin/synthetic-batches"),
    ("post", "/admin/synthetic-batches/11111111-2222-3333-4444-555555555555/cancel"),
])
def test_routes_require_admin(client, method, path):
    response = client.get(path) if method == "get" else client.post(path, json=BODY)
    assert response.status_code == 401


def test_launch_returns_batch_and_requires_explicit_cost_confirmation(client):
    with patch.object(main.synthetic_batches, "start", new=AsyncMock(return_value={"batch_id": "batch", "status": "running"})) as start:
        response = client.post("/admin/synthetic-batches", headers=HEADERS, json=BODY)
        assert response.status_code == 202
        assert response.json()["batch_id"] == "batch"
        response = client.post("/admin/synthetic-batches", headers=HEADERS, json={**BODY, "confirm_api_usage": False})
        assert response.status_code == 422
        start.assert_awaited_once()


def test_conflicting_batch_is_reported(client):
    with patch.object(main.synthetic_batches, "start", new=AsyncMock(side_effect=ValueError("A synthetic batch is already running"))):
        response = client.post("/admin/synthetic-batches", headers=HEADERS, json=BODY)
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


def test_launch_accepts_editable_randomization_settings(client):
    with patch.object(main.synthetic_batches, "start", new=AsyncMock(return_value={"batch_id": "batch"})) as start:
        response = client.post("/admin/synthetic-batches", headers=HEADERS, json={
            **BODY, "seed_mode": "automatic", "stance": "seeded_balanced",
            "vary_participants": True, "participant_traits": {"style": "brief", "topic_knowledge": "high"},
        })
    assert response.status_code == 202
    spec = start.await_args.args[0]
    assert spec.seed_mode == "automatic" and spec.stance == "seeded_balanced"
    assert spec.participant_traits.style == "brief"
    assert spec.participant_traits.topic_knowledge == "high"
    assert spec.participant_traits.activity == "automatic"


def test_list_filters_source(client):
    with patch.object(main, "list_batches", new=AsyncMock(return_value=[])) as listed:
        response = client.get("/admin/synthetic-batches?source_experiment_id=study", headers=HEADERS)
    assert response.status_code == 200
    listed.assert_awaited_once_with("study")


def test_cancellation(client):
    batch_id = "11111111-2222-3333-4444-555555555555"
    with patch.object(main.synthetic_batches, "cancel", new=AsyncMock()) as cancel:
        response = client.post(f"/admin/synthetic-batches/{batch_id}/cancel", headers=HEADERS)
    assert response.status_code == 200
    cancel.assert_awaited_once_with(batch_id)


@pytest.mark.asyncio
async def test_synthetic_experiment_cannot_become_live():
    with patch.object(main, "_get_pool", return_value="pool"), \
         patch.object(main.config_repo, "get_experiment_config", new=AsyncMock(return_value={"synthetic": {"batch_id": "batch"}})):
        with pytest.raises(main.HTTPException) as error:
            await main._make_experiment_live("synthetic-batch")
    assert error.value.status_code == 409
