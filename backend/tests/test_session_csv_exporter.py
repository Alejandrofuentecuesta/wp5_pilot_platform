import csv

from models import Message
from utils.session_csv_exporter import export_session_messages_csv


def _msg(sender: str, content: str) -> Message:
    return Message.create(sender=sender, content=content)


def test_export_session_messages_csv_creates_annotation_template(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_CSV_EXPORT_DIR", str(tmp_path))

    csv_path = export_session_messages_csv(
        session_id="session-123",
        messages=[_msg("Alice", "Hola"), _msg("participant", "¿Qué tal?")],
    )

    assert csv_path == str(tmp_path / "session-123.csv")

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {
            "message": "Hola",
            "incivility": "",
            "hate_speech": "",
            "threats_to_dem_freedom": "",
            "impoliteness": "",
            "stance": "",
            "human_like": "",
            "other": "",
        },
        {
            "message": "¿Qué tal?",
            "incivility": "",
            "hate_speech": "",
            "threats_to_dem_freedom": "",
            "impoliteness": "",
            "stance": "",
            "human_like": "",
            "other": "",
        },
    ]
