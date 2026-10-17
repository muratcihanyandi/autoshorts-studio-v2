# AutoShorts Studio — Current Progress

## Current Project State

**Overall status:** Milestones 0–6 COMPLETE. Repository public on GitHub
(`muratcihanyandi/autoshorts-studio-v2`) with CI building ARM64+AMD64 images
to GHCR (every run green, latest `39010166549`). The user deployed the stack
on the Pi via CasaOS (UI/API/database verified from the user's logs); the app
database lives in its own `postgres:17` container (ADR-005).

**Current milestone:** Milestone 7 — Horizontal Video Processing

**Current task:** M7 kickoff — authorized media-source adapters, sequential
downloads with bandwidth limits, media integrity validation.

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
| 4. Source Monitoring and Planning | COMPLETED | Source registration + rights records, quota-gated cached YouTube discovery with dedupe, filter rules, durable planning ledger (2026-10-17) |
| 5. LLM Provider Manager | COMPLETED | Bounded three-provider fallback, encrypted masked keys, request log (2026-10-17) |
| 6. Job Queue and Resource Management | COMPLETED | Persistent SKIP LOCKED queue, worker + heartbeat + stale recovery, token-bucket limit, disk guard, tmp cleanup (2026-10-17) |
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

### Milestone 4 — Source Monitoring and Planning (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 4
- Task: source-channel registration with rights records, official YouTube
  metadata integration, quota tracking and caching, duplicate prevention,
  filter/exclusion rules, durable planning.
- Implementation (commits `2edc878`, `1c00ebc`, `7e1e1bb`):
  - Slice 1 — source registration + rights records: `/api/channels/{id}/sources`
    CRUD over the existing `source_channels` model; permission status
    (pending/authorized/rejected) with authorization notes and timestamps;
    only authorized sources are polled. Migration `0003` (`source_videos`).
  - Slice 2 — YouTube discovery: `app/services/youtube_client.py` — Data
    API v3 reader gated by a daily quota ledger (`quota_usage` table);
    `QuotaBudgetExceeded` raised before the request so polling can never
    silently burn past the limit; TTL response cache. `discovery_service.py`
    polls channel uploads and inserts new videos into `source_videos` with
    a unique (channel, video) constraint — duplicate discovery cannot
    create duplicate rows or duplicate jobs.
  - Slice 3 — filter rules + planning: `source_rules.py` (per-source
    duration bounds, title patterns, exclusion rules), `planning_service.py`
    + migration `0004` (`planning`): durable planning ledger — every
    decision recorded (planned/skipped) with its reason, so planning is
    auditable.
- Verification: 19 new tests (test_sources 7, test_discovery 5,
  test_planning 7); YouTube endpoints mocked via httpx MockTransport;
  quota overshoot rejected and dedupe asserted in tests; CI run for
  slice 3 `38997282380`: success. Secret scan clean.
- Remaining limitations: polling real YouTube requires user-provided
  credentials (YouTube API key / OAuth client values — the site-managed
  settings below provide the entry path; B4); polling cadence runs on the
  M6 worker.

### Site-managed settings + brand identity (user-directed interlude, 2026-10-17)

- Date: 2026-10-17
- Milestone: user-requested work between M4 and M5
- Task: every setting editable from the site (including YouTube API
  keys); AutoShorts Studio brand kit applied everywhere.
- Implementation (commits `9011398`, `2100eec`):
  - Brand kit: brand palette tokens, self-hosted brand fonts (Noto Sans
    Display, Google Sans, Noto Sans — full Turkish glyph coverage
    verified via fontTools cmap), logos (full + icon, light/dark
    variants), and the "AutoShorts Studio" name across page titles,
    favicon, UI copy, and Docker/CasaOS labels.
  - Runtime settings: `settings_service.py` — overrides stored in
    `app_meta` under `runtime_settings` (database over environment;
    empty string reverts to the env value), masked GET `/api/settings`
    (secrets never returned), authenticated PUT; Ayarlar screen with
    masked secret inputs; YouTube API key, OAuth client values, and
    base URLs editable at runtime.
- Verification: test_settings 10 (masking, DB-over-env precedence,
  revert-to-env, update round trip); secret scan clean; CI runs
  `38998768270` (brand) and `38999691672` (settings): success.

### Milestone 5 — LLM Provider Manager (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 5
- Task: configurable providers with bounded fallback, masked API key
  management, timeout/retry/rate-limit handling, structured response
  validation, latency and error categories.
- Implementation (commits `63ca3eb`, `100876c`):
  - `app/services/llm_service.py` (ADR-011): up to 3 providers
    (`MAX_PROVIDERS = 3`) with order, model IDs, endpoints, per-provider
    timeout; a completion tries `1 + max_retries` times per provider
    (retries only for network/timeout errors), then falls to the next
    provider — bounded, no infinite retries; invalid structured
    responses are rejected safely and recorded by error category;
    per-request latency and error category recorded (Son İstekler
    panel); provider API keys Fernet-encrypted at rest and masked in
    every API response and log.
  - Migration `0005` (`llm_providers`); `/api/llm/providers` CRUD +
    connection test + request log; LLM Sağlayıcıları screen.
- Verification: test_llm 18 (main failure triggers fallback; invalid
  JSON rejected; bounded retries; secrets never logged — log redaction
  asserted); CI runs `39000726932` / `39000791274`: success.
- Remaining limitations: real provider calls need user-entered keys (via
  site settings or env); the fallback contract is covered by
  simulated-failure tests.

### Milestone 6 — Durable Job Queue and Resource Management (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 6
- Task: persistent job states, worker heartbeat, retry and cancellation,
  restart recovery, configurable concurrency, download bandwidth limits,
  disk-space checks, CPU/memory monitoring, safe temporary-file cleanup.
- Implementation (commit `548d793`):
  - `app/services/job_service.py`: job rows in PostgreSQL (migration
    `0006`), claim via `SELECT … FOR UPDATE SKIP LOCKED` (single consumer
    per job; sqlite runs the same code path in tests), worker heartbeat +
    attempt counters, stale running jobs reclaimed past the heartbeat
    threshold (restart recovery), cancel semantics, deduped enqueue (the
    same job_type + payload does not double-queue), configurable worker
    concurrency.
  - `app/worker.py`: background worker task (`WORKER_ENABLED` env), busy
    loop with concurrency limit, periodic `source_discover` scheduling
    per channel, hourly tmp cleanup.
  - Resource management: `rate_limiter.py` token bucket (download
    bandwidth limit), disk-space guard refuses unsafe new jobs, psutil
    CPU/RAM/disk monitoring via `/api/system`, safe temp-file cleanup
    (`temp_cleanup.py`), labelled media tree (`media_storage.py`:
    downloads/edited/clips/stock/tmp under MEDIA_ROOT).
  - Otomasyon screen: job queue list with status pills + cancel.
- Verification: test_jobs 16, test_media 7, test_resources 6 (29 new:
  restart recovery, dedupe, cancel consistency, disk guard, token
  bucket, tmp cleanup); CI run `39003038671`: success.

### Deployment polish + canon redesign (2026-10-17)

- Date: 2026-10-17
- Milestone: post-M6 deployment hardening and theme change (user-directed)
- Task: CasaOS-facing deployment polish; theme switched to the
  "Kategori Standardı" catalog direction.
- Implementation (commits `1bab11b`, `f3ea1af`, `e816bd4`, `c8f2fbb`,
  `f091f24`, `121e175`):
  - Light-logo favicon + Docker/CasaOS app name and branding
    (`1bab11b`); GHCR compose template duplicate name fix (`f3ea1af`);
    frontend listed first in compose so the CasaOS app card opens the UI
    (`e816bd4`); labelled media tree volumes under
    `/mnt/usb/Autoshorts_Studio` + PNG favicon (`c8f2fbb`); backend
    container runs as UID/GID 1000 instead of root (`f091f24`).
  - Canon redesign (`121e175`): the "Kategori Standardı" catalog mock's
    structure applied with the AutoShorts Studio brand — ivory page,
    white cards with 1px border + single soft shadow, dark navy rail
    with dot indicators, 4-card stat grid, title-bar table panels, soft
    status pills, 6px round meters; screen titles converted to sentence
    case; the Yeşilçam marquee/stamp/bill-row components removed;
    `DESIGN.md` rewritten for the new direction.
- Verification: frontend vitest 10/10, oxlint 0 errors, `tsc -b` clean,
  production build ok; DOM audits of 4 screens via headless Edge (stat
  cards, panels, pills, meters present; no legacy classes); CI runs
  through `39010166549`: success.
- Deployment note (2026-10-17, read-only postgres MCP): the shared
  PostgreSQL instance contains an EMPTY `autoshorts_studio` database — a
  leftover; the deployed stack uses its own `postgres:17` container per
  ADR-005. Cleanup decision belongs to the user.

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

Verified 2026-10-17 (post-M6 + canon redesign session) on the dev machine
(Windows 11, Python 3.11.9 venv, Node 24.13.0). Commands run from the
stated directories.

- Backend — `cd backend && ./.venv/Scripts/python.exe -m pytest`
  - Passed: 115 (test_llm 18, test_jobs 16, test_oauth 14, test_settings
    10, test_channels 9, test_sources 7, test_planning 7, test_media 7,
    test_resources 6, test_discovery 5, test_health 4, test_security 3,
    test_overview 2, test_migrations 2, test_logging 2, test_config 2,
    test_system 1 — collected per file)
  - Failed: 0; Skipped: 0
  - sqlite test connections enforce foreign keys (production parity).
  - 2 warnings: starlette TestClient deprecation notice (dev-only) and a
    pytest unhandled-thread-exception notice from a worker test.
- Frontend — `cd frontend && npx vitest run`
  - Passed: 10 (App 4, SettingsScreen 3, AutomationScreen 3)
  - Failed: 0
- Frontend lint — `npx oxlint`: 0 errors (1 React Compiler advisory note).
- Frontend build — `npm run build` (`tsc -b && vite build`): succeeded.
- Secret scan — `python tools/scan_secrets.py` from repository root:
  clean (token/key-handling lines carry justified `# secret-scan-ok`
  markers; synthetic test fixtures marked).
- CI — GitHub Actions `build-images` on `main`: every run since the last
  record completed `success` (verified via `gh run list` 2026-10-17;
  latest `39010166549` for commit `121e175`).
- Live deployment — Pi (CasaOS): stack deployed by the user; UI, API,
  and migrated database verified from the user's logs (2026-10-17).
  Note: the app database lives in the stack's own `postgres:17`
  container; the empty `autoshorts_studio` on the shared instance is an
  unused leftover (see the deployment-polish record).

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
  - `2edc878` / `1c00ebc` / `7e1e1bb` Milestone 4 slices 1–3
  - `9011398` AutoShorts Studio brand kit; `2100eec` site-managed runtime settings
  - `63ca3eb` / `100876c` Milestone 5 (+ secret-scanner fixture marks)
  - `548d793` Milestone 6: durable job queue and resource management
  - `1bab11b` / `f3ea1af` / `e816bd4` / `c8f2fbb` / `f091f24` deployment polish
  - `121e175` canon "Kategori Standardı" redesign with studio brand
- Working tree: clean after the final commit
- Uncommitted changes: none after each milestone commit

## 9. Immediate Next Actions

1. Milestone 7 (next): authorized media-source adapters — a download job
   handler on the M6 queue (token-bucket bandwidth limit, sequential
   downloads into the labelled media tree), media integrity validation
   via ffprobe/ffmpeg.
2. User (to connect a real YouTube channel): enter the Google Cloud
   OAuth client values + Fernet key via the site settings screen or
   compose env vars (B4).
3. User (security): confirm gates G1/G2 in `docs/SECURITY.md` (B3).
4. User (optional): decide whether to drop the empty leftover
   `autoshorts_studio` database on the shared PostgreSQL instance.

## 10. Handoff Notes

- What was implemented: Milestones 0–6. M4: source registration with
  rights records, quota-gated cached YouTube discovery with dedupe,
  filter rules, durable auditable planning ledger. Interlude: the
  AutoShorts Studio brand kit applied everywhere and site-managed
  runtime settings (masked secrets, DB-over-env precedence, revert on
  empty). M5: bounded three-provider LLM fallback (ADR-011) with
  Fernet-encrypted keys, latency/error-category request log. M6:
  PostgreSQL SKIP LOCKED job queue with heartbeat, stale-job recovery,
  dedupe and cancel; worker with concurrency limit, periodic source
  discovery and hourly tmp cleanup; token-bucket download limit;
  disk-space guard; labelled media tree. Post-M6: CasaOS deployment
  polish (frontend first, UID/GID 1000, `/mnt/usb/Autoshorts_Studio`
  volumes, branding) and the canon "Kategori Standardı" redesign (stat
  cards, title-bar table panels, soft pills, round meters) with
  `DESIGN.md` rewritten.
- Tests: backend 115/115, frontend 10/10, oxlint/tsc/build clean, secret
  scan clean, CI green on every push (latest run `39010166549`).
- Deployment state: user-verified CasaOS stack on the Pi (UI/API/DB);
  the app database is in the stack's own `postgres:17` container; the
  empty `autoshorts_studio` on the shared instance is an unused
  leftover flagged for a user cleanup decision.
- Outstanding: B3 (gates G1/G2 user confirmation), B4 (OAuth/env values
  for a real YouTube connection — site settings now provide the entry
  path); the ghp_ token exposed in chat must stay revoked.
- Exact next task: Milestone 7 slice 1 — the authorized media-source
  download handler as an M6 job (bandwidth-limited, sequential,
  integrity-checked into `downloads/`).
- Decisions to preserve: ADR-001…ADR-011 plus the implementation
  contracts: OAuth tokens and LLM keys encrypted at rest and never in
  API responses; audit trail append-only; job claim via SKIP LOCKED
  with heartbeat-driven recovery; runtime settings override env only
  with explicit non-empty values; canon design system per `DESIGN.md`.

**Never infer progress from previous plans. The repository and test
results are the source of truth.**
