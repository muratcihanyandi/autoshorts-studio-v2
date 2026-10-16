# Security Checklist — Autonomous Creator Studio

Living document. Every gate must be re-checked before deployment. Never
store real secrets in this file or any committed file.

## 1. Incident Context

A previous project lineage (`Documents\AutoShortsStudio`,
`Documents\AutoShortsStudio_RaspberryPi5_`) exposed a GitHub token and a
PostgreSQL password. This repository is a clean restart
(see `docs/DECISIONS.md` ADR-001).

Standing rules:

- Never read, copy, print, or reuse credentials from those old projects,
  their `.env` files, their git history, or any MCP server configuration.
- Never extract the credential stored inside the ZCode postgres MCP
  configuration; that connection is for read-only inspection only.
- Never commit `.env` files or any file containing a real secret.

## 2. Deployment Gates (must all be YES before deployment)

| # | Gate | Status | Evidence / action |
|---|---|---|---|
| G1 | Previously exposed GitHub token revoked | **PENDING user confirmation** | User must verify in GitHub → Settings → Developer settings → Token (classic / fine-grained). Agent verified no live token exists in the current environment (`gh auth status`: not logged in; GitHub MCP `user:@me` → HTTP 422, no authenticated context). Absence here is consistent with revocation but is not proof of it. |
| G2 | PostgreSQL password rotated | **PENDING user confirmation** | User must change the password of the shared PostgreSQL instance (and any place it is stored). **Update 2026-10-16:** the shared-instance credential (role `muratcihanyandi` @ `192.168.2.170:5432`) was pasted into the agent chat by the user and must now be treated as EXPOSED. It was not written to any file or commit. The app must not use that role at all: create a dedicated least-privilege role (`autoshorts_app`) with a freshly generated password. Rotating the shared admin role itself also requires updating every dependent service (n8n, affine, …) — user decision. |
| G3 | New app credentials freshly generated | Not yet applicable | `autoshorts_studio` database role/password will be generated at deployment; never copied from old projects. |
| G4 | `.env` excluded from git | **In place, verified** | `.gitignore` + `.dockerignore` (also excluded from images); `tools/scan_secrets.py` fails if any `.env*` (except `.env.example`) is tracked. Scan clean on 2026-10-16. |
| G5 | OAuth tokens and LLM API keys encrypted at rest | Planned (Milestones 3/5) | Application-level encryption; key delivered via environment variable. |
| G6 | Secrets never returned by API responses | Planned | API schemas exclude secret fields; tests assert masked output. |
| G7 | Secret scan of Git changes | **Basic guard in place** | `tools/scan_secrets.py` scans tracked+untracked files for common secret patterns (GitHub/OpenAI/AWS keys, credentialed DB URLs, private keys, assigned secrets) with compose `${VAR}` expansion; run before each commit. It is a pragmatic guard, not a guarantee. |
| G8 | Rights records enforced before publication | Planned (Milestones 4/10) | Publication blocked without a recorded rights record for the source. |

## 3. Handling Rules

### Secret storage

- All runtime secrets arrive via environment variables (`.env` on the Pi,
  never committed; `.env.example` documents the keys without values).
- YouTube OAuth refresh tokens and LLM provider keys are stored encrypted
  in PostgreSQL; the encryption key itself comes from the environment.
- Logs must never contain secret values; structured logging includes a
  redaction filter for known secret-bearing fields.

### Access

- The backend API must not be exposed to the public internet without
  authentication (CasaOS local network by default).
- Database port is not published beyond the Docker network unless the user
  explicitly chooses otherwise.
- YouTube API usage: official Data API and OAuth 2.0 only; no scraping, no
  ToS-violating source acquisition. Source media requires recorded
  authorization.

### Backups

- PostgreSQL volume + media volumes are backed up (Milestone 12).
- Backups must not contain plaintext secrets beyond what the database
  already encrypts.

## 4. Verification Log

| Date | Check | Result |
|---|---|---|
| 2026-10-16 | No secrets in the three pre-existing workspace files (`AGENTS.md` was empty, `docs/ROADMAP.md`, `docs/PROGRESS.md` are documentation) | Pass (manual review) |
| 2026-10-16 | `gh auth status` | Not logged into any GitHub hosts — no token present in environment |
| 2026-10-16 | GitHub MCP authenticated context (`user:@me`) | HTTP 422 — no authenticated user; consistent with revoked/absent token |
| 2026-10-16 | Workspace `.env` / secret files | None exist (`find` over workspace shows only the three documentation files) |
| 2026-10-16 | PostgreSQL exposure | Server reachable via MCP with stored credential; rotation status unknown → Gate G2 pending |
| 2026-10-16 | Secret scan before each Milestone 1 commit (`tools/scan_secrets.py`) | Clean on every run; flagged synthetic test fixtures were annotated with `# secret-scan-ok`; compose variable references are expanded, literal secrets and secret defaults still fail (self-tested) |
| 2026-10-16 | `.env` tracked in git | Not tracked (`git ls-files` via scanner check); `.gitignore` and `.dockerignore` both exclude it |
| 2026-10-16 | Deployment stack secret handling | `deploy/docker-compose.yml` requires a fresh `POSTGRES_PASSWORD` (fails fast if unset), keeps PostgreSQL on an internal Docker network only, and publishes only the frontend port |
| 2026-10-16 | Shared PostgreSQL credential pasted into agent chat (`192.168.2.170`, role `muratcihanyandi`) | Treated as EXPOSED: not copied into any file, commit, or compose template; deployment path requires a new `autoshorts_app` role with a fresh password; rotation of the exposed credential itself is the user's decision (high blast radius across other CasaOS services) |
| 2026-10-16 | CasaOS compose templates (`deploy/casaos/`) | Contain only `BURAYA`/`__GENERATED_PASSWORD__` placeholders; secret scan clean; scanner extended with an SQL password-literal pattern and placeholder markers |
