# Autonomous Creator Studio — Current Progress

## Current Project State

**Overall status:** Milestones 0–3 COMPLETE. Repository public on GitHub
(`muratcihanyandi/autoshorts-studio-v2`) with CI building ARM64+AMD64 images
to GHCR; the Pi runs the app (M2 interface verified live); the M3 image is
on GHCR awaiting a CasaOS restart by the user.

**Current milestone:** Milestone 4 — Source Monitoring and Planning

**Current task:** M4 kickoff — source-channel registration, YouTube
metadata integration, quota tracking, durable planning.

**Last updated:** 2026-10-17

**Primary coding agent:** GLM-5.3 via ZCode

**Target platform:** Raspberry Pi 5, 8GB RAM, CasaOS, ARM64 Linux

**Important:** This document describes the verified state. No implementation,
integration, deployment, or test is considered complete until verified
against the actual repository and environment.

## 1. Verified Environment

All items below were verified by direct inspection on 2026-10-16 unless
marked otherwise. Evidence commands are listed; none expose secrets.

- [x] Existing repository inspected. — Workspace
  `C:\Users\Murat\Documents\AutoShortsStudio_RaspberryPi5_2` contained only
  `AGENTS.md` (empty), `docs/ROADMAP.md`, `docs/PROGRESS.md` and three empty
  directories (`backend/`, `frontend/`, `Autonomous-Creator-Studio/`).
  Verified via `find <workspace> -type f`.
- [x] Git status inspected. — `git status` → `fatal: not a git repository`
  (fresh start, no prior history to preserve). Local repository initialized
  during Milestone 0 (commit `cfb1c35` baseline of original files).
- [x] ZCode workspace path verified. — See above; matches the session
  working directory.
- [x] Installed skills inspected. — Session skill list contains
  `impeccable`, `frontend-design`, and the full game/media/tooling set.
  `codebase-memory`, `postgres`, `github`, `context7`, `blender`,
  `node_repl` MCP servers are configured.
- [x] Impeccable skill availability verified. — Present in the session
  skill list; to be loaded for Milestone 2 UI work.
- [x] Frontend Design skill availability verified. — Present in the session
  skill list; to be loaded for Milestone 2 UI work.
- [x] CodebaseMemory MCP availability verified. — `list_projects` returned
  12 indexed projects (none is this workspace; includes a stale entry for
  the old `AutoShortsStudio` project).
- [x] PostgreSQL connectivity verified. — postgres MCP query succeeded:
  PostgreSQL 17.10 (Debian 17.10-1.pgdg13+1) on
  aarch64-unknown-linux-gnu, server address `172.18.0.2` (Docker bridge
  network) port 5432, role `muratcihanyandi`.
- [x] PostgreSQL database name confirmed. — Existing databases on the
  shared instance: affine, balkurye, fakeyol, mmorpg, muratcihanyandi, n8n,
  nodehabercom, paketci, postgres, raspberrypi, wedding_memories. No
  project database exists yet. **Decision (ADR-005):** the app will use a
  dedicated `autoshorts_studio` database in its own `postgres:17`
  container on the Pi with freshly generated credentials.
- [x] Raspberry Pi architecture and OS verified. — Target server CPU is
  aarch64 (from the PostgreSQL server build running on the Pi, Debian
  pgdg). Pi 5 / 8GB per project brief. OS-level details of the Pi beyond
  the PostgreSQL container cannot be inspected from the dev machine.
- [~] CasaOS deployment environment verified (partial). — Strong evidence:
  PostgreSQL runs in a Docker bridge network on the ARM64 host alongside
  typical self-hosted service databases (n8n, affine). Direct CasaOS
  verification requires access to the Pi; recorded as a deployment-time
  check.
- [~] GitHub authentication verified (negative finding). — `gh` CLI is
  installed but `gh auth status` reports "not logged into any GitHub
  hosts". The GitHub MCP server has no authenticated user context
  (`user:@me` search → HTTP 422). **No live GitHub token exists in this
  environment.** Consistent with the previously exposed token having been
  revoked, but final confirmation belongs to the user (Security gate G1).
