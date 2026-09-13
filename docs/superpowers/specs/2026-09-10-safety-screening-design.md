# Safety screening and human review — design

Date: 2026-09-10
Status: implemented and tested locally (13 Sept 2026)

## Purpose

Every message that reaches a participant is screened by a dedicated safety
classifier (Llama Guard 3 8B) before publication, every flagged message is
queued for explicit human review, and a researcher can pause, resume or end
any live session from the admin panel. Participant messages are screened as
well, so that self-harm disclosures and stated violent intent are surfaced to
the reviewer. The system fails closed: if the classifier cannot return a
verdict, the agent turn is withheld.

Flags do not block publication in this version. An `unsafe` agent message is
published and flagged; the researcher decides what to do. Automatic pausing on
flag thresholds is deliberately not included.

## Components

### `backend/utils/safety/client.py` — `SafetyClient`

Sends a fully rendered prompt string to the classifier and returns a
`SafetyVerdict`:

```
status:      "safe" | "unsafe" | "unavailable"
categories:  list[str]      # e.g. ["S10", "S1"]; empty unless unsafe
raw:         str            # model output verbatim, "" if unavailable
model:       str
latency_ms:  int
unsafe_prob: float | None   # first-token probability when the host returns logprobs
error:       str | None     # reason when unavailable
```

Two transports behind one interface, chosen by config:

| transport | host | request |
|---|---|---|
| `openai_completions` | Konstanz vLLM | `POST {base_url}/v1/completions` with `prompt`, `max_tokens=20`, `temperature=0`, `logprobs=1` |
| `ollama_raw` | SAL Ollama (direct, or via Open WebUI with base_url `…/ollama`) | `POST {base_url}/api/generate` with `prompt`, `raw: true`, `stream: false`, `options.temperature=0`, `options.num_predict=20` |

Both send the identical prompt bytes. Auth is a bearer token from
`SAFETY_API_KEY`. Timeout 8 s (assumes an always-warm host; use a longer
`timeout_s` where the model may be cold-loaded), one retry on transport
error; any other outcome is `unavailable` with `error` set. The client never
raises. The Ollama transport also sends `options.num_ctx` (`safety.num_ctx`,
default 4096): the prompt is short, and the server's default context would
otherwise reserve far more GPU memory than needed.

### `backend/utils/safety/prompt.py` — prompt renderer and parser

`render_prompt(conversation: list[tuple[role, text]], categories: list[Category]) -> str`
renders the Llama Guard 3 chat template exactly as shipped in the model's
`tokenizer_config.json`: task header naming the role under test (`Agent` when
the conversation has an even number of turns, `User` when odd), the category
block, the conversation with `User:` / `Agent:` labels and stripped text, and
the assessment instruction. Roles must alternate starting with `User`; the
renderer raises `ValueError` otherwise, which the gate maps to `unavailable`.

Default categories are the 14 titles from the template (`S1: Violent Crimes.`
… `S14: Code Interpreter Abuse.`), names only, no definitions. A category
entry carries an optional `definition`; when present it is rendered on the
line after the title, as in Meta's Llama Guard recipes. This is the hook for
the project's own hate-speech definition later; the default configuration
does not use it.

`parse_verdict(raw: str) -> (status, categories)` accepts exactly the
documented shape: first line `safe` or `unsafe`, optional second line of
comma-separated category codes. Anything else parses as `unavailable`.

### Conversation mapping

Llama Guard is trained on two-party User/Agent conversations and judges only
the last turn. The multi-party chatroom is mapped as follows.

- Agent message under test: `[("user", <participant's most recent message>), ("assistant", <agent message>)]`.
  If the participant has not written yet, the user turn is the seed news
  article body.
- Participant message under test: `[("user", <participant message>)]`.

Other agents' messages are not included.

### `backend/platforms/safety_screen.py` — `SafetyScreen`

The gate. Constructed per session with the session's safety config and a
`SafetyClient`.

```
async screen_agent(result: TurnResult, state) -> bool     # True = publish
async screen_participant(message: Message, state) -> None
```

Policy:

| verdict | agent message | participant message |
|---|---|---|
| `safe` | publish, `messages.safety_verdict = "safe"` | `safety_verdict = "safe"` |
| `unsafe` | publish, `safety_verdict = "unsafe"`, flag row with `displayed_at` | `safety_verdict = "unsafe"`, flag row |
| `unavailable` | withhold turn, flag row with `content` and `displayed_at = NULL`, event `safety_turn_withheld` | flag row (message already published) |

