"""Reusable CSV/bundle builders for researcher data exports.

These helpers return CSV *text* (str) so they can be streamed directly by an
endpoint or bundled into a single ZIP by the "download everything" export.
Keeping the builders here (rather than inline in each route) gives every export
path one source of truth for column layout.
"""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import asyncpg

from db.repositories import message_repo, session_repo


def _as_dict(value: Any) -> dict:
    """Normalise a JSONB column that may arrive as dict or str."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _message_from_row(row: Any) -> dict:
    """Normalise a raw message DB row to the public session-export shape."""
    item = dict(row)
    liked_by = list(item.get("liked_by") or [])
    message = {
        "message_id": str(item["message_id"]),
        "sender": item["sender"],
        "content": item["content"],
        "timestamp": item["sent_at"].isoformat(),
        "reply_to": str(item["reply_to"]) if item.get("reply_to") else None,
        "quoted_text": item.get("quoted_text"),
        "mentions": list(item["mentions"]) if item.get("mentions") else None,
        "likes_count": len(liked_by),
        "liked_by": liked_by,
        "reported": item.get("reported", False),
        "is_incivil": item.get("is_incivil"),
        "is_like_minded": item.get("is_like_minded"),
        "inferred_participant_stance": item.get("inferred_participant_stance"),
        "classification_rationale": item.get("classification_rationale"),
    }
    metadata = _as_dict(item.get("metadata"))
    if metadata:
        message.update(metadata)
    return message


def _manual_evaluation_from_row(row: Any) -> dict:
    item = dict(row)
    return {
        "incivility": bool(item["incivility"]),
        "hate_speech": bool(item["hate_speech"]),
        "threats_to_dem_freedom": bool(item["threats_to_dem_freedom"]),
        "impoliteness": bool(item["impoliteness"]),
        "alignment": item.get("alignment") or "",
        "human_like": item.get("human_like") or "",
        "other": item.get("other") or "",
        "updated_at": item["updated_at"].isoformat() if item.get("updated_at") else None,
    }


def _session_payload(
    session_row: Any,
    messages: list[dict],
    saved_evaluations: dict[str, dict],
    agent_blocks: dict[str, str],
    event_rows: list[Any],
    *,
    exported_at: str,
) -> dict:
    row = dict(session_row)
    return {
        "exported_at": exported_at,
        "session": {
            "session_id": str(row["session_id"]),
            "experiment_id": row["experiment_id"],
            "token": row.get("token"),
            "treatment_group": row["treatment_group"],
            "status": row["status"],
            "user_name": row["user_name"],
            "participant_stance": row.get("participant_stance"),
            "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
            "ended_at": row["ended_at"].isoformat() if row.get("ended_at") else None,
            "end_reason": row.get("end_reason"),
            "random_seed": row.get("random_seed"),
            "simulation_config": _as_dict(row.get("simulation_config")),
            "experimental_config": _as_dict(row.get("experimental_config")),
            "agent_blocks": agent_blocks,
        },
        "messages": [
            {
                **message,
                "manual_evaluation": saved_evaluations.get(message["message_id"]),
            }
            for message in messages
        ],
        "events": [
            {
                "id": event["id"],
                "session_id": str(event["session_id"]),
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"].isoformat(),
                "data": _as_dict(event["data"]),
            }
            for event in event_rows
        ],
    }


async def build_session_payload(pool: asyncpg.Pool, session_row: dict) -> dict:
    """Build the canonical JSON bundle used by individual and bulk exports."""
    session_id = str(session_row["session_id"])
    messages = await message_repo.get_session_messages(pool, session_id)
    evaluations = await message_repo.get_manual_evaluations(pool, session_id)
    blocks = await session_repo.get_agent_blocks(pool, session_id)
    async with pool.acquire() as conn:
        events = await conn.fetch(
            """
            SELECT id, session_id, event_type, occurred_at, data
            FROM events
            WHERE experiment_id = $1 AND session_id = $2
            ORDER BY id ASC
            """,
            session_row["experiment_id"],
            session_id,
        )
    return _session_payload(
        session_row,
        messages,
        evaluations,
        blocks,
        list(events),
        exported_at=datetime.now(timezone.utc).isoformat(),
    )


async def build_experiment_session_payloads(
    pool: asyncpg.Pool,
    experiment_id: str,
) -> list[dict]:
    """Build every session JSON with five bulk queries, avoiding N+1 exports."""
    async with pool.acquire() as conn:
        sessions = await conn.fetch(
            """
            SELECT * FROM sessions
            WHERE experiment_id = $1
            ORDER BY started_at DESC NULLS LAST, session_id
            """,
            experiment_id,
        )
        messages = await conn.fetch(
            """
            SELECT message_id, session_id, sender, content, sent_at, reply_to,
                   quoted_text, mentions, liked_by, reported, is_incivil,
                   is_like_minded, inferred_participant_stance,
                   classification_rationale, metadata, seq
            FROM messages
            WHERE experiment_id = $1
            ORDER BY session_id, seq
            """,
            experiment_id,
        )
        evaluations = await conn.fetch(
            """
            SELECT session_id, message_id, incivility, hate_speech,
                   threats_to_dem_freedom, impoliteness, alignment, human_like,
                   other, updated_at
            FROM manual_message_evaluations
            WHERE experiment_id = $1
            """,
            experiment_id,
        )
        blocks = await conn.fetch(
            """
            SELECT b.session_id, b.agent_name, b.blocked_at
            FROM agent_blocks b
            JOIN sessions s ON s.session_id = b.session_id
            WHERE s.experiment_id = $1
            """,
            experiment_id,
        )
        events = await conn.fetch(
            """
            SELECT id, session_id, event_type, occurred_at, data
            FROM events
            WHERE experiment_id = $1
            ORDER BY session_id, id
            """,
            experiment_id,
        )

    messages_by_session: dict[str, list[dict]] = defaultdict(list)
    evaluations_by_session: dict[str, dict[str, dict]] = defaultdict(dict)
    blocks_by_session: dict[str, dict[str, str]] = defaultdict(dict)
    events_by_session: dict[str, list[Any]] = defaultdict(list)

    for row in messages:
        messages_by_session[str(row["session_id"])].append(_message_from_row(row))
    for row in evaluations:
        evaluations_by_session[str(row["session_id"])][str(row["message_id"])] = (
            _manual_evaluation_from_row(row)
        )
    for row in blocks:
        blocks_by_session[str(row["session_id"])][row["agent_name"]] = row["blocked_at"].isoformat()
    for row in events:
        events_by_session[str(row["session_id"])].append(row)

    exported_at = datetime.now(timezone.utc).isoformat()
    return [
        _session_payload(
            row,
            messages_by_session[str(row["session_id"])],
            evaluations_by_session[str(row["session_id"])],
            blocks_by_session[str(row["session_id"])],
            events_by_session[str(row["session_id"])],
            exported_at=exported_at,
        )
        for row in sessions
    ]


async def build_sessions_csv(
    pool: asyncpg.Pool,
    experiment_id: str,
    experiment: dict,
) -> str:
    """One row per message (or one row per empty session), with session context.

    Mirrors GET /admin/sessions/csv so the standalone download and the bundled
    export stay identical.
    """
    async with pool.acquire() as conn:
        session_rows = await conn.fetch(
            """
            SELECT session_id, treatment_group, status, started_at, ended_at,
                   end_reason, simulation_config, experimental_config
            FROM   sessions
            WHERE  experiment_id = $1
            ORDER  BY started_at DESC NULLS LAST, session_id
            """,
            experiment_id,
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "experiment_id", "experiment_description", "session_id",
            "treatment_group", "session_status", "started_at", "ended_at",
            "end_reason", "session_duration_minutes", "messages_per_minute",
            "evaluate_interval", "action_window_size", "performer_memory_size",
            "director_model", "performer_model", "moderator_model",
            "chatroom_context", "ecological_validity_criteria", "message_id",
            "sender", "content", "sent_at", "reply_to", "reported",
            "is_incivil", "is_like_minded", "inferred_participant_stance",
            "classification_rationale",
        ]
    )

    for session_row in session_rows:
        sim_cfg = _as_dict(session_row["simulation_config"])
        exp_cfg = _as_dict(session_row["experimental_config"])
        messages = await message_repo.get_session_messages(pool, str(session_row["session_id"]))

        base = [
            experiment_id,
            experiment.get("description", ""),
            str(session_row["session_id"]),
            session_row["treatment_group"],
            session_row["status"],
            session_row["started_at"].isoformat() if session_row["started_at"] else "",
            session_row["ended_at"].isoformat() if session_row["ended_at"] else "",
            session_row["end_reason"] or "",
            sim_cfg.get("session_duration_minutes", ""),
            sim_cfg.get("messages_per_minute", ""),
            sim_cfg.get("evaluate_interval", ""),
            sim_cfg.get("action_window_size", ""),
            sim_cfg.get("performer_memory_size", ""),
            sim_cfg.get("director_llm_model", ""),
            sim_cfg.get("performer_llm_model", ""),
            sim_cfg.get("moderator_llm_model", ""),
            exp_cfg.get("chatroom_context", ""),
            exp_cfg.get("ecological_validity_criteria", ""),
        ]

        if not messages:
            writer.writerow(base + ["", "", "", "", "", "", "", "", "", ""])
            continue

        for msg in messages:
            writer.writerow(
                base
                + [
                    msg["message_id"],
                    msg["sender"],
                    msg["content"],
                    msg["timestamp"],
                    msg.get("reply_to") or "",
                    "1" if msg.get("reported") else "0",
                    msg.get("is_incivil"),
                    msg.get("is_like_minded"),
                    msg.get("inferred_participant_stance") or "",
                    msg.get("classification_rationale") or "",
                ]
            )

    return buf.getvalue()


async def build_events_csv(pool: asyncpg.Pool, experiment_id: str) -> str:
    """One row per event, including client behavioural telemetry.

    ``data_json`` holds the full event payload; the flattened columns are
    convenience projections of the keys emitted by the behaviour tracker.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, event_type, occurred_at, data
            FROM   events
            WHERE  experiment_id = $1
            ORDER  BY session_id, occurred_at, id
            """,
            experiment_id,
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "experiment_id", "event_id", "session_id", "event_type",
            "occurred_at", "client_at", "compose_ms", "keystrokes",
            "backspaces", "char_count", "pasted", "is_visible",
            "had_mouse_move", "had_keyboard", "data_json",
        ]
    )
    for r in rows:
        data = _as_dict(r["data"])
        writer.writerow(
            [
                experiment_id,
                r["id"],
                str(r["session_id"]),
                r["event_type"],
                r["occurred_at"].isoformat() if r["occurred_at"] else "",
                data.get("client_at", ""),
                data.get("compose_ms", ""),
                data.get("keystrokes", ""),
                data.get("backspaces", ""),
                data.get("char_count", ""),
                data.get("pasted", ""),
                data.get("is_visible", ""),
                data.get("had_mouse_move", ""),
                data.get("had_keyboard", ""),
                json.dumps(data, ensure_ascii=False),
            ]
        )
    return buf.getvalue()


async def build_tokens_csv(pool: asyncpg.Pool, experiment_id: str) -> str:
    from db.repositories import token_repo

    tokens = await token_repo.list_tokens(pool, experiment_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["token", "treatment_group", "used", "used_at", "session_id"])
    for t in tokens:
        writer.writerow(
            [
                t["token"],
                t["treatment_group"],
                t["used"],
                t["used_at"].isoformat() if t.get("used_at") else "",
                str(t["session_id"]) if t.get("session_id") else "",
            ]
        )
    return buf.getvalue()


CODEBOOK = """# WP5 Pilot Platform — Data Export Codebook

