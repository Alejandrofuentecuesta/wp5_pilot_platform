# STAGElab

A research platform for running controlled human-facing experiments in AI-agent chatrooms. A single human participant interacts with multiple AI agents whose behaviour is coordinated to realise experimentally controlled treatment conditions.

**Status**: Under active development for the [What-If](https://what-if-horizon.eu/) project by https://github.com/Rptkiddle.

![Chatroom â€” participant view](assets/chatroom.png)

**[STAGE Framework](#stage-framework)** Â· **[Installation](#installation)** Â· **[Setup Wizard](#setup-wizard)** Â· **[Dashboard](#dashboard)** Â· **[API](#api-endpoints)** Â· **[Project Structure](#project-structure)**


## STAGE Framework

**STAGE** (**S**imulated **T**heater for **A**gent-**G**enerated **E**xperiments) is a generative multi-agent coordination framework that lets a researcher describe experimental conditions in plain language and produces a live chatroom that realises those conditions around a real human participant.

In a participant-facing chatroom experiment, the experimental stimulus is not a fixed input â€” it is a property of the *conversation itself*, emerging from the complex interactions of multiple AI agents and a human participant. The researcher cannot script this discourse in advance. It must unfold naturally, respond to whatever the human says, and still satisfy the intended experimental manipulation. STAGE governs this emergence.

STAGE gives the researcher two levers â€” **internal validity** criteria (what the experimental manipulation requires, defined per treatment group) and **ecological validity** criteria (what makes the experience feel realistic, defined per experiment) â€” and uses a dedicated coordinating model (the Director) to steer every agent action toward both goals simultaneously. Message generation is handled by a separate model (the Performer) that can be swapped or fine-tuned for natural online speech in the target language or domain, while all identities are anonymised so the Director cannot distinguish human from agent.

### Design

STAGE adopts the **centralised orchestrator** pattern from multi-agent system design (Kim et al., 2025) â€” a dedicated coordinator plans and delegates work to task-specific agents, rather than allowing agents to act independently. This allows the platform to handle the many degrees of freedom in multi-agent interaction â€” turn-taking, action selection, targeting, and other dialogics â€” without requiring the researcher to specify these dynamics in advance. 

The design draws inspiration from Concordia (Vezhnevets et al., 2023), which introduced the Game Master pattern for generative agent-based simulations. Whereas Concordia facilitates open-ended social simulation between autonomous agents, STAGE is purpose-built for **treatment-outcome research with human participants**: the simulation framework optimises for researcher-defined validity criteria, and the platform provides the surrounding infrastructure needed to run controlled studies.

> **Cautionary note on emergent content:** Because STAGE coordinates multiple large language models (LLMs), the resulting chatroom discourse is emergent and cannot be fully predetermined. Responsibility for participant safety lies with the researcher, who must ensure appropriate informed consent, ethical approval, and active monitoring of study sessions. This is especially important when using unaligned, fine-tuned, or otherwise higher-risk models within the pipeline.

### Roles

| Role | Responsibility |
|------|----------------|
| **Director** | Behind-the-scenes coordinator that never produces visible messages. It maintains a model of each participant's behaviour, monitors the chatroom against researcher-defined validity criteria, and on each turn decides *who* should speak, *what kind* of action they should take, and *what* they should try to achieve. This is expressed as a structured instruction (Objective, Motivation, Directive). |
| **Performer** | Generates the chatroom message. It receives the Director's O/M/D instruction, the participant's accumulated behavioural profile, their most recent messages, the relevant target message (if the action requires responding to one). This separation-of-concerns means the Performer can be swapped or fine-tuned for domain- or language-specific online speech, and multiple performers can be called on depending on the type of speech required. |
| **Moderator** | Quality gate that extracts clean message content from the Performer's raw output, stripping any reasoning, meta-commentary, or formatting artefacts. If extraction fails, the Performer is retried (up to 3 attempts). |

### Validity criteria

The Director balances two researcher-defined criteria that shape every action decision:

- **Internal validity** â€” defined per treatment group (e.g. *"the chatroom should strike a mildly uncivil tone"*). Ensures the conversation satisfies the experimental manipulation.
- **Ecological validity** â€” defined per experiment (e.g. *"messages should be short, informal, and dialogic"*). Ensures the conversation would look natural to a human participant.

The Evaluate call (below) produces running assessments of both criteria, maintained by the Director.

### Per-turn pipeline

Each orchestrator turn runs the following sequence. The tick loop fires every second, with a configurable probability gate controlling how often a turn actually executes. For now, turns are sequential, meaning that only one agent can act at a time. All director reasoning for all decision-making is logged. 

```
 1. Director Update     â€” revise last acting participant's behavioural profile
                          (skipped on first turn; skipped for likes)
 2. Director Evaluate   â€” revise validity assessments against the recent
                          chat log (every turn during warm-up, then every
                          evaluate_interval turns as set by researcher)
 3. Director Action     â€” read validity evaluations + profiles + chat log â†’
                          select performer, action type, target, write O/M/D
 4. Performer           â€” generate message from O/M/D + profile + target
                          (skipped for likes)
 5. Moderator           â€” extract message content (retry up to 3Ã—)
```

### Action types

The Director selects one action per turn:

| Action | Description |
|--------|-------------|
| `message` | A new message to the room. Can be a standalone contribution (`target_user` = null) or a response to a specific participant's most recent message (`target_user` = X). |
| `reply` | Quote-reply to a specific earlier message â€” used to resurface something from further back in the conversation. |
| `@mention` | Message directed at a participant who did not send the most recent message â€” used to draw them back into the conversation. |
| `like` | Non-verbal endorsement of a message (no Performer call needed). |


### Anonymization

All identities (performers and participant) are replaced with shuffled anonymous labels (*"Performer 1", "Performer 2", ...*) before any LLM call, via a seeded shuffle that remains stable for the session. This prevents the Director from distinguishing the human from agents and eliminates name-associated bias. The human's display name is stored only in the browser and never sent to the backend â€” the backend knows the human only as `"participant"`, and the LLM knows them only as one of the numbered performers.

### Model selection

The Director, Performer, and Moderator each use independently configured LLM providers and models. The Director should be a capable instruction-following model (it reasons over validity criteria and makes multi-step decisions). The Performer can be a smaller or fine-tuned instruction-following model optimised for convincing online speech in the target language or domain. The Moderator needs only basic extraction capability. This separation allows each role to use the model best suited to its task.

### Validation scripts

A script in `backend/agents/STAGE/validation/` supports manual inspection of the pipeline:

#    If ports are already occupied, set FRONTEND_PORT / BACKEND_PORT too.
docker compose up --build

By default, the backend is available at `http://localhost:8000` and the frontend at `http://localhost:3000`.
If those ports are in use, change `BACKEND_PORT` / `FRONTEND_PORT` in `.env`.


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

### Production deployment

For hosting on a server where participants will access the platform over the internet:

```bash
# 1. Create your environment file
cp .env.example .env

# 2. Edit .env â€” set these values:
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

### Setup Wizard

If no experiment is currently active, the admin panel will direct you to a setup wizard:

![Setup Wizard](assets/wizard.png)

The wizard walks you through six steps. Once an experiment is saved, its configuration is **immutable** â€” to change settings you must create a new experiment.

<details>
<summary><b>Step 1: Experiment Identity</b></summary>

| Setting | Description |
|---------|-------------|
| **Experiment ID** | Unique identifier for this experiment (e.g. `pilot_2026_civility`). Used to isolate data in the database. |
| **Description** | Free-text note for your own reference. |
| **Starts At / Ends At** | Optional participation window â€” outside this window, tokens will be rejected. |
| **Redirect URL** | Optional URL to send participants to after their session ends (e.g. a Qualtrics survey). If empty, a built-in thank-you page is shown. |

</details>

<details>
<summary><b>Step 2: Session & Agents</b></summary>

| Setting | Default | Description |
|---------|---------|-------------|
| **Duration** | 5 min | How long each session lasts before it ends automatically. |
| **Number of Agents** | 5 | How many AI agents appear in the chatroom alongside the participant. |
| **Agent Names** | â€” | Display names the participant sees (e.g. "Alex", "Sam"). Participant-facing only; the LLM pipeline uses anonymised labels. |
| **Random Seed** | 42 | Controls the anonymised name shuffle and other randomised behaviour. Use the same seed for reproducibility. |

**Pacing & pipeline settings:**

| Setting | Default | Description |
|---------|---------|-------------|
| **Messages Per Minute** | 6 | Target upper bound for message frequency. The tick loop fires every second; this value controls the probability that a given tick triggers a turn. Actual throughput is also limited by LLM latency. |
| **Validity Check Interval** | 5 | After the warm-up period, the Director's Evaluate call runs every *N* turns. During warm-up (the first *N* turns), it runs every turn. Higher values reduce LLM costs but make the Director less responsive to drift. |
| **Action Window Size** | 5 | How many recent messages the Director sees in its Action and Evaluate calls. Larger windows give more context but increase token usage. |
| **Performer Memory Size** | 3 | How many of the Performer's own recent messages are included in its prompt to help prevent repetition. Set to 0 to disable. |

</details>

<details>
<summary><b>Step 3: LLM Pipeline</b></summary>

Select a provider and model for each of the three STAGE roles. Available providers depend on which API keys are set in your `.env`. Each role has a **Test** button to verify the connection before proceeding.

| Role | Responsibility | Model guidance |
|------|----------------|----------------|
| **Director** | Decides who speaks, selects the action type, and writes the structured instruction. | Needs strong instruction-following and reasoning (e.g. Claude Haiku, GPT-4o-mini). |
| **Performer** | Generates the actual chatroom message. | Can be a smaller or fine-tuned model optimised for natural online speech in the target language or domain. |
| **Moderator** | Extracts clean content from the Performer's raw output. | A fast, cheap model with low temperature works well. |

Each role has independent settings for **provider**, **model**, **temperature**, **top-p**, and **max tokens**. Default generation parameters:

|  | Director | Performer | Moderator |
|--|----------|-----------|-----------|
| Temperature | 0.8 | 0.8 | 0.2 |
| Top-p | 0.8 | 0.8 | 1.0 |
| Max tokens | 1024 | 256 | 256 |

Some providers treat temperature and top-p as mutually exclusive â€” the wizard warns you if so.

</details>

<details>
<summary><b>Step 4: Treatment Groups</b></summary>

**Global context** (shared across all groups):

| Setting | Description |
|---------|-------------|
| **Chatroom Context** | Description of the chatroom scenario injected into every prompt (e.g. *"A Telegram group chat about climate change policy"*). |
| **Ecological Validity Criteria** | What "realistic" behaviour looks like. Guides the Director's Evaluate call (e.g. *"Messages should be short, informal, and include a mix of replies, mentions, and likes"*). |

**Per-group settings** â€” each group defines one treatment condition:

| Setting | Description |
|---------|-------------|
| **Group Name** | Identifier for the condition (e.g. `civil`, `uncivil`). Auto-sanitised to lowercase with underscores. |
| **Internal Validity Criteria** | What the experimental manipulation requires for this condition. This is the key lever: the Director uses it to steer agent behaviour. Be precise (e.g. *"3 of the 5 agents should express climate-sceptical views; the remaining 2 should be climate-concerned"*). |
| **Features** | Optional composable features: **News Article** (seeds the conversation with an article) and **Gate Until User Post** (agents wait for the participant to post first). |

You can add groups manually or use the **2x2 Factorial Design Builder** to generate four groups from two dimensions (e.g. *civility* x *stance*).

</details>

<details>
<summary><b>Step 5: Participant Tokens</b></summary>

Generate single-use access codes, one per participant. Each token is pre-assigned to a treatment group, ensuring balanced enrollment. Download as **CSV** for distribution (e.g. embed in survey links).

</details>

<details>
<summary><b>Step 6: Review & Save</b></summary>

A read-only summary of all settings. Click **Save** to write the configuration to the database and activate the experiment â€” participants can immediately start joining with their tokens.

To modify settings after saving, create a new experiment with a new ID. You can pause, reset, or delete experiments from the dashboard.

</details>


### Dashboard

After saving an experiment, the admin panel switches to a monitoring dashboard with four tabs:

![Admin Dashboard](assets/dashboard.png)

- **Overview** â€” live statistics, per-group enrollment, experimental configuration, and CSV token download.
- **Sessions** â€” table of all sessions with status, treatment group, token, timestamps, duration, and message count.
- **Logs** â€” real-time event stream, filterable by event type, with error highlighting.
- **Settings** â€” pause and resume enrollment, danger zone for resetting sessions (keeps config and tokens) or permanently deleting an experiment and all its data; both require typing the experiment ID to confirm.

The dashboard polls the backend continuously so no manual refresh is needed.

If you have multiple experiments, you can switch between them using the dropdown in the header. 


## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/session/start` | Consume a participant token and reserve a session |
| `WS` | `/ws/{session_id}` | WebSocket for real-time chat (handles reconnects) |
| `POST` | `/session/{id}/message/{mid}/like` | Toggle a like on a message |
| `POST` | `/session/{id}/message/{mid}/report` | Report a message (optionally block sender) |
| `GET` | `/session/{id}/report` | Generate an HTML session report from the DB |
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

> âš ï¸ **NOTE**: these are for development purposes, and should not be run during normal usage of the platform.

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
â”œâ”€â”€ docker-compose.yml        # PostgreSQL + Redis + backend + frontend
â”œâ”€â”€ .env.example              # Environment variable template
â”œâ”€â”€ backend/
â”‚   â”œâ”€â”€ main.py               # FastAPI app: lifespan, REST + WebSocket endpoints
â”‚   â”œâ”€â”€ agents/
â”‚   â”‚   â”œâ”€â”€ agent_manager.py  # Handles turn results: DB persist + Redis publish
â”‚   â”‚   â””â”€â”€ STAGE/            # Director-Performer-Moderator pipeline
â”‚   â”œâ”€â”€ platforms/
â”‚   â”‚   â””â”€â”€ chatroom.py       # SimulationSession: tick loop, DB writes, pub/sub
â”‚   â”œâ”€â”€ db/                   # PostgreSQL schema, connection pool, repositories
â”‚   â”œâ”€â”€ cache/                # Redis client (session cache, pub/sub, context window)
â”‚   â”œâ”€â”€ models/               # Agent, Message, SessionState dataclasses
â”‚   â”œâ”€â”€ features/             # Composable session features (seed content, agent gating)
â”‚   â”œâ”€â”€ utils/                # Logger, session/token managers, LLM clients
â”‚   â””â”€â”€ tests/                # pytest suite (Redis + DB tests)
â”œâ”€â”€ frontend/                 # Next.js chat UI + researcher admin panel (/admin)
â”‚   â”œâ”€â”€ app/                  # Page routes (participant chat + admin)
â”‚   â”œâ”€â”€ components/           # Chat UI components + admin wizard
â”‚   â”œâ”€â”€ hooks/                # useChat, useWebSocket, useLocalStorage
â”‚   â””â”€â”€ lib/                  # Types, API helpers, constants
â””â”€â”€ README.md
```

## Citation

If you use this platform in your research, please cite it:

> Kiddle, R. & van Atteveldt, W. (2026). *STAGElab: A Platform for Agent-Generated Experiments* [Software]. GitHub. https://github.com/Rptkiddle/wp5_pilot_platform

A methods paper is forthcoming â€” this section will be updated with a full reference when available.

### References

- Kim, Y., Gu, K., Park, C., et al. (2025). *Towards a Science of Scaling Agent Systems*. arXiv preprint [arXiv:2512.08296](https://arxiv.org/abs/2512.08296).
- Vezhnevets, A. S., Agapiou, J. P., Aharon, A., et al. (2023). *Generative agent-based modeling with actions grounded in physical, social, or digital space using Concordia*. arXiv preprint [arXiv:2312.03664](https://arxiv.org/abs/2312.03664).

GitHub also provides a "Cite this repository" button (powered by [`CITATION.cff`](CITATION.cff)).

## License

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html) â€” you are free to use, modify, and distribute this software, provided that any derivative work is also released under the same license and includes attribution to the original author.

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