The screen catches every exception internally and treats it as
`unavailable`. It writes flags through `safety_repo`, logs events through the
session logger, and returns; it never touches WebSocket or Redis.

When `safety.enabled` is false the gate is bypassed and `safety_verdict`
stays `NULL` (never `safe`).

### Call sites

- `AgentManager._handle_message(result)`: drop the turn if a researcher hold
  is in force (a turn already in flight when the hold began must not
  publish; event `turn_dropped_during_hold`), then call `screen_agent`;
  return without persisting or broadcasting when it returns `False`. Both turn paths
  (`_guarded_turn`, `_parallel_turn`) converge here, so no other publication
  route exists for agent text. The call happens after the typing-delay sleep,
  so classifier latency (expected 0.5–1.5 s) adds to the turn; that is
  accepted in exchange for a single choke point.
- `ChatRoom.handle_user_message`: after persist and broadcast, await
  `screen_participant`.

### Pause control

The pause engine in `ChatRoom` gains a `safety` trigger:

- `pause_for_safety(by: str)`: same freeze as idle pause (clock stops, no
  turns, paused time credited back on resume). Persists
  `sessions.safety_paused_at`, logs `session_paused {trigger: "safety", by}`,
  and sends WebSocket event `session_paused {trigger: "hold", notice}` to the
  client. Client-facing values are deliberately neutral (`hold`, and
  `held`/`hold_notice` in `session_config`) so a participant inspecting the
  socket learns only that the room is held. Not cleared by participant activity; the rejoin/abandon timer does
  not run while safety-paused.
- `resume_from_safety(by)`: clears `safety_paused_at`, credits paused time,
  logs `session_resumed`, sends `session_resumed`.
- `end_for_safety(by)`: existing stop path with `end_reason = "safety_stop"`
  in the database; the browser receives `session_end {reason:
  "closed_by_researcher"}`; participant goes to the thank-you screen; NetQuest
  return code `r=2` (server-side ping as well, in case no browser is attached).

Crash recovery: a recovered session with `safety_paused_at` set resumes in the
paused state, and the downtime is credited as paused time. A graceful backend
shutdown ends live sessions as `server_shutdown` (existing behaviour), so
recovery applies to crashes only.

Client: on `session_paused {trigger: "hold"}` the chat shows a neutral
banner, "La sala está en pausa por un momento técnico. Volverá en breve.",
disables input and hides the countdown; `session_resumed` clears it. No
reason is shown.

### Admin API

All under the existing `_require_admin` gate.

```
GET  /admin/safety/flags?status=open|reviewed&session_id=&limit=&before=
GET  /admin/safety/summary                      # counts, screening status, live/paused sessions
POST /admin/safety/flags/{flag_id}/review       # {verdict: "no_concern"|"concern", note?, reviewer}
POST /admin/safety/sessions/{session_id}/pause  # {reviewer}
POST /admin/safety/sessions/{session_id}/resume # {reviewer}
POST /admin/safety/sessions/{session_id}/end    # {reviewer}
```

Review is idempotent per flag; a second review overwrites and logs.

### Safety tab (`frontend/components/admin/SafetyTab.tsx`)

- Summary strip: open flags, live sessions, paused sessions, screening
  status (age of last verdict, `unavailable` count in the last 10 minutes),
  and a warning banner for any live experiment with `safety.enabled = false`.
- Open queue, newest first. Row columns: created time and live elapsed
  counter since `displayed_at` (`withheld` when null); session alias, short
  id, treatment cell and live/paused/ended badge; sender (participant rows in
  a distinct colour band with an icon); verdict and category chips showing
  code and name, raw output on hover; message text with the User turn it was
  judged against expandable beneath; review buttons **No concern** /
  **Concern** with optional note; session buttons **Pause** / **Resume** /
  **End**.
- Reviewed view: closed flags with reviewer, verdict, note; filter by
  session.
- Session drawer: all flags for one session in order.
- Polls every 5 s; unread count in the tab label; short sound on new open
  flags.
- Reviewer name entered once per browser, kept in local storage, sent with
  every action.

## Data model

New table `safety_flags`:

```
flag_id          uuid primary key
session_id       uuid not null references sessions
experiment_id    text not null
message_id       uuid null references messages
seq              bigint null
sender_type      text not null      -- 'agent' | 'participant'
sender           text not null
content          text not null
context_user_turn text not null     -- the User turn the message was judged against
verdict          text not null      -- 'unsafe' | 'unavailable'
categories       text[] not null default '{}'
raw_output       text
model            text
prompt_hash      text not null      -- sha256 of the rendered prompt
unsafe_prob      double precision
latency_ms       integer
error            text
displayed_at     timestamptz null
created_at       timestamptz not null default now()
reviewed_at      timestamptz null
reviewed_by      text null
review_verdict   text null          -- 'no_concern' | 'concern'
review_note      text null
```

