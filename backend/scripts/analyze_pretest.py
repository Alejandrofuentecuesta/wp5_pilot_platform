#!/usr/bin/env python3
"""Create a local, aggregate pre-test audit from survey and platform exports.

Raw messages and open-text survey answers are never written to the report. The
participant-level CSV contains identifiers and derived metrics, but no message
content or open comments.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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


SURVEY_OUTCOMES = ("QD22", "QD23", "QE6")
ISSUE_FIELDS = ("session_id", "participant_id", "severity", "issue", "value")


def _csv_limit() -> None:
    limit = sys.maxsize
    while limit:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _rows_by_header(sheet: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
    iterator = sheet.iter_rows(values_only=True)
    headers = [str(value or "") for value in next(iterator)]
    return headers, list(iterator)


def _row_dict(headers: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {headers[index]: row[index] for index in range(min(len(headers), len(row)))}


def _load_survey(path: Path) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    data_headers, data_rows = _rows_by_header(workbook["Datos"])
    label_headers, label_rows = _rows_by_header(workbook["Labels"])
    if data_headers != label_headers or len(data_rows) != len(label_rows):
        raise ValueError("Datos and Labels sheets do not have the same structure.")

    output: list[dict[str, Any]] = []
    for raw_row, label_row in zip(data_rows, label_rows):
        raw = _row_dict(data_headers, raw_row)
        labels = _row_dict(label_headers, label_row)
        token = str(raw.get("key") or "").strip()
        if not token:
            continue
        output.append({"token": token, "raw": raw, "labels": labels})
    return output


def _find_zip_member(archive: zipfile.ZipFile, filename: str) -> str:
    matches = [name for name in archive.namelist() if PurePosixPath(name).name == filename]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {filename} in the experiment ZIP.")
    return matches[0]


def _load_tokens(path: Path) -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(path, "r") as archive:
        member = _find_zip_member(archive, "tokens.csv")
        with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig") as handle:
            return {
                str(row.get("token") or "").strip(): row
                for row in csv.DictReader(handle)
                if str(row.get("token") or "").strip()
            }


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_minutes(session: dict[str, Any]) -> float | None:
    start = _parse_iso(session.get("started_at"))
    end = _parse_iso(session.get("ended_at"))
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 60, 2)


def _performer_profiles(events: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for event in events:
        if event.get("type") != "llm_call":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        name = str(data.get("agent_name") or "")
        if not name or name.startswith("__"):
            continue
        prompt = str(data.get("prompt") or "")
        stance = re.search(r"\*\*Topic stance\*\*:\s*([a-z_]+)", prompt, re.I)
        incivility = re.search(r"\*\*Incivility\*\*:\s*([a-z_]+)", prompt, re.I)
        if stance or incivility:
            profiles[name] = {
                "stance": stance.group(1).lower() if stance else "",
                "incivility": incivility.group(1).lower() if incivility else "",
            }
    return profiles


def _target_rates(group: str) -> tuple[int | None, int | None]:
    if group.startswith("not_incivil_"):
        incivility = 20
    elif group.startswith("incivil_"):
        incivility = 80
    elif group.startswith("mix_"):
        incivility = 50
    else:
        incivility = None

    if group.endswith("_not_like_minded"):
        like_minded = 20
    elif group.endswith("_like_minded"):
        like_minded = 80
    elif group.endswith("_mix"):
        like_minded = 50
    else:
        like_minded = None
    return incivility, like_minded


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def _participant_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _analyse_session(
    survey: dict[str, Any], token_row: dict[str, str], session_json: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(session_json.read_text(encoding="utf-8"))
    session = payload.get("session") or {}
    events = payload.get("events") or []
    profiles = _performer_profiles(events)
    counts = Counter(str(event.get("type") or "") for event in events)
    errors = Counter()
    participant_message_ids: set[str] = set()
    agent_messages = 0
    agent_uncivil = 0
    agent_same_side = 0
    agent_replies = 0
    stance = ""

    start_event = next((event for event in events if event.get("type") == "session_start"), None)
    if start_event and isinstance(start_event.get("data"), dict):
        stance = str(start_event["data"].get("participant_stance_hint") or "")

    for event in events:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        event_type = event.get("type")
        if event_type == "error":
            errors[str(data.get("error_type") or "unknown")] += 1
        elif event_type == "participant_safety_classification":
            message_id = str(data.get("message_id") or "")
            if message_id:
                participant_message_ids.add(message_id)
        elif event_type == "message":
            profile = profiles.get(str(data.get("sender") or ""))
            if not profile:
                continue
            agent_messages += 1
            agent_uncivil += int(profile.get("incivility") == "uncivil")
            agent_same_side += int(profile.get("stance") == stance)
            agent_replies += int(bool(data.get("reply_to")))

    group = str(session.get("treatment_group") or token_row.get("treatment_group") or "")
    target_incivility, target_like_minded = _target_rates(group)
    actual_incivility = _pct(agent_uncivil, agent_messages)
    actual_like_minded = _pct(agent_same_side, agent_messages)
    participant = _participant_id(survey["token"])
    labels = survey["labels"]
    comment = str(labels.get("COMENTARIO_EXPERIMENTO") or "").strip()

    row = {
        "participant_id": participant,
        "session_id": session.get("session_id") or token_row.get("session_id"),
        "survey_status": labels.get("status"),
        "session_status": session.get("session_status"),
        "end_reason": session.get("end_reason"),
        "treatment_group": group,
        "participant_stance": stance,
        "duration_minutes": _duration_minutes(session),
        "participant_messages": len(participant_message_ids),
        "agent_messages": agent_messages,
        "agent_replies": agent_replies,
        "likes": counts.get("message_like", 0),
        "reactions": counts.get("message_reaction", 0),
        "reports": counts.get("message_report", 0),
        "blocks": counts.get("user_block", 0),
        "exit_attempts": counts.get("client_exit_attempt", 0),
        "exit_surveys": counts.get("exit_survey", 0),
        "idle_prompts": counts.get("client_idle_prompt_shown", 0),
        "tab_hidden_events": counts.get("client_tab_hidden", 0),
        "all_logged_errors": sum(errors.values()),
        "director_action_failed": errors.get("director_action_failed", 0),
        "director_unknown_label": errors.get("director_action_unknown_performer_label", 0),
        "performer_retries_exhausted": errors.get("performer_retries_exhausted", 0),
        "performer_output_truncated": errors.get("performer_output_truncated", 0),
        "safety_classifier_errors": sum(
            1
            for event in events
            if event.get("type") == "llm_call"
            and isinstance(event.get("data"), dict)
            and event["data"].get("error")
            and str(event["data"].get("agent_name") or "")
            in {"__participant_safety_classifier__", "__safety__"}
        ),
        "target_incivility_pct": target_incivility,
        "actual_incivility_pct": actual_incivility,
        "target_like_minded_pct": target_like_minded,
        "actual_like_minded_pct": actual_like_minded,
        "perceived_others": labels.get("QD22"),
        "perceived_composition": labels.get("QD23"),
        "relative_incivility": labels.get("QE6"),
        "has_open_comment": bool(comment and comment.lower() not in {"no", "ninguno", "ninguna"}),
    }

    issues: list[dict[str, Any]] = []

    def add(severity: str, issue: str, value: Any) -> None:
        issues.append(
            {
                "session_id": row["session_id"],
                "participant_id": participant,
                "severity": severity,
                "issue": issue,
                "value": value,
            }
        )

    if row["session_status"] != "ended" or row["end_reason"] != "duration_expired":
        add("high", "session_not_completed_normally", f"{row['session_status']} / {row['end_reason']}")
    if row["participant_messages"] == 0:
        add("high", "no_participant_messages", 0)
    elif row["participant_messages"] < 3:
        add("medium", "low_participant_messages", row["participant_messages"])
    if row["agent_messages"] < 15:
        add("high", "low_agent_message_count", row["agent_messages"])
    if (row["duration_minutes"] or 0) > 30:
        add("medium", "wall_clock_duration_over_30_minutes", row["duration_minutes"])
    if row["director_action_failed"] >= 3:
        add("medium", "repeated_director_action_failures", row["director_action_failed"])
    if row["performer_retries_exhausted"]:
        add("high", "performer_retries_exhausted", row["performer_retries_exhausted"])
    if row["performer_output_truncated"]:
        add("medium", "performer_output_truncated", row["performer_output_truncated"])
    if row["safety_classifier_errors"]:
        add("high", "safety_classifier_error", row["safety_classifier_errors"])
    return row, issues


def _distribution(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts = Counter(str(row.get(field) or "Missing") for row in rows)
    total = sum(counts.values())
    return [
        {"variable": field, "response": response, "count": count, "percent": round(100 * count / total, 1)}
        for response, count in counts.most_common()
    ]


def _numeric_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = sorted(float(row[field]) for row in rows if row.get(field) not in (None, ""))
    if not values:
        return {}
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "mean": round(statistics.mean(values), 2),
        "max": round(max(values), 2),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _fidelity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["treatment_group"])].append(row)
    output = []
    for group, group_rows in sorted(grouped.items()):
        agent_messages = sum(int(row["agent_messages"]) for row in group_rows)
        incivility_weighted = sum(
            float(row["actual_incivility_pct"] or 0) * int(row["agent_messages"])
            for row in group_rows
        )
        like_weighted = sum(
            float(row["actual_like_minded_pct"] or 0) * int(row["agent_messages"])
            for row in group_rows
        )
        target_incivility, target_like = _target_rates(group)
        actual_incivility = round(incivility_weighted / agent_messages, 1) if agent_messages else None
        actual_like = round(like_weighted / agent_messages, 1) if agent_messages else None
        output.append(
            {
                "treatment_group": group,
                "sessions": len(group_rows),
                "agent_messages": agent_messages,
                "target_incivility_pct": target_incivility,
                "actual_incivility_pct": actual_incivility,
                "incivility_gap_points": round(actual_incivility - target_incivility, 1)
                if actual_incivility is not None and target_incivility is not None
                else None,
                "target_like_minded_pct": target_like,
                "actual_like_minded_pct": actual_like,
                "like_minded_gap_points": round(actual_like - target_like, 1)
                if actual_like is not None and target_like is not None
                else None,
            }
        )
    return output


def _report_markdown(summary: dict[str, Any], fidelity: list[dict[str, Any]]) -> str:
    lines = [
        "# Pre-test audit",
        "",
        "This report contains aggregate metrics only. Raw messages and open-text answers were not included.",
        "",
        "## Coverage",
        "",
        f"- Survey rows: {summary['survey_rows']}",
        f"- Survey rows linked to a platform session: {summary['linked_sessions']}",
        f"- Platform sessions excluded because they had no survey match: {summary['unlinked_platform_sessions']}",
        f"- Normally completed linked sessions: {summary['normally_completed_sessions']}",
        "",
        "## Participation",
        "",
        f"- Participant messages per session: median {summary['participant_messages']['median']}, mean {summary['participant_messages']['mean']}.",
        f"- Agent messages per session: median {summary['agent_messages']['median']}, mean {summary['agent_messages']['mean']}.",
        f"- Sessions with an exit attempt: {summary['sessions_with_exit_attempt']}.",
        f"- Sessions with no participant messages: {summary['sessions_with_no_participant_messages']}.",
        "",
        "## Treatment fidelity",
        "",
        "| Group | n | Incivility target | Incivility actual | Like-minded target | Like-minded actual |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in fidelity:
        lines.append(
            f"| {row['treatment_group']} | {row['sessions']} | {row['target_incivility_pct']}% | "
            f"{row['actual_incivility_pct']}% | {row['target_like_minded_pct']}% | "
            f"{row['actual_like_minded_pct']}% |"
        )
    lines.extend(
        [
            "",
            "## Automated review",
            "",
            f"- High-severity flags: {summary['issue_counts'].get('high', 0)}.",
            f"- Medium-severity flags: {summary['issue_counts'].get('medium', 0)}.",
            "- See `session_issues.csv` for the affected session IDs and reasons.",
            "- Logged `error` events include normalisation and retry telemetry; they should not all be treated as failures.",
            "",
            "## Survey impressions",
            "",
        ]
    )
    for variable, distribution in summary["survey_outcomes"].items():
        lines.append(f"### {variable}")
        lines.append("")
        for item in distribution:
            lines.append(f"- {item['response']}: {item['count']} ({item['percent']}%)")
        lines.append("")
    return "\n".join(lines)


def analyse(survey_xlsx: Path, experiment_zip: Path, sessions_dir: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    survey_rows = _load_survey(survey_xlsx)
    token_rows = _load_tokens(experiment_zip)
    platform_files = list(sessions_dir.glob("*.json"))
    participant_rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    missing_links = 0

    for survey in survey_rows:
        token_row = token_rows.get(survey["token"])
        if not token_row or not token_row.get("session_id"):
            missing_links += 1
            continue
        session_path = sessions_dir / f"{token_row['session_id']}.json"
        if not session_path.exists():
            missing_links += 1
            continue
        row, row_issues = _analyse_session(survey, token_row, session_path)
        participant_rows.append(row)
        issues.extend(row_issues)

    fidelity = _fidelity(participant_rows)
    survey_distributions = [
        item for field in SURVEY_OUTCOMES for item in _distribution(participant_rows, {
            "QD22": "perceived_others",
            "QD23": "perceived_composition",
            "QE6": "relative_incivility",
        }[field])
    ]
    issue_counts = Counter(issue["severity"] for issue in issues)
    summary = {
        "survey_rows": len(survey_rows),
        "linked_sessions": len(participant_rows),
        "missing_survey_session_links": missing_links,
        "platform_sessions": len(platform_files),
        "unlinked_platform_sessions": len(platform_files) - len(participant_rows),
        "normally_completed_sessions": sum(
            row["session_status"] == "ended" and row["end_reason"] == "duration_expired"
            for row in participant_rows
        ),
        "treatment_group_counts": dict(Counter(row["treatment_group"] for row in participant_rows)),
        "duration_minutes": _numeric_summary(participant_rows, "duration_minutes"),
        "participant_messages": _numeric_summary(participant_rows, "participant_messages"),
        "agent_messages": _numeric_summary(participant_rows, "agent_messages"),
        "sessions_with_exit_attempt": sum(row["exit_attempts"] > 0 for row in participant_rows),
        "sessions_with_no_participant_messages": sum(
            row["participant_messages"] == 0 for row in participant_rows
        ),
        "issue_counts": dict(issue_counts),
        "survey_outcomes": {
            "QD22 perceived people/AI": _distribution(participant_rows, "perceived_others"),
            "QD23 perceived composition": _distribution(participant_rows, "perceived_composition"),
            "QE6 relative incivility": _distribution(participant_rows, "relative_incivility"),
        },
        "privacy_note": "Raw messages, prompts, model responses, tokens and open-text answers are excluded.",
    }

    participant_fields = list(participant_rows[0]) if participant_rows else []
    fidelity_fields = list(fidelity[0]) if fidelity else []
    _write_csv(output_dir / "participant_sessions.csv", participant_rows, participant_fields)
    _write_csv(output_dir / "session_issues.csv", issues, ISSUE_FIELDS)
    _write_csv(output_dir / "treatment_fidelity.csv", fidelity, fidelity_fields)
    _write_csv(
        output_dir / "survey_distributions.csv",
        survey_distributions,
        ("variable", "response", "count", "percent"),
    )
    (output_dir / "pretest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "pretest_report.md").write_text(
        _report_markdown(summary, fidelity) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local aggregate pre-test audit.")
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
