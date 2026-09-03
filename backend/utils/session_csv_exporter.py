import csv
import io
from typing import Iterable

from models import Message


CSV_COLUMNS = [
    "message",
    "incivility",
    "hate_speech",
    "threats_to_dem_freedom",
    "impoliteness",
    "stance",
    "human_like",
    "other",
]


def render_session_messages_csv(messages: Iterable[Message]) -> str:
    """Render an annotation-ready CSV of session messages, in memory.

    Session data lives only in the database; the admin download endpoint
    renders this on demand. Nothing is written to the filesystem.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for msg in messages:
        writer.writerow(
            {
                "message": msg.content,
                "incivility": "",
                "hate_speech": "",
                "threats_to_dem_freedom": "",
                "impoliteness": "",
                "stance": "",
                "human_like": "",
                "other": "",
            }
        )
    return buffer.getvalue()
