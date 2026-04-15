import asyncio
import csv
import io
import json
import os
import secrets
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
import uuid

from fastapi import FastAPI, Header, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from platforms import SimulationSession
from models import Message
from utils.session_manager import session_manager
from utils import token_manager
from utils.log_viewer import generate_html_from_lines
from utils.session_csv_exporter import export_session_messages_csv
from db import connection as db_conn
from cache import redis_client
from db.repositories import message_repo, session_repo, event_repo, config_repo, token_repo
from features import AVAILABLE_FEATURES, FEATURES_META


# ── Configuration ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://wp5user:wp5pass@localhost:5432/wp5"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_experiment_id: str = ""


def get_experiment_id() -> str:
    """Return the active experiment ID, or raise if none is set."""
    if not _experiment_id:
        raise HTTPException(
            status_code=409,
            detail="No experiment is active. Use the admin wizard to configure one.",
        )
    return _experiment_id


ADMIN_PASSPHRASE = os.environ.get("ADMIN_PASSPHRASE", "")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "")  # comma-separated, e.g. "https://example.com"


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: F841 — FastAPI requires the parameter
    # ── Startup ──
    if not ADMIN_PASSPHRASE:
        raise RuntimeError(
            "ADMIN_PASSPHRASE is not set. The admin panel is required for study setup — "
            "please set ADMIN_PASSPHRASE in your .env file."
        )

    # Connect to PostgreSQL and apply schema.
    pool = await db_conn.init_pool(DATABASE_URL)
    print(f"DB pool ready ({DATABASE_URL})")

    # Connect to Redis.
    await redis_client.init_redis(REDIS_URL)
    print(f"Redis ready ({REDIS_URL})")

    # Auto-activate the most recently created non-paused experiment so
    # participants can join without the researcher re-activating after restart.
    global _experiment_id
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT experiment_id FROM experiments "
            "WHERE paused IS NOT TRUE "
            "ORDER BY created_at DESC LIMIT 1"
        )
    if row:
        _experiment_id = row
        print(f"Auto-activated experiment: {_experiment_id}")

    # Warn about missing LLM API keys (they're only needed at runtime,
    # but an early heads-up saves debugging time).
    _llm_keys = {
        "ANTHROPIC_API_KEY": "Anthropic (Claude)",
        "HF_API_KEY": "HuggingFace",
        "GEMINI_API_KEY": "Google Gemini",
        "MISTRAL_API_KEY": "Mistral",
    }
    missing = [label for env, label in _llm_keys.items()
               if not os.environ.get(env) or os.environ.get(env) == "your_api_key_here"]
    if missing:
        print(f"⚠  No API key set for: {', '.join(missing)}. "
              "These providers will fail if selected in the admin wizard.")

    print("Backend ready. Configure experiments via the admin panel at /admin.")

    yield

    # ── Shutdown ──
    sessions = await session_manager.list_sessions()
    for sid, session in sessions.items():
        try:
            await session.stop(reason="server_shutdown")
        except Exception as e:
            print(f"Error stopping session {sid} during shutdown: {e}")

    await db_conn.close_pool()
    await redis_client.close_redis()
    print("DB pool and Redis connections closed.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Simulcra: Backend", lifespan=lifespan)

# Build CORS allowed origins: always allow localhost for development,
# plus any additional origins from CORS_ORIGINS env var.
_cors_origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]
if CORS_ORIGINS:
    _cors_origins.extend(o.strip() for o in CORS_ORIGINS.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
)


# ── Pydantic request/response models ─────────────────────────────────────────

class SessionStartRequest(BaseModel):
    token: str
    participant_name: Optional[str] = None
    participant_stance: Optional[Literal["favor", "against", "skeptical"]] = None


class SessionStartResponse(BaseModel):
    session_id: str
    message: str


class ParticipantStanceUpdateRequest(BaseModel):
    participant_stance: Literal["favor", "against", "skeptical"]


class LikeRequest(BaseModel):
    user: str


class ReportRequest(BaseModel):
    user: str
    block: Optional[bool] = False
    reason: Optional[str] = None


class ManualEvaluationRowRequest(BaseModel):
    message_id: str
    incivility: bool = False
    hate_speech: bool = False
    threats_to_dem_freedom: bool = False
    impoliteness: bool = False
    alignment: Literal["", "like_minded", "not_like_minded"] = ""
    human_like: Literal["", "yes", "no"] = ""
    other: str = ""


class SessionEvaluationSaveRequest(BaseModel):
    rows: List[ManualEvaluationRowRequest]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_pool():
    """Return the DB pool or raise a 503 if not yet initialised."""
    try:
        return db_conn.get_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database unavailable")


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@app.post("/session/start", response_model=SessionStartResponse)
async def start_session(request: SessionStartRequest):
    """Start a new simulation session.

    Validates and atomically consumes the participant token via the DB
    (PostgreSQL SELECT FOR UPDATE — safe across multiple workers).
    The experiment_id is resolved from the token row.
    """
    session_id = str(uuid.uuid4())

    pool = _get_pool()
    result = await token_manager.consume_token(pool, request.token, session_id)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or already-used token")

    group, experiment_id = result

    # Check experiment availability (date window + paused status).
    unavailable = await config_repo.check_experiment_availability(pool, experiment_id)
    if unavailable:
        # Roll back token consumption so the participant can try again later.
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tokens SET used = FALSE, used_at = NULL, session_id = NULL WHERE token = $1",
                request.token,
            )
        raise HTTPException(status_code=403, detail=unavailable)

    await session_manager.reserve_pending(
        session_id,
        {
            "treatment_group": group,
            "user_name": request.participant_name or "participant",
            "token": request.token,
            "participant_stance": request.participant_stance,
        },
        experiment_id=experiment_id,
    )

    return SessionStartResponse(
        session_id=session_id,
        message=f"Session created (group: {group}). Connect via WebSocket to start.",
    )


