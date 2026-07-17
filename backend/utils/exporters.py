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
from typing import Any, Dict, List, Optional

import asyncpg

from db.repositories import message_repo


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
`emotions_checkup_trigger`, `emotions_checkup_response`, `websocket_attach`,
`websocket_detach`, …) and **client behavioural telemetry** (prefixed
`client_`):

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

Flattened convenience columns (`compose_ms`, `keystrokes`, `backspaces`,
`char_count`, `pasted`, `is_visible`, `had_mouse_move`, `had_keyboard`) are
projections of `data_json`; they are blank for events that don't carry them.

Behavioural note: telemetry is only collected when enabled for the experiment
and covers coarse presence/activity signals (tab visibility, window focus,
typing effort, periodic mouse/keyboard activity). No keystroke *content* and no
mouse coordinates are recorded.
"""


async def build_experiment_zip(
    pool: asyncpg.Pool,
    experiment_id: str,
    experiment: dict,
) -> bytes:
    """Bundle every per-experiment CSV plus a codebook into a single ZIP."""
    import zipfile

    sessions_csv = await build_sessions_csv(pool, experiment_id, experiment)
    events_csv = await build_events_csv(pool, experiment_id)
    tokens_csv = await build_tokens_csv(pool, experiment_id)

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{experiment_id}/sessions_and_messages.csv", sessions_csv)
        zf.writestr(f"{experiment_id}/events.csv", events_csv)
        zf.writestr(f"{experiment_id}/tokens.csv", tokens_csv)
        zf.writestr(f"{experiment_id}/codebook.md", CODEBOOK)
    mem.seek(0)
    return mem.getvalue()