- [ ] Private GitHub repository created or existing remote verified. —
  **BLOCKED**: requires user to run `gh auth login` or provide a new token
  (see Blockers).
- [~] Docker Compose availability verified (partial). — Docker CLI is NOT
  available on the Windows dev machine (no `docker.exe`; Docker Desktop
  data directories exist but no usable CLI; WSL unavailable). Docker IS
  running on the Pi (PostgreSQL container evidence). Compose files are
  authored here, syntax-validated locally, and executed on the Pi.
- [x] FFmpeg and ffprobe availability verified. — 8.1.1
  (gyan.dev essentials build) at `C:\ffmpeg\bin` on the dev machine;
  on the Pi the containers will use the `linux/arm64` ffmpeg builds.
- [x] Additional tooling: node v24.13.0, npm 11.6.2, Python 3.11.9,
  pip 24.0, git 2.52.0.windows.1. Git Bash on this machine requires
  `export PATH="/c/Program Files/Git/cmd:/c/Program Files/Git/usr/bin:$PATH"`
  (default PATH lacks Git `usr/bin` coreutils in the agent shell).

## 2. Milestone Status

| Milestone | Status | Notes |
|---|---|---|
| 0. Environment and Architecture | COMPLETED | All deliverables created and committed; evidence in section 3 |
| 1. Repository and Foundation | COMPLETED (local) | All local acceptance criteria verified (section 3, section 7); private GitHub remote pending user auth (B1) |
| 2. Studio Interface | COMPLETED | Yeşilçam Baskı Odası world; finish review `ship`; DESIGN.md recorded (2026-10-17) |
| 3. Database and Channel Management | COMPLETED | Migration 0002 applied on Pi DB; OAuth handshake with Fernet-encrypted tokens; channels UI; Pi restart pending (2026-10-17) |
| 4. Source Monitoring and Planning | IN_PROGRESS | Started 2026-10-17 |
| 5. LLM Provider Manager | NOT_STARTED | Three-provider fallback |
| 6. Job Queue and Resource Management | NOT_STARTED | Persistent background jobs |
| 7. Horizontal Video Processing | NOT_STARTED | Authorized media pipeline |
| 8. Vertical Studio and Webcam Detection | NOT_STARTED | Tracking and calibration |
| 9. Subtitles and Metadata | NOT_STARTED | Turkish correction |
| 10. Upload and Publishing | NOT_STARTED | Private uploads and schedules |
| 11. End-to-End Automation | NOT_STARTED | Full pipeline integration |
| 12. Production Hardening | NOT_STARTED | Stress, recovery, and security tests |

## 3. Completed Tasks

### Milestone 0 — Environment and Architecture (completed 2026-10-16)

- Date: 2026-10-16
- Milestone: 0
- Task: Environment inspection, architecture documentation, security
  checklist, git initialization.
- Implementation:
  - Inspected workspace, git state, gh auth, GitHub MCP auth context,
    node/npm/Python/pip/ffmpeg/ffprobe/Docker/WSL availability,
    PostgreSQL server (version, architecture, address, databases) via the
    read-only postgres MCP, codebase-memory MCP.
  - Created `AGENTS.md` (project agent contract; the pre-existing file was
    empty).
  - Created `docs/ARCHITECTURE.md` (verified environment facts, component
    architecture, deployment topology, constraints).
  - Created `docs/DECISIONS.md` (ADR-001 … ADR-010).
  - Created `docs/SECURITY.md` (incident context, deployment gates
    G1–G8, handling rules, verification log).
- Verification: every claim in section 1 maps to a command executed in this
  session; deliverable files exist in the repository (commits `cfb1c35`,
  `0f37870`).
- Test results: no automated tests existed at Milestone 0 (by design;
  first tests arrived in Milestone 1).
