import json
import pytest
from unittest.mock import AsyncMock, patch

from utils.participant_privacy import personal_information_category
from tests.test_chatroom import _patch_externals, _create_session
from platforms.chatroom import build_return_url


@pytest.mark.parametrize("text,category", [
    ("mi correo es persona.prueba@gmail.com", "email"),
    ("escribeme a prueba+estudio@outlook.es", "email"),
    ("prueba [arroba] gmail [punto] com", "email"),
    ("prueba(at)example(dot)org", "email"),
    ("mi tel\u00e9fono es +34 612 345 678", "phone"),
    ("contactame por WhatsApp: 912345678", "phone"),
    ("mi DNI: 12345678Z", "identity_document"),
    ("mi NIE es X1234567L", "identity_document"),
    ("cuenta ES91 2100 0418 4502 0005 1332", "bank_account"),
    ("texto " * 500 + "prueba@gmail.com", "email"),
])
def test_detects_direct_identifiers(text, category):
    assert personal_information_category(text) == category


@pytest.mark.parametrize("text", [
    "hola", "@Carlos no estoy de acuerdo", "Pedro Sanchez y Ayuso",
    "La poblacion es de 612345678 personas", "El paro subio un 12,5%",
    "Tengo cuenta en Gmail", "Hay que mejorar la vivienda en Madrid",
])
def test_does_not_stop_ordinary_discussion(text):
    assert personal_information_category(text) is None


@pytest.mark.asyncio
async def test_email_ends_session_without_exposing_message():
    with _patch_externals() as mocks, \
         patch("platforms.chatroom.event_repo") as events, \
         patch("platforms.chatroom.asyncio.sleep", new=AsyncMock()):
        events.insert_event_strict = AsyncMock()
        session, _ = _create_session()
        session.running = True
        session._publish_session_end = AsyncMock()
        session.stop = AsyncMock()
        session._run_participant_safety_check = AsyncMock()
        session._screen_participant = AsyncMock()
        await session.handle_user_message("Mi correo es prueba@gmail.com")
        assert session._safety_intervention_triggered
        assert session.state.messages == []
        assert not getattr(session, "_first_user_message_received", False)
        mocks["message_repo"].insert_message.assert_not_called()
        mocks["redis"].push_to_window.assert_not_called()
        session._run_participant_safety_check.assert_not_called()
        session._screen_participant.assert_not_called()
        session._publish_session_end.assert_awaited_once_with("participant_privacy")
        session.stop.assert_awaited_once_with(reason="participant_privacy")
        audit = events.insert_event_strict.await_args.kwargs
        assert audit["event_type"] == "participant_privacy_triggered"
        assert audit["data"]["category"] == "email"
        assert "prueba@gmail.com" not in json.dumps(audit)
        await session.handle_user_message("No quiero terminar")
        assert events.insert_event_strict.await_count == 1
        assert session.state.messages == []


def test_privacy_exit_is_noncomplete_not_voluntary_exit():
    assert build_return_url("https://example.org/end", "token", "participant_privacy").endswith("r=2")
