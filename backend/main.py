import asyncio
import io
import json
import os
import secrets
import socket
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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
from db.repositories import message_repo, session_repo, event_repo, config_repo
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



async def _retry_startup_dependency(name: str, connect_coro_factory, attempts: int = 20, delay_seconds: float = 1.0):
    """Retry a startup dependency connection to tolerate transient DNS/network errors."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return await connect_coro_factory()
        except (socket.gaierror, OSError, ConnectionError, TimeoutError) as e:
            last_error = e
            print(f"{name} connection attempt {attempt}/{attempts} failed: {type(e).__name__}: {e}")
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
        except Exception as e:
            last_error = e
            print(f"{name} connection attempt {attempt}/{attempts} failed: {type(e).__name__}: {e}")
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)

    raise RuntimeError(f"Failed to connect to {name} after {attempts} attempts: {last_error}")

# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: F841 — FastAPI requires the parameter
    # ── Startup ──
    if not ADMIN_PASSPHRASE:
        raise RuntimeError(
            "ADMIN_PASSPHRASE is not set. The admin panel is required for study setup — "
            "please set ADMIN_PASSPHRASE in your .env file."
        )

    # Connect to PostgreSQL and apply schema (with retries for transient DNS issues).
    pool = await _retry_startup_dependency(
        "PostgreSQL",
        lambda: db_conn.init_pool(DATABASE_URL),
    )
    print(f"DB pool ready ({DATABASE_URL})")

    # Connect to Redis (with retries for transient DNS issues) and verify with PING.
    r = await _retry_startup_dependency(
        "Redis",
        lambda: redis_client.init_redis(REDIS_URL),
    )
    await r.ping()
    print(f"Redis ready ({REDIS_URL})")

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


class SessionStartResponse(BaseModel):
    session_id: str
    message: str


class LikeRequest(BaseModel):
    user: str


class ReportRequest(BaseModel):
    user: str
    block: Optional[bool] = False
    reason: Optional[str] = None


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
        {"treatment_group": group, "user_name": "participant", "token": request.token},
        experiment_id=experiment_id,
    )

    return SessionStartResponse(
        session_id=session_id,
        message=f"Session created (group: {group}). Connect via WebSocket to start.",
    )


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
            "GET /session/{session_id}/messages-csv": "Download session messages annotation CSV",
            "GET /health": "Health check",
            "GET /admin/session/{session_id}/messages": "List session messages for admin evaluation",
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
            )
        except RuntimeError as e:
            print(f"WebSocket session creation failed for {session_id}: {e}")
            await websocket.close(code=1011)
            return
        # Attach so the pub/sub loop starts delivering messages to this WebSocket.
        await session.attach_websocket(send_to_frontend)

    # Background heartbeat: send a ping every 30 seconds to detect stale connections.
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
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
        lines.append({
            "timestamp": evt["occurred_at"],
            "event_type": evt["event_type"],
            "session_id": session_id,
            "data": evt["data"],
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
    """Generate and return an annotation-ready CSV for a session's messages."""
    pool = _get_pool()

    row = await session_repo.get_session(pool, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    raw_messages = await message_repo.get_session_messages(pool, session_id)
    messages = [
        Message(
            sender=m["sender"],
            content=m["content"],
            timestamp=datetime.fromisoformat(m["timestamp"]),
            message_id=m["message_id"],
            reply_to=m.get("reply_to"),
            quoted_text=m.get("quoted_text"),
            mentions=m.get("mentions"),
            liked_by=set(m.get("liked_by", [])),
            reported=m.get("reported", False),
            metadata={k: v for k, v in m.items() if k not in (
                "sender", "content", "timestamp", "message_id", "reply_to",
                "quoted_text", "mentions", "liked_by", "reported", "likes_count",
            )},
        )
        for m in raw_messages
    ]

    csv_path = export_session_messages_csv(session_id, messages)
    with open(csv_path, "rb") as f:
        payload = f.read()

    headers = {"Content-Disposition": f'attachment; filename="{session_id}.csv"'}
    return StreamingResponse(io.BytesIO(payload), media_type="text/csv", headers=headers)


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


class TestLLMRequest(BaseModel):
    provider: str
    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: int = 64


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

    test_prompt = "Reply with exactly one sentence: The quick brown fox"

    try:
        client = _create_client(
            provider,
            model=body.model,
            temperature=effective_temperature,
            top_p=effective_top_p,
            max_tokens=body.max_tokens,
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
    """Update an existing experiment's configuration.

    Unlike POST /admin/config, this endpoint modifies an existing experiment.
    The experiment_id cannot be changed.
    """
    _require_admin(x_admin_key)

    pool = _get_pool()
    existing = await config_repo.get_experiment(pool, experiment_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

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

    # Parse schedule dates.
    description = (body.get("description") or "").strip()
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

    # Update config in DB.
    config_blob = {"simulation": sim, "experimental": exp}
    try:
        await config_repo.update_experiment_config(
            pool, experiment_id, config_blob, description,
            starts_at=starts_at, ends_at=ends_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "updated", "experiment_id": experiment_id}


@app.post("/admin/experiment/{experiment_id}/clone")
async def admin_clone_experiment(experiment_id: str, body: dict, x_admin_key: str = Header(None)):
    """Clone an existing experiment under a new ID.

    Copies the full config (simulation + experimental) and generates fresh tokens
    preserving the group structure and counts from the source experiment.
    """
    _require_admin(x_admin_key)

    new_id = (body.get("new_experiment_id") or "").strip()
    if not new_id:
        raise HTTPException(status_code=422, detail="new_experiment_id is required")

    pool = _get_pool()
    source = await config_repo.get_experiment(pool, experiment_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    description = (body.get("description") or f"Clone of {experiment_id}").strip()
    config_blob = source["config"]

    try:
        await config_repo.save_experiment_config(pool, new_id, config_blob, description)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Clone tokens: generate new unique tokens preserving group names and counts.
    async with pool.acquire() as conn:
        token_rows = await conn.fetch(
            "SELECT treatment_group FROM tokens WHERE experiment_id = $1",
            experiment_id,
        )
    group_counts: Dict[str, int] = {}
    for row in token_rows:
        group = row["treatment_group"]
        group_counts[group] = group_counts.get(group, 0) + 1

    if group_counts:
        seen: set = set()
        new_token_groups: Dict[str, List[str]] = {}
        for group, count in group_counts.items():
            tokens = []
            for _ in range(count):
                while True:
                    t = _generate_token()
                    if t not in seen:
                        seen.add(t)
                        tokens.append(t)
                        break
            new_token_groups[group] = tokens
        await token_manager.seed_tokens(pool, new_id, new_token_groups)

    return {
        "status": "cloned",
        "source_experiment_id": experiment_id,
        "new_experiment_id": new_id,
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
    """Pause an experiment so no new sessions can be started."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    try:
        await config_repo.set_paused(pool, experiment_id, True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "paused", "experiment_id": experiment_id}


@app.post("/admin/experiment/{experiment_id}/resume")
async def admin_resume_experiment(experiment_id: str, x_admin_key: str = Header(None)):
    """Resume a paused experiment."""
    _require_admin(x_admin_key)
    pool = _get_pool()
    try:
        await config_repo.set_paused(pool, experiment_id, False)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "resumed", "experiment_id": experiment_id}


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


@app.get("/admin/session/{session_id}/messages")
async def admin_session_messages(
    session_id: str,
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Return ordered session messages for admin-side evaluation UI."""
    _require_admin(x_admin_key)
    eid = experiment_id or get_experiment_id()
    pool = _get_pool()

    async with pool.acquire() as conn:
        belongs = await conn.fetchval(
            "SELECT 1 FROM sessions WHERE session_id = $1 AND experiment_id = $2",
            session_id,
            eid,
        )
    if not belongs:
        raise HTTPException(status_code=404, detail="Session not found for experiment")

    messages = await message_repo.get_session_messages(pool, session_id)
    return {
        "messages": [
            {
                "message_id": m["message_id"],
                "sender": m["sender"],
                "content": m["content"],
                "timestamp": m["timestamp"],
            }
            for m in messages
        ]
    }


@app.get("/admin/sessions")
async def admin_list_sessions(
    experiment_id: Optional[str] = None,
    x_admin_key: str = Header(None),
):
    """Return all sessions for an experiment with message and classifier stats."""
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
                COALESCE(m.msg_count, 0) AS message_count,
                COALESCE(c.agent_msg_count, 0) AS agent_message_count,
                COALESCE(c.incivil_count, 0) AS incivil_message_count,
                COALESCE(c.incivil_classified_count, 0) AS incivil_classified_count,
                COALESCE(c.like_minded_count, 0) AS like_minded_message_count,
                COALESCE(c.like_minded_classified_count, 0) AS like_minded_classified_count
            FROM sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS msg_count
                FROM messages GROUP BY session_id
            ) m USING (session_id)
            LEFT JOIN (
                SELECT
                    m.session_id,
                    COUNT(*) AS agent_msg_count,
                    COUNT(*) FILTER (WHERE m.is_incivil IS TRUE) AS incivil_count,
                    COUNT(*) FILTER (WHERE m.is_incivil IS NOT NULL) AS incivil_classified_count,
                    COUNT(*) FILTER (WHERE m.is_like_minded IS TRUE) AS like_minded_count,
                    COUNT(*) FILTER (WHERE m.is_like_minded IS NOT NULL) AS like_minded_classified_count
                FROM messages m
                JOIN sessions s2 ON s2.session_id = m.session_id
                WHERE m.sender <> s2.user_name
                GROUP BY m.session_id
            ) c USING (session_id)
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
                "agent_message_count": r["agent_message_count"],
                "incivil_message_count": r["incivil_message_count"],
                "incivil_classified_count": r["incivil_classified_count"],
                "like_minded_message_count": r["like_minded_message_count"],
                "like_minded_classified_count": r["like_minded_classified_count"],
                "incivil_pct": round(
                    (r["incivil_message_count"] / r["incivil_classified_count"]) * 100, 1
                ) if r["incivil_classified_count"] > 0 else None,
                "like_minded_pct": round(
                    (r["like_minded_message_count"] / r["like_minded_classified_count"]) * 100, 1
                ) if r["like_minded_classified_count"] > 0 else None,
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


@app.get("/admin/sessions/csv/{experiment_id}")
async def admin_sessions_csv(experiment_id: str, x_admin_key: str = Header(None)):
    """Download all session data for an experiment as a flat CSV.

    One row per message. Includes experiment parameters, session metadata,
    and per-message classifier labels for cross-experiment comparison.
    """
    _require_admin(x_admin_key)
    pool = _get_pool()

    async with pool.acquire() as conn:
        exp_row = await conn.fetchrow(
            "SELECT experiment_id, description, config FROM experiments WHERE experiment_id = $1",
            experiment_id,
        )
    if not exp_row:
        raise HTTPException(status_code=404, detail=f"Experiment '{experiment_id}' not found")

    cfg = exp_row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    sim = cfg.get("simulation", {})

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                s.session_id, s.treatment_group, s.status, s.user_name,
                s.started_at, s.ended_at, s.end_reason,
                m.message_id, m.sender, m.content, m.sent_at,
                m.is_incivil, m.is_like_minded,
                m.inferred_participant_stance, m.classification_rationale,
                m.reply_to, m.reported
            FROM sessions s
            JOIN messages m ON m.session_id = s.session_id
            WHERE s.experiment_id = $1
            ORDER BY s.started_at, m.seq
        """, experiment_id)

    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "experiment_id", "description",
        "director_model", "performer_model", "moderator_model", "classifier_model",
        "session_duration_minutes", "messages_per_minute", "context_window_size",
        "session_id", "treatment_group", "session_status",
        "session_started_at", "session_ended_at", "end_reason",
        "message_id", "sender", "sender_type", "content", "sent_at",
        "is_incivil", "is_like_minded",
        "inferred_participant_stance", "classification_rationale",
        "reply_to", "reported",
    ])
    for r in rows:
        sender_type = "participant" if r["sender"] == r["user_name"] else "agent"
        writer.writerow([
            experiment_id,
            exp_row["description"] or "",
            f"{sim.get('director_llm_provider','')}:{sim.get('director_llm_model','')}",
            f"{sim.get('performer_llm_provider','')}:{sim.get('performer_llm_model','')}",
            f"{sim.get('moderator_llm_provider','')}:{sim.get('moderator_llm_model','')}",
            f"{sim.get('classifier_llm_provider','')}:{sim.get('classifier_llm_model','')}",
            sim.get("session_duration_minutes", ""),
            sim.get("messages_per_minute", ""),
            sim.get("context_window_size", ""),
            str(r["session_id"]),
            r["treatment_group"],
            r["status"],
            r["started_at"].isoformat() if r["started_at"] else "",
            r["ended_at"].isoformat() if r["ended_at"] else "",
            r["end_reason"] or "",
            str(r["message_id"]),
            r["sender"],
            sender_type,
            r["content"],
            r["sent_at"].isoformat(),
            r["is_incivil"] if r["is_incivil"] is not None else "",
            r["is_like_minded"] if r["is_like_minded"] is not None else "",
            r["inferred_participant_stance"] or "",
            r["classification_rationale"] or "",
            str(r["reply_to"]) if r["reply_to"] else "",
            r["reported"],
        ])

    buf.seek(0)
    filename = f"{experiment_id}_sessions.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