- Commit: `cfb1c35` (baseline preserving the original three files) +
  `0f37870` (Milestone 0 deliverables).
- Remaining limitations: CasaOS and Pi OS cannot be directly inspected from
  the dev machine; GitHub token revocation and PostgreSQL password rotation
  require user confirmation (gates G1, G2).

### Milestone 1 — Repository and Foundation (completed 2026-10-16, local work)

- Date: 2026-10-16
- Milestone: 1
- Task: Repository foundation, backend, frontend, ARM64 Compose, tests.
- Implementation (commits `20ffb5e`, `754ed5c`, `36f6dff`, `3b17ad3`):
  - `.gitignore` (env/secrets, venv, node_modules, media), `.gitattributes`
    (LF normalization for the Linux target), `.env.example` (keys only,
    placeholders marked CHANGE_ME), `.dockerignore` (keeps `.env` and docs
    out of images).
  - `tools/scan_secrets.py`: pattern-based secret guard (GitHub/OpenAI/AWS
    keys, DB URLs with credentials, private keys, assigned secrets,
    tracked .env check) with compose `${VAR}` expansion so variable
    references pass while secret defaults still fail; self-tested.
  - Backend (`backend/`): FastAPI app factory with lifespan-managed async
    SQLAlchemy engine; Pydantic v2 settings from environment; JSON
    structured logging with secret redaction; `/api/health` liveness and
    `/api/health/ready` readiness (DB round-trip, error class only — no
    connection details leaked); Alembic async env + initial `app_meta`
    migration; frozen `requirements.txt` (venv+pip per dependency rules);
    `requirements-dev.txt`.
  - Frontend (`frontend/`): Vite react-ts scaffold (React 19, Vite 8,
    TypeScript 6); minimal dark studio shell with Turkish microcopy and
    backend health wiring (loading/ok/error+retry, cancellation-safe
    effect); typed API client; dev proxy `/api` → `127.0.0.1:8000`;
    vitest + testing-library; oxlint clean.
  - Deployment: `backend/Dockerfile` (python:3.11-slim, migrations before
    API start), `frontend/Dockerfile` (node:24-alpine build → nginx:alpine
    serve + `/api` proxy), `deploy/docker-compose.yml` (linux/arm64,
    dedicated `postgres:17-alpine`, healthcheck-gated startup, required
    fresh `POSTGRES_PASSWORD`, only the frontend port published),
    `docs/DEPLOYMENT.md` (CasaOS: security gates, setup, verify, update,
    backup, troubleshooting).
- Verification:
  - Backend pytest: 10/10 passed (health liveness/readiness incl. error
    path, settings, logging redaction, offline migration SQL up+down).
  - Frontend: vitest 2/2 passed, oxlint 0 warnings/errors,
    `tsc -b && vite build` succeeded.
  - Live HTTP: uvicorn served `/api/health` (200), `/api/health/ready`
    (503 degraded, correct without DATABASE_URL), `/openapi.json` (200);
    Vite dev server served the page (200, correct title/root) and its
    `/api` proxy reached the backend (health 200, ready 503).
  - Compose: YAML parse + structural validation passed (arm64 platform
    pins, internal-only postgres, healthcheck dependency, password
    required, .env excluded from context).
  - Secret scan over tracked+untracked files: clean.
- Test results: section 7.
- Commit: `20ffb5e`, `754ed5c`, `36f6dff`, `3b17ad3` (+ final progress
  commit).
