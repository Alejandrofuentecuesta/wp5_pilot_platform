#!/usr/bin/env python3
"""Summarise behavioural and survey outcomes for every pre-test session."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import openpyxl


def _csv_limit() -> None:
    limit = sys.maxsize
    while limit:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _zip_member(archive: zipfile.ZipFile, filename: str) -> str:
    matches = [name for name in archive.namelist() if PurePosixPath(name).name == filename]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {filename} in the experiment ZIP.")
    return matches[0]


def _token_sessions(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path, "r") as archive:
        member = _zip_member(archive, "tokens.csv")
        with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig") as handle:
            return {
                str(row.get("token") or "").strip(): str(row.get("session_id") or "").strip()
                for row in csv.DictReader(handle)
                if str(row.get("token") or "").strip()
            }


def _sheet_rows(sheet: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
    iterator = sheet.iter_rows(values_only=True)
    return [str(value or "") for value in next(iterator)], list(iterator)


def _survey_comments(
    survey_path: Path, token_sessions: dict[str, str]
) -> tuple[dict[str, list[str]], set[str]]:
    workbook = openpyxl.load_workbook(survey_path, read_only=True, data_only=True)
    headers, rows = _sheet_rows(workbook["Labels"])
    positions = {header: index for index, header in enumerate(headers)}
    output: dict[str, list[str]] = defaultdict(list)
    linked_session_ids: set[str] = set()
    ignored = {"", "no", "no.", "nada", "ninguno", "ninguna", "n/a", "na", "-", "...."}
    for row in rows:
        token = str(row[positions["key"]] or "").strip()
        session_id = token_sessions.get(token, "")
        if not session_id:
            continue
        linked_session_ids.add(session_id)
        for field in ("QB25", "COMENTARIO_EXPERIMENTO"):
            text = str(row[positions[field]] or "").strip()
            if text.lower() not in ignored:
                output[session_id].append(text)
    return output, linked_session_ids


def _factor_levels(group: str) -> tuple[str, str]:
    if group.startswith("not_incivil_"):
        incivility = "low"
    elif group.startswith("incivil_"):
        incivility = "high"
    else:
        incivility = "mix"

    if group.endswith("_not_like_minded"):
        like_minded = "low"
    elif group.endswith("_like_minded"):
        like_minded = "high"
    else:
        like_minded = "mix"
    return incivility, like_minded


def _profiles(events: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for event in events:
        if event.get("type") != "llm_call":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        name = str(data.get("agent_name") or "")
        prompt = str(data.get("prompt") or "")
        if name and not name.startswith("__") and "**Topic stance**:" in prompt:
            names.add(name)
    return names


def _minutes(session: dict[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(str(session.get("started_at") or "").replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(session.get("ended_at") or "").replace("Z", "+00:00"))
        return round((end - start).total_seconds() / 60, 2)
    except ValueError:
        return None


def _comment_themes(comments: list[str]) -> set[str]:
    text = " ".join(comments).lower()
    patterns = {
        "positive_or_interesting": r"gust|interes|entreten|original|genial|excelente|buena|encant|curios|sorprend|parec.a real",
        "ai_or_realism": r"\bia\b|\bbot|personas reales|human[oa]|nombres|\bnick\b|parec.a real",
        "repetition": r"repet",
        "latency_or_technical": r"tard|lent|no contestan|no habla nadie|a nuestro nombre",
        "hostility_or_discomfort": r"rabia|hostil|insult|ofend|atac|inc.mod",
        "negative_overall": r"no me ha gustado|\bmala\b|no merece|mejorad la ia|pero asi no",
    }
    return {theme for theme, pattern in patterns.items() if re.search(pattern, text, re.I)}


def _session_row(path: Path, survey_comments: dict[str, list[str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    session = payload.get("session") or {}
    events = payload.get("events") or []
    session_id = str(session.get("session_id") or path.stem)
    group = str(session.get("treatment_group") or "missing")
    incivility, like_minded = _factor_levels(group)
    agent_names = _profiles(events)
    participant_ids: set[str] = set()
    agent_messages = 0
    liked = 0
    unliked = 0
    report_count = 0
    block_count = 0
    impression_reached = False
    tempted_report: bool | None = None
    tempted_block: bool | None = None
    emotion_triggered = False
    emotion_responded = False
    emotion_rows: list[dict[str, Any]] = []
    exit_reason = ""

    for event in events:
        event_type = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event_type == "participant_safety_classification":
            message_id = str(data.get("message_id") or "")
            if message_id:
                participant_ids.add(message_id)
        elif event_type == "message":
            agent_messages += int(str(data.get("sender") or "") in agent_names)
        elif event_type == "message_like":
            liked += int(data.get("action") == "liked")
            unliked += int(data.get("action") == "unliked")
        elif event_type == "message_report":
            report_count += 1
        elif event_type == "user_block":
            block_count += 1
        elif event_type == "agent_impressions":
            impression_reached = True
            survey = data.get("report_block_survey") or {}
            tempted_report = bool(survey.get("tempted_to_report"))
            tempted_block = bool(survey.get("tempted_to_block"))
        elif event_type == "emotions_checkup_trigger":
            emotion_triggered = True
        elif event_type == "emotions_checkup_response":
            emotion_responded = True
            for emotion in data.get("emotions") or []:
                if not isinstance(emotion, dict):
                    continue
                emotion_rows.append(
                    {
                        "session_id": session_id,
                        "treatment_group": group,
                        "incivility_level": incivility,
                        "like_minded_level": like_minded,
                        "emotion": str(emotion.get("emotion") or "Missing"),
                        "intensity": emotion.get("intensity"),
                    }
                )
        elif event_type == "exit_survey":
            exit_reason = str(data.get("reason") or "")

    comments = survey_comments.get(session_id, [])
    themes = _comment_themes(comments)
    end_reason = str(session.get("end_reason") or "missing")
    row = {
        "session_id": session_id,
        "treatment_group": group,
        "incivility_level": incivility,
        "like_minded_level": like_minded,
        "session_status": session.get("session_status"),
        "end_reason": end_reason,
        "chat_completed": end_reason == "duration_expired",
        "survey_linked": bool(comments or session.get("token")),
        "duration_minutes": _minutes(session),
        "participant_messages": len(participant_ids),
        "agent_messages": agent_messages,
        "user_exit": end_reason == "user_exit",
        "exit_reason": exit_reason,
        "report_count": report_count,
        "reported_any": report_count > 0,
        "block_count": block_count,
        "blocked_any": block_count > 0,
        "like_actions": liked,
        "unlike_actions": unliked,
        "net_likes": liked - unliked,
        "liked_any": liked > 0,
        "impression_reached": impression_reached,
        "tempted_report": tempted_report,
        "tempted_block": tempted_block,
        "emotion_triggered": emotion_triggered,
        "emotion_responded": emotion_responded,
        "meaningful_comment": bool(comments),
        "comment_themes": "|".join(sorted(themes)),
    }
    return row, emotion_rows


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if row.get(field) not in (None, "")]
    return round(statistics.mean(values), 2) if values else 0.0


def _median(rows: list[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows if row.get(field) not in (None, "")]
    return round(statistics.median(values), 2) if values else 0.0


def _rate(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def _aggregate(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[field])].append(row)
    output = []
    for group, group_rows in sorted(grouped.items()):
        n = len(group_rows)
        impression_rows = [row for row in group_rows if row["impression_reached"]]
        comment_eligible = [row for row in group_rows if row["survey_linked"]]
        output.append(
            {
                field: group,
                "sessions": n,
                "chat_completed_n": sum(row["chat_completed"] for row in group_rows),
                "chat_completed_pct": _rate(sum(row["chat_completed"] for row in group_rows), n),
                "user_exit_n": sum(row["user_exit"] for row in group_rows),
                "user_exit_pct": _rate(sum(row["user_exit"] for row in group_rows), n),
                "other_incomplete_n": sum(not row["chat_completed"] and not row["user_exit"] for row in group_rows),
                "participant_messages_mean": _mean(group_rows, "participant_messages"),
                "participant_messages_median": _median(group_rows, "participant_messages"),
                "reported_any_n": sum(row["reported_any"] for row in group_rows),
                "reported_any_pct": _rate(sum(row["reported_any"] for row in group_rows), n),
                "blocked_any_n": sum(row["blocked_any"] for row in group_rows),
                "blocked_any_pct": _rate(sum(row["blocked_any"] for row in group_rows), n),
                "liked_any_n": sum(row["liked_any"] for row in group_rows),
                "liked_any_pct": _rate(sum(row["liked_any"] for row in group_rows), n),
                "net_likes_mean": _mean(group_rows, "net_likes"),
                "temptation_answered_n": len(impression_rows),
                "tempted_report_n": sum(row["tempted_report"] is True for row in impression_rows),
                "tempted_report_pct": _rate(sum(row["tempted_report"] is True for row in impression_rows), len(impression_rows)),
                "tempted_block_n": sum(row["tempted_block"] is True for row in impression_rows),
                "tempted_block_pct": _rate(sum(row["tempted_block"] is True for row in impression_rows), len(impression_rows)),
                "emotion_triggered_n": sum(row["emotion_triggered"] for row in group_rows),
                "emotion_responded_n": sum(row["emotion_responded"] for row in group_rows),
                "emotion_responded_pct": _rate(sum(row["emotion_responded"] for row in group_rows), n),
                "survey_comment_eligible_n": len(comment_eligible),
                "meaningful_comment_n": sum(row["meaningful_comment"] for row in comment_eligible),
                "meaningful_comment_pct": _rate(sum(row["meaningful_comment"] for row in comment_eligible), len(comment_eligible)),
            }
        )
    return output


def _emotion_distribution(emotions: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    response_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in sessions:
        if not row["emotion_responded"]:
            continue
        for group_field in ("treatment_group", "incivility_level", "like_minded_level"):
            response_counts[(group_field, str(row[group_field]))] += 1

    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in emotions:
        emotion = str(row["emotion"])
        for group_field in ("treatment_group", "incivility_level", "like_minded_level"):
            key = (group_field, str(row[group_field]), emotion)
            if row.get("intensity") not in (None, ""):
                grouped[key].append(float(row["intensity"]))

    output = []
    for (group_field, group, emotion), intensities in sorted(grouped.items()):
        responses = response_counts[(group_field, group)]
        output.append(
            {
                "grouping": group_field,
                "group": group,
                "emotion": emotion,
                "selected_n": len(intensities),
                "respondents_n": responses,
                "selected_pct_of_respondents": _rate(len(intensities), responses),
                "mean_intensity": round(statistics.mean(intensities), 2) if intensities else None,
            }
        )
    return output


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _exit_reasons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(row["exit_reason"] or "No reason recorded" for row in rows if row["user_exit"])
    total = sum(counter.values())
    return [
        {"reason": reason, "count": count, "percent_of_user_exits": _rate(count, total)}
        for reason, count in counter.most_common()
    ]


def _comment_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for grouping in ("treatment_group", "incivility_level", "like_minded_level"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["survey_linked"]:
                groups[str(row[grouping])].append(row)
        for group, group_rows in sorted(groups.items()):
            theme_counts = Counter(
                theme
                for row in group_rows
                for theme in str(row["comment_themes"] or "").split("|")
                if theme
            )
            for theme, count in theme_counts.items():
                output.append(
                    {
                        "grouping": grouping,
                        "group": group,
                        "theme": theme,
                        "sessions_with_theme": count,
                        "survey_linked_sessions": len(group_rows),
                        "percent": _rate(count, len(group_rows)),
                    }
                )
    return output


def analyse(survey: Path, experiment_zip: Path, sessions_dir: Path, output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    token_sessions = _token_sessions(experiment_zip)
    comments, linked_session_ids = _survey_comments(survey, token_sessions)

    rows: list[dict[str, Any]] = []
    emotions: list[dict[str, Any]] = []
    for path in sessions_dir.glob("*.json"):
        row, session_emotions = _session_row(path, comments)
        row["survey_linked"] = row["session_id"] in linked_session_ids
        rows.append(row)
        emotions.extend(session_emotions)

    rows.sort(key=lambda row: str(row["session_id"]))
    by_treatment = _aggregate(rows, "treatment_group")
    by_incivility = _aggregate(rows, "incivility_level")
    by_like_minded = _aggregate(rows, "like_minded_level")
    emotion_distribution = _emotion_distribution(emotions, rows)
    exit_reasons = _exit_reasons(rows)
    comment_summary = _comment_summary(rows)

    _write_csv(output / "all_session_outcomes.csv", rows)
    _write_csv(output / "outcomes_by_treatment.csv", by_treatment)
    _write_csv(output / "outcomes_by_incivility.csv", by_incivility)
    _write_csv(output / "outcomes_by_like_mindedness.csv", by_like_minded)
    _write_csv(output / "emotion_distribution.csv", emotion_distribution)
    _write_csv(output / "exit_reasons.csv", exit_reasons)
    _write_csv(output / "comment_themes.csv", comment_summary)

    end_reasons = Counter(str(row["end_reason"]) for row in rows)
    summary = {
        "sessions": len(rows),
        "chat_completed": sum(row["chat_completed"] for row in rows),
        "survey_linked": sum(row["survey_linked"] for row in rows),
        "end_reasons": dict(end_reasons),
        "emotion_responses": sum(row["emotion_responded"] for row in rows),
        "impression_responses": sum(row["impression_reached"] for row in rows),
        "privacy_note": "No raw messages, prompts, tokens, open comments or emotion explanations are included.",
    }
    (output / "outcomes_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse outcomes for complete and incomplete sessions.")
    parser.add_argument("survey_xlsx", type=Path)
    parser.add_argument("experiment_zip", type=Path)
    parser.add_argument("sessions_dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    _csv_limit()
    try:
        summary = analyse(
            args.survey_xlsx.resolve(),
            args.experiment_zip.resolve(),
            args.sessions_dir.resolve(),
            args.output.resolve(),
        )
    except (FileExistsError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
