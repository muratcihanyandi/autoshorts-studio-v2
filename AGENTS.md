# AGENTS.md — Autonomous Creator Studio

Instructions for coding agents working in this repository
(`AutoShortsStudio_RaspberryPi5_2`). This file is the project-level contract;
user-level agent rules still apply where they do not conflict.

## Project Mission

A reliable, autonomous YouTube Creator Studio for Raspberry Pi 5 (8GB RAM,
CasaOS, ARM64 Linux). It manages multiple YouTube channels, monitors
authorized source media, processes horizontal videos into vertical clips,
corrects Turkish subtitles, prepares metadata, maintains a private video
stock, and publishes on configurable schedules.

Priorities in order: reliability, resource limits, content rights,
maintainability.

## Non-Negotiable Rules

1. **Read before acting.** Read `docs/ROADMAP.md` and `docs/PROGRESS.md`
   before starting any session. The repository and test results are the only
   source of truth — never infer progress from plans or chat history.
2. **Evidence-based status.** Never mark a milestone, task, or test complete
   without verified evidence. Record evidence in `docs/PROGRESS.md`.
3. **Secrets.** Never commit, print, or log API keys, tokens, passwords, or
   OAuth secrets. Never reuse credentials from the earlier
   `AutoShortsStudio` / `AutoShortsStudio_RaspberryPi5_` projects
   (see `docs/SECURITY.md` for the incident context and deployment gates).
4. **Deployment gates.** Do not deploy until the user confirms (a) the
   previously exposed GitHub token has been revoked and (b) the PostgreSQL
   password has been rotated. New credentials must be freshly generated.
5. **Preserve working systems.** Minimum change + maximum correctness. Do not
   rewrite working code, do not refactor without cause, do not delete user
   data or files.
6. **One milestone at a time.** Follow `docs/ROADMAP.md` order. Small safe
   side tasks may be parallelized.

## Workflow Per Session

1. Inspect `docs/PROGRESS.md` (especially "Handoff Notes") and the repository
   state (`git status`, `git log`).
2. Pick the current milestone's next task.
3. Implement with minimal, idiomatic changes; keep naming and architecture.
4. Test: unit tests first, then integration, then build/lint/type check.
5. Fix what you broke; do not hide failures with try/except or skips.
6. Commit incrementally with clear messages (never commit secrets).
7. Update `docs/PROGRESS.md` with verified results and handoff notes.

## Technology Stack (Planned — see docs/DECISIONS.md)

- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2.
- Frontend: React, TypeScript, Vite.
- Database: PostgreSQL 17 (dedicated database, durable job state).
- Media: FFmpeg / ffprobe.
- LLM: three configurable providers with bounded fallback.
- YouTube: official Data API + OAuth 2.0 only.
- Deployment: Docker Compose, ARM64 (linux/arm64), CasaOS on Raspberry Pi 5.

## Repository Layout

```
AGENTS.md               Agent contract (this file)
docs/                   Roadmap, progress, architecture, decisions, security
backend/                FastAPI application, Alembic migrations, tests
frontend/               React + TypeScript + Vite application
deploy/                 Docker Compose and deployment assets
```

## Environment Notes (verified 2026-10-16)

- Development machine: Windows 11. Git, Node 24, Python 3.11, ffmpeg 8.1
  available. Docker CLI NOT available on the dev machine; Compose files are
  authored here and executed on the Raspberry Pi.
- Git Bash on this machine needs
  `export PATH="/c/Program Files/Git/cmd:/c/Program Files/Git/usr/bin:$PATH"`
  because the default PATH lacks Git's `usr/bin` (coreutils) in this shell.
- Target: Raspberry Pi 5 (aarch64), PostgreSQL 17.10 runs there inside a
  Docker bridge network; CasaOS hosts the containers.
- `gh` CLI is installed but not authenticated. GitHub MCP server has no
  authenticated user context. Remote repository work is blocked until the
  user authenticates.

## Language Rules

- Agent-to-user communication: Turkish.
- Code, identifiers, file names, terminal commands: ASCII only (no Turkish
  characters). Turkish characters are allowed only in UI strings.
- Project documentation: English (matches existing `docs/` files).

## Testing Rules

- Backend: pytest. Frontend: Vitest + TypeScript checks. Run tests before
  every commit that changes code.
- Never report a test as passed if it was skipped or not executed.
- Record commands, environment, and results in `docs/PROGRESS.md`.