- Remaining limitations:
  - Private GitHub remote not created (B1: user must authenticate; exact
    commands in section 4).
  - Compose stack never executed (B2: no Docker on dev machine); first
    execution and app-level PostgreSQL connectivity verification happen
    on the Pi per `docs/DEPLOYMENT.md` section 4.
  - Migrations verified via offline SQL generation only; live `alembic
    upgrade head` runs in the container at deployment.
  - Server-level PostgreSQL connectivity IS verified (postgres MCP query
    to the Pi's PostgreSQL 17.10, Milestone 0 evidence); app-level
    readiness check implemented and unit-tested but not yet pointed at
    the production database (requires user-provisioned `.env`).
  - starlette TestClient emits a deprecation warning suggesting httpx2;
    dev-only, tests pass, recorded for later follow-up.

### Milestone 2 — Studio Interface (completed 2026-10-17)

- Date: 2026-10-16/17
- Milestone: 2
- Task: replace the placeholder screen with the real monitoring-first
  studio dashboard.
- Implementation (commits `72aec8b`, `e30e0e1`):
  - Design direction chosen through the impeccable decision round (five
    sketches served on a live decision page): user picked "Yeşilçam
    Baskı Odası" (concept-seed key edec7d88, code-led build, Operate
    surface). Confirmed user answers: durum takibi ağırlıklı
    (monitoring-first Overview) and tam otomatik (full-auto publishing,
    approval as override).
  - Backend: `/api/overview` (phase vocabulary setup → awaiting_channels
    → running; honest counts; database state) and `/api/system` (psutil
    CPU/RAM/disk/temperature, Linux-guarded sensors call).
  - Frontend: self-hosted Anton (latin + latin-ext), design tokens (ink
    ground, cream plate, poster state inks with on-plate/on-dark
    variants), app shell with rail nav (8 screens, Turkish microcopy),
    marquee plate + phase stamp, jenerik bill rows, ink gauges,
    empty/error/stale states, `usePolling` with stale-data retention.
  - Finish review per the impeccable contract (fresh-context reviewer
    subagent; the shipped reviewer agent is unavailable in this harness —
    substitution disclosed in the review returns): first verdict
    `disposition: fix` with six material findings; all six fixed and
    measured-verified (stamp-wait ink 4.78:1, plate-muted/plate-body-ink
    tokens, faint-on-dark 5.13:1 on panels, stamp replays on phase
    change via remount key, settings copy made verifiable against
    `.github/workflows/build-images.yml`, plate corners 0px, red
    intervention-stamp preview); verdict round scored 6/6 resolved with
    no regressions: `disposition: ship` (scope: the scored fixes of that
    review round, as the reviewer stated).
  - `DESIGN.md` (token-bearing frontmatter per the DESIGN.md spec) and
    `.impeccable/design.json` sidecar written; review rasters with
    embedded provenance under `.impeccable/review/` (gitignored).
