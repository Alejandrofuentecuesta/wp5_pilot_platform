import csv
import io

from models import Message
from utils.session_csv_exporter import render_session_messages_csv


def _msg(sender: str, content: str) -> Message:
    return Message.create(sender=sender, content=content)


def test_render_session_messages_csv_creates_annotation_template():
    csv_text = render_session_messages_csv(
        [_msg("Alice", "Hola"), _msg("participant", "¿Qué tal?")]
    )

    rows = list(csv.DictReader(io.StringIO(csv_text)))

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