This bundle contains every record collected for one experiment. All timestamps
are UTC ISO-8601 unless noted. Files:

- `sessions/` — one complete JSON file per session, using the same structure
  as the download button on an individual session: session metadata and config,
  messages, manual evaluations, blocks, and events.
- `sessions_and_messages.csv` — one row per chat message, prefixed with the
  owning session's configuration and treatment context. Sessions with no
  messages appear as a single row with blank message columns.
- `events.csv` — append-only event log for every session, including
  server-side lifecycle events and **client behavioural telemetry** (see
  below). `data_json` holds the full payload for each event.
- `tokens.csv` — participation tokens and which session (if any) consumed them.

## sessions_and_messages.csv

| column | meaning |
|---|---|
| experiment_id / experiment_description | experiment identity |
| session_id | UUID of the participant's session |
| treatment_group | assigned experimental cell |
| session_status | pending / active / ended / crashed |
| started_at / ended_at / end_reason | session lifecycle |
| session_duration_minutes … moderator_model | simulation configuration snapshot |
| chatroom_context / ecological_validity_criteria | experimental configuration |
| message_id / sender / content / sent_at | the message itself |
| reply_to | message_id this message replies to (blank if none) |
| reported | 1 if the participant reported this message |
| is_incivil / is_like_minded | classifier labels |
| inferred_participant_stance / classification_rationale | classifier output |

