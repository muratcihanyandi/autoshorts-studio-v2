# Architecture — Autonomous Creator Studio

Status: initial version (Milestone 0). Everything marked **[VERIFIED]** was
confirmed by direct inspection on 2026-10-16. Everything marked **[PLANNED]**
is a design decision not yet implemented; see `docs/DECISIONS.md`.

## 1. System Context

```
+---------------------------+          +----------------------------------+
| Windows 11 dev machine    |          | Raspberry Pi 5 (8GB, ARM64)      |
| (authoring, testing)      |          | CasaOS host                      |
|                           |          |                                  |
|  - ZCode agent (GLM-5.3)  |--LAN/--->|  - Docker engine                 |
|  - git, Node 24,          |          |  - PostgreSQL 17.10 container    |
|    Python 3.11, ffmpeg 8  |          |    (172.18.0.2:5432)             |
|  - postgres MCP (read-    |          |  - [PLANNED] app stack:          |
|    only, to Pi DB)        |          |    backend + frontend + worker   |
|  - NO Docker CLI          |          |    + dedicated postgres + volumes|
+---------------------------+          +----------------------------------+
                                       | YouTube Data API / OAuth 2.0     |
                                       | LLM provider APIs                |
                                       +----------------------------------+
```

### Verified environment facts

| Fact | Evidence |
|---|---|
| Workspace path | `C:\Users\Murat\Documents\AutoShortsStudio_RaspberryPi5_2`; contains only `AGENTS.md`, `docs/ROADMAP.md`, `docs/PROGRESS.md`, and three empty directories (`backend/`, `frontend/`, `Autonomous-Creator-Studio/`) |
| Not a git repository | `git status` → `fatal: not a git repository` before Milestone 0 |
| Git available | git 2.52.0.windows.1 via `C:\Program Files\Git\cmd\git.exe` |
| GitHub CLI installed but unauthenticated | `gh auth status` → "not logged into any GitHub hosts" |
| GitHub MCP has no authenticated context | `user:@me` search returns HTTP 422 |
| Node / npm | node v24.13.0, npm 11.6.2 |
| Python | 3.11.9 with pip 24.0 |
| FFmpeg / ffprobe | 8.1.1 (gyan.dev essentials build) at `C:\ffmpeg\bin` |
| Docker on dev machine | NOT available (no `docker.exe` found; Docker Desktop data directories exist but no CLI) |
| WSL | not available |
| PostgreSQL server | PostgreSQL 17.10 (Debian 17.10-1.pgdg13+1), aarch64 — queried through the ZCode postgres MCP (read-only) |
| PostgreSQL location | `inet_server_addr()` = `172.18.0.2` (Docker bridge network address) → runs as a container on the ARM64 host, i.e. on the Raspberry Pi |
| PostgreSQL role used by MCP | `muratcihanyandi` (default database of the same name) |
| Existing databases on that server | affine, balkurye, fakeyol, mmorpg, muratcihanyandi, n8n, nodehabercom, paketci, postgres, raspberrypi, wedding_memories — no project database exists yet |
| Target CPU architecture | aarch64 / ARM64 (from the PostgreSQL server build; Raspberry Pi 5) |
| Skills available in ZCode | `impeccable`, `frontend-design` (for UI work), plus game/media/tooling skills — both UI skills confirmed present in the session skill list |
| MCP servers available | postgres (verified working), codebase-memory (verified working, 12 indexed projects), github (working, unauthenticated), context7, blender, node_repl |

### Facts that cannot be verified from the dev machine

- CasaOS presence and version on the Pi (strongly implied: Docker bridge
  network, multiple self-hosted service databases, `raspberrypi` database).
- Whether the previously exposed GitHub token has been revoked (only the
  user can confirm in GitHub settings; no live token exists in this
  environment).
- Whether the PostgreSQL password has been rotated (the MCP's stored
  credential works, but rotation state is only knowable by the user).

