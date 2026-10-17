# Architecture Decision Records — AutoShorts Studio

Each decision records context, the decision, and its status. Decisions are
revisited only with cause; changes are recorded as new ADRs.

## ADR-001: Fresh repository, no reuse of the earlier projects

- **Status:** Accepted (2026-10-16)
- **Context:** Earlier attempts exist in
  `Documents\AutoShortsStudio` and `Documents\AutoShortsStudio_RaspberryPi5_`.
  A credential-exposure incident occurred in that lineage (GitHub token and
  PostgreSQL password). The current workspace `..._2` contains only fresh
  documentation.
- **Decision:** Start a new git repository here. Never copy code, config, or
  credentials from the earlier projects. If a specific old file is ever
  needed, it must be reviewed for secrets before import and re-written, not
  copied.
- **Consequences:** No tainted history enters this repository; some
  re-implementation cost.

## ADR-002: Monorepo with backend/ + frontend/ + deploy/

- **Status:** Accepted (2026-10-16)
- **Context:** One product, one deployment unit, single developer with agent
  assistance.
- **Decision:** Single repository: `backend/` (FastAPI), `frontend/`
  (React), `deploy/` (Compose), `docs/`. Matches the pre-existing empty
  directories in the workspace.
- **Consequences:** Atomic cross-stack changes; CI stays simple.

## ADR-003: FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2 for the backend

- **Status:** Accepted (2026-10-16, planned)
- **Context:** Roadmap requires Python, async, typed validation, migrations.
- **Decision:** FastAPI with async endpoints; SQLAlchemy 2 (async engine)
  for data access; Alembic for migrations; Pydantic v2 settings for config.
- **Consequences:** Standard, well-documented stack on ARM64.

## ADR-004: React + TypeScript + Vite for the frontend

- **Status:** Accepted (2026-10-16, planned)
- **Context:** Roadmap mandates React, TypeScript, Vite. UI work in
  Milestone 2 must use the `impeccable` and `frontend-design` skills
  (both verified available in this ZCode environment).
- **Decision:** Vite React-TS template; design tokens and components are
  established in Milestone 2 under those skills, not ad hoc.

## ADR-005: Dedicated PostgreSQL database, fresh credentials, no shared-instance dependency

- **Status:** Accepted (2026-10-16, planned). **Addendum 2026-10-16:** the
  user selected the documented alternative — reuse the *server* (the
  existing PostgreSQL 17.10 on the Pi at `192.168.2.170:5432`) instead of a
  dedicated container, to save RAM. Conditions unchanged and mandatory: a
  dedicated least-privilege role (`autoshorts_app`) owning a dedicated
  `autoshorts_studio` database with a freshly generated password. The
  shared admin role (`muratcihanyandi`) must never be used by the app, and
  its password (exposed in chat on 2026-10-16) must not be reused.
  Implementation: `deploy/casaos/docker-compose.external-db.yml` (no
  postgres service; backend points at the external instance). The bundled
  container variant remains available as
  `deploy/casaos/docker-compose.casaos.yml`.
  **Verification 2026-10-17 (read-only pg_stat_activity):** the live stack
  connects to `autoshorts_studio` on the shared instance from the Docker
  bridge (2 idle pool connections) — the server-reuse choice is in effect.
  One condition is NOT met: the app connects as the shared admin role
  (`muratcihanyandi`), not the planned least-privilege `autoshorts_app`
  role. Aligning the role (or explicitly accepting the deviation) belongs
  to the user; related to gate G2 (password rotation) in
  `docs/SECURITY.md`.
- **Context:** The Pi already runs a shared PostgreSQL 17.10 (Docker network
  172.18.0.2) hosting several service databases, all owned by a single
  role. Its credentials are part of the exposed-credential lineage and must
  not be reused. The postgres MCP available to the agent is read-only and
  its stored credential must not be extracted or copied.
- **Decision:** The deployment Compose stack includes its own
  `postgres:17` (multi-arch, ARM64) container with a dedicated
  `autoshorts_studio` database and a freshly generated role/password set at
  deployment time via environment variables. Using the existing shared
  instance is allowed only as an alternative chosen by the user, with a
  newly created least-privilege role and a new password — never with
  existing credentials.
- **Consequences:** ~100MB extra RAM on the Pi for a second PostgreSQL
  instance; total isolation from the other services and from exposed
  credentials. Deletion of the app stack cannot damage other databases.

## ADR-006: PostgreSQL as the only durable store, including job state

- **Status:** Accepted (2026-10-16, planned)
- **Context:** Jobs must survive restarts (Milestone 6); the Pi already
  requires PostgreSQL; adding Redis/RabbitMQ would add RAM and failure
  modes.
- **Decision:** Durable job queue implemented as PostgreSQL tables
  (`SELECT ... FOR UPDATE SKIP LOCKED` pattern) with worker heartbeats.
- **Consequences:** No extra broker service; throughput is far below
  PostgreSQL limits for a single-node pipeline.

## ADR-007: Docker Compose with explicit linux/arm64, validated locally without Docker

- **Status:** Accepted (2026-10-16, planned)
- **Context:** The dev machine has no Docker CLI. The target is Raspberry
  Pi 5 / CasaOS.
- **Decision:** Compose files pin `platform: linux/arm64` and multi-arch
  images; local validation is limited to YAML schema/syntax checks;
  runtime verification is a deployment step on the Pi, recorded in
  `docs/PROGRESS.md`.
