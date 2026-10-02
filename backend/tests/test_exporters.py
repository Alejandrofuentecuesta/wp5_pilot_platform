import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest

from utils import exporters


@pytest.mark.asyncio
async def test_experiment_zip_contains_one_json_per_session(monkeypatch):
    payloads = [
        {
            "exported_at": "2026-09-30T10:00:00+00:00",
            "session": {"session_id": "session-a", "experiment_id": "exp"},
            "messages": [],
            "events": [],
        },
        {
            "exported_at": "2026-09-30T10:00:00+00:00",
            "session": {"session_id": "session-b", "experiment_id": "exp"},
            "messages": [{"message_id": "message-b", "content": "Hola"}],
            "events": [],
        },
    ]
    monkeypatch.setattr(exporters, "build_sessions_csv", AsyncMock(return_value="sessions"))
    monkeypatch.setattr(exporters, "build_events_csv", AsyncMock(return_value="events"))
    monkeypatch.setattr(exporters, "build_tokens_csv", AsyncMock(return_value="tokens"))
    monkeypatch.setattr(
        exporters,
        "build_experiment_session_payloads",
        AsyncMock(return_value=payloads),
    )

    body = await exporters.build_experiment_zip(object(), "exp", {"description": "Test"})

    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert set(archive.namelist()) == {
            "exp/sessions/session-a_stage_session.json",
            "exp/sessions/session-b_stage_session.json",
            "exp/sessions_and_messages.csv",
            "exp/events.csv",
            "exp/tokens.csv",
            "exp/codebook.md",
        }
        session_b = json.loads(
            archive.read("exp/sessions/session-b_stage_session.json").decode("utf-8")
        )

    assert session_b == payloads[1]