## events.csv

`event_type` values include server events (`session_start`, `session_end`,
`message`, `message_like`, `message_report`, `user_block`,
`emotions_checkup_trigger`, `emotions_checkup_response`, `exit_survey`,
`participant_safety_classification`, `participant_safety_triggered`,
`agent_impressions_open`, `agent_impressions`
(open-ended reason the participant gave when leaving early; payload key
`reason`; optional final agent ratings use `ratings`, each with
`agent_name`, a 1–5 `rating`, and an optional `comment`; the same event's
`report_block_survey` (nullable) holds the end-of-session block/report
survey: `tempted_to_block`/`tempted_to_report` (nullable bool, asked only
when the participant didn't actually block/report anyone), `block_reasons`/
`report_reasons` plus a free-text `block_other`/`report_other`,
`tempted_block_agent_names`/`tempted_report_agent_names` (who they say they
considered blocking/reporting without doing it), `blocked_agent_names` (who
they actually blocked), and `reported_message_ids`/`reported_examples` for
messages actually reported),
`websocket_attach`, `websocket_detach`, …) and **client
behavioural telemetry** (prefixed `client_`):

Safety events link the classifier decision to `message_id` and include
`should_stop`, `category` (`self_harm`, `severe_distress`, or `none`),
`confidence`, and a short `rationale`. A positive result additionally emits
`participant_safety_triggered` and ends the session with reason
`participant_safety`; this outcome is treated as non-complete (`r=2`).

| event_type | meaning | key payload fields |
|---|---|---|
| `client_tab_hidden` | participant switched away from the tab / minimised | is_visible=false |
| `client_tab_visible` | participant returned to the tab | is_visible=true |
| `client_window_blur` | chat window lost focus | — |
| `client_window_focus` | chat window regained focus | — |
| `client_compose` | a message composition finished (on send) | compose_ms (ms from first keystroke to send), keystrokes, backspaces, char_count, pasted |
| `client_activity` | periodic heartbeat while the tab is open | is_visible, had_mouse_move, had_keyboard (in the interval) |
| `client_idle_prompt_shown` | the "please write in the chat" reminder was shown | idle_seconds (threshold that fired) |
| `client_page_unload` | the participant closed / navigated away from the page | — |
| `client_exit_attempt` | participant clicked “Salir”, whether they later confirmed or cancelled | source |

Flattened convenience columns (`compose_ms`, `keystrokes`, `backspaces`,
`char_count`, `pasted`, `is_visible`, `had_mouse_move`, `had_keyboard`) are
projections of `data_json`; they are blank for events that don't carry them.

Behavioural note: routine telemetry is only collected when enabled for the
experiment and covers coarse presence/activity signals (tab visibility, window
focus, typing effort, periodic mouse/keyboard activity). `client_exit_attempt`
is always recorded because it is an explicit study interaction. No keystroke
*content* and no mouse coordinates are recorded.
"""


async def build_experiment_zip(
    pool: asyncpg.Pool,
    experiment_id: str,
    experiment: dict,
) -> bytes:
    """Bundle per-session JSONs, analysis CSVs, and a codebook in one ZIP."""
    import zipfile

    sessions_csv = await build_sessions_csv(pool, experiment_id, experiment)
    events_csv = await build_events_csv(pool, experiment_id)
    tokens_csv = await build_tokens_csv(pool, experiment_id)
    session_payloads = await build_experiment_session_payloads(pool, experiment_id)

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for payload in session_payloads:
            session_id = payload["session"]["session_id"]
            zf.writestr(
                f"{experiment_id}/sessions/{session_id}_stage_session.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        zf.writestr(f"{experiment_id}/sessions_and_messages.csv", sessions_csv)
        zf.writestr(f"{experiment_id}/events.csv", events_csv)
        zf.writestr(f"{experiment_id}/tokens.csv", tokens_csv)
        zf.writestr(f"{experiment_id}/codebook.md", CODEBOOK)
    mem.seek(0)
    return mem.getvalue()
