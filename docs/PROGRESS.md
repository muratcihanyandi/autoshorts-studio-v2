# AutoShorts Studio — Current Progress

## Current Project State

**Overall status:** Milestones 0–11 COMPLETE. Repository public on GitHub
(`muratcihanyandi/autoshorts-studio-v2`) with CI building ARM64+AMD64 images
to GHCR (every run green, latest `39019597052`). The user deployed the stack
on the Pi via CasaOS (UI/API/database verified from the user's logs); the
app's live database is `autoshorts_studio` on the shared PostgreSQL
instance (verified 2026-10-17 via read-only pg_stat_activity — see the
deployment-polish record; ADR-005 addendum in `docs/DECISIONS.md`).

**Current milestone:** Milestone 14 (Channel Automation — Start/Stop,
stock-target refill, status tags) COMPLETE; Milestone 12 production
hardening continues in parallel on the Pi.

**Current task:** Product surface (2026-10-19): first-run studio login with an
HttpOnly session cookie; the media library now shows only engine-selected
videos (current video + completed selections) with a stage track, YouTube
thumbnails and source-channel links. Ready clips are compact cards that open a
detail dialog with a Range-streamed player, YouTube publishing plan, title,
description, tags, filters and cover image. Backend 403/403, frontend 22/22,
type check/build and secret scan clean.

**Last updated:** 2026-10-19

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
| 7. Horizontal Video Processing | COMPLETED | Stage-gated media pipeline on the queue: adapters, ffprobe integrity, transcripts, silence/scene/energy analysis, scored candidates with similarity checks (2026-10-17) |
| 8. Vertical Studio and Webcam Detection | COMPLETED | OpenCV multi-frame detection + calibration + 9:16 render with review semantics (2026-10-17) |
| 9. Subtitles and Metadata | COMPLETED | LLM subtitle correction (timestamps preserved, uncertainty flagged), channel templates, revisioned metadata (2026-10-17) |
| 10. Upload and Publishing | COMPLETED | Resumable private-first uploads with rights/approval guards, timezone-aware schedules, reconciliation (2026-10-17) |
| 11. End-to-End Automation | COMPLETED | Auto-plan chaining, target/stock/pause-aware publishing, channel isolation, ops summaries (2026-10-17) |
| 12. Production Hardening | IN_PROGRESS | Fault injection, backup/restore, guide screen done; Pi field verification pending |
| 14. Channel Automation (Start/Stop) | COMPLETED | Per-channel state machine, stock-target refill, #done/#confirmed tags, hype evaluation, content modes (2026-10-18) |

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
- Deployment note (2026-10-17, read-only postgres MCP, corrected after user
  feedback): the app's live database is `autoshorts_studio` on the shared
  PostgreSQL instance — `pg_stat_activity` shows 2 idle connections to it
  from the Docker bridge (172.18.0.1, the app backend's SQLAlchemy pool)
  and `pg_database_size` is 8342 kB, consistent with the migrated schema.
  This matches the ADR-005 addendum's server-reuse choice (2026-10-16);
  one deviation observed: the app connects as the shared admin role
  (`muratcihanyandi`) rather than the planned least-privilege
  `autoshorts_app` role (verification note in `docs/DECISIONS.md`;
  related to gate G2). An earlier note calling this database an "empty
  leftover" was a query artifact — information_schema was read from the
  `muratcihanyandi` database, so the `table_catalog` filter could not
  match `autoshorts_studio` tables.

### Milestone 7 — Horizontal Video Processing (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 7
- Task: authorized media-source adapters, sequential downloads, media
  integrity validation, ffprobe inspection, transcript generation,
  intro/outro detection, scene/reaction analysis, clip-candidate
  generation, content similarity checks, results in PostgreSQL.
- Plan: `docs/plans/2026-10-17-m7-horizontal-processing.md` (nine
  tasks, TDD, one commit per task).
- Implementation (commits `511ecd7`..`11226eb`, one per task, ADR-012):
  - Schema (migration `0007`): `media_assets` (unique source_video_id,
    origin, stage/status, sha256, analysis JSONB), `media_inspections`
    (unique per asset), `transcripts` (unique per asset, segments
    JSONB), `clip_candidates` (indexed by source_video_id,
    end>start constraint, duplicate_of pointer).
  - `media_probe.py`: ffprobe subprocess (JSON), stream/duration
    integrity rules, chunked sha256 off the event loop.
  - `media_download.py`: adapter protocol — LocalImportAdapter (copies
    operator-authorized files + sidecar, originals untouched) and
    YtDlpAdapter (subprocess, `--limit-rate` from settings, auto-subs,
    PATH probe with Turkish error). Sequential downloads via one shared
    asyncio lock in the worker handler registry.
  - `media_transcript.py`: in-process VTT/SRT parsers (malformed cues
    skipped), sidecar discovery incl. yt-dlp `<id>.<lang>.vtt` naming,
    windowed text extraction.
  - `media_analysis.py`: silencedetect log pairing (intro/outro runs),
    scene cuts via `select=gt(scene,T),showinfo`, per-second audio RMS
    from decoded mono PCM; parse helpers pure and unit-tested.
  - `clip_candidates.py`: window scoring (energy/scene density/
    transcript coverage minus silence overlap), greedy non-overlapping
    top-K, word 3-gram Jaccard near-duplicate detection.
  - `media_pipeline.py`: stage-gated orchestrator — every stage commits
    its progress; a retried job resumes at the failed stage (no
    redownload); failures mark the asset `failed` with a Turkish
    `last_error` and stage stays for resume; per-stage audit events
    (`media.download`..`media.candidates`); unauthorized sources
    rejected; disk guard before download.
  - Worker: `media_process` job type registered with the shared
    download lock; `enqueue_planned_jobs` feeds one job per `planned`
    video every `planned_poll_interval_minutes` (deduped, priority 8).
  - Image: Debian `ffmpeg` package added to the backend Dockerfile;
    `yt-dlp==2026.8.19` pinned in requirements.txt (subprocess binary,
    never imported; dev tests never require it).
- Verification (2026-10-17, dev machine, `backend/.venv`):
  - Backend suite: **172 passed, 0 failed, 0 skipped** in 36.39s
    (`cd backend && ./.venv/Scripts/python.exe -m pytest`). 57 new
    tests: test_media_pipeline 19 (incl. full-pipeline e2e with real
    ffmpeg media, idempotent re-run, failure+resume, corrupt-media
    integrity, unauthorized rejection, sequential-lock, cross-video
    similarity, worker-level e2e), test_media_probe 9, test_media_analysis
    10, test_media_transcript 7, test_clip_candidates 10, test_jobs +3.
  - Acceptance criteria evidence: entire pipeline on authorized test
    media = `test_full_pipeline_with_local_import` +
    `test_worker_runs_media_process_end_to_end` (real ffmpeg binaries,
    all four tables populated, audit trail per stage); failures recorded
    and recoverable = corrupt-media + retry-resume tests; valid
    candidate timestamps = invariant assertions (`0 <= start < end <=
    duration`, min/max clip bounds); originals preserved = import copies
    (never moves) + originals-untouched assertion, downloads stay in
    `downloads/`, tmp cleanup only prunes `tmp/`; resource limits =
    sequential download lock test, disk guard, `--limit-rate` flag
    test, worker concurrency limit (M6 tests).
  - Known limitation: the yt-dlp YouTube path is verified via command
    construction and injected runners only; a real authorized YouTube
    download is a Pi-deployment verification step (no network/YouTube
    dependency in unit tests, per ADR-008).

### Milestone 8 — Vertical Studio and Webcam Detection (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 8
- Task: 9:16 rendering templates, multi-frame webcam detection,
  tracking + confidence scoring, streamer calibration, manual region
  selection, top-webcam/bottom-video composition, subtitle
  positioning, generated-video validation, representative test videos.
- Plan: `docs/plans/2026-10-17-m8-vertical-studio.md` (ADR-013).
- Implementation (commits `f2d2ec5` + `dc2b62b`-series, see git log):
  - `webcam_detect.py`: OpenCV headless 4.12.0.88 (aarch64 wheel
    verified) — 1 fps frame sampling over the clip window via
    cv2.VideoCapture, Haar frontalface_alt2 per frame (grayscale +
    equalizeHist), greedy IoU clustering across frames; best cluster =
    detection rate then area; confidence = detection rate with
    size-jitter penalty; `FaceDetector` protocol for future YuNet.
  - `webcam_calibration.py` + `webcam_calibrations` table (migration
    `0008`): manual region wins outright (detection skipped);
    per-source min_confidence override; below-threshold detection
    returns region=None so the pipeline routes to review — a wrong
    crop is never rendered. Calibration API: GET/PUT/DELETE
    `/api/sources/{id}/webcam-calibration`.
  - `vertical_render.py`: pure layout math (top webcam crop padded +
    aspect-corrected, bottom center crop, subtitle band guaranteed
    below the webcam section) + one-pass ffmpeg render (split -> two
    crops -> scale -> vstack, x264 veryfast + aac, ASS-style subtitle
    burn with MarginV) + `validate_output` (ffprobe: 1080x1920,
    duration tolerance, audio presence, A/V stream sync <= 0.25s).
  - `vertical_pipeline.py` + `rendered_clips` table: `clip_render` job
    (unique per candidate, idempotent re-runs) — resolve region ->
    review short-circuit with audit `render.review` -> render ->
    validate -> persist with layout/validation/webcam JSON. Worker
    feed: `enqueue_render_jobs` for candidates without a render row
    (interval-gated, deduped). Image gains `fonts-dejavu-core` for
    libass.
  - Test fixtures: public-domain NASA portrait (resized, 102KB,
    Haar-verified) committed under `tests/assets/`;
    `make_face_stream_video` composites it with jitter over a dark
    1280x720 background with audio — a realistic streamer layout.
- Verification (2026-10-17, dev machine):
  - Backend suite: **195 passed, 0 failed, 0 skipped** in 34.7s
    (M8 adds 23: test_webcam_detect 9 — real detection on the face
    fixture, no-face video negative, clustering/confidence math;
    test_vertical_render 7 — layout invariants, real 1080x1920 render
    with burned subtitles, validation, invalid-range rejection;
    test_vertical_pipeline 7 — worker-level e2e render, idempotent
    re-run, uncertainty -> review (nothing rendered), manual
    calibration override, rejected-candidate refusal, render-feed
    enqueue, calibration API roundtrip).
  - Acceptance criteria evidence: expected layout = probed 1080x1920
    two-section render; uncertainty -> review = forced-threshold test
    (`render.review` audit event, no output file); A/V sync = stream
    duration delta <= 0.25s asserted; cropping/subtitle overlap =
    layout invariant tests (subtitle band strictly below the webcam
    section) + rendered probe; limitations documented = ADR-013
    (Haar vs neural detectors, CPU cost, calibration fallback).
  - Detection performance note: Haar on 1280x720 sampled frames costs
    well under a second per frame on the dev machine; on the Pi expect
    a few seconds per sampled frame worst case — acceptable at 1 fps
    sampling inside a queued job.

### Milestone 9 — Turkish Subtitle Correction and Metadata (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 9
- Task: timestamped transcript storage (done in M7), Turkish spelling
  and punctuation correction, name/timestamp preservation, uncertain
  correction flags, channel-specific metadata templates, title/
  description/tag generation, metadata validation, revision storage.
- Implementation:
  - Schema (migration `0009`): `corrected_transcripts` (unique per
    media asset, parallel to the untouched original), 
    `metadata_templates` (unique per channel; patterns may reference
    {title}/{summary}/{channel}, unknown placeholders stay literal),
    `clip_metadata` (unique (candidate, revision); append-only
    revisions; status draft/approved/rejected).
  - `subtitle_correction.py`: the M5 provider chain corrects numbered
    segment chunks (20 per request) with strict rules (preserve
    names/numbers, never merge or reorder, flag uncertain). The
    response contract is verified (exact count + index coverage) and
    timestamps are copied verbatim from the original — the LLM never
    sees or sets them, so corrections cannot silently alter timing.
    Corrected/flagged counts + provider recorded; audit
    `subtitle.corrected`; idempotent re-run.
  - `metadata_service.py`: proposal schema (title/summary/tags) via
    the LLM chain from the clip's transcript window (corrected
    preferred); channel template applied; `validate_metadata` enforces
    YouTube limits (title 5-100, description 20-5000, tags <= 30 x 50)
    and rejects invalid output without storing anything;
    `regenerate=True` appends revision max+1; tags deduped. Template
    API: GET/PUT `/api/channels/{id}/metadata-template` ({title}
    required in title pattern, {summary} in description pattern).
  - Worker: `subtitle_correct` (media_asset_id) and `metadata_generate`
    (clip_candidate_id) job types; `enqueue_content_jobs` interval-
    gated feed (uncorrected transcripts + rendered clips without
    metadata).
- Verification (2026-10-17): backend suite **210 passed, 0 failed,
  0 skipped** in 38.9s (M9 adds 15: test_subtitle_correction 6 —
  timestamp preservation, flag counting, original untouched,
  idempotency, wrong-count rejection with no row, worker error path,
  feed; test_metadata 9 — validation rules, pattern application, tag
  dedupe, template application + revision storage, skip/regenerate
  semantics, invalid result rejection, channel template isolation,
  worker feed, template API roundtrip). Migration 0009 offline SQL
  generation passes. Acceptance criteria: originals recoverable
  (transcripts row never modified — asserted), no silent timestamp
  changes (verbatim copy — asserted), invalid metadata rejected
  (no-row test), template changes isolated per channel (two-channel
  test). LLM interactions are tested through MockTransport per the
  M5 chain contract; real-provider behavior is site configuration.

### Milestone 10 — YouTube Upload and Publishing (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 10
- Task: official API uploads (resumable), private upload handling,
  YouTube video ID storage, per-channel publishing schedules,
  timezone-aware planning, visibility checks, retry/reconciliation,
  publication approval controls.
- Implementation:
  - Schema (migration `0010`): `published_videos` — unique
    clip_candidate_id (structural duplicate prevention), channel,
    youtube_video_id, visibility private/public, status
    uploading/uploaded/verified/failed, resumable session URI (kept so
    interrupted uploads reconcile instead of restarting), published_at.
  - `publishing_schedule.py` (pure): publish-time slots from the
    publishing profile (`settings.publish_times`, default three),
    timezone-aware next-due computation via zoneinfo (tzdata pinned in
    requirements — Windows needs the package; Debian ships it).
  - `youtube_upload.py`: resumable protocol client — POST metadata
    (snippet + status private) -> session URI, PUT media bytes ->
    video id, videos.list?part=status verification. Access tokens come
    from a new `OAuthService.access_token()` (refresh-first, decrypted
    in-memory only). All calls through an injectable httpx client.
  - `publishing_service.py`: guards before any upload — source rights
    authorized (enforced in code), render exists and succeeded,
    approved metadata (or channel profile `auto_approve_metadata`),
    never published before. Private-first upload + visibility
    verification; failures mark the row failed with a Turkish reason
    and the job retries, reusing the stored session URI.
    `approve_metadata`, `due_channels`, `next_ready_candidate`.
  - Worker: `publish_clip` + `publish_due` job types;
    `enqueue_publish_jobs` interval-gated feed
    (`publish_check_interval_minutes`, default 10) for connected
    channels whose slot arrived.
  - API: POST `/api/clips/{id}/publish`, POST `/api/clips/{id}/approve`,
    GET `/api/channels/{id}/published`.
- Verification (2026-10-17): backend suite **223 passed, 0 failed,
  0 skipped** (M10 adds 13: schedule parsing/timezone/due rules;
  full private-verified publish, duplicate skip, rights guard,
  approval guard + approve-then-publish, auto-approve profile, render
  guard, failed-upload reconciliation on the same row with the stored
  session URI, worker publish_due e2e through a mock transport, worker
  feed, API roundtrip). Migration 0010 offline SQL passes. Acceptance
  criteria: uploads succeed (mock), duplicates prevented (unique row +
  skip), private visibility verified (videos.list check asserted),
  scheduling tested (timezone-aware pure functions), rights checks
  before publication (guard test), failed uploads recovered
  (reconciliation test). Live YouTube API verification is a Pi-time
  step gated on B4 (OAuth values).

### Milestone 11 — End-to-End Automation (completed 2026-10-17)

- Date: 2026-10-17
- Milestone: 11
- Task: connect monitoring to planning, planning to the media queue (M7),
  media completion to review/publishing (M8-M10 feeds), configurable
  daily targets, stock-level monitoring, schedule-aware prioritization,
  notifications and operational summaries.
- Implementation:
  - `automation_service.py`: `publish_for_channel` — pause flag first,
    then daily target (published-today >= daily_clip_target waits for
    the next slot), then stock check (empty stock publishes NOTHING and
    records `publish.stock_low`); `stock_level` / `daily_published_count`
    (local-midnight aware); `operational_summary` (stage counts + stock +
    target, audited as `ops.summary`).
  - Worker: `source_discover` now chains auto-planning (monitoring ->
    planning connection); `publish_due` uses the target/stock/pause-aware
    flow; new `ops_summary` job type enqueued once per local day per
    connected channel (`enqueue_summary_jobs`, payload-day dedupe).
  - `publishing_service.due_channels` skips paused channels.
  - API: GET/PUT `/api/channels/{id}/publishing` (target, publish times,
    auto-approve, pause), GET `/api/channels/{id}/summary`.
- Verification (2026-10-17): backend suite **230 passed, 0 failed,
  0 skipped** in 43.1s (M11 adds 7: the full-chain e2e — real ffmpeg
  media through media_process -> clip_render -> subtitle_correct ->
  metadata_generate -> publish_due with mocked LLM/YouTube, every job
  succeeded and every stage row verified; empty stock publishes nothing
  (+ audit event); daily target reached returns a reason; paused channel
  skipped (and excluded from due list); channel failure isolated (one
  channel's publish failure doesn't block the other — verified with a
  failing OAuth-less channel next to a succeeding one); auto-plan after
  discovery (both discovered videos planned); profile API roundtrip).
  Note: full-suite runs must be foreground on this machine — backgrounded
  runs hung twice at an unrelated worker test (environment quirk recorded
  in agent memory, not a code defect; foreground runs are stable).

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

Verified 2026-10-19 (product surface session: auth + selected-only media
library + clip detail/player) on the dev machine (Windows 11, Python
3.11.9 venv, Node 24.13.0). Commands run from the stated directories.
NOTE: on this machine pytest must be run with file redirection, not
through pipes — piped runs hang (known dev-env quirk); the full suite
ran foreground with redirection.

- Backend — `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
  (output redirected to a log file)
  - Passed: **403**, Failed: 0, Skipped: 0 (403 collected; 5 new auth
    tests, 4 new product media tests; the media regression test
    explicitly requests `active_only=false` for its tag-vocabulary
    assertions).
  - Real ffmpeg renders and real OpenCV detection run against local
    fixtures; sqlite test connections enforce foreign keys.
  - 1 warning (starlette TestClient deprecation).
- Frontend — `cd frontend && npx vitest run`: 22 passed, 0 failed
  (App 6, SettingsScreen 4, AutomationScreen 3, CharactersScreen 5,
  MediaLibraryScreen 3, LogsScreen 1).
- Frontend types — `npx tsc -b`: clean. Production build —
  `npm run build`: succeeded.
- Secret scan — `python tools/scan_secrets.py`: clean (synthetic test
  credentials carry justified `# secret-scan-ok` markers).

Previous full-suite record (2026-10-18, post-scheduled-public +
library-cleanup sessions): backend 383/384 (two chunks), frontend
21→22 — superseded by the totals above.

Previous full-suite record (2026-10-17, connection-guide + LLM
management session):

- Backend — `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
  - Passed: **248**, Failed: 0, Skipped: 0 (media-tooling tests run
    real ffmpeg/ffprobe from PATH; webcam tests run real OpenCV on
    the committed PD face fixture; sqlite test connections enforce
    foreign keys).
  - This session added: LLM `api_base` endpoint-path rejection,
    invalid-cipher-key 503 (LLM create + OAuth callback), and
    provider duplication (limit, unique names, encrypted-key copy)
    tests.
- Frontend — `cd frontend && npx vitest run`
  - Passed: 10 (App 4, SettingsScreen 3, AutomationScreen 3),
    Failed: 0
- Frontend types — `npx tsc -b`: clean. Lint — `npx oxlint`: 0
  errors (1 pre-existing React Compiler advisory in the
  SettingsScreen loadSettings effect).

Previous full-suite record (post-M11 session; per-file counts
historical, superseded by the totals above):

- Backend — `cd backend && ./.venv/Scripts/python.exe -m pytest`
  - Passed: **230** (test_automation 7, test_publishing 13,
    test_subtitle_correction 6,
    test_metadata 9, test_media_pipeline 19, test_media_probe 9,
    test_media_analysis 10, test_media_transcript 7, test_clip_candidates
    10, test_llm 18, test_jobs 18, test_oauth 14, test_settings 10,
    test_channels 9, test_sources 7, test_planning 7, test_media 7,
    test_resources 6, test_discovery 5, test_health 4, test_security 3,
    test_overview 2, test_migrations 2, test_logging 2, test_config 2,
    test_system 1, test_webcam_detect 9, test_vertical_render 7,
    test_vertical_pipeline 7 — collected per file; correction: the M7
    record's per-file list overcounted test_jobs by one, the M7 total
    172 was correct)
  - Failed: 0; Skipped: 0 (media-tooling tests run real ffmpeg/ffprobe
    from PATH — dev machine and CI image both provide them;
    webcam tests run real OpenCV on the committed PD face fixture)
  - sqlite test connections enforce foreign keys (production parity).
  - 2 warnings: starlette TestClient deprecation notice (dev-only) and a
    pytest unhandled-thread-exception notice from a worker test
    (both pre-existing).
- Frontend — `cd frontend && npx vitest run`
  - Passed: 10 (App 4, SettingsScreen 3, AutomationScreen 3)
  - Failed: 0
- Frontend lint — `npx oxlint`: 0 errors (1 React Compiler advisory note).
- Frontend build — `npm run build` (`tsc -b && vite build`): succeeded.
- Secret scan — `python tools/scan_secrets.py` from repository root:
  clean (token/key-handling lines carry justified `# secret-scan-ok`
  markers; synthetic test fixtures marked).
