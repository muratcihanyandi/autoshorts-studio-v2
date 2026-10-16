# Autonomous Creator Studio — Development Roadmap

## Project Objective

Build a professional, reliable, autonomous YouTube Creator Studio for Raspberry Pi 5 (8GB RAM) and CasaOS.

The system will manage multiple YouTube channels, monitor authorized source media, process horizontal videos, generate vertical clips, correct Turkish subtitles, prepare metadata, maintain private video stock, and publish content according to configurable schedules.

The project must prioritize reliability, resource limits, content rights, and maintainability.

## Status Legend

- `NOT_STARTED`: No implementation has been verified.
- `IN_PROGRESS`: Implementation is underway.
- `BLOCKED`: Progress requires an external dependency or decision.
- `TESTING`: Implementation exists and is being verified.
- `COMPLETED`: Acceptance criteria have been verified.
- `DEFERRED`: Intentionally postponed with a documented reason.

Do not mark a milestone complete merely because its code has been generated.

---

## Milestone 0 — Environment and Architecture

Status: COMPLETED (2026-10-16; evidence in `docs/PROGRESS.md` section 3)

Tasks:
- Inspect the ZCode workspace and Git state.
- Verify available skills and MCP servers.
- Inspect available GitHub authentication.
- Confirm PostgreSQL reachability and identify the intended database.
- Verify target ARM64 and CasaOS constraints.
- Document the architecture and initial assumptions.
- Establish the initial project directory structure.
- Create a security checklist.