Indexes on `(reviewed_at) where reviewed_at is null`, `(session_id, created_at)`.

`messages` gains `safety_verdict text null` (`safe` | `unsafe`).
`sessions` gains `safety_paused_at timestamptz null`.

Session events added: `session_paused {trigger: safety, by}`,
`session_resumed {by, paused_for_seconds}`,
`session_ended {reason: safety_stop, by}`, `safety_turn_withheld {sender, error}`,
`safety_flag_reviewed {flag_id, verdict, by}`.

Exports: the session CSV and annotation exports include `safety_verdict`; a
flags CSV endpoint is not part of this version.

## Configuration

`config.experimental.safety`:

```
enabled:          bool     (default false)
transport:        "openai_completions" | "ollama_raw"
base_url:         str
model:            str      (e.g. "meta-llama/Llama-Guard-3-8B" or "llama-guard3:8b")
timeout_s:        float    (default 8)
categories:       list of {code, title, definition?}   (default: the 14 template titles)
```

Environment fallbacks when a key is absent from config: `SAFETY_TRANSPORT`,
`SAFETY_BASE_URL`, `SAFETY_MODEL`; the API key is only ever read from
`SAFETY_API_KEY`. The rendered prompt's hash is stored on every flag so a
change to `categories` after fielding is detectable.

## Failure handling

- Timeout, transport error, HTTP error, empty or malformed output, renderer
  error: `unavailable`. Agent turn withheld and flagged; participant message
  flagged. The next turn tries again. No automatic pause.
- Gate exceptions of any other kind are caught and treated as `unavailable`.
- The screen never raises into the turn loop and never publishes by
  exception.
- Participant screening runs after publication and cannot affect the
  message.
- The seed news article and typing indicators are not screened. Replaced
  (blocked) agents need no special handling.

## Testing

- Unit: prompt renderer compared byte-for-byte against the Hugging Face
  chat template rendered with `jinja2` for one-turn and two-turn inputs;
  parser on `safe`, `unsafe\nS10,S1`, trailing whitespace, malformed;
  `SafetyScreen` with a fake client for each verdict, asserting publish or
  withhold and the flag row; pause persistence and recovery; admin endpoints.
- Equivalence on SAL: replay the existing dump of heretic-model agent
  messages through `SafetyClient` (`ollama_raw`) and compare verdicts with
  the earlier manual run of the same model (42 unsafe of 863, 38 of them
  S10). Agreement validates transport and prompt rendering.
- End to end on the developer machine: backend with an all-Anthropic
  experiment and `safety.enabled = true` against SAL; run sessions, provoke
  flags with participant messages, exercise review, pause, resume and end;
  check the NetQuest return code and database state.
- Before the pre-test: repeat the replay against Konstanz
  (`openai_completions`, bf16 weights) and compare with SAL (4-bit weights)
  to quantify any quantisation gap.

## Deployment

- Migration adds `safety_flags`, `messages.safety_verdict`,
  `sessions.safety_paused_at`.
- VM `.env` gains `SAFETY_API_KEY` and the Konstanz `SAFETY_BASE_URL`;
  outbound traffic goes through the VU proxy as for the performer endpoint.
- Live experiment config sets `safety.enabled = true` with the default
  categories; demo experiments keep screening off.
- Confirm with Konstanz that the served model is `meta-llama/Llama-Guard-3-8B`
  (bf16), not a quantised or community variant.
- `KONSTANZ_BASE_URL` overrides the performer client's host for development.

## Verified locally (13 Sept 2026)

Against a local backend with Llama Guard 3 on SAL (GPU) and `llama3.1:8b`
agents: unsafe agent and participant flags with correct categories and
`displayed_at`; `safety_verdict` on both message kinds and in the sessions
CSV; hold → client notice, no agent turns, in-flight turn dropped; resume
credits held time; crash mid-hold → session recovered still held with
downtime credited; end → `r=2`, no impressions survey; classifier outage →
turn withheld with text kept, nothing reaches the client, turns resume when
the host returns; review API and audit event; no safety fields in the
participant's WebSocket stream beyond the neutral hold events.

## Out of scope

Automatic pausing on flag counts; blocking or regenerating `unsafe` agent
messages; outbound alerts (email, chat webhook); admin user accounts; custom
category definitions (supported by the renderer, not configured).