- CI — GitHub Actions `build-images` on `main`: M7 head commit `2eabbf4`
  built successfully (run `39019597052`, 2026-10-17, 7m10s — first
  image including the ffmpeg layer; every earlier run since the last
  record also `success`, previous latest `39010166549` for `121e175`).
- Live deployment — Pi (CasaOS): stack deployed by the user; UI, API,
  and migrated database verified from the user's logs (2026-10-17).
  The app's live database is `autoshorts_studio` on the shared
  PostgreSQL instance (2 live app connections observed via
  pg_stat_activity; see the deployment-polish record).

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
  - `a8133fe` deployment DB record correction
  - `511ecd7`..`11226eb` Milestone 7 (eight task commits: schema,
    probe, adapters, transcript, analysis, candidates, pipeline,
    worker wiring + image)
- Working tree: clean after the final commit
- Uncommitted changes: none after each milestone commit

## 9. Immediate Next Actions

1. Milestone 12 (next): production hardening (fault injection, backups,
   repeated test runs, Pi verification).
2. User (to exercise M7/M8 on the Pi): pull the new image (includes
   ffmpeg + yt-dlp + OpenCV + fonts), run `alembic upgrade head`
   (migrations 0007+0008), and optionally import authorized test media
   via a `media_process` job payload with `import_path`, or connect a
   real YouTube source (B4).