Deliverables:
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/SECURITY.md`
- `docs/ROADMAP.md`
- `docs/PROGRESS.md`

Acceptance criteria:
- Existing files and Git history are preserved.
- Required environment details are documented.
- Secrets are not copied into project files.
- Architectural decisions are recorded.

## Milestone 1 — Repository and Foundation

Status: IN_PROGRESS (started 2026-10-16; remote repo creation blocked on GitHub auth)

Tasks:
- Create or connect a private GitHub repository.
- Configure `.gitignore` and `.env.example`.
- Establish frontend and backend project structures.
- Set up Docker Compose for ARM64.
- Configure FastAPI.
- Configure React, TypeScript, Vite, and the UI foundation.
- Configure PostgreSQL connectivity and Alembic migrations.
- Implement health endpoints and structured logging.
- Create initial automated tests.

Acceptance criteria:
- The project builds.
- The frontend loads.
- The backend health endpoint responds.
- PostgreSQL connectivity is verified.
- Migrations can be applied safely.
- No secrets are committed.
- CasaOS deployment instructions exist.

## Milestone 2 — Studio Interface

Status: NOT_STARTED

Tasks:
- Read the Impeccable and Frontend Design skill instructions.
- Establish design tokens and reusable components.
- Implement responsive navigation.
- Implement Overview, Channels, Media Library, Calendar, Automation, LLM Providers, Logs, and Settings screens.
- Add loading, empty, error, and retry states.
- Connect dashboard widgets to real API data.
- Add system resource indicators.
- Verify accessibility and keyboard navigation.

Acceptance criteria:
- The UI has a consistent studio-oriented visual identity.
- Navigation works.
- Data comes from the backend.
- Loading and failure states are handled.
- The interface remains responsive during background jobs.

## Milestone 3 — Database and Channel Management

Status: NOT_STARTED

Tasks:
- Implement channel, OAuth credential, source channel, and publishing profile models.
- Implement migrations and repository/service layers.
- Implement multiple connected YouTube channels.
- Implement secure OAuth flows.
- Implement token refresh and reconnection.
- Implement channel-specific settings.
- Implement audit events.

Acceptance criteria:
- Multiple channels can be represented independently.
- OAuth state validation works.
- Secrets are not exposed in API responses.
- A disconnected channel does not disable other channels.
- Database changes survive restarts.

## Milestone 4 — Source Monitoring and Planning

Status: NOT_STARTED

Tasks:
- Integrate official YouTube metadata APIs.
- Implement source-channel registration.
- Implement configurable polling.
- Add quota tracking and caching.
- Add source filtering and exclusion rules.
- Implement rights records.
- Implement a durable planning service.
- Prevent duplicate source records and duplicate jobs.

Acceptance criteria:
- New source videos can be detected through authorized API access.
- Quota limits are respected.
- Source permissions are recorded.
- Duplicate discovery does not create duplicate jobs.
- Planning decisions are auditable.

## Milestone 5 — LLM Provider Manager

Status: NOT_STARTED

Tasks:
- Implement main provider configuration.
- Implement fallback provider 1.
- Implement fallback provider 2.
- Implement configurable model IDs and API endpoints.
- Add masked API key management.
- Add timeout, retry, and rate-limit handling.
- Validate structured responses.
- Record request latency and error categories.
- Add simulated provider-failure tests.

Acceptance criteria:
- Main-provider failure triggers fallback.
- Invalid responses are rejected safely.
- Repeated failures do not cause infinite retries.
- Secrets are never logged.
- The provider manager can be tested independently.

## Milestone 6 — Durable Job Queue and Resource Management

Status: NOT_STARTED

Tasks:
- Implement persistent job states.
- Implement worker heartbeat.
- Implement retry and cancellation.
- Implement restart recovery.
- Implement configurable concurrency.
- Implement download bandwidth limits.
- Add disk-space checks.
- Add CPU and memory monitoring.
- Implement safe temporary-file cleanup.

Acceptance criteria:
- Jobs survive application restarts.
- Duplicate execution is prevented where possible.
- Cancellation leaves consistent state.
- Download speed limiting is measured.
- Low disk space prevents unsafe new jobs.
- Heavy work does not block API requests.

## Milestone 7 — Horizontal Video Processing

Status: NOT_STARTED

Tasks:
- Implement authorized media-source adapters.
- Implement sequential downloads.
- Validate media integrity.
- Inspect metadata with ffprobe.
- Implement transcript generation.
- Implement intro/outro candidate detection.
- Implement scene and reaction analysis.
- Implement clip-candidate generation.
- Add content similarity checks.
- Store processing results in PostgreSQL.

Acceptance criteria:
- Authorized test media can pass through the entire pipeline.
- Failures are recorded and recoverable.
- Candidate timestamps are valid.
- Original files are preserved while needed.
- The worker remains within configured resource limits.

## Milestone 8 — Vertical Studio and Webcam Detection

Status: NOT_STARTED

Tasks:
- Implement 9:16 rendering templates.
- Implement multi-frame webcam detection.
- Implement webcam tracking and confidence scoring.
- Implement streamer-specific calibration.
- Implement manual region selection.
- Implement top-webcam/bottom-video composition.
- Implement subtitle positioning.
- Implement generated-video validation.
- Add representative test videos.

Acceptance criteria:
- Test clips render with the expected layout.
- Webcam uncertainty triggers review.
- Audio and video remain synchronized.
- Cropping and subtitle overlap are validated.
- Performance and detection limitations are documented.

## Milestone 9 — Turkish Subtitle Correction and Metadata

Status: NOT_STARTED

Tasks:
- Implement timestamped transcript storage.
- Implement Turkish spelling and punctuation correction.
- Preserve names and timestamps.
- Flag uncertain corrections.
- Implement channel-specific metadata templates.
- Generate titles, descriptions, and tags.
- Validate metadata length and content accuracy.
- Store metadata revisions.

Acceptance criteria:
- Original transcripts remain recoverable.
- Corrections do not silently alter timestamps.
- Invalid metadata is rejected.
- Template changes do not affect unrelated channels.

## Milestone 10 — YouTube Upload and Publishing

Status: NOT_STARTED

Tasks:
- Implement official API uploads.
- Implement resumable upload where supported.
- Implement private upload handling.
- Store YouTube video IDs.
- Implement per-channel publishing schedules.
- Implement timezone-aware planning.
- Implement visibility checks.
- Implement retry and reconciliation after failures.
- Implement publication approval controls.

Acceptance criteria:
- Authorized test videos upload successfully.
- Duplicate uploads are prevented.
- Private visibility is verified.
- Scheduling behavior is tested against the actual API.
- Rights checks run before publication.
- Failed uploads can be recovered.

## Milestone 11 — End-to-End Automation

Status: NOT_STARTED

Tasks:
- Connect source monitoring to the planning engine.
- Connect the planning engine to the media queue.
- Connect media completion to the review and publishing pipeline.
- Implement configurable daily targets.
- Implement stock-level monitoring.
- Implement schedule-aware prioritization.
- Add notifications and operational summaries.

Acceptance criteria:
- The full pipeline runs on authorized test content.
- Jobs progress through valid states.
- Insufficient stock does not cause unsafe publication.
- Channel failures remain isolated.
- The system can pause and resume safely.

## Milestone 12 — Production Hardening

Status: NOT_STARTED

Tasks:
- Run long-duration workloads on Raspberry Pi 5.
- Measure CPU, RAM, disk, and thermal behavior.
- Test network interruptions.
- Test database disconnections.
- Test LLM outages.
- Test disk exhaustion.
- Test worker restarts.
- Test OAuth expiration.
- Test upload interruption.
- Validate backup and restore.
- Perform security and secret scans.
- Document deployment, upgrades, and recovery.

Acceptance criteria:
- Critical failure scenarios have verified recovery behavior.
- Resource limits are documented.
- Backups can be restored.
- No known critical security issue remains unaddressed.
- Actual test results are documented.

---

## Cross-Milestone Rules

- Work on one primary milestone at a time.
- Small independent tasks may be completed in parallel when safe.
- Do not begin full autonomous publishing before rights, quality, and recovery checks work.
- Update `docs/PROGRESS.md` after each meaningful task.
- Update this roadmap when scope or dependencies change.
- Record significant architectural decisions in `docs/DECISIONS.md`.
- Every completed milestone must have verifiable evidence.
- Never claim that the entire application is production-ready without end-to-end verification.

## Immediate Next Action

Milestone 0 is complete. Proceed with Milestone 1 (local foundation).

GitHub authentication is currently unavailable (`gh` not logged in), so the
private repository creation is blocked; complete all local work, commit
incrementally, and report the exact blocker. When authentication is
available, create the private repository and push.

Deployment remains gated on the user confirming GitHub token revocation and
PostgreSQL password rotation (`docs/SECURITY.md` gates G1/G2).