@app.post("/session/{session_id}/participant-stance")
async def update_participant_stance(session_id: str, request: ParticipantStanceUpdateRequest):
    """Update the participant self-report after they read the seed article."""
    updated = await session_manager.update_participant_stance(session_id, request.participant_stance)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "participant_stance": request.participant_stance,
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "message": "WP5 Chatroom Backend",
        "version": "0.3.0",
        "endpoints": {
            "POST /session/start": "Start a new session",
            "WS /ws/{session_id}": "WebSocket for chat communication",
            "GET /session/{session_id}/report": "Generate HTML session report",
            "GET /health": "Health check",
        },
    }


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Real-time chat WebSocket.

    Handles both new connections and reconnects (same or different worker).
    Messages from the agent pipeline arrive via Redis pub/sub (see
    SimulationSession._pubsub_loop) and are forwarded to the WebSocket.
    """
    await websocket.accept()

    async def send_to_frontend(message_dict: dict):
        await websocket.send_json(message_dict)

    # Existing session check — handles reconnects (same worker).
    session = await session_manager.get_or_reconstruct(session_id, send_to_frontend)

    if session:
        # Reconnect: attach new WebSocket (replays history + subscribes pub/sub).
        await session.attach_websocket(send_to_frontend)
    else:
        # New connection: pop pending metadata and create session.
        pending = await session_manager.pop_pending(session_id)
        treatment_group = pending.get("treatment_group")

        if not treatment_group:
            await websocket.close(code=1008)
            print(f"WebSocket rejected for {session_id}: missing treatment_group")
            return

        user_name = pending.get("user_name", "participant")
        participant_stance = pending.get("participant_stance")
        experiment_id = pending.get("experiment_id")
        if not experiment_id:
            await websocket.close(code=1008)
            print(f"WebSocket rejected for {session_id}: missing experiment_id")
            return

        try:
            session = await session_manager.create_session(
                session_id,
                send_to_frontend,
                treatment_group=treatment_group,
                user_name=user_name,
                experiment_id=experiment_id,
                participant_stance=participant_stance,
            )
        except RuntimeError as e:
            print(f"WebSocket session creation failed for {session_id}: {e}")
            await websocket.close(code=1011)
            return
        # Attach so the pub/sub loop starts delivering messages to this WebSocket.
        await session.attach_websocket(send_to_frontend)

    # Background heartbeat: send a ping every 30 seconds to detect stale connections.
    # Also closes the WebSocket when the session ends.
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(5)
                if session and not session.running:
                    # Session has ended — close the WebSocket cleanly.
                    await websocket.close(code=1000, reason="session_ended")
                    return
                await websocket.send_json({"type": "ping"})
        except Exception:
            pass  # connection closed — the main loop handles cleanup

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "pong":
                continue  # heartbeat response, ignore
            if data.get("type") == "user_message":
                content = data.get("content", "").strip()
                if content:
                    await session.handle_user_message(
                        content,
                        reply_to=data.get("reply_to"),
                        quoted_text=data.get("quoted_text"),
                        mentions=data.get("mentions"),
                    )

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for session {session_id}")
        if session:
            session.detach_websocket()

    except Exception as e:
        print(f"WebSocket error for session {session_id}: {e}")
        if session:
            session.detach_websocket()

    finally:
        heartbeat_task.cancel()


# ── Like / report endpoints ───────────────────────────────────────────────────

@app.post("/session/{session_id}/message/{message_id}/like")
async def like_message(session_id: str, message_id: str, payload: LikeRequest):
    """Toggle a like on a message and persist the change."""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    message = next((m for m in session.state.messages if m.message_id == message_id), None)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    user_id = payload.user
    result = message.toggle_like(user_id)

    # Persist likes update to DB.
    try:
        pool = _get_pool()
        await message_repo.update_message_likes(pool, message_id, list(message.liked_by))
    except Exception as exc:
        session.logger.log_error("persist_like", str(exc))

    # Log event (fire-and-forget).
    session.logger.log_event("message_like", {
        "message_id": message_id,
        "user": user_id,
        "action": result,
        "likes_count": message.likes_count,
    })

    # Broadcast via Redis pub/sub.
    event = {
        "event_type": "message_like",
        "session_id": session_id,
        "message_id": message_id,
        "action": result,
        "likes_count": message.likes_count,
        "liked_by": list(message.liked_by),
        "user": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = redis_client.get_redis()
        await redis_client.publish_event(r, session_id, event)
    except Exception as exc:
        session.logger.log_error("publish_like", str(exc))

    return {"message": message.to_dict()}


@app.post("/session/{session_id}/message/{message_id}/report")
async def report_message(session_id: str, message_id: str, payload: ReportRequest):
    """Report a message and optionally block the sender."""
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    message = next((m for m in session.state.messages if m.message_id == message_id), None)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    user_id = payload.user
    result = message.toggle_report()

    # Persist reported flag.
    try:
        pool = _get_pool()
        await message_repo.update_message_reported(pool, message_id, message.reported)
    except Exception as exc:
        session.logger.log_error("persist_report", str(exc))

    blocked = None
    target_sender = message.sender
    if payload.block and target_sender and target_sender != session.state.user_name:
        when_iso = datetime.now(timezone.utc).isoformat()
        session.state.block_agent(target_sender, when_iso)

        # Persist block to DB.
        try:
            pool = _get_pool()
            await session_repo.upsert_agent_block(
                pool,
                session_id=session_id,
                agent_name=target_sender,
                blocked_at=datetime.now(timezone.utc),
                blocked_by=user_id,
            )
        except Exception as exc:
            session.logger.log_error("persist_agent_block", str(exc))

        session.logger.log_event("user_block", {
            "agent_name": target_sender,
            "blocked_at": when_iso,
            "by": user_id,
        })
        blocked = dict(session.state.blocked_agents)

    session.logger.log_event("message_report", {
        "message_id": message_id,
        "user": user_id,
        "action": result,
        "blocked": blocked,
        "reason": payload.reason,
    })

    # Broadcast via pub/sub.
    try:
        r = redis_client.get_redis()
        await redis_client.publish_event(r, session_id, {
            "event_type": "message_report",
            "session_id": session_id,
            "message_id": message_id,
            "action": result,
            "user": user_id,
            "reported": message.reported,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if blocked is not None:
            await redis_client.publish_event(r, session_id, {
                "event_type": "user_block",
                "session_id": session_id,
                "user": user_id,
                "blocked": blocked,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as exc:
        session.logger.log_error("publish_report", str(exc))

    return {"message": message.to_dict(), "blocked": blocked}


# ── HTML report endpoint ──────────────────────────────────────────────────────

@app.get("/session/{session_id}/report", response_class=HTMLResponse)
async def session_report(session_id: str):
    """Generate and return an HTML session report from the DB."""
    pool = _get_pool()

    row = await session_repo.get_session(pool, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await message_repo.get_session_messages(pool, session_id)
    events = await event_repo.get_session_events(pool, session_id)

    lines = []

    for evt in events:
        # Skip "message" events — messages are loaded separately from the messages table
        if evt["event_type"] == "message":
            continue
        data = evt["data"]
        if evt["event_type"] == "session_start" and isinstance(data, dict):
            if not data.get("participant_stance_hint") and row.get("participant_stance"):
                data = {**data, "participant_stance_hint": row.get("participant_stance")}
        lines.append({
            "timestamp": evt["occurred_at"],
            "event_type": evt["event_type"],
            "session_id": session_id,
            "data": data,
        })

    for msg in messages:
        lines.append({
            "timestamp": msg["timestamp"],
            "event_type": "message",
            "session_id": session_id,
            "data": msg,
        })

    lines.sort(key=lambda x: x["timestamp"])

    buf = io.StringIO()
    for line in lines:
        buf.write(json.dumps(line) + "\n")
    buf.seek(0)

    html = generate_html_from_lines(buf, session_id)
    return HTMLResponse(content=html)


@app.get("/session/{session_id}/messages-csv")
async def session_messages_csv(session_id: str):
    """Download a single-session annotation template CSV."""
    pool = _get_pool()

    row = await session_repo.get_session(pool, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    raw_messages = await message_repo.get_session_messages(pool, session_id)
    messages = [
        Message(
            sender=msg["sender"],
            content=msg["content"],
            timestamp=datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00")),
            message_id=msg["message_id"],
            reply_to=msg.get("reply_to"),
            quoted_text=msg.get("quoted_text"),
            mentions=msg.get("mentions"),
            liked_by=set(msg.get("liked_by") or []),
            reported=bool(msg.get("reported")),
            metadata={
                k: v
                for k, v in msg.items()
                if k
                not in {
                    "sender",
                    "content",
                    "timestamp",
                    "message_id",
                    "reply_to",
                    "quoted_text",
                    "mentions",
                    "likes_count",
                    "liked_by",
                    "reported",
                }
            },
        )
        for msg in raw_messages
    ]

    csv_path = export_session_messages_csv(session_id, messages)
    with open(csv_path, "rb") as handle:
        csv_bytes = handle.read()

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.csv"'},
    )


# ── Admin endpoints (guarded by ADMIN_PASSPHRASE env var) ────────────────────

def _require_admin(x_admin_key: str = Header(None)):
    """Raise 401 if the admin passphrase is wrong."""
    if x_admin_key != ADMIN_PASSPHRASE:
        raise HTTPException(status_code=401, detail="Invalid admin key")


def _generate_token() -> str:
    """Generate a cryptographically random token in format xK9m-Rw2p."""
    alphabet = string.ascii_letters + string.digits
    left = "".join(secrets.choice(alphabet) for _ in range(4))
    right = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{left}-{right}"


class TokenGenerateRequest(BaseModel):
    participants_per_group: int
    groups: List[str]


@app.get("/admin/verify")
async def admin_verify(x_admin_key: str = Header(None)):
    """Verify admin passphrase."""
    _require_admin(x_admin_key)
    return {"status": "ok"}


# ── Provider key management ───────────────────────────────────────────────────
# Keys are stored only in the .env file on disk and in os.environ in-process.
# The API NEVER returns key values — only present/absent status.

# Map provider name → (env var name, optional extra env vars)
_PROVIDER_KEY_MAP: dict[str, dict] = {
    "anthropic":   {"key_var": "ANTHROPIC_API_KEY"},
    "gemini":      {"key_var": "GEMINI_API_KEY"},
    "huggingface": {"key_var": "HF_API_KEY"},
    "mistral":     {"key_var": "MISTRAL_API_KEY"},
    "konstanz":    {"key_var": "KONSTANZ_API_KEY"},
    "bsc":         {"key_var": "BSC_API_KEY", "extra": {"BSC_API_BASE_URL": "Endpoint URL"}},
}

_PLACEHOLDER = "your_api_key_here"


def _find_dotenv_path() -> Optional[str]:
    """Find the .env file — check repo root and backend dir."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
        ".env",
    ]
    for c in candidates:
        p = os.path.abspath(c)
        if os.path.isfile(p):
            return p
    # If none exists yet, return the repo-root path so we can create it.
    return os.path.abspath(candidates[0])