3. User (to connect a real YouTube channel): enter the Google Cloud
   OAuth client values + Fernet key via the site settings screen or
   compose env vars (B4).
4. User (security): confirm gates G1/G2 in `docs/SECURITY.md` (B3).

## 10. Handoff Notes

- Product surface session (2026-10-19, user request: "login ekranı olsun,
  sadece seçilen videolar görünsün, hazır videolar izlenebilsin"):
  (1) Login — `app_meta.studio_auth` stores the first-run operator username,
  PBKDF2-SHA256 password hash and a random session secret. `AuthService` +
  `install_auth_middleware` close every non-public `/api` route once a
  password exists; health and auth endpoints stay open, the console docs are
  closed. `POST /api/auth/setup` is first-run only; login/logout/status are
  cookie-based (HttpOnly, SameSite=Lax, 7-day TTL, `AUTH_COOKIE_SECURE` for
  HTTPS). The React app gates the whole studio behind `AuthScreen`
  (first-run setup or login) and returns to it on any 401
  (`studio:unauthorized` event in `api/client.ts`).
  (2) Product media view — GET `/api/media` gained `engine_selected_only`
  and `ready_only`. Engine mode shows only sources with a `selected`
  candidate plus the currently running source; league/backlog rows stay
  hidden. Each source carries `stages` (download → inspect → transcript →
  analysis → candidates → selection), `selected_candidates` (times, score,
  hype confidence, render status), `source_channel_title`, `youtube_url`,
  reaction/trim/filter metadata and `is_current`.
  (3) Ready clips — GET `/api/media/clips/{id}` returns the player URL,
  cover URL, latest metadata revision, candidate/hype detail, source,
  publishing plan (upload status, visibility, next slot, timezone, daily
  limit) and applied filters. GET `/api/media/clips/{id}/stream` serves the
  rendered file with Starlette Range support; `/thumbnail` serves the
  composed cover. Render jobs now write a text-free preview thumbnail
  (`thumbnails/preview_{render_id}.jpg`) so clips are visible before
  metadata approval; approval still writes the final text cover.
  (4) UI — MediaLibraryScreen is a product view: current-engine panel,
  selected-video cards with YouTube channel links, compact ready-clip grid,
  and ClipDetailModal (HTML5 player, metadata/title/description/tags,
  cover, selection reason, filters, YouTube plan). Admin screens are grouped
  under "Yönetim" in the rail; logout lives in the rail footer.
  Verified: backend 403/403, frontend 22/22, `tsc -b` clean,
  `npm run build` clean, secret scan clean. DB migration not required.
- UI de-clutter session (2026-10-19, "arayüzden ne olup bittiğini
  anlayamıyorum"): four operator-facing complaints addressed. (1) The
  Overview "Canlı boru hattı" panel (job cards, queue, "Son sonuçlar")
  was removed outright — LivePipeline.tsx + its test deleted, dead
  pipeline-*/pj-* CSS cleaned. (2) The Overview "Boru hattı" summary
  table gained a Detay button opening the new
  PipelineDetailModal.tsx: it lists the authorized source channels
  (new `sources` block in GET /api/pipeline: title, platform,
  publishing channel, monitored-video count, excluded not counted)
  plus current and queued jobs. (3) AutomationScreen was rewritten as
  a natural-language activity view: GET /api/jobs now enriches every
  job with title/channel_name/ribbon_color/stage (route-level
  `_enrich` calling the new PipelineViewService.job_context), the
  screen groups jobs into "Şu an sürüyor / Sırada bekleyen / Son
  bitenler" under a status-pill strip; shared phrasing lives in
  frontend/src/jobNarrative.ts (used by the detail modal too).
  (4) The media library default list now carries only videos that
  entered the system: GET /api/media gained `active_only` (asset
  present OR confirmed OR a running media/hype job, so asset-less
  in-flight videos stay visible), summary gained
  `entered`/`queued_pool`, and the first stat card reads "İşleme
  giren". Untouched discovery-pool rows remain reachable via the
  "Sırada" filter; "Hata" also reads the full pool so asset-less
  failed jobs stay visible; "Daha fazla yükle" now shows in every
  filter. Verified: backend 394/394 (two new tests:
  test_overview_lists_authorized_sources,
  test_active_only_keeps_entered_videos, plus extended
  test_api_endpoints_roundtrip), frontend 22/22, `npm run build`
  clean. Separately investigated a user-pasted
  "ERROR:root:... tts.py, line 144: only 0-size arrays..." log:
  proven NOT from this stack (no tts.py in v2 or the local old
  projects; v2 backend logs are structured JSON, not `ERROR:root:`);
  source unidentified — ask the user where it appeared if it recurs.
- AV1-codec session (2026-10-19, live follow-up "sistem hiç düzgün
  çalışmıyor"): the user's complaint traced to ONE root cause — YouTube
  serves AV1 even at 1080p, and the container's OpenCV wheel cannot
  decode AV1 (cv2 read: False; "Missing Sequence Header") while ffmpeg
  CLI can (dav1d). Consequences: all 6 rendered clips sat in 'review'
  ("ornek kare okunamadi" — webcam detection reads frames via OpenCV),
  and scene/silence analyses timed out (AV1 decode is 3-5x slower than
  H.264 on the Pi; video 103's media_process exhausted retries).
  Fixes (e676b9b): yt-dlp format now prefers H.264 at ≤1080p
  (`bv*[height<=1080][vcodec^=avc]+ba/...` with an unrestricted
  fallback) so future downloads are OpenCV-decodable and fast;
  `webcam_detect.sample_frames` gained an ffmpeg frame-extraction
  fallback (`_sample_frames_ffmpeg`: fps-filter → PNGs → imread,
  concept-verified against the live AV1 file before deploy; missing
  files still raise); both vertical_pipeline call sites now run
  detection via `asyncio.to_thread` (the ffmpeg pass can take minutes
  and must not block the event loop). Live result after deploy +
  re-enqueueing the 6 review clips: 4 rendered (stock 0 → 4), 2 remain
  in review (no stable face in those windows); subtitle corrections
  grind through 61-86 LLM chunks per video (long compilations) with
  chunk retries absorbing the provider's occasional 300s timeouts;
  video 103 stays failed (its already-downloaded AV1 file exceeds the
  600s scene-analysis timeout — future downloads are H.264 so this
  does not recur). Known follow-up candidates: raise the scene
  analysis timeout for very long videos; recover_stale still runs only
  at worker startup.
- Reasoning-model session (2026-10-19, live follow-up "Token şifreleme
  anahtarı... diyor ancak girmiştim"): the user's restart had picked the
  bdaf5fd image (built before 25bfdc1 existed), so the cipher fix wasn't
  live yet — repulled and restarted with the 25bfdc1 image. The cipher
  error was then gone (first LLM call 200 OK) but a NEW live failure
  surfaced: `AttributeError: 'NoneType' object has no attribute 'strip'`
  in subtitle_correct/hype jobs, unlogged in llm_request_logs (crash
  before the log line). Root cause (probed live with a container-side
  script that never prints the API key — response body only): the
  user's provider routes google/gemma-4-31b, a REASONING model that
  spends completion tokens on thinking BEFORE visible content; when
  the max_tokens budget is consumed by reasoning the OpenAI-compat
  response comes back 200 with `content: null` (ping with 8 tokens:
  null + reasoning_budget_exhausted; subtitle-like prompt with 1024:
  valid JSON — 309 reasoning + 60 content). The old `_call_openai`
  returned the null content unchecked and `_parse_json(None)` crashed.
  Fixes: all three adapters (openai/anthropic/google) now validate the
  extracted text is a non-empty string, else `_BadResponseBody` →
  logged invalid_response + chain falls through (no more raw
  AttributeError); `_parse_json` is None-defensive; `complete()`
  default max_tokens 1024 → 4096 (reasoning headroom for 20-segment
  subtitle chunks); the Dene ping test uses 256 tokens instead of 8
  (a reasoning model can never answer within 8) and catches
  _BadResponseBody → invalid_response result instead of an unhandled
  500. Tests: test_llm +1 (null-content → LlmServiceError with
  invalid_response log, not AttributeError), chain-dependent files
  re-run clean (test_llm 23, subtitle/metadata/automation/
  channel_automation 54). Deploy: image pull + restart; then retry a
  subtitle_correct job live and verify llm_request_logs shows success.
- Reaction-channels + recency session (2026-10-19, user directive:
  "1080p üstü indirmesin; motor indirmiyor; güncellik önemli — RRaenee
  tepki videoları paylaşan kanallar tespit etsin, son 7/15 gün
  videoları indirilsin"): (1) Diagnosis — the engine was healthy; the
  monitored RRaenee channels carry ZERO reaction videos (all 50 recent
  uploads are gameplay content, correctly excluded by the rule), hence
  nothing to download. (2) Live actions (no restart needed, all via the
  running image's API): yt-dlp flat search on the Pi found channels
  reposting RRaenee reactions — Craftest (UCRXsu9ORjM6F-LjBRDXF2lw),
  cFyt (UC3E_eF5GHqA05nPPm1riHYg), Elranedits0
  (UC_eAwc9rF1hPYJjnmQgEJLQ) — all three were added to channel 4 as
  authorized youtube sources bound to character RRaenee with
  require_reaction_content + max_age_days=7 presets; the two existing
  Rraenee sources got max_age_days=7 via PATCH (rule evaluation for
  max_age_days has been live since M4). Discovery found 18 fresh
  (≤7-day, reaction-titled) videos; planning marked them planned; the
  stock refill began downloading immediately — video 101 processed
  end-to-end (5 clip candidates) and 102 followed. (3) Repo changes:
  yt-dlp format capped at `bv*[height<=1080]+ba/b[height<=1080]` (the
  4K-AV1 f401 + faststart double-write was the 39-minute "stuck
  download"); age-rule hardening — AGE_RULE_PREFIX extracted with an
  `age_exclusion()` helper, reapply now restores BOTH reaction- and
  age-rule exclusions when the window widens/rule turns off, and
  `refill_channel_stock` skips planned videos that aged while queued
  (kept planned, not excluded, so widening restores them); Characters
  screen source rows gained a "Güncellik" select (sınırsız/7/15/30
  gün → filter_rules.max_age_days). (4) Worker cipher bug found on
  live (subtitle_correct jobs failing with "Token şifreleme anahtarı
  yapılandırılmamış"): the worker's hype_evaluate/subtitle_correct/
  metadata_generate handlers built LlmProviderService with raw env
  settings while TOKEN_ENCRYPTION_KEY lives in site settings (DB) —
  all three now resolve effective_settings() first (channels.py
  _metadata_service too); regression test seeds a DB-only key and runs
  a worker subtitle_correct job to success. Tests: backend 388/388
  (4 new), frontend 23/23 (+1 recency select test), tsc/build/secret
  scan clean. Deploy note: the 1080p cap, recency hardening, cipher
  fix, and library hiding (bdaf5fd) all need the next image pull +
  restart; live processing continues meanwhile on the old image
  (reaction rule + 7-day window already active there).
- Library cleanup session (2026-10-19, live + repo): after the user
  enabled "Yalnız Tepki" on both live sources (rules_reapplied
  2026-10-18 22:23 UTC), ALL 50 backlog videos were excluded by the
  rule — the media library filled with "Hariç" rows and the user asked
  for a cleanup. Live actions on the Pi (verified with before/after
  counts): deleted the 50 `source_videos` rows with status=excluded
  (FK cascades removed their planning_decisions/media_assets cleanly;
  0 orphans left) and removed the orphaned download files
  (downloads/1.mp4 3.26 GB + 1.tr.vtt + 20.f251.webm 87 MB — disk went
  85% → 74%). NOTE for live debugging: the container's /data/media
  maps to host `/mnt/usb/Autoshorts_Studio/` directly — there is NO
  `media/` subfolder on the host side. Repo change so the clutter does
  not rebuild: the Media Library now hides excluded videos by default
  — `library_view.media_library(include_excluded=False)` filters
  `status != 'excluded'` from the listing, `sources_total`, and the
  summary's `sources_total`; `/api/media` gained
  `?include_excluded=true`; the frontend gained a "Hariç" filter chip
  that fetches with that param (excluded rows keep their "İşleme al"
  re-include button under the chip). Discovery re-adding future
  funny-moments videos as excluded is expected — they stay out of the
  default view now. Tests: backend 21/21 in the touched files
  (test_pipeline_view +new test_excluded_hidden_by_default), frontend
  22/22 (+new Hariç-filter test), tsc/build clean.
  Diagnostics also collected this session (no code change): the
  39-minute "download" for video 1 was yt-dlp fetching bestvideo f401
  (AV1 4K, 3.19 GB) then ffmpeg `-movflags +faststart` rewriting the
  whole 3.25 GB merge a second time on a USB disk at 45% iowait — the
  job ended as succeeded/skipped because the reaction rule excluded
  the video mid-merge (pipeline guard worked as designed). Candidate
  future improvement (needs user go-ahead): cap yt-dlp format at
  `bv*[height<=1080]+ba` to avoid 4K downloads on the Pi.
- Scheduled-public session (2026-10-18, user directive): approved
  content no longer waits for the engine to upload. `approve_metadata`
  and `approve_full_cut` now enqueue `publish_clip` / `publish_full_cut`
  jobs (new worker handler) that upload PRIVATE immediately
  (`_publish` stamps visibility=private, no published_at — "Gizli
  yukleme tamam: yayin ani degil, public yapma ani doldurur"). The
  automation engine's `publish_for_channel` then walks both
  orientations — ("vertical", daily_clip_target) then ("horizontal",
  PublishingProfile.daily_horizontal_limit, new in migration 0013,
  default 3; 0 = unlimited) — and flips one verified-private row to
  public per free slot: `next_ready_public` picks vertical rows by
  ClipCandidate.score desc, horizontal by row id; `make_public` calls
  videos.update privacyStatus=public, verifies with fetch_status, then
  stamps visibility=public + public_at + published_at and audits
  "publish.public". Daily counts come from `today_published_counts`
  (published_at >= local midnight, per orientation). Overview stat
  cards now read "Bugün yayınlanan yatay n/limit" / "dikey n/limit"
  (limits are sums across channels; ∞ when 0) and the channel settings
  modal exposes both limits (0..50). Media retention:
  `media_retention_days` site setting (0 = right after going public —
  the default, N days, -1 = never) drives an hourly worker pass
  `cleanup_published_media` that deletes render files + thumbnails of
  public rows past the cutoff (vertical rows resolve their source via
  the render's source_video_id fallback since PublishedVideo rows for
  clips historically lack the FK — 0013 adds the FK for full cuts) and
  also removes the media asset when the source is confirmed; audit
  "media.cleaned"; private rows are never touched. Migration 0013 is
  additive (daily_horizontal_limit, public_at, source_video_id + FK +
  index), runs automatically on container start. Tests: backend
  383/383 (7 new in test_scheduled_public.py), frontend 21/21 (mocks
  updated for the TodayPublished object), tsc/oxlint/build clean,
  secret scan clean.
- Reaction-only content rule (2026-10-18, user directive): publishing a
  source publisher's own horizontal edits is forbidden — only their
  reaction/tepkime videos may be processed (the user's example: an
  RRaenee source must yield only reactions; funny-moments compilations
  are banned, but "Reacting to funny moments" is a reaction and stays
  free). Implemented as a POSITIVE title match, not an exclude list:
  `source_rules` gained `require_reaction_content` with
  `REACTION_TITLE_MARKERS` (react/watching/izliyorum/izlerken/tepki/
  reaksiyon — "react" as a substring also covers reacts/reacting/
  reaction). A title carrying a cue stays eligible whatever it watches;
  a title without one is excluded with reason "tepkime kuralı: başlıkta
  tepki göstergesi yok". Rules apply at discovery AND, because the
  user's live backlog was already planned, `SourceService.update_source`
  now reruns `_reapply_source_rules` whenever filter_rules change: it
  re-evaluates the source's unprocessed videos (no asset or failed
  asset — mid-flight downloads stop too) and flips them to excluded
  with a synced planning_decisions ledger row; when the rule is turned
  off, ONLY rows excluded by this rule (reason prefix) come back —
  manual exclusions are never resurrected. Processed/confirmed videos
  are untouchable. The pipeline enforces the rule mid-run:
  `MediaPipelineService.run` returns skipped for an excluded video
  before any stage and rechecks between stages, so a video excluded
  while downloading stops instead of finishing. Manual correction:
  `POST /api/sources/videos/{id}/status` (planned|excluded, 422 on
  processed) backs the Media Library's "İşleme al"/"Hariç tut" row
  actions; Characters' source rows gained a "Yalnız Tepki" toggle (and
  the add-source form a checkbox) that flips the rule and triggers the
  reapply. Tests: backend 376/376 in 78 s (7 new in
  test_reaction_rules.py: marker semantics incl. the funny-moments
  reaction case, reapply keep/exclude/restore semantics, API
  roundtrip + processed guard, pipeline skip without asset);
  frontend 21/21, tsc/oxlint/build clean.
- Visibility session (2026-10-18, live overview + library + logs): the
  user could not see per-video progress anywhere, and the Media Library
  and Logs screens were still placeholder EmptyStates. Delivered in
  three layers. (1) Backend read-models: `pipeline_view.py` (active
  jobs with stage index, elapsed seconds, .part download bytes read
  from MEDIA_ROOT, ETA derived from the rolling average of the last 10
  succeeded jobs per type, expected download size from the last 5
  processed assets — never fabricated), `library_view.py` (sources with
  StatusService-tag vocabulary, rendered clips, stock summary;
  paginated), `audit_view.py` (audit_events cursor pagination +
  category/channel filters with escaped LIKE). New routes
  `/api/pipeline`, `/api/media`, `/api/logs` registered in main.py;
  job→video/channel resolution happens in Python from payload JSON so
  the queries run identically on PostgreSQL and sqlite. (2) Frontend:
  `LivePipelinePanel` on the Overview (5 s poll; per-job stage track of
  5 segments, percent, download bytes + rate measured from consecutive
  polls, "≈ N kaldı" ETA, queued positions, recent results with error
  summaries); MediaLibraryScreen rebuilt with a summary stat grid,
  status filter pills, sources table (title/channel/tag/duration/size/
  updated) and clips table; LogsScreen rebuilt as a live stream (5 s
  poll, category pills, channel select, Turkish event-label dictionary
  covering all 36 recorded event types, cursor "load older"). All in
  the committed Kategori Standardı component language (ink-panel,
  stat-card, pill, stage-track as segmented meter, filter pills with
  ocean active state). One real bug found by the new tests: the panel
  computed `active` with a fresh `[]` on every render while loading,
  retriggering the rate-measuring effect in a render loop that hung
  the vitest worker (180 s timeout, exit 134) — fixed with a stable
  module-level `NO_JOBS` reference. Tests: backend 369/369 in 75 s
  (6 new in test_pipeline_view.py: overview cards/download bytes/ETA,
  tag derivation, pagination+filters, API roundtrip), frontend 21/21
  in 2.5 s (LivePipeline 2, MediaLibrary 3, Logs 1), tsc/oxlint/build
  clean (oxlint: 6 advisories — 3 pre-existing React Compiler notes
  plus the intentional setState-in-effect in useDownloadRates, which
  derives rates from polled data).
- Production fix (2026-10-18, live download failures on the Pi): the
  worker failed every media download with `MediaDownloadError: yt-dlp
  basarisiz` after the M14 restart, for two stacked causes.
  (1) Ownership: `/mnt/usb/Autoshorts_Studio` and its five labelled
  subfolders were created `3000:3000` (predates the v2 deploy; the v1
  stack most likely made them) while the backend container runs
  `1000:1000` (Dockerfile `USER 1000:1000`), so every write into
  `/data/media/downloads` hit `Errno 13 Permission denied` (26 failed
  job cycles 01:46–06:00 UTC, video 20 etc.). Fixed on the Pi with
  `sudo chown -R 1000:1000 /mnt/usb/Autoshorts_Studio` — the step the
  Dockerfile comment already prescribed; verified with an in-container
  write test. (2) YouTube rate limiting: auto-subtitle fetches for
  `en` consistently return HTTP 429 from the Pi's IP while `tr`
  downloads fine (timedtext limit), and yt-dlp exits 1, failing the
  whole job even though the video and the `tr` sidecar land. Fix in
  code: `YtDlpAdapter.build_command` now passes `--ignore-errors`
  (backend/app/services/media_download.py) so a single dead subtitle
  language no longer kills the job; if the video itself fails the
  adapter's existing output-glob check still raises. Bridge until the
  image is rebuilt: `/mnt/usb/Autoshorts_Studio/yt-dlp.conf`
  (`--ignore-errors`) is bind-mounted read-only to
  `/etc/yt-dlp.conf` in the live CasaOS compose (backup saved as
  `docker-compose.yml.bak-20261018`); once the GHCR image carries this
  commit the mount can stay or be removed — the flag is idempotent.
  Live verification on the Pi: real yt-dlp runs write `tr.vtt`
  (778 KiB) and return exit 0 with `en` still 429; job 1415 (video 20)
  was retried and queued; recovered job 1416 (video 21) downloaded a
  1.7+ GB video with its `tr.vtt` sidecar landing in `downloads/`.
  Two follow-up observations (not fixed here): `recover_stale` only
  runs at worker startup (worker.py:934) so a long-lived worker never
  collects ghosts mid-run; httpx INFO logs print the YouTube Data API
  key inside the request URL at `LOG_LEVEL=info` (consider redacting
  or lowering httpx logs). Tests after the change: backend 363/363 in
  77 s (foreground, file-redirected — a background run reproduced the
  known full-suite hang quirk and was killed).
- What was implemented (2026-10-18, M14 "channel automation /
  Start/Stop"): the automation root cause was deployment-side — the
  compose templates in actual use did not set `WORKER_ENABLED` or
  `MEDIA_ROOT` on the backend, so the worker never started on the Pi
  (all three templates now set both; the local generated file's real
  DB password was scrubbed to a placeholder — the file is gitignored
  and never pushed, but the user should still rotate that password as
  hygiene). On top of that, the engine became genuinely controllable:
  per-channel `automation_state` (stopped/running/paused/error) with
  Start/Stop/Pause API + Overview buttons (stop cancels the channel's
  queued jobs, running jobs finish, state and queue survive
  restarts); stock-target refill enqueues exactly ONE media_process
  when ready horizontal stock (#done, not #confirmed) is below the
  channel target (default 3) and no source is in-flight globally;
  heavy jobs serialize on a shared lock with `max_heavy_jobs`; the
  central StatusService computes the #queued/#downloading/
  #processing/#done/#confirmed/#shorts/#error tags and the
  #confirmed transition; hype_evaluate (LLM with transcript context,
  validated + sentence-snapped windows, score fallback on provider
  outage) selects the candidates the render feed takes; metadata
  gained the auto/on/off modes with independent +18/AI disclosure
  decisions; whisper fallback (PATH-probed CLI) when no sidecar
  exists; worker heartbeats into `app_meta.worker_state` and the
  Overview shows a live worker banner + per-channel rows; Settings
  gained the resource-limit section (CPU/RAM/threads/retry/stock
  defaults/transcription), applied live by the worker loop. Tests:
  backend 352/352 (110 s), frontend 14/14, tsc/oxlint/build clean,
  secret scan clean — see section 7.
- Deployment (M14): migration `0012` runs automatically on container
  start (additive columns/tables only — no data migration, existing
  rows default to `stopped`/3/auto). The Pi needs an image rebuild +
  app restart (push to `main` triggers GHCR), AND the compose used on
  the Pi must now carry `WORKER_ENABLED: "true"` and `MEDIA_ROOT:
  /data/media` + the media volume — the updated
  `deploy/casaos/docker-compose.ghcr.yml` shows the exact backend
  block. After restart, verify the Overview worker banner reads
  "Worker çalışıyor" before pressing Başlat.
- Whisper runtime install (2026-10-18, M14 addendum, user-requested):
  the Settings screen shows a "Whisper'ı İndir ve Kur" button when
  Whisper is missing; `POST /api/whisper/install` runs a
  platform-aware background pip install (openai-whisper pinned) —
  direct into the venv on Windows, `--target <MEDIA_ROOT>/.whisper` +
  PYTHONPATH on the Linux/Pi container (uid 1000 cannot write system
  site-packages; the target also survives container recreation on the
  persistent media volume). Invocation switched to `python -m whisper`
  (no PATH dependency); install state tracked honestly in app_meta
  (running/succeeded/failed with pip tail) and polled by the UI;
  guards: 400 already installed, 409 double start, 503 <2 GB free
  disk. Verified by test_whisper_install (11 tests, faked pip).
- Known limitations (do not present as complete): external
  transcription services are not implemented; YouTube age-restriction
  fields are not set at upload (decisions live on metadata rows +
  UI); live YouTube/Kick flows remain mock-tested only (ADR-008) —
  real-platform verification is a Pi-time step; the whisper install
  button downloads from PyPI at runtime (pinned package) — first
  real install on the Pi is a deployment-time verification.

- What was implemented (2026-10-18, M13 "characters + multi-platform
  sources", built via three parallel subagents per
  `docs/plans/2026-10-18-character-system.md`): streamer characters
  (photo upload with Haar-extracted reference face, per-character
  system prompt, notes) with full CRUD and masked API views;
  multi-platform sources (youtube/twitch/kick platform key, character
  binding, reaction flag, head/tail trims) with rights records intact
  and manual VOD import (`POST /api/sources/{id}/videos` enqueues
  `media_process` with the URL as `import_path`; discovery stays
  YouTube-only and reports skipped platforms); reaction-source
  dual-orientation output — one trimmed 1920x1080 horizontal full cut
  (subtitles never burned, RenderedClip with NULL candidate +
  source_video set, idempotent) plus the existing vertical shorts
  (subtitle-burned), while non-reaction sources hard-guard to vertical
  only; metadata prompt chain character → global
  (`metadata_system_prompt` site setting) → built-in Turkish default,
  with new `hook`/`thumbnail_text` fields and full-cut metadata
  generation; thumbnails composed at approval from the sharpest of
  three probe frames with the approved text (DejaVu; ASCII-safe
  fallback), path stored on `rendered_clips.thumbnail_path`; webcam
  regions validated against the character's reference face (HSV+ORB
  similarity, calibration threshold default 0.30, template-search
  fallback, review routing unchanged when no reference exists);
  publishing per orientation with composite uniques; frontend
  Characters screen (channel selector, character cards with photo
  thumbs, source add/authorize/discover/VOD actions), Settings prompt
  textarea, guide section 3. `python-multipart` added to backend
  requirements (photo upload). Technical debt noted in code: full-cut
  duplicate-publish prevention is code-guarded via metadata identity
  (PublishedVideo lacks a source_video_id FK — schema was frozen at
  Task 0; revisit if full cuts misbehave).
- Tests: backend 330/330 (81s, real ffmpeg/OpenCV fixtures), frontend
  14/14, tsc clean, oxlint 0 errors, secret scan clean — see section 7.
  Dev-env reminder: run pytest with file redirection; piped runs hang.
- Deployment: migration `0011` runs automatically on container start;
  Pi needs an image rebuild + app restart (push to `main` triggers
  GHCR build). No data migration for existing rows (all new columns
  carry defaults).

- What was implemented (2026-10-17, connection-guide + LLM-management
  session, triggered by live-Pi user feedback): (1) Robustness: a
  malformed `TOKEN_ENCRYPTION_KEY` arriving from the environment no
  longer crashes LLM/OAuth routes with an unhandled `ValueError`
  (HTTP 500); `TokenCipher` now raises `TokenEncryptionError` and both
  services convert it to a clear Turkish 503. (2) LLM providers:
  `api_base` values that already contain an endpoint path
  (`/chat/completions`, `/messages`, `:generateContent`) are rejected
  with an explanatory message (the path is appended per provider type);
  the form labels now state each type's endpoint, show a live "request
  URL" preview, and support editing (PATCH, key kept when left blank)
  and one-click duplication (`POST /api/llm/providers/{id}/duplicate`
  copies the row including the encrypted key, disabled, unique name,
  lowest free priority). (3) A "Rehber" guide screen (route `/rehber`,
  last nav item) documents the full Google Cloud Console setup —
  YouTube Data API v3 enablement, consent screen (In production vs
  7-day Testing tokens), Web-application client, exact per-channel
  redirect URI `http://localhost:1478/api/channels/{id}/oauth/callback`,
  the Google HTTP/localhost-only redirect rule, the SSH-tunnel consent
  flow, settings fields, LLM provider setup, and a troubleshooting
  table; the Channels screen OAuth-failure note now links to it.
  Live-Pi findings behind these changes: the user's LLM endpoint works
  through the app (4 successful test calls logged), and the live
  channel row is id 4 — the redirect URI to register is
  `http://localhost:1478/api/channels/4/oauth/callback` (user's
  console attempts used origin-only or fake-domain URIs, causing
  redirect_uri_mismatch).
- Tests: backend 248/248, frontend 10/10, tsc clean, oxlint 0 errors
  (1 pre-existing advisory) — see section 7 for the commands.
- Deployment note: these changes reach the Pi with the next image
  build + container restart (no new migrations; runtime settings and
  stored providers are untouched).

- What was implemented: Milestones 0–8. M4: source registration with
  rights records, quota-gated cached YouTube discovery with dedupe,
  filter rules, durable auditable planning ledger. Interlude: the
  AutoShorts Studio brand kit applied everywhere and site-managed
  runtime settings (masked secrets, DB-over-env precedence, revert on
  empty). M5: bounded three-provider LLM fallback (ADR-011) with
  Fernet-encrypted keys, latency/error-category request log. M6:
  PostgreSQL SKIP LOCKED job queue with heartbeat, stale-job recovery,
  dedupe and cancel; worker with concurrency limit, periodic source
  discovery and hourly tmp cleanup; token-bucket download limit;
  disk-space guard; labelled media tree. M7 (ADR-012): stage-gated
  media pipeline as `media_process` jobs — local-import and yt-dlp
  adapters (sequential, rate-limited, disk-guarded), ffprobe integrity
  + sha256, VTT/SRT transcript sidecars, silence/scene/energy analysis
  via ffmpeg subprocesses, scored non-overlapping clip candidates with
  word-3-gram similarity rejection, all results in migration-0007
  tables, resumable at the failed stage on retry. M8 (ADR-013):
  OpenCV multi-frame webcam detection with IoU clustering and
  confidence scoring, per-source calibration table (manual region wins;
  below-threshold detection routes to review — never a wrong crop),
  9:16 top-webcam/bottom-video ffmpeg composition with burned
  subtitles in the video section, output validation (1080x1920, A/V
  sync), `clip_render` jobs with idempotent rendered_clips rows and a
  worker candidate feed. Post-M6: CasaOS deployment polish (frontend
  first, UID/GID 1000, `/mnt/usb/Autoshorts_Studio` volumes, branding)
  and the canon "Kategori Standardı" redesign (stat cards, title-bar
  table panels, soft pills, round meters) with `DESIGN.md` rewritten.
- Tests: backend 230/230 (57 M7 + 23 M8 + 15 M9 + 13 M10 + 7 M11 tests
  incl. real-ffmpeg and real-OpenCV e2e), frontend 10/10, oxlint/tsc/
  build clean, secret scan clean (re-verified 2026-10-17 post-M11).
- Deployment state: user-verified CasaOS stack on the Pi (UI/API/DB);
  the app's live database is `autoshorts_studio` on the shared
  PostgreSQL instance (verified via pg_stat_activity; ADR-005 addendum
  recorded in `docs/DECISIONS.md`). M7+M8 need an image rebuild + pull
  on the Pi (now includes ffmpeg, fonts, OpenCV; yt-dlp via pip) and
  `alembic upgrade head` (migrations 0007+0008) before media/render
  jobs can run there.
- Outstanding: B3 (gates G1/G2 user confirmation), B4 (OAuth/env values
  for a real YouTube connection — site settings now provide the entry
  path); the ghp_ token exposed in chat must stay revoked.
- Exact next task: Milestone 12 — production hardening: fault-injection
  tests (DB disconnect, LLM outage, disk exhaustion, worker restart,
  upload interruption), backup/restore validation, security scans,
  repeated full-suite runs, Pi deployment verification.
- Decisions to preserve: ADR-001…ADR-013 (M9 added no new ADR — it
  composes ADR-011's chain under a stricter response contract) plus the
  implementation
  contracts: OAuth tokens and LLM keys encrypted at rest and never in
  API responses; audit trail append-only; job claim via SKIP LOCKED
  with heartbeat-driven recovery; runtime settings override env only
  with explicit non-empty values; media tools subprocess-isolated and
  PATH-probed; media pipeline stage-gated and idempotent; canon design
  system per `DESIGN.md`.

**Never infer progress from previous plans. The repository and test
results are the source of truth.**
