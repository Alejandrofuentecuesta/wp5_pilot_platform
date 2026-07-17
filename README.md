# WP5 Pilot Platform v2 — Getting Started from Scratch

This README is intended for someone starting from zero: a new machine, nothing set up, who wants to run the platform locally using this repository.

## Pipeline Documentation

For a detailed explanation of the conversational pipeline — including `prompt-based` and `agent-based` modes, `self-report`, bot selection, and the Director loop:

- [Pipeline README](./docs/PIPELINE-README.md)
- [Pipeline Diagram](./docs/pipeline-diagram.svg)

## 1) Prerequisites (install from scratch)

### 1.1 Git
- Download and install Git: https://git-scm.com/downloads
- Verify:

```bash
git --version
```

### 1.2 Docker Desktop (includes Docker Compose)
- Install Docker Desktop: https://docs.docker.com/get-docker/
- Open Docker Desktop and wait until it shows "running".
- Verify:
```bash
docker --version
docker compose version
```
> If `docker compose version` fails, update Docker Desktop.

---

## 2) Clone the repository

```bash
git clone <REPO_URL>
cd wp5_pilot_platform_v2
```

If you already have it cloned, enter the project folder:

```bash
cd wp5_pilot_platform_v2
```

---

## 3) Create your environment file

Copy the variable template:

```bash
cp .env.example .env
```

Open `.env` and fill in at least:
- `ADMIN_PASSPHRASE` (required to access the admin panel)
- API keys for the LLM provider you plan to use (`ANTHROPIC_API_KEY`, `HF_API_KEY`, `GEMINI_API_KEY`, etc.)

Optional (if you have ports already in use):
- `BACKEND_PORT` (default: 8000)
- `FRONTEND_PORT` (default: 3000)

---

## 4) Start the platform

From the repo root:

```bash
docker compose up --build
```

This starts:
- PostgreSQL
- Redis
- Backend (API)
- Frontend (web + admin)

Once it finishes starting up:
- Frontend: `http://localhost:3000` (or the value of `FRONTEND_PORT`)
- Admin: `http://localhost:3000/admin`
- Backend: `http://localhost:8000` (or the value of `BACKEND_PORT`)

---

## 5) First access to the Admin panel

1. Open `http://localhost:3000/admin`
2. Enter the `ADMIN_PASSPHRASE` you set in `.env`
3. Configure the experiment using the setup wizard

---

## 6) Basic operation commands

### View logs
```bash
docker compose logs -f
```

### Stop services
```bash
docker compose down
```

### Stop and delete volumes (full local data reset)
```bash
docker compose down -v
```

### Restart and rebuild images
```bash
docker compose up -d --build
```

---

## 7) Common issues

### Error: `Bind for 0.0.0.0:8000 failed: port is already allocated`
Port 8000 is in use by another process.
Fix:
1. Edit `.env`
2. Change, for example:
   - `BACKEND_PORT=8010`
   - `FRONTEND_PORT=3001` (if port 3000 is also taken)
3. Restart:
```bash
docker compose up --build
```

### Docker won't start
- Make sure Docker Desktop is open and in running state.
- Restart Docker Desktop.

### I changed `.env` but don't see the changes
Recreate the containers:
```bash
docker compose up -d --force-recreate
```

---

## 8) Quick checklist (zero to running)

1. Install Git ✅
2. Install Docker Desktop ✅
3. Clone the repo ✅
4. `cp .env.example .env` ✅
5. Fill in `ADMIN_PASSPHRASE` + API key(s) ✅
6. `docker compose up --build` ✅
7. Open `http://localhost:3000/admin` ✅

Done.

---

## Desktop launcher

If you want to start the platform with a double-click from your desktop, use the included launchers:

- **Linux:** `scripts/start-linux.sh`
- **macOS:** `scripts/start-macos.command`
- **Windows:** `scripts/start-windows.bat`

Minimum steps:
1. Run the launcher for your OS once.
2. It will create `.env` if it doesn't exist and start Docker automatically.
3. Create a desktop shortcut to the launcher for future use.

> Requirements: Docker + Docker Compose installed.
> If `8000` or `3000` are in use, change `APP_PORT` and/or `FRONTEND_PORT` in `.env`.

---

## Citation

If you use this platform in your research, please cite it:

> Kiddle, R., van Atteveldt, W., de la Fuente Cuesta, A., Garcia, M., & Casadevall, A. (2026). *STAGElab: A Platform for Agent-Generated Experiments* [Software]. GitHub. https://github.com/Rptkiddle/wp5_pilot_platform

A methods paper is forthcoming — this section will be updated with a full reference when available.

### References

- Kim, Y., Gu, K., Park, C., et al. (2025). *Towards a Science of Scaling Agent Systems*. arXiv preprint [arXiv:2512.08296](https://arxiv.org/abs/2512.08296).
- Vezhnevets, A. S., Agapiou, J. P., Aharon, A., et al. (2023). *Generative agent-based modeling with actions grounded in physical, social, or digital space using Concordia*. arXiv preprint [arXiv:2312.03664](https://arxiv.org/abs/2312.03664).

GitHub also provides a "Cite this repository" button (powered by [`CITATION.cff`](CITATION.cff)).

## License

This project is licensed under the [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html) — you are free to use, modify, and distribute this software, provided that any derivative work is also released under the same license and includes attribution to the original author.