def _read_dotenv_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        return []


def _write_env_var(var: str, value: str) -> None:
    """Write or update a single env var in the .env file and os.environ.

    Security: value is written directly to disk — never logged or returned.
    """
    path = _find_dotenv_path()
    lines = _read_dotenv_lines(path)

    # Replace existing line if present, otherwise append.
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{var}=") or stripped.startswith(f"{var} ="):
            new_lines.append(f"{var}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        # Add a blank line before if file doesn't end with one.
        if new_lines and not new_lines[-1].endswith("\n\n"):
            if new_lines[-1].strip():
                new_lines.append("\n")
        new_lines.append(f"{var}={value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Also update the live process environment so the change takes effect
    # immediately without requiring a container restart.
    os.environ[var] = value


def _is_key_configured(var: str) -> bool:
    """Return True if the env var is set to a non-placeholder, non-empty value."""
    val = (os.environ.get(var) or "").strip()
    return bool(val) and val != _PLACEHOLDER


@app.get("/admin/provider-keys")
async def admin_get_provider_keys(x_admin_key: str = Header(None)):
    """Return configured status for each provider key.

    NEVER returns key values — only True/False per variable.
    """
    _require_admin(x_admin_key)
    result: dict[str, dict] = {}
    for provider, cfg in _PROVIDER_KEY_MAP.items():
        key_var = cfg["key_var"]
        entry: dict = {"key_var": key_var, "configured": _is_key_configured(key_var)}
        extra = cfg.get("extra", {})
        if extra:
            entry["extra"] = {
                var: {"label": label, "configured": _is_key_configured(var)}
                for var, label in extra.items()
            }
        result[provider] = entry
    return result


class ProviderKeyUpdate(BaseModel):
    provider: str
    key_value: str                    # the new API key — never stored in DB
    extra_values: Optional[Dict[str, str]] = None  # e.g. {"BSC_API_BASE_URL": "..."}


@app.post("/admin/provider-keys")
async def admin_set_provider_key(
    body: ProviderKeyUpdate,
    x_admin_key: str = Header(None),
):
    """Write a provider API key to the .env file and reload into os.environ.

    The key value is written to disk only. It is never stored in the DB,
    never logged, and never returned in any response.
    """
    _require_admin(x_admin_key)

    if body.provider not in _PROVIDER_KEY_MAP:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {body.provider}")

    cfg = _PROVIDER_KEY_MAP[body.provider]
    key_var = cfg["key_var"]

    if not body.key_value.strip():
        raise HTTPException(status_code=422, detail="key_value must not be empty")

    _write_env_var(key_var, body.key_value.strip())

    # Handle optional extra vars (e.g. BSC endpoint URL)
    if body.extra_values:
        allowed_extra = cfg.get("extra", {})
        for var, val in body.extra_values.items():
            if var not in allowed_extra:
                raise HTTPException(status_code=422, detail=f"Unknown extra var: {var}")
            _write_env_var(var, val.strip())

    return {"status": "ok", "provider": body.provider}


@app.get("/admin/meta")
async def admin_get_meta(x_admin_key: str = Header(None)):
    """Return platform metadata for the admin wizard (available features, LLM providers)."""
    _require_admin(x_admin_key)
    from utils.llm.provider import PROVIDER_REGISTRY, PROVIDER_PARAMS

    return {
        "available_features": [
            {"id": fid, **FEATURES_META.get(fid, {"label": fid, "description": ""})}
            for fid in AVAILABLE_FEATURES
        ],
        "llm_providers": list(PROVIDER_REGISTRY.keys()),
        "provider_models": PROVIDER_REGISTRY,
        "provider_params": PROVIDER_PARAMS,
    }


@app.get("/admin/prompt-defaults")
async def admin_prompt_defaults(x_admin_key: str = Header(None)):
    """Return the default prompt template file contents for all roles."""
    _require_admin(x_admin_key)
    from pathlib import Path
    prompts_dir = Path(__file__).parent / "agents" / "STAGE" / "prompts"
    def _read(filename: str) -> str:
        try:
            return (prompts_dir / filename).read_text(encoding="utf-8")
        except Exception:
            return ""
    return {
        "performer_prompt_template": _read("performer_prompt.md"),
        "director_action_prompt_template": _read("director_action_prompt.md"),
        "director_evaluate_prompt_template": _read("director_evaluate_prompt.md"),
        "moderator_prompt_template": _read("moderator_prompt.md"),
        "classifier_prompt_template": _read("system/classifier_prompt.md") + "\n---\n" + _read("user/classifier_prompt.md"),
    }


class TestLLMRequest(BaseModel):
    provider: str
    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: int = 64
    bsc_model_version: Optional[str] = None


@app.post("/admin/test-llm")
async def admin_test_llm(body: TestLLMRequest, x_admin_key: str = Header(None)):
    """Send a short test prompt to an LLM provider and return the raw call details.

    This lets the admin verify credentials, model availability, and parameter
    support before committing to a config.
    """
    _require_admin(x_admin_key)
    from utils.llm.llm_manager import _create_client
    from utils.llm.provider import PROVIDER_PARAMS

    provider = body.provider.lower()
    params_meta = PROVIDER_PARAMS.get(provider, {})
    warnings: List[str] = []

    # Detect mutual-exclusion violations and report them.
    effective_temperature = body.temperature
    effective_top_p = body.top_p
    mutex = params_meta.get("mutual_exclusion")
    if mutex and body.temperature is not None and body.top_p is not None:
        warnings.append(
            f"{provider} does not allow both temperature and top_p — "
            f"top_p will be ignored (temperature takes priority)."
        )
        effective_top_p = None

    # Build the call summary the user will see.
    call_params = {
        "provider": provider,
        "model": body.model,
        "temperature": effective_temperature,
        "top_p": effective_top_p,
        "max_tokens": body.max_tokens,
    }
    if provider == "bsc":
        bsc_model_version = (body.bsc_model_version or "v1").lower()
        if bsc_model_version not in {"v1", "v2"}:
            raise HTTPException(status_code=422, detail="bsc_model_version must be 'v1' or 'v2'")
        call_params["bsc_model_version"] = bsc_model_version
    else:
        bsc_model_version = None

    test_prompt = "Reply with exactly one sentence: The quick brown fox"

    try:
        client = _create_client(
            provider,
            model=body.model,
            temperature=effective_temperature,
            top_p=effective_top_p,
            max_tokens=body.max_tokens,
            bsc_model_version=bsc_model_version,
        )
    except Exception as e:
        return {
            "ok": False,
            "call_params": call_params,
            "prompt": test_prompt,
            "error": f"Client creation failed: {e}",
            "warnings": warnings,
        }

    try:
        response_text = await client.generate_response_async(
            test_prompt, max_retries=0
        )
    except Exception as e:
        response_text = None
        error_msg = str(e)
    else:
        error_msg = None if response_text else "No response returned (model may be unavailable)"
    finally:
        # Clean up client resources.
        if hasattr(client, "aclose"):
            try:
                await client.aclose()
            except Exception:
                pass

    # Truncate long responses for display.
    truncated = response_text[:300] + "…" if response_text and len(response_text) > 300 else response_text

    return {
        "ok": response_text is not None,
        "call_params": call_params,
        "prompt": test_prompt,
        "response": truncated,
        "error": error_msg,
        "warnings": warnings,
    }


@app.get("/admin/config/{experiment_id}")
async def admin_get_config(experiment_id: str, x_admin_key: str = Header(None)):
    """Return the saved config for an experiment from the DB."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    experiment = await config_repo.get_experiment(pool, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")
    return experiment


@app.post("/admin/config")
async def admin_save_config(body: dict, x_admin_key: str = Header(None)):
    """Validate and save experiment config to the DB (immutable).

    Once saved, the configuration cannot be changed. A new experiment
    must be created for different settings.
    """
    _require_admin(x_admin_key)
    global _experiment_id

    new_experiment_id = (body.get("experiment_id") or "").strip()
    if not new_experiment_id:
        raise HTTPException(
            status_code=422,
            detail="experiment_id is required.",
        )

    description = (body.get("description") or "").strip()

    # Validate simulation config.
    sim = body.get("simulation")
    if not sim:
        raise HTTPException(status_code=422, detail="simulation config is required")
    try:
        sim = config_repo.validate_simulation_config(sim)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"Simulation config error: {e}")

    # Validate experimental config.
    exp = body.get("experimental")
    if not exp:
        raise HTTPException(status_code=422, detail="experimental config is required")
    try:
        exp = config_repo.validate_experimental_config(exp, AVAILABLE_FEATURES)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Experimental config error: {e}")

    # Validate tokens.
    token_groups = (body.get("tokens") or {}).get("groups", {})
    try:
        config_repo.validate_token_groups(token_groups, exp.get("groups", {}))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Token error: {e}")

    # Parse schedule dates.
    starts_at = None
    ends_at = None
    raw_starts = body.get("starts_at")
    raw_ends = body.get("ends_at")
    if raw_starts:
        try:
            starts_at = datetime.fromisoformat(raw_starts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid starts_at datetime")
    if raw_ends:
        try:
            ends_at = datetime.fromisoformat(raw_ends.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid ends_at datetime")
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")

    # Save config to DB (immutable — rejects duplicates).
    pool = _get_pool()
    config_blob = {"simulation": sim, "experimental": exp}
    try:
        await config_repo.save_experiment_config(
            pool, new_experiment_id, config_blob, description,
            starts_at=starts_at, ends_at=ends_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Seed tokens into the DB for this experiment.
    await token_manager.seed_tokens(pool, new_experiment_id, token_groups)

    # Activate this experiment.
    _experiment_id = new_experiment_id

    return {"status": "saved", "experiment_id": new_experiment_id}


@app.put("/admin/config/{experiment_id}")
async def admin_update_config(experiment_id: str, body: dict, x_admin_key: str = Header(None)):
    """Validate and update an existing experiment config."""
    _require_admin(x_admin_key)

    description = (body.get("description") or "").strip()

    sim = body.get("simulation")
    if not sim:
        raise HTTPException(status_code=422, detail="simulation config is required")
    try:
        sim = config_repo.validate_simulation_config(sim)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"Simulation config error: {e}")

    exp = body.get("experimental")
    if not exp:
        raise HTTPException(status_code=422, detail="experimental config is required")
    try:
        exp = config_repo.validate_experimental_config(exp, AVAILABLE_FEATURES)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Experimental config error: {e}")

    starts_at = None
    ends_at = None
    raw_starts = body.get("starts_at")
    raw_ends = body.get("ends_at")
    if raw_starts:
        try:
            starts_at = datetime.fromisoformat(raw_starts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid starts_at datetime")
    if raw_ends:
        try:
            ends_at = datetime.fromisoformat(raw_ends.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid ends_at datetime")
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")

    pool = _get_pool()
    config_blob = {"simulation": sim, "experimental": exp}
    try:
        await config_repo.update_experiment_config(
            pool,
            experiment_id,
            config_blob,
            description,
            starts_at=starts_at,
            ends_at=ends_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "updated", "experiment_id": experiment_id}


@app.post("/admin/experiment/{experiment_id}/clone")
async def admin_clone_experiment(experiment_id: str, body: dict, x_admin_key: str = Header(None)):
    """Clone an experiment under a new ID and generate fresh tokens."""
    _require_admin(x_admin_key)

    new_experiment_id = (body.get("new_experiment_id") or "").strip()
    if not new_experiment_id:
        raise HTTPException(status_code=422, detail="new_experiment_id is required")

    pool = _get_pool()
    experiment = await config_repo.get_experiment(pool, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    existing = await config_repo.get_experiment(pool, new_experiment_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Experiment '{new_experiment_id}' already exists")

    description = (body.get("description") or f"Clone of {experiment_id}").strip()
    cfg = experiment["config"]

    try:
        await config_repo.save_experiment_config(
            pool,
            new_experiment_id,
            cfg,
            description,
            starts_at=experiment.get("starts_at"),
            ends_at=experiment.get("ends_at"),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    existing_tokens = await token_repo.list_tokens(pool, experiment_id)
    token_counts: Dict[str, int] = {}
    for row in existing_tokens:
        group = row["treatment_group"]
        token_counts[group] = token_counts.get(group, 0) + 1

    new_token_groups: Dict[str, List[str]] = {}
    seen_tokens: set[str] = set()
    for group, count in token_counts.items():
        generated: List[str] = []
        for _ in range(count):
            while True:
                token = _generate_token()
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    generated.append(token)
                    break
        new_token_groups[group] = generated

    if new_token_groups:
        await token_manager.seed_tokens(pool, new_experiment_id, new_token_groups)

    return {
        "status": "cloned",
        "source_experiment_id": experiment_id,
        "new_experiment_id": new_experiment_id,
    }


@app.post("/admin/experiment/{experiment_id}/activate")
async def admin_activate_experiment(experiment_id: str, x_admin_key: str = Header(None)):
    """Set the active experiment (for dashboard context and session routing)."""
    _require_admin(x_admin_key)
    global _experiment_id

    pool = _get_pool()
    exists = await config_repo.get_experiment_config(pool, experiment_id)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    _experiment_id = experiment_id
    return {"status": "activated", "experiment_id": experiment_id}


@app.post("/admin/experiment/{experiment_id}/pause")
async def admin_pause_experiment(experiment_id: str, x_admin_key: str = Header(None)):
    """Pause an experiment — blocks new sessions and silences active ones."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    try:
        await config_repo.set_paused(pool, experiment_id, True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    affected = session_manager.set_experiment_paused(experiment_id, True)
    return {"status": "paused", "experiment_id": experiment_id, "sessions_paused": affected}


@app.post("/admin/experiment/{experiment_id}/resume")
async def admin_resume_experiment(experiment_id: str, x_admin_key: str = Header(None)):
    """Resume a paused experiment."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    try:
        await config_repo.set_paused(pool, experiment_id, False)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    affected = session_manager.set_experiment_paused(experiment_id, False)
    return {"status": "resumed", "experiment_id": experiment_id, "sessions_resumed": affected}


@app.post("/admin/tokens/generate")
async def admin_generate_tokens(body: TokenGenerateRequest, x_admin_key: str = Header(None)):
    """Generate cryptographically random tokens for each treatment group."""
    _require_admin(x_admin_key)

    if body.participants_per_group <= 0:
        raise HTTPException(status_code=422, detail="participants_per_group must be > 0")
    if not body.groups:
        raise HTTPException(status_code=422, detail="At least one group is required")

    seen: set = set()
    result: Dict[str, List[str]] = {}
    for group in body.groups:
        tokens = []
        for _ in range(body.participants_per_group):
            while True:
                t = _generate_token()
                if t not in seen:
                    seen.add(t)
                    tokens.append(t)
                    break
        result[group] = tokens

    total = sum(len(v) for v in result.values())
    return {"tokens": result, "total": total}


@app.get("/admin/experiments")
async def admin_list_experiments(x_admin_key: str = Header(None)):
    """Return experiment IDs in the database with summary counts."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                e.experiment_id,
                e.description,
                e.created_at,
                e.starts_at,
                e.ends_at,
                e.paused,
                COALESCE(s.session_count, 0)  AS sessions,
                COALESCE(m.message_count, 0)  AS messages,
                COALESCE(t.token_count, 0)    AS tokens,
                COALESCE(t.used_count, 0)     AS tokens_used
            FROM experiments e
            LEFT JOIN (
                SELECT experiment_id, COUNT(*) AS session_count
                FROM sessions GROUP BY experiment_id
            ) s USING (experiment_id)
            LEFT JOIN (
                SELECT experiment_id, COUNT(*) AS message_count
                FROM messages GROUP BY experiment_id
            ) m USING (experiment_id)
            LEFT JOIN (
                SELECT experiment_id,
                       COUNT(*) AS token_count,
                       COUNT(*) FILTER (WHERE used) AS used_count
                FROM tokens GROUP BY experiment_id
            ) t USING (experiment_id)
            ORDER BY e.created_at DESC
        """)
    return {
        "experiments": [
            {
                "experiment_id": r["experiment_id"],
                "description": r["description"] or "",
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "starts_at": r["starts_at"].isoformat() if r["starts_at"] else None,
                "ends_at": r["ends_at"].isoformat() if r["ends_at"] else None,
                "paused": r["paused"] or False,
                "sessions": r["sessions"],
                "messages": r["messages"],
                "tokens": r["tokens"],
                "tokens_used": r["tokens_used"],
            }
            for r in rows
        ],
        "active_experiment_id": _experiment_id,
    }


@app.post("/admin/reset-sessions")
async def admin_reset_sessions(
    body: Dict[str, Any] = None,
    x_admin_key: str = Header(None),
):
    """Reset all session data for an experiment, keeping config and tokens intact."""
    _require_admin(x_admin_key)
    body = body or {}
    target_id = body.get("experiment_id", "").strip()
    if not target_id:
        raise HTTPException(status_code=422, detail="experiment_id is required")

    pool = _get_pool()

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM experiments WHERE experiment_id = $1", target_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Experiment '{target_id}' not found")

    # Stop in-memory sessions that belong to this experiment.
    for sid in list((await session_manager.list_sessions()).keys()):
        try:
            s = await session_manager.get_session(sid)
            if s and getattr(s, "experiment_id", None) == target_id:
                await s.stop(reason="admin_reset")
        except Exception:
            pass

    # Delete session data but keep experiment config and tokens.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT session_id FROM sessions WHERE experiment_id = $1",
            target_id,
        )
        session_ids = [r["session_id"] for r in rows]

        await conn.execute(
            "DELETE FROM events WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM messages WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM agent_blocks WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM sessions WHERE experiment_id = $1",
            target_id,
        )
        # Reset token consumption so tokens can be reused.
        await conn.execute(
            "UPDATE tokens SET used = FALSE, used_at = NULL, session_id = NULL WHERE experiment_id = $1",
            target_id,
        )

    # Flush Redis session caches.
    r = redis_client.get_redis()
    for sid in session_ids:
        await redis_client.invalidate_session(r, sid)

    return {"status": "sessions_reset", "experiment_id": target_id, "sessions_deleted": len(session_ids)}


@app.post("/admin/reset-db")
async def admin_reset_db(
    body: Dict[str, Any] = None,
    x_admin_key: str = Header(None),
):
    """Delete an experiment and all its data from the database."""
    _require_admin(x_admin_key)
    global _experiment_id
    body = body or {}
    target_id = body.get("experiment_id", "").strip()
    if not target_id:
        raise HTTPException(status_code=422, detail="experiment_id is required")

    pool = _get_pool()

    # Verify experiment exists.
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM experiments WHERE experiment_id = $1", target_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Experiment '{target_id}' not found")

    # Stop in-memory sessions that belong to this experiment.
    for sid in list((await session_manager.list_sessions()).keys()):
        try:
            s = await session_manager.get_session(sid)
            if s and getattr(s, "experiment_id", None) == target_id:
                await s.stop(reason="admin_reset")
        except Exception:
            pass

    # Collect session IDs before deleting so we can flush Redis.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT session_id FROM sessions WHERE experiment_id = $1",
            target_id,
        )
        session_ids = [r["session_id"] for r in rows]

        await conn.execute(
            "DELETE FROM events WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM messages WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM agent_blocks WHERE session_id IN "
            "(SELECT session_id FROM sessions WHERE experiment_id = $1)",
            target_id,
        )
        await conn.execute(
            "DELETE FROM sessions WHERE experiment_id = $1",
            target_id,
        )
        await conn.execute(
            "DELETE FROM tokens WHERE experiment_id = $1",
            target_id,
        )
        await conn.execute(
            "DELETE FROM experiments WHERE experiment_id = $1",
            target_id,
        )

    # Flush Redis session caches so stale metadata doesn't trigger reconstruction.
    r = redis_client.get_redis()
    for sid in session_ids:
        await redis_client.invalidate_session(r, sid)

    # Clear active experiment if it was the deleted one.
    if _experiment_id == target_id:
        _experiment_id = ""

    return {"status": "experiment_deleted", "experiment_id": target_id}


@app.get("/admin/sessions")
async def admin_list_sessions(
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Return all sessions for an experiment with message counts."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                s.session_id,
                s.treatment_group,
                s.token,
                s.status,
                s.started_at,
                s.ended_at,
                s.end_reason,
                COALESCE(m.msg_count, 0) AS message_count
            FROM sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS msg_count
                FROM messages GROUP BY session_id
            ) m USING (session_id)
            WHERE s.experiment_id = $1
            ORDER BY s.started_at DESC NULLS LAST
        """, eid)
    return {
        "sessions": [
            {
                "session_id": str(r["session_id"]),
                "treatment_group": r["treatment_group"],
                "token": r["token"],
                "status": r["status"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                "end_reason": r["end_reason"],
                "message_count": r["message_count"],
            }
            for r in rows
        ]
    }


@app.get("/admin/events")
async def admin_list_events(
    experiment_id: Optional[str] = None,
    after_id: int = 0,
    limit: int = 200,
    x_admin_key: str = Header(None),
):
    """Return recent events for an experiment, with cursor-based pagination.

    Pass `after_id` to fetch only events newer than a given event ID.
    """
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    limit = min(limit, 500)
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.id, e.session_id, e.event_type, e.occurred_at, e.data
            FROM events e
            WHERE e.experiment_id = $1 AND e.id > $2
            ORDER BY e.id ASC
            LIMIT $3
            """,
            eid,
            after_id,
            limit,
        )
    return {
        "events": [
            {
                "id": r["id"],
                "session_id": str(r["session_id"]),
                "event_type": r["event_type"],
                "occurred_at": r["occurred_at"].isoformat(),
                "data": r["data"] if isinstance(r["data"], dict) else json.loads(r["data"]),
            }
            for r in rows
        ],
    }


@app.get("/admin/session/{session_id}/messages")
async def admin_session_messages(
    session_id: str,
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Return ordered messages for a session, scoped to the selected experiment."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()

    session_row = await session_repo.get_session(pool, session_id)
    if not session_row or session_row["experiment_id"] != eid:
        raise HTTPException(status_code=404, detail="Session not found for this experiment")

    messages = await message_repo.get_session_messages(pool, session_id)
    saved_evaluations = await message_repo.get_manual_evaluations(pool, session_id)
    return {
        "messages": [
            {
                "message_id": msg["message_id"],
                "sender": msg["sender"],
                "is_participant_message": msg["sender"] == session_row["user_name"],
                "content": msg["content"],
                "timestamp": msg["timestamp"],
                "is_incivil": msg.get("is_incivil"),
                "is_like_minded": msg.get("is_like_minded"),
                "inferred_participant_stance": msg.get("inferred_participant_stance"),
                "classification_rationale": msg.get("classification_rationale"),
                "manual_evaluation": saved_evaluations.get(msg["message_id"]),
            }
            for msg in messages
        ]
    }


@app.get("/admin/session/{session_id}/export")
async def admin_export_session_bundle(
    session_id: str,
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Download a single session bundle with session row, messages, and events."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()

    session_row = await session_repo.get_session(pool, session_id)
    if not session_row or session_row["experiment_id"] != eid:
        raise HTTPException(status_code=404, detail="Session not found for this experiment")

    messages = await message_repo.get_session_messages(pool, session_id)
    saved_evaluations = await message_repo.get_manual_evaluations(pool, session_id)
    agent_blocks = await session_repo.get_agent_blocks(pool, session_id)

    async with pool.acquire() as conn:
        event_rows = await conn.fetch(
            """
            SELECT id, session_id, event_type, occurred_at, data
            FROM events
            WHERE experiment_id = $1 AND session_id = $2
            ORDER BY id ASC
            """,
            eid,
            session_id,
        )

    sim_cfg = session_row.get("simulation_config")
    exp_cfg = session_row.get("experimental_config")
    if isinstance(sim_cfg, str):
        sim_cfg = json.loads(sim_cfg)
    if isinstance(exp_cfg, str):
        exp_cfg = json.loads(exp_cfg)

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "session": {
            "session_id": str(session_row["session_id"]),
            "experiment_id": session_row["experiment_id"],
            "token": session_row["token"],
            "treatment_group": session_row["treatment_group"],
            "status": session_row["status"],
            "user_name": session_row["user_name"],
            "participant_stance": session_row.get("participant_stance"),
            "started_at": session_row["started_at"].isoformat() if session_row.get("started_at") else None,
            "ended_at": session_row["ended_at"].isoformat() if session_row.get("ended_at") else None,
            "end_reason": session_row.get("end_reason"),
            "random_seed": session_row.get("random_seed"),
            "simulation_config": sim_cfg,
            "experimental_config": exp_cfg,
            "agent_blocks": agent_blocks,
        },
        "messages": [
            {
                **msg,
                "manual_evaluation": saved_evaluations.get(msg["message_id"]),
            }
            for msg in messages
        ],
        "events": [
            {
                "id": row["id"],
                "session_id": str(row["session_id"]),
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"].isoformat(),
                "data": row["data"] if isinstance(row["data"], dict) else json.loads(row["data"]),
            }
            for row in event_rows
        ],
    }

    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    headers = {
        "Content-Disposition": f'attachment; filename="{session_id}_stage_session.json"'
    }
    return StreamingResponse(io.BytesIO(body), media_type="application/json; charset=utf-8", headers=headers)


@app.put("/admin/session/{session_id}/evaluation")
async def admin_save_session_evaluation(
    session_id: str,
    request: SessionEvaluationSaveRequest,
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Persist the full manual evaluation snapshot for a session."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()

    session_row = await session_repo.get_session(pool, session_id)
    if not session_row or session_row["experiment_id"] != eid:
        raise HTTPException(status_code=404, detail="Session not found for this experiment")

    messages = await message_repo.get_session_messages(pool, session_id)
    participant_name = session_row["user_name"]
    valid_message_ids = {
        msg["message_id"]
        for msg in messages
        if msg["sender"] != participant_name
    }
    request_ids = [row.message_id for row in request.rows]
    unknown_ids = sorted(set(request_ids) - valid_message_ids)
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail="Evaluation payload contains unknown or participant message ids",
        )

    await message_repo.replace_manual_evaluations(
        pool,
        session_id=session_id,
        experiment_id=eid,
        evaluations=[row.model_dump() for row in request.rows if row.message_id in valid_message_ids],
    )
    return {
        "status": "ok",
        "session_id": session_id,
        "saved_rows": len(request.rows),
    }


@app.get("/admin/tokens/stats")
async def admin_token_stats(
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Return per-group token usage for an experiment."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                treatment_group,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE used) AS used
            FROM tokens
            WHERE experiment_id = $1
            GROUP BY treatment_group
            ORDER BY treatment_group
        """, eid)
    return {
        "groups": [
            {
                "group": r["treatment_group"],
                "total": r["total"],
                "used": r["used"],
            }
            for r in rows
        ]
    }


@app.get("/admin/experiment/{experiment_id}/compliance")
async def admin_experiment_compliance(experiment_id: str, x_admin_key: str = Header(None)):
    """Return treatment fidelity stats per group for a given experiment.

    Per treatment group:
    - session_count: how many sessions exist
    - classified_count: agent messages that were classified (is_incivil not null)
    - incivil_count / incivil_pct: number and % of incivil agent messages
    - like_minded_count / like_minded_pct: number and % of like-minded agent messages
      (denominator is stance_classified_count, i.e. only messages where like-mindedness was determined)
    """
    _require_admin(x_admin_key)
    pool = _get_pool()

    experiment = await config_repo.get_experiment(pool, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.treatment_group,
                COUNT(DISTINCT s.session_id)                                        AS session_count,
                COUNT(m.message_id) FILTER (WHERE m.is_incivil IS NOT NULL)         AS classified_count,
                COUNT(m.message_id) FILTER (WHERE m.is_incivil = true)              AS incivil_count,
                COUNT(m.message_id) FILTER (WHERE m.is_like_minded IS NOT NULL)     AS stance_classified_count,
                COUNT(m.message_id) FILTER (WHERE m.is_like_minded = true)          AS like_minded_count
            FROM sessions s
            LEFT JOIN messages m
                ON s.session_id = m.session_id
                AND m.sender != s.user_name
            WHERE s.experiment_id = $1
            GROUP BY s.treatment_group
            ORDER BY s.treatment_group
            """,
            experiment_id,
        )

    def _pct(num, den):
        return round(100.0 * num / den, 1) if den > 0 else None

    groups = []
    for r in rows:
        classified = r["classified_count"]
        incivil = r["incivil_count"]
        stance_classified = r["stance_classified_count"]
        like_minded = r["like_minded_count"]
        groups.append({
            "group": r["treatment_group"],
            "session_count": r["session_count"],
            "classified_count": classified,
            "incivil_count": incivil,
            "incivil_pct": _pct(incivil, classified),
            "stance_classified_count": stance_classified,
            "like_minded_count": like_minded,
            "like_minded_pct": _pct(like_minded, stance_classified),
        })

    return {"experiment_id": experiment_id, "groups": groups}


@app.get("/admin/evaluations/summary-csv/{experiment_id}")
async def admin_evaluations_summary_csv(experiment_id: str, x_admin_key: str = Header(None)):
    """Download one summary row per session with saved manual evaluations."""
    _require_admin(x_admin_key)
    pool = _get_pool()

    experiment = await config_repo.get_experiment(pool, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                s.session_id,
                s.treatment_group,
                s.status,
                COUNT(m.message_id) AS total_messages,
                COUNT(ev.message_id) AS saved_rows,
                COUNT(*) FILTER (WHERE ev.incivility) AS incivility_count,
                COUNT(*) FILTER (WHERE ev.hate_speech) AS hate_speech_count,
                COUNT(*) FILTER (WHERE ev.impoliteness) AS impoliteness_count,
                COUNT(*) FILTER (WHERE ev.threats_to_dem_freedom) AS threats_to_democracy_count,
                COUNT(*) FILTER (WHERE ev.alignment = 'like_minded') AS like_minded_count,
                COUNT(*) FILTER (WHERE ev.alignment = 'not_like_minded') AS not_like_minded_count,
                COUNT(*) FILTER (WHERE ev.alignment <> '') AS aligned_rows,
                COUNT(*) FILTER (WHERE ev.human_like = 'yes') AS human_like_yes_count,
                COUNT(*) FILTER (WHERE ev.human_like <> '') AS human_like_labeled_count,
                COUNT(*) FILTER (WHERE btrim(COALESCE(ev.other, '')) <> '') AS other_filled_count,
                MAX(ev.updated_at) AS last_evaluated_at
            FROM sessions s
            LEFT JOIN messages m
                ON m.session_id = s.session_id
                AND m.sender != s.user_name
            LEFT JOIN manual_message_evaluations ev
                ON ev.session_id = s.session_id
                AND ev.message_id = m.message_id
            WHERE s.experiment_id = $1
            GROUP BY s.session_id, s.treatment_group, s.status
            HAVING COUNT(ev.message_id) > 0
            ORDER BY last_evaluated_at DESC NULLS LAST, s.session_id
            """,
            experiment_id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="No saved evaluations found for this experiment")

    def _pct(value: int, total: int) -> str:
        return f"{(value / total) * 100:.1f}%" if total > 0 else ""

    def _expected_targets_from_treatment(treatment_group: str) -> tuple[Optional[int], Optional[int]]:
        group = (treatment_group or "").lower()

        expected_incivility: Optional[int] = None
        if "not_incivil" in group:
            expected_incivility = 0
        elif "incivil" in group:
            expected_incivility = 100
        elif "mix" in group:
            expected_incivility = 50

        expected_like_minded: Optional[int] = None
        if "not_like_minded" in group:
            expected_like_minded = 0
        elif "like_minded" in group:
            expected_like_minded = 100
        elif "mix" in group:
            expected_like_minded = 50

        return expected_incivility, expected_like_minded

    def _compliance(actual_value: int, total: int, expected_pct: Optional[int]) -> str:
        if total <= 0 or expected_pct is None:
            return ""
        actual_pct = (actual_value / total) * 100.0
        return f"{max(0.0, 100.0 - abs(actual_pct - expected_pct)):.1f}%"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "experiment_id",
            "experiment_description",
            "session_id",
            "treatment_group",
            "session_status",
            "saved_rows",
            "n_messages",
            "n_incivility",
            "n_hate_speech",
            "n_impoliteness",
            "n_threats_to_democracy",
            "n_like_minded",
            "n_not_like_minded",
            "perc_incivility",
            "perc_hate_speech",
            "perc_impoliteness",
            "perc_threats_to_democracy",
            "perc_like_minded",
            "perc_not_like_minded",
            "compliance_incivility_target",
            "compliance_like_minded_target",
            "compliance_human_like_target_100",
            "n_other_filled",
            "perc_other_filled",
            "last_evaluated_at",
        ]
    )
    for row in rows:
        total_messages = int(row["total_messages"] or 0)
        saved_rows = int(row["saved_rows"] or 0)
        incivility_count = int(row["incivility_count"] or 0)
        hate_speech_count = int(row["hate_speech_count"] or 0)
        impoliteness_count = int(row["impoliteness_count"] or 0)
        threats_count = int(row["threats_to_democracy_count"] or 0)
        like_minded_count = int(row["like_minded_count"] or 0)
        not_like_minded_count = int(row["not_like_minded_count"] or 0)
        aligned_rows = int(row["aligned_rows"] or 0)
        human_like_yes_count = int(row["human_like_yes_count"] or 0)
        human_like_labeled_count = int(row["human_like_labeled_count"] or 0)
        other_filled_count = int(row["other_filled_count"] or 0)
        expected_incivility, expected_like_minded = _expected_targets_from_treatment(
            str(row["treatment_group"] or "")
        )
        writer.writerow(
            [
                experiment_id,
                experiment.get("description", ""),
                str(row["session_id"]),
                row["treatment_group"],
                row["status"],
                saved_rows,
                total_messages,
                incivility_count,
                hate_speech_count,
                impoliteness_count,
                threats_count,
                like_minded_count,
                not_like_minded_count,
                _pct(incivility_count, total_messages),
                _pct(hate_speech_count, total_messages),
                _pct(impoliteness_count, total_messages),
                _pct(threats_count, total_messages),
                _pct(like_minded_count, aligned_rows),
                _pct(not_like_minded_count, aligned_rows),
                _compliance(incivility_count, total_messages, expected_incivility),
                _compliance(like_minded_count, aligned_rows, expected_like_minded),
                _compliance(human_like_yes_count, human_like_labeled_count, 100),
                other_filled_count,
                _pct(other_filled_count, saved_rows),
                row["last_evaluated_at"].isoformat() if row["last_evaluated_at"] else "",
            ]
        )

    buf.seek(0)
    filename = f"{experiment_id}_evaluation_summary.csv"
    return StreamingResponse(
        io.StringIO(buf.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/admin/sessions/csv/{experiment_id}")
async def admin_sessions_csv(experiment_id: str, x_admin_key: str = Header(None)):
    """Download all session messages for an experiment as a flat CSV."""
    _require_admin(x_admin_key)
    pool = _get_pool()

    experiment = await config_repo.get_experiment(pool, experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    async with pool.acquire() as conn:
        session_rows = await conn.fetch(
            """
            SELECT
                session_id,
                treatment_group,
                status,
                started_at,
                ended_at,
                end_reason,
                simulation_config,
                experimental_config
            FROM sessions
            WHERE experiment_id = $1
            ORDER BY started_at DESC NULLS LAST, session_id
            """,
            experiment_id,
        )

    if not session_rows:
        raise HTTPException(status_code=404, detail="No sessions found for this experiment")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
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
        ]
    )

    for session_row in session_rows:
        sim_cfg = session_row["simulation_config"] or {}
        exp_cfg = session_row["experimental_config"] or {}
        if isinstance(sim_cfg, str):
            sim_cfg = json.loads(sim_cfg)
        if isinstance(exp_cfg, str):
            exp_cfg = json.loads(exp_cfg)
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
            writer.writerow(base + ["", "", "", "", "", ""])
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

    buf.seek(0)
    filename = f"{experiment_id}_sessions.csv"
    return StreamingResponse(
        io.StringIO(buf.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/admin/tokens/csv/{experiment_id}")
async def admin_tokens_csv(experiment_id: str, x_admin_key: str = Header(None)):
    """Download all tokens for an experiment as a CSV file."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    from db.repositories import token_repo
    tokens = await token_repo.list_tokens(pool, experiment_id)
    if not tokens:
        raise HTTPException(status_code=404, detail="No tokens found for this experiment")

    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["token", "treatment_group", "used", "used_at", "session_id"])
    for t in tokens:
        writer.writerow([
            t["token"],
            t["treatment_group"],
            t["used"],
            t["used_at"].isoformat() if t.get("used_at") else "",
            str(t["session_id"]) if t.get("session_id") else "",
        ])
    buf.seek(0)
    filename = f"{experiment_id}_tokens.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