- **Consequences:** Container runtime bugs surface only on the Pi; the
  tradeoff is accepted because installing Docker on the dev machine is out
  of scope.

## ADR-008: Local test strategy without project PostgreSQL credentials

- **Status:** Accepted (2026-10-16, planned)
- **Context:** The agent must not know or handle the database password.
  Unit tests must run on the dev machine.
- **Decision:** Unit/integration tests use SQLite in-memory (SQLAlchemy)
  or FastAPI TestClient with dependency overrides. Migration correctness is
  checked via Alembic offline SQL generation. End-to-end PostgreSQL
  verification runs on the Pi at deployment, after the user provisions
  `.env`.
- **Consequences:** PostgreSQL-specific behavior (concurrency, SKIP LOCKED)
  is only fully tested on the Pi; documented as a known limitation.

## ADR-009: Deployment gated on credential revocation and rotation

- **Status:** Accepted (2026-10-16)
- **Context:** The user requires verification that the previously exposed
  GitHub token is revoked and the PostgreSQL password rotated before any
  deployment.
- **Decision:** Recorded as hard deployment gates in `docs/SECURITY.md`.
  The agent verified that no live GitHub token exists in the current
  environment (`gh` unauthenticated; GitHub MCP has no user context), but
  final revocation/rotation confirmation belongs to the user and must be
  obtained before deployment.
- **Consequences:** Development, commits, and local tests proceed; remote
  repository creation and deployment wait for authentication and gate
  confirmation.

## ADR-010: git identity and remote setup

- **Status:** Accepted (2026-10-16)
- **Context:** `gh` is not authenticated, so no private GitHub repository
  can be created yet. Global git identity exists (Murat /
  murat@example.com).
- **Decision:** Initialize the repository locally and commit incrementally.
  When GitHub access is available, create a **private** repository and push.
  The placeholder email `murat@example.com` should be replaced with the
  user's real GitHub email before pushing (or commits will not be linked
  to the account).
- **Consequences:** Remote backup is deferred; all work is safe locally.

## ADR-011: LLM provider manager with bounded fallback

- **Status:** Accepted (2026-10-17)
- **Context:** Subtitle correction and metadata generation need an LLM.
  Milestone 5 requires three configurable providers with bounded
  fallback: a failing main provider must not stall the studio, but
  failures must also never cause unbounded retries. API keys are secrets
  and must never appear in responses or logs.
- **Decision:** Store up to three provider rows (name, type, api_base,
  model_id, encrypted api_key, priority, timeout, retries) in
  `llm_providers`; keys are Fernet-encrypted with the same
  TOKEN_ENCRYPTION_KEY used for OAuth tokens. Requests walk the enabled
  providers in priority order; each provider gets `1 + max_retries`
  attempts (network/timeout only), then the chain moves on. Every
  attempt writes a `llm_request_logs` row (status category + latency,
  grouped by a request UUID); values and keys are never logged. A
  request fails outright once the chain is exhausted — no background
  retry loop. Structured (JSON) responses are validated with the
  caller's Pydantic model; invalid output counts as a provider failure
  and triggers fallback.
- **Consequences:** Worst case per user request is bounded:
  `sum(1 + retries_i)` attempts. Adding a provider is a site operation
  (Settings-style API, masked keys). The manager is testable with
  injected HTTP transports, independent of any vendor account.

## ADR-012: Subprocess-isolated media tools, stage-gated pipeline, caption-sidecar transcripts

- **Status:** Accepted (2026-10-17)
- **Context:** Milestone 7 must download authorized media, validate
  integrity, inspect metadata, obtain transcripts, analyze
  silence/scenes/energy, and produce clip candidates on a
  memory-constrained Raspberry Pi 5. ffmpeg/ffprobe and yt-dlp are
  mature C/Python tools, but in-process use (especially yt-dlp) risks
  worker memory and crash isolation problems; ASR (Whisper) is far too
  heavy for the Pi and unnecessary when sources carry captions.
- **Decision:**
  1. External media tools run as **subprocesses**, probed on PATH
     (`ffmpeg_bin`, `ffprobe_bin`, yt-dlp binary). yt-dlp is installed
     in the container image via requirements.txt but never imported;
     dev-machine tests never require it (adapters take injected
     runners). Zero new Python imports at runtime.
  2. The pipeline is **stage-gated and idempotent** on the M6 job
     queue: `media_assets.stage` names the next pending stage
     (download -> inspect -> transcript -> analysis -> candidates);
     each stage commits its own progress, so a retried job resumes at
     the failed stage instead of redownloading. Downloads serialize
     through one shared asyncio lock and respect the M6 disk guard and
     rate limit (`--limit-rate`).
  3. **Transcripts come from caption sidecars**: yt-dlp writes
     auto-subs next to the media; local imports may carry their own
     .vtt/.srt. VTT/SRT are parsed in-process; missing transcripts
     degrade to transcript-less scoring rather than failing the job.
     Heavy ASR stays out of scope for the Pi.
  4. **Local import adapter** (`origin='local_import'`) lets operators
     feed already-authorized files (copied, never moved) — this is also
     the acceptance-test path for "authorized test media" without any
     YouTube dependency.
- **Consequences:** Crashes of external tools cannot take down the
  worker; the ARM64 image grows by the Debian ffmpeg package; yt-dlp
  availability is a deployment property verified on the Pi. Similarity
  checks are transcript-text based (word 3-gram Jaccard), which is
  cheap and explainable but blind to visually similar silent clips —
  acceptable for M7; revisit with perceptual hashing if needed.
