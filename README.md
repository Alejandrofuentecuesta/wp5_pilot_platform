# What-If - WP5 Pilot Platform

This is a research platform for integrating AI agents into simulated social media environments to support immersive user studies. In this current iteration, a single human participant interacts with multiple AI agents in a chatroom, with agent behaviour driven by experimentally controlled treatment conditions.

**Status**: Under active development for the [What-If](https://what-if-horizon.eu/) project by https://github.com/Rptkiddle.


## STAGE Framework

The platform is powered by **STAGE** (**S**imulated **T**heater for **A**gent-**G**enerated **E**xperiments), a multi-agent framework that separates agent coordination from message generation.

| Role | Responsibility |
|------|----------------|
| **Director** | Reads the chatroom and decides *who speaks next*, *what kind of action to take*, and *who to address*. Balances two criteria: **internal validity** (is the conversation satisfying the treatment?) and **ecological validity** (would it look natural to a human?). Passes structured instructions — *Objective, Motivation, Directive* — to the Performer. |
| **Performer** | Generates the actual chatroom message in the agent's voice, from the Director's instructions. Can be swapped or fine-tuned for domain- or language-specific online speech.|
| **Moderator** | Quality gate that extracts clean message content from the Performer's raw output. If extraction fails, the Performer is retried (up to 3 attempts). |

All models should be capable at instruction following. The director model should be a large, possibly reasoning model, as it is responsible for monitoring internal and ecological valicity criteria and directing the actions of agents accordingly. The performer model should be a smaller model with domain or language-specific pretraining or fine-tuning, permissive of more convincing online speech in the target domain/language. This seperation of concerns allows for specification of models better specialized for each of these tasks.

All identities (agents and participant) are replaced with shuffled anonymous labels (*"Member 1", "Member 2", ...*) before being sent to any LLM, preventing the model from distinguishing human from agent and eliminating name-associated bias. Participant display names are stored only in the browser on their device and never sent to the backend.

> ⚠️ **Cautionary note on emergent content:** Because the STAGE framework coordinates multiple generative models, the resulting chatroom discourse is emergent and cannot be fully predetermined. Responsibility for participant safety lies with the researcher, who must ensure appropriate informed consent, ethical approval, and active monitoring of study sessions. This is especially important when using unaligned, fine-tuned, or otherwise higher-risk models within the pipeline.

## Installation

Requires [Docker](https://docs.docker.com/get-docker/) with Compose.

### Local development

```bash
# 1. Create your environment file from the template
cp .env.example .env

# 2. Open .env and set your ADMIN_PASSPHRASE and API keys for the
#    LLM providers you plan to use (see .env.example for the full list)

# 3. Start everything (PostgreSQL, Redis, backend, and frontend)
docker compose up
```

The backend will be available at `http://localhost:8000` and the frontend at `http://localhost:3000`.

### BSC performer integration

The platform now includes the BSC WHAT-IF incivility API as an LLM provider for the `Performer` role.

- Provider id in the admin wizard: `bsc`
- Suggested model: `incivility`
- Environment variables: `BSC_API_KEY` and optional `BSC_API_BASE_URL`

Use this when you want short, social-media style replies from the performer while keeping a stronger general model for the Director. Integration notes and API behavior are documented in [docs/BSC-INCIVILITY-API.md](docs/BSC-INCIVILITY-API.md).

### Arranque directo desde el escritorio

Si quieres iniciar la plataforma con doble clic desde el escritorio, usa los launchers incluidos:

- **Linux:** `scripts/start-linux.sh`
- **macOS:** `scripts/start-macos.command`
- **Windows:** `scripts/start-windows.bat`

Pasos mínimos:
1. Ejecuta una vez el launcher de tu sistema.
2. Se creará `.env` si no existe y se levantará Docker automáticamente.
3. Crea un acceso directo en el escritorio al launcher y úsalo para futuros arranques.

> Requisito: Docker + Docker Compose instalados.
> Si `8000` o `3000` están ocupados, cambia `APP_PORT` y/o `FRONTEND_PORT` en `.env`.

### Production deployment

For hosting on a server where participants will access the platform over the internet:

```bash
# 1. Create your environment file
cp .env.example .env

# 2. Edit .env — set these values:
#    ADMIN_PASSPHRASE=<a strong passphrase>
#    DOMAIN=yourdomain.example.com
#    NEXT_PUBLIC_BACKEND_BASE=            (leave empty)
#    + your LLM API keys

# 3. Start with the production profile (includes Caddy reverse proxy)
docker compose --profile production up -d
```

This starts a [Caddy](https://caddyserver.com/) reverse proxy that:
- Serves both the frontend and backend on a single domain
- Automatically obtains and renews HTTPS certificates via Let's Encrypt
- Handles WebSocket upgrades for the chat connections

Your server must have **ports 80 and 443 open** and the domain's DNS must point to the server's IP address. Once running, the platform is available at `https://yourdomain.example.com` and the admin panel at `https://yourdomain.example.com/admin`.

## Quick Start

All experiment configuration and monitoring is managed through the **Admin Panel** at `http://localhost:3000/admin`. 

### Setup

If no experiment is currently active, the admin panel will direct you to a setup wizard:

![Setup Wizard](https://github.com/user-attachments/assets/ab72014c-fe6e-4997-a92d-44aca71c1b7a)

1. **Experiment Identity** — unique experiment ID and description
2. **Session & Agents** — duration, agent settings, message pacing
3. **LLM Pipeline** — Director, Performer, and Moderator model selection and testing
4. **Treatment Groups** — chatroom context, treatment descriptions, composable features.
5. **Participant Tokens** — auto-generate random single-use tokens with CSV download
6. **Review & Save** — review all settings and save experiment to the database (as read-only)

Once an experiment is saved, its configuration is locked in and cannot be changed.

You can pause and resume experiments, as well as reset or delete them, from the dashboard (see below).

If you want to try the BSC model first, set the LLM pipeline like this:

- `Director`: a strong general model such as Anthropic or Mistral
- `Performer`: `bsc` / `incivility`
- `Moderator`: a reliable extraction model
- `Classifier`: a reliable structured-output model


### Dashboard

After saving an experiment, the admin panel switches to a monitoring dashboard with five tabs:

![Admin Dashboard](https://github.com/user-attachments/assets/8adf5502-a030-4294-8461-ac7dd7324096)

- **Overview** — live statistics, per-group enrollment, experimental configuration, CSV token download, and quick actions to edit or duplicate an experiment as a new editable draft.
- **Sessions** — table of all sessions with status, treatment group, token, timestamps, duration, and message count, plus export links (HTML report and CSV for ended sessions).
- **Evaluate** — annotation workspace to label session messages (incivility, hate speech, threats, impoliteness, stance, human-like, notes) and download the annotated CSV.
- **Logs** — real-time event stream, filterable by event type, with error highlighting.
- **Settings** — pause and resume enrollment, danger zone for resetting sessions (keeps config and tokens) or permanently deleting an experiment and all its data; both require typing the experiment ID to confirm.

The dashboard polls the backend continuously so no manual refresh is needed.

If you have multiple experiments, you can switch between them using the dropdown in the header. 

### Session CSV export for annotation

When a session ends, the backend automatically writes an annotation-ready CSV with one row per chat message.

- Default output directory: `backend/exports/session_csv/`
- Filename format: `<session_id>.csv`
- Columns: `message`, `incivility`, `hate_speech`, `threats_to_dem_freedom`, `impoliteness`, `stance`, `human_like`, `other`

You can override the output directory with the `SESSION_CSV_EXPORT_DIR` environment variable.


## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/session/start` | Consume a participant token and reserve a session |
| `WS` | `/ws/{session_id}` | WebSocket for real-time chat (handles reconnects) |
| `POST` | `/session/{id}/message/{mid}/like` | Toggle a like on a message |
| `POST` | `/session/{id}/message/{mid}/report` | Report a message (optionally block sender) |
| `GET` | `/session/{id}/report` | Generate an HTML session report from the DB |
| `GET` | `/session/{id}/messages-csv` | Download annotation CSV for session messages |
| `GET` | `/health` | Health check |

### Admin Endpoints

Protected by `X-Admin-Key` header (must match `ADMIN_PASSPHRASE`). Returns 503 if the passphrase is not configured, 401 if incorrect.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/verify` | Verify admin passphrase |
| `GET` | `/admin/meta` | Platform metadata (available features, LLM providers and models) |
| `POST` | `/admin/test-llm` | Test an LLM provider with a sample prompt |
| `GET` | `/admin/config/{experiment_id}` | Return saved config for an experiment |
| `POST` | `/admin/config` | Validate and save experiment config to the database |
| `GET` | `/admin/experiments` | List all experiments with summary counts |
| `POST` | `/admin/experiment/{id}/activate` | Set the active experiment |
| `POST` | `/admin/experiment/{id}/pause` | Pause enrollment for an experiment |
| `POST` | `/admin/experiment/{id}/resume` | Resume enrollment for an experiment |
| `POST` | `/admin/tokens/generate` | Generate cryptographically random participant tokens |
| `GET` | `/admin/tokens/stats` | Token usage statistics for an experiment |
| `GET` | `/admin/tokens/csv/{experiment_id}` | Download tokens as CSV |
| `GET` | `/admin/sessions` | List sessions for an experiment |
| `GET` | `/admin/events` | Cursor-based event stream (filterable by type) |
| `POST` | `/admin/reset-sessions` | Delete sessions but keep config and tokens |
| `POST` | `/admin/reset-db` | Delete an experiment and all its data |

## Running Tests

```bash
# Run the full test suite inside Docker (recommended):
docker compose run --rm test

# Or run locally against a running stack:
cd backend
TEST_DATABASE_URL=postgresql://wp5user:wp5pass@localhost:5432/wp5 \
  python -m pytest tests/ -v

# DB tests skip gracefully when PostgreSQL is not reachable.
```

## Project Structure

```
wp5_pilot_platform/
├── docker-compose.yml        # PostgreSQL + Redis + backend + frontend
├── .env.example              # Environment variable template
├── backend/
│   ├── main.py               # FastAPI app: lifespan, REST + WebSocket endpoints
│   ├── agents/
│   │   ├── agent_manager.py  # Handles turn results: DB persist + Redis publish
│   │   └── STAGE/            # Director-Performer-Moderator pipeline
│   ├── platforms/
│   │   └── chatroom.py       # SimulationSession: tick loop, DB writes, pub/sub
│   ├── db/                   # PostgreSQL schema, connection pool, repositories
│   ├── cache/                # Redis client (session cache, pub/sub, context window)
│   ├── models/               # Agent, Message, SessionState dataclasses
│   ├── features/             # Composable session features (seed content, agent gating)
│   ├── utils/                # Logger, session/token managers, LLM clients
│   └── tests/                # pytest suite (Redis + DB tests)
├── frontend/                 # Next.js chat UI + researcher admin panel (/admin)
│   ├── app/                  # Page routes (participant chat + admin)
│   ├── components/           # Chat UI components + admin wizard
│   ├── hooks/                # useChat, useWebSocket, useLocalStorage
│   └── lib/                  # Types, API helpers, constants
└── README.md
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html) — you are free to use, modify, and distribute this software, provided that any derivative work is also released under the same license and includes attribution to the original author. 
