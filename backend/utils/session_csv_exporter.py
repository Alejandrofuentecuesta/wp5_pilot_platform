import csv
import os
from pathlib import Path
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


def export_session_messages_csv(session_id: str, messages: Iterable[Message]) -> str:
    """Export session messages to an annotation-ready CSV file.

    The output path defaults to ``backend/exports/session_csv`` and can be
    overridden with ``SESSION_CSV_EXPORT_DIR``.
    """
    export_dir = os.environ.get(
        "SESSION_CSV_EXPORT_DIR",
        str(Path(__file__).resolve().parent.parent / "exports" / "session_csv"),
    )
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    csv_path = export_path / f"{session_id}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for msg in messages:
            writer.writerow({
                "message": msg.content,
                "incivility": "",
                "hate_speech": "",
                "threats_to_dem_freedom": "",
                "impoliteness": "",
                "stance": "",
                "human_like": "",
                "other": "",
            })

    return str(csv_path)