These are recorded as deployment gates in `docs/SECURITY.md`.

## 2. Component Architecture [PLANNED]

```
                       +--------------------------------------------+
                       |                FastAPI backend              |
                       |  /api/*  channels, media, calendar, jobs,   |
                       |          LLM providers, settings, logs      |
                       |  /health  liveness + readiness (DB check)   |
                       +------+-----------------+-------------------+
                              |                 |
                    SQLAlchemy 2 / Alembic    job queue tables
                              |                 |
                     +--------v--------+      +-v------------------+
                     |   PostgreSQL    |<-----|  Worker processes   |
                     | autoshorts_     |      |  - media pipeline   |
                     | studio database |      |  - vertical render  |
                     +--------^--------+      |  - subtitle/metadata|
                              |               |  - upload/publish   |
                     +--------+----------------+-------------------+
                     |        shared volumes (media cache, renders)  |
                     +--------^----------------+-------------------+
                              |
                     +--------+---------+
                     | ffmpeg / ffprobe |
                     +------------------+
```

- **Web API (FastAPI)**: serves the SPA and a JSON API. Never runs heavy
  media work in request handlers.
- **Workers**: separate processes consuming a durable PostgreSQL-backed job
  queue. Heartbeat, retry, cancellation, restart recovery (Milestone 6).
- **Media pipeline** (Milestones 7–8): authorized download → integrity +
  ffprobe inspection → transcript → clip candidates → 9:16 render.
- **LLM provider manager** (Milestone 5): three configurable providers,
  bounded fallback, structured output validation, latency/error metrics.
- **YouTube integration** (Milestones 3, 4, 10): official Data API and OAuth
  2.0 only; tokens stored encrypted; per-channel credentials.
- **Frontend (React + TS + Vite)**: studio UI (Milestone 2) served as static
  files by the backend or a small nginx container on the Pi.

## 3. Deployment Topology [PLANNED]

- `deploy/docker-compose.yml` targets `linux/arm64` explicitly.
- Services: `backend` (api), `worker`, `frontend`, `postgres`
  (`postgres:17` multi-arch image), optional `nginx`.
- A dedicated `autoshorts_studio` PostgreSQL database with a freshly
  generated role/password at deployment time. The existing shared
  PostgreSQL instance (172.18.0.2) stays untouched; using it is an
  documented alternative, never with old credentials.
- Media volumes: `media_cache` (downloads), `media_out` (renders/stock),
  with disk-space checks before new jobs.
- On CasaOS: install via App Store customCompose / Docker Compose import.

## 4. Key Constraints and Assumptions

1. **Resource ceiling**: 8GB RAM shared with other CasaOS services (n8n,
   affine, ...). FFmpeg jobs are constrained (`-threads`, single-job
   rendering), concurrency is configurable, and backpressure prevents OOM.
2. **ARM64 only**: all images must support `linux/arm64`. The dev machine
   cannot build/test containers (no Docker CLI); Compose files are
   syntax-validated locally and runtime-verified on the Pi.
3. **Content rights**: every source channel requires a recorded rights
   record; publication is blocked without it. Rights checks are enforced in
   code, independent of LLM output.
4. **Secrets**: environment variables only (`.env`, never committed).
   OAuth tokens and provider API keys are stored encrypted at rest in
   PostgreSQL (application-level encryption; key from environment).
5. **Local test strategy** (dev machine has no reachable project
   PostgreSQL credentials): unit tests run against SQLite in-memory or
   fast isolated configs; Alembic migrations are verified via offline SQL
   generation (`alembic upgrade head --sql`); full PostgreSQL verification
   happens on the Pi during deployment (documented in
   `docs/PROGRESS.md`).

## 5. Milestone 0 Directory Decision

The pre-existing empty directories `backend/` and `frontend/` are used for
their intended purpose. The pre-existing empty directory
`Autonomous-Creator-Studio/` is left untouched (git does not track empty
directories) and is not part of the planned layout.
