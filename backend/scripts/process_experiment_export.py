#!/usr/bin/env python3
"""Convert a platform experiment ZIP into per-session JSON files and an index.

The conversion is entirely local. The large events CSV is read as a stream and
only one session's events are held in memory at a time.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SESSION_COLUMNS = {
    "experiment_id",
    "experiment_description",
    "session_id",
    "treatment_group",
    "session_status",
    "started_at",
    "ended_at",
    "end_reason",
    "session_duration_minutes",
    "messages_per_minute",
    "evaluate_interval",
    "action_window_size",
    "performer_memory_size",
    "director_model",
    "performer_model",
    "moderator_model",
    "chatroom_context",
    "ecological_validity_criteria",
}

MESSAGE_COLUMNS = {
    "message_id",
    "sender",
    "content",
    "sent_at",
    "reply_to",
    "reported",
    "is_incivil",
    "is_like_minded",
    "inferred_participant_stance",
    "classification_rationale",
}

INDEX_COLUMNS = [
    "experiment_id",
    "session_id",
    "treatment_group",
    "session_status",
    "started_at",
    "ended_at",
    "actual_duration_minutes",
    "end_reason",
    "configured_duration_minutes",
    "messages_per_minute",
    "total_messages",
    "classified_messages",
    "incivil_messages",
    "incivil_percent",
    "like_minded_messages",
    "like_minded_percent",
    "reported_messages",
    "message_like_events",
    "message_reaction_events",
    "message_report_events",
    "user_block_events",
    "llm_call_events",
    "error_events",
    "safety_events",
    "compose_events",
    "tab_hidden_events",
    "idle_prompt_events",
    "exit_attempt_events",
    "total_events",
    "json_file",
]


def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while limit:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "")}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "unknown-session"


def _find_member(archive: zipfile.ZipFile, filename: str) -> str:
    matches = [name for name in archive.namelist() if Path(name).name == filename]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one {filename!r} in the ZIP, found {len(matches)}."
        )
    return matches[0]


def _dict_reader(archive: zipfile.ZipFile, member: str) -> Iterable[dict[str, str]]:
    raw = archive.open(member, "r")
    text = __import__("io").TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
    try:
        yield from csv.DictReader(text)
    finally:
        text.close()


def _load_tokens(archive: zipfile.ZipFile, member: str) -> dict[str, dict[str, Any]]:
    tokens: dict[str, dict[str, Any]] = {}
    for row in _dict_reader(archive, member):
        session_id = (row.get("session_id") or "").strip()
        if not session_id:
            continue
        token_data = _clean_row(row)
        token_data["used"] = _parse_bool(row.get("used"))
        tokens[session_id] = token_data
    return tokens


def _load_sessions(
    archive: zipfile.ZipFile,
    member: str,
    tokens: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}
    for row in _dict_reader(archive, member):
        session_id = (row.get("session_id") or "").strip()
        if not session_id:
            continue

        if session_id not in sessions:
            metadata = _clean_row({key: row.get(key) for key in SESSION_COLUMNS})
            if session_id in tokens:
                metadata["token"] = tokens[session_id]
            sessions[session_id] = {"session": metadata, "messages": []}

        message_id = (row.get("message_id") or "").strip()
        if not message_id:
            continue

        message = _clean_row({key: row.get(key) for key in MESSAGE_COLUMNS})
        message["timestamp"] = message.pop("sent_at", None)
        message["reported"] = _parse_bool(row.get("reported"))
        message["is_incivil"] = _parse_bool(row.get("is_incivil"))
        message["is_like_minded"] = _parse_bool(row.get("is_like_minded"))
        sessions[session_id]["messages"].append(message)

    return sessions


def _parse_event(row: dict[str, str]) -> dict[str, Any]:
    data_raw = row.get("data_json") or ""
    try:
        data = json.loads(data_raw) if data_raw else {}
    except json.JSONDecodeError:
        data = {"unparsed_data": data_raw}

    event = {
        "id": row.get("event_id"),
        "session_id": row.get("session_id"),
        "type": row.get("event_type"),
        "timestamp": row.get("occurred_at"),
        "data": data,
    }
    optional_fields = {
        "client_at": row.get("client_at"),
        "compose_ms": row.get("compose_ms"),
        "keystrokes": row.get("keystrokes"),
        "backspaces": row.get("backspaces"),
        "char_count": row.get("char_count"),
        "pasted": _parse_bool(row.get("pasted")),
        "is_visible": _parse_bool(row.get("is_visible")),
        "had_mouse_move": _parse_bool(row.get("had_mouse_move")),
        "had_keyboard": _parse_bool(row.get("had_keyboard")),
    }
    event.update({key: value for key, value in optional_fields.items() if value not in (None, "")})
    return event


def _duration_minutes(started_at: Any, ended_at: Any) -> float | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
        return round((end - start).total_seconds() / 60, 2)
    except (TypeError, ValueError):
        return None


def _percentage(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(100 * numerator / denominator, 2)


def _event_count(counts: Counter[str], *names: str) -> int:
    return sum(counts.get(name, 0) for name in names)


def _enrich_messages(messages: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    supplements: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "message":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        message_id = str(data.get("message_id") or data.get("id") or "")
        if message_id:
            supplements[message_id] = data

    supplemental_keys = (
        "quoted_text",
        "mentions",
        "liked_by",
        "likes_count",
        "reactions",
        "msg_type",
        "headline",
        "source",
        "body",
    )
    for message in messages:
        extra = supplements.get(str(message.get("message_id") or ""))
        if not extra:
            continue
        for key in supplemental_keys:
            if key in extra and key not in message:
                message[key] = extra[key]


def _build_index_row(
    payload: dict[str, Any],
    events: list[dict[str, Any]],
    json_file: str,
) -> dict[str, Any]:
    session = payload["session"]
    messages = payload["messages"]
    event_counts = Counter(str(event.get("type") or "") for event in events)
    classified = [message for message in messages if message.get("is_incivil") is not None]
    incivil = sum(message.get("is_incivil") is True for message in classified)
    like_classified = [
        message for message in messages if message.get("is_like_minded") is not None
    ]
    like_minded = sum(message.get("is_like_minded") is True for message in like_classified)

    safety_events = sum(
        count
        for event_type, count in event_counts.items()
        if "safety" in event_type.lower() or "concern" in event_type.lower()
    )
    return {
        "experiment_id": session.get("experiment_id"),
        "session_id": session.get("session_id"),
        "treatment_group": session.get("treatment_group"),
        "session_status": session.get("session_status"),
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "actual_duration_minutes": _duration_minutes(
            session.get("started_at"), session.get("ended_at")
        ),
        "end_reason": session.get("end_reason"),
        "configured_duration_minutes": session.get("session_duration_minutes"),
        "messages_per_minute": session.get("messages_per_minute"),
        "total_messages": len(messages),
        "classified_messages": len(classified),
        "incivil_messages": incivil,
        "incivil_percent": _percentage(incivil, len(classified)),
        "like_minded_messages": like_minded,
        "like_minded_percent": _percentage(like_minded, len(like_classified)),
        "reported_messages": sum(message.get("reported") is True for message in messages),
        "message_like_events": _event_count(event_counts, "message_like", "like"),
        "message_reaction_events": _event_count(event_counts, "message_reaction", "reaction"),
        "message_report_events": _event_count(event_counts, "message_report", "report"),
        "user_block_events": _event_count(event_counts, "user_block", "block"),
        "llm_call_events": _event_count(event_counts, "llm_call"),
        "error_events": _event_count(event_counts, "error"),
        "safety_events": safety_events,
        "compose_events": sum(
            count for name, count in event_counts.items() if "compose" in name.lower()
        ),
        "tab_hidden_events": _event_count(event_counts, "tab_hidden", "visibility_hidden"),
        "idle_prompt_events": sum(
            count for name, count in event_counts.items() if "idle" in name.lower()
        ),
        "exit_attempt_events": sum(
            count for name, count in event_counts.items() if "exit" in name.lower()
        ),
        "total_events": len(events),
        "json_file": json_file,
    }


def _write_session(
    output_dir: Path,
    payload: dict[str, Any],
    events: list[dict[str, Any]],
    pretty: bool,
) -> dict[str, Any]:
    session_id = str(payload["session"].get("session_id") or "unknown-session")
    _enrich_messages(payload["messages"], events)
    payload["events"] = events
    relative_path = Path("sessions") / f"{_safe_filename(session_id)}.json"
    destination = output_dir / relative_path
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
        handle.write("\n")
    return _build_index_row(payload, events, relative_path.as_posix())


def convert_export(source_zip: Path, output_dir: Path, pretty: bool = False) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. Choose a new directory."
        )
    (output_dir / "sessions").mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source_zip, "r") as archive:
        session_member = _find_member(archive, "sessions_and_messages.csv")
        event_member = _find_member(archive, "events.csv")
        token_member = _find_member(archive, "tokens.csv")

        tokens = _load_tokens(archive, token_member)
        sessions = _load_sessions(archive, session_member, tokens)
        print(f"Loaded metadata and messages for {len(sessions)} sessions.", flush=True)

        index_rows: list[dict[str, Any]] = []
        total_events = 0
        current_session_id: str | None = None
        current_events: list[dict[str, Any]] = []

        def flush_current() -> None:
            nonlocal current_session_id, current_events
            if current_session_id is None:
                return
            payload = sessions.pop(
                current_session_id,
                {"session": {"session_id": current_session_id}, "messages": []},
            )
            index_rows.append(
                _write_session(output_dir, payload, current_events, pretty)
            )
            current_events = []

        for row_number, row in enumerate(_dict_reader(archive, event_member), start=1):
            session_id = (row.get("session_id") or "").strip() or "unknown-session"
            if current_session_id is None:
                current_session_id = session_id
            elif session_id != current_session_id:
                flush_current()
                current_session_id = session_id
            current_events.append(_parse_event(row))
            total_events += 1
            if row_number % 10_000 == 0:
                print(f"Processed {row_number:,} event rows...", flush=True)

        flush_current()

    for session_id in sorted(sessions):
        index_rows.append(_write_session(output_dir, sessions[session_id], [], pretty))

    index_rows.sort(key=lambda row: (str(row.get("started_at") or ""), str(row["session_id"])))
    with (output_dir / "session_index.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(index_rows)

    total_messages = sum(int(row["total_messages"]) for row in index_rows)
    summary = {
        "source_zip": str(source_zip.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_count": len(index_rows),
        "message_count": total_messages,
        "event_count": total_events,
        "pretty_json": pretty,
        "outputs": {
            "sessions": "sessions/",
            "session_index": "session_index.csv",
        },
        "processing_note": "Created locally without sending conversation data to an external service.",
    }
    with (output_dir / "conversion_summary.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one JSON per session plus an Excel-friendly session index."
    )
    parser.add_argument("source_zip", type=Path, help="Platform experiment export ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: <ZIP name>_processed beside the ZIP)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Indent JSON files for manual reading (uses more disk space)",
    )
    args = parser.parse_args()

    source_zip = args.source_zip.expanduser().resolve()
    if not source_zip.is_file():
        parser.error(f"ZIP file not found: {source_zip}")
    output_dir = (
        args.output.expanduser().resolve()
        if args.output
        else source_zip.with_name(f"{source_zip.stem}_processed")
    )

    _raise_csv_field_limit()
    try:
        summary = convert_export(source_zip, output_dir, pretty=args.pretty)
    except (FileExistsError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: {summary['session_count']} sessions, "
        f"{summary['message_count']} messages and {summary['event_count']} events.",
        flush=True,
    )
    print(f"Output: {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