- Verification: backend 13/13 tests at commit; frontend 3/3 tests,
  oxlint 0, production build passed, impeccable detector `[]`; live
  smoke against the Pi deployment (http://192.168.2.170:1478/) with
  DOM/computed-style audits at 1440x900 and 390x844 (Anton loaded,
  marquee 115.2px desktop / 64px mobile, plate colors exact, no
  horizontal overflow, rail collapse at ≤900px verified); CI runs for
  both commits: success.
- Test results: see section 7 for the final combined state.
- Remaining limitations: the reviewing model in this harness cannot view
  images, so the review used measured DOM/computed-style audits as
  render evidence (disclosed inside every review return); the user can
  eyeball `.impeccable/review/*.png` (desktop, mobile, automation,
  settings captures with provenance).

### Milestone 3 — Database and Channel Management (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 3
- Task: channel/OAuth credential/source channel/publishing profile
  models, migrations, repository/service layers, secure OAuth flows,
  token refresh, channel-specific settings, audit events.
- Implementation (commits `66f3301`, `b38fa7f`, `a5c261d`):
  - Models (`app/models.py`): Channel (status vocabulary pending/
    connected/disconnected/error, ribbon color), OAuthCredential
    (encrypted token columns), OAuthState (single-use CSRF states),
    SourceChannel (permission status pending/authorized/rejected),
    PublishingProfile (per-channel settings, JSONB), AuditEvent
    (append-only; survives channel deletion via ON DELETE SET NULL).
    Migration `0002` applied to the Pi database (`alembic current` →
    `0002 (head)`, verified).
  - Repository + service layers; every mutation writes an audit event
    (channel.created/updated/deleted/disconnected, oauth.started/
    connected/failed/token_refreshed/token_refresh_failed).
  - `/api/channels` CRUD + disconnect + `oauth/start` + `oauth/callback`
    + `oauth/refresh`. OAuth handshake: single-use 10-minute states
    (wrong/expired/replayed states rejected; state bound to the channel),
    Google code exchange, YouTube channel fetch, duplicate YouTube
    channel across studio channels rejected, tokens stored
    Fernet-encrypted (`cryptography`), disconnect deletes the
    credential row, callback redirects to the frontend channels screen
    when `FRONTEND_BASE_URL` is set (plain JSON otherwise). No token or
    secret appears in any API response (tested).
  - Kanallar screen: ribbon-colored list with status words,
    connect/disconnect/two-step delete, new-channel form (name + ribbon
    picker), OAuth feedback notes from the callback redirect; Overview
    KANALLAR panel lists real channel ribbons (first 5 + count).
  - Real bug caught by the real-Postgres smoke and fixed: channel
    deletion wrote the audit event after the row delete (FK violation on
    PostgreSQL; sqlite tests had FKs off and missed it). The event is
    now written and flushed before the delete, and sqlite test
    connections enforce `PRAGMA foreign_keys=ON` (parity with
    production).
- Verification: backend 39/39 (17 new OAuth/security tests; Google
  endpoints mocked via httpx MockTransport; foreign keys enforced),
  frontend 4/4, oxlint 0, production build passed, detector `[]`;
  real-Postgres round trip against the Pi database through a local
  uvicorn (create → list → patch → delete → overview totals/phase);
  secret scan clean; CI run `38993105069` (all three commits): success.
- Remaining limitations:
  - The Pi still runs the pre-M3 image until the user restarts the app
    in CasaOS; the DB migration is already applied so the restart is the
    only step.
  - Connecting a real YouTube channel additionally requires the user's
    Google Cloud OAuth client via env vars (`GOOGLE_CLIENT_ID`,
    `GOOGLE_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY` (Fernet key),
    `OAUTH_REDIRECT_BASE`, `FRONTEND_BASE_URL`). Without them the Bağla
    button returns an explanatory 503; nothing else degrades.

## 4. Current Blockers

### B1 — GitHub remote (RESOLVED 2026-10-16)

- Description: remote repository creation was blocked on authentication.
- Resolution: the user authenticated `gh` (browser flow) and asked for a
  public repository; `muratcihanyandi/autoshorts-studio-v2` was created
  and every milestone since is pushed. GitHub Actions builds
  linux/amd64 + linux/arm64 images to GHCR on every push to `main`
  (`build-images` workflow; verified runs ending `success`).
- Note: the old public repo `AutoShorts-Studio` (v1 project) still exists
  and stays untouched (ADR-001).

### B2 — No Docker CLI on the dev machine (does not block authoring)

- Description: docker/docker-compose unavailable on Windows dev machine.
- Affected component: runtime verification of the Compose stack locally.
- Why it blocks: cannot run containers locally.
- Required action: run the stack on the Raspberry Pi (CasaOS). The user
  already deployed the stack themselves (verified live in Milestone 2);
  updates flow via GHCR image pulls + CasaOS restart.
- Independent work continues: yes.

### B3 — Deployment gates G1/G2 pending user confirmation

- Description: user must confirm the previously exposed GitHub token is
  revoked and the PostgreSQL password rotated (`docs/SECURITY.md`).
- Note: the user chose to deploy the stack on the Pi themselves before
  confirming the gates; the confirmation is still outstanding and should
  be recorded before further credentials are introduced.
- Independent work continues: yes.

### B4 — OAuth environment variables pending (blocks YouTube connection only)

- Description: connecting a real YouTube channel requires the user's
  Google Cloud OAuth client and a Fernet key via env vars
  (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY`,
  `OAUTH_REDIRECT_BASE`, `FRONTEND_BASE_URL`).
- Affected component: the OAuth handshake end-to-end with Google (the
  code path is implemented and fully tested against mocks).
- Required action: user provides the values in the CasaOS compose
  environment.
- Independent work continues: yes — all other functionality works; the
  Bağla button returns an explanatory 503 until configured.

## 5. Architecture Decisions

Short summaries; full details in `docs/DECISIONS.md`.

- ADR-001: Fresh repository; never reuse code or credentials from the old
  AutoShortsStudio projects.
- ADR-002: Monorepo (backend/ + frontend/ + deploy/ + docs/).
- ADR-003: FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2.
- ADR-004: React + TypeScript + Vite; Milestone 2 UI under impeccable +
  frontend-design skills.
- ADR-005: Dedicated `autoshorts_studio` PostgreSQL database in its own
  container with freshly generated credentials; shared instance untouched.
- ADR-006: PostgreSQL-backed durable job queue (SKIP LOCKED), no extra
  broker.
- ADR-007: Compose targets linux/arm64; local validation is syntax-only.
- ADR-008: Local tests use SQLite/TestClient; PostgreSQL verified on the Pi.
- ADR-009: Deployment gated on credential revocation/rotation confirmation.
- ADR-010: Local git now; private GitHub remote when auth is available.

## 6. Current Risks

### Raspberry Pi resource pressure
Mitigation: Limit concurrency, monitor CPU/RAM/disk, constrain FFmpeg, and
apply backpressure. (Unchanged.)

### Webcam detection errors
Mitigation: Multi-frame tracking, confidence thresholds, calibration
profiles, preview, and review. (Unchanged.)

### LLM provider failures
Mitigation: Three-provider fallback, bounded retries, timeouts, and
structured output validation. (Unchanged.)

### YouTube API quotas and upload failures
Mitigation: Quota tracking, resumable uploads where supported, retry
policies, and reconciliation. (Unchanged.)

### Unauthorized source media
Mitigation: Rights records, authorization checks, and publication blocks.
(Unchanged.)

### Secret exposure
Status: ACTIVE until gates G1/G2 are confirmed. No secrets exist in this
workspace (verified 2026-10-16). Mitigation: environment variables only,
`.env` ignored, secret scans before commits, encrypted token storage.

### Restart and network failures
Mitigation: Persistent jobs, idempotent transitions, health checks, and
recovery tests. (Unchanged.)

### Dev/target platform mismatch (new)
Windows dev machine without Docker; runtime behavior only verifiable on the
Pi. Mitigation: strict CI-style local tests, syntax validation of Compose,
and a documented deployment checklist with verification steps.

## 7. Last Verified Test Results

Verified 2026-10-17 on the dev machine (Windows 11, Python 3.11.9 venv,
Node 24.13.0). Commands run from the stated directories.

- Backend — `cd backend && ./.venv/Scripts/python.exe -m pytest`
  - Passed: 39 (test_health 4, test_config 2, test_logging 2,
    test_migrations 2, test_overview 2, test_system 1, test_channels 9,
    test_security 3, test_oauth 14 — collected per file)
  - Failed: 0; Skipped: 0
  - sqlite test connections enforce foreign keys (production parity).
  - 1 warning: starlette TestClient deprecation notice (dev-only).
- Frontend — `cd frontend && npx vitest run`
  - Passed: 4 (shell+overview from mocked API, error+retry, rail href,
    channels screen list + form)
  - Failed: 0
- Frontend lint — `npx oxlint src`: 0 warnings, 0 errors.
- Frontend build — `npm run build` (`tsc -b && vite build`): succeeded.
- Impeccable detector — `impeccable detect --json --target
  frontend/src/App.tsx`: `[]` (clean).
- Secret scan — `python tools/scan_secrets.py` from repository root:
  clean (all OAuth token-handling lines carry justified
  `# secret-scan-ok` markers; synthetic test fixtures marked).
- Real-Postgres integration (2026-10-17, local uvicorn → Pi database):
  channels create → list → patch → delete round trip 201/200/200/204;
  `/api/overview` reported live totals and phase before/after.
- CI — GitHub Actions `build-images` on `main`: latest run
  `38993105069` (M3 slice 3) completed `success`; images on GHCR.
- Live deployment — Pi (http://192.168.2.170:1478/): M2 interface
  verified live (DOM/computed-style audits at two viewports); the M3
  image awaits the user's CasaOS restart.

## 8. Git State

- Repository URL: https://github.com/muratcihanyandi/autoshorts-studio-v2
  (public, per user request; B1 resolved)
- Current branch: `main` (pushed; CI builds images on every push)
- Commit history (oldest first, milestone-relevant):
  - `cfb1c35` baseline: original three files preserved
  - `0f37870` Milestone 0 deliverables
  - `20ffb5e` / `754ed5c` / `36f6dff` / `3b17ad3` Milestone 1 (+ progress commit)
  - `72aec8b` Milestone 2: Yeşilçam Baskı Odası studio interface
  - `e30e0e1` Milestone 2 finish review fixes + DESIGN.md
  - `66f3301` Milestone 3 slice 1: channel model, migration 0002, CRUD API
  - `b38fa7f` Milestone 3 slice 2: OAuth handshake + encrypted tokens
  - `a5c261d` Milestone 3 slice 3: channels screen, overview ribbons, FK parity
- Working tree: clean after the final commit
- Uncommitted changes: none after each milestone commit

## 9. Immediate Next Actions

1. Milestone 4 (in progress): source-channel registration API on the
   existing `source_channels` model (rights records), YouTube metadata
   client with quota tracking and caching, source-video discovery with
   duplicate prevention, filtering/exclusion rules, durable planning
   service.
2. User (any time): restart the app in CasaOS to pick up the M3 image
   (GHCR `latest`; DB migration already applied).
3. User (to connect a real YouTube channel): provide the Google Cloud
   OAuth client values + Fernet key via compose env vars (B4).
4. User (security): confirm gates G1/G2 in `docs/SECURITY.md` (B3).

## 10. Handoff Notes

- What was implemented: Milestones 0–3. M2: the Yeşilçam Baskı Odası
  studio interface (monitoring-first dashboard, marquee plate + phase
  stamp, jenerik bill rows, gauges, 8 screens, polling with stale-data
  retention) with a fully documented finish review ending `ship`, plus
  `DESIGN.md` + `.impeccable/design.json`. M3: channel domain (6 models,
  migration 0002 applied on the Pi DB), repository/service/audit layers,
  channel CRUD + OAuth handshake (single-use states, Fernet-encrypted
  tokens, refresh, frontend redirect), Kanallar screen and Overview
  ribbon list, sqlite FK parity in tests.
- Tests: backend 39/39, frontend 4/4, lint/build/detector clean, secret
  scan clean, real-Postgres round trip verified, CI success on all
  pushes (latest `38993105069`).
- Deployment state: the Pi runs the app (M2 verified live); the M3 image
  is on GHCR and arrives with a CasaOS restart (no DB step needed).
- Outstanding: B3 (gates G1/G2 user confirmation), B4 (OAuth env vars),
  ghp_ token exposed in chat should stay revoked.
- Exact next task: Milestone 4 slice 1 — source-channel registration API
  (`/api/channels/{id}/sources` CRUD + rights records) with tests; then
  the YouTube metadata client with quota tracking.
- Decisions to preserve: ADR-001…ADR-010 plus the M2/M3 implementation
  contracts (Yeşilçam Baskı Odası design system in `DESIGN.md`; OAuth
  tokens encrypted at rest and never in API responses; audit trail
  append-only).

**Never infer progress from previous plans. The repository and test
results are the source of truth.**
