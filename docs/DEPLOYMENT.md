# Deployment — Raspberry Pi 5 / CasaOS

Target: Raspberry Pi 5 (8GB, ARM64) running CasaOS with Docker. Everything
below runs **on the Pi** unless noted. The dev machine has no Docker CLI;
Compose files are authored there and executed here.

## 0. Security gates (mandatory, do this first)

Before deploying, confirm both gates from `docs/SECURITY.md`:

- **G1:** the previously exposed GitHub token has been revoked
  (GitHub → Settings → Developer settings → tokens).
- **G2:** the PostgreSQL password of the shared instance has been rotated.

Then generate **fresh** credentials for this stack — never reuse anything
from the old projects.

## 1. Prerequisites (on the Pi)

- Docker + Docker Compose v2 (CasaOS provides these).
- git (`sudo apt install git` if missing).
- Outbound HTTPS for image pulls (python, node, nginx, postgres images).
- Free RAM: the stack adds roughly 300–500MB (PostgreSQL ~100MB, backend
  ~150MB, nginx ~10MB). The Pi's 8GB must also hold the existing services.

## 2. Get the code and configure

```bash
git clone <REPOSITORY_URL> ~/autoshorts-studio
cd ~/autoshorts-studio
cp .env.example .env
```

Edit `.env`:

- `POSTGRES_PASSWORD` — generate fresh, e.g.
  `openssl rand -hex 24`. Use letters/digits only (the value is embedded
  in a database URL; avoid `@ : / # ?` characters).
- `POSTGRES_USER` / `POSTGRES_DB` — defaults `autoshorts` /
  `autoshorts_studio` are fine.
- `FRONTEND_PORT` — LAN port for the web UI (default `8080`).

## 3. Start the stack

From the repository root (note the explicit flags — they pin the project
directory and env file regardless of where compose runs from):

```bash
docker compose --project-directory . -f deploy/docker-compose.yml \
  --env-file .env up -d --build
```

First build takes several minutes on the Pi (Python and Node image pulls,
pip install, npm ci, Vite build). Later builds reuse layers.

## 4. Verify

```bash
docker compose --project-directory . -f deploy/docker-compose.yml ps
curl http://localhost:8080/api/health        # {"status":"ok",...}
curl http://localhost:8080/api/health/ready  # {"status":"ok","database":"reachable"}
```

The backend runs `alembic upgrade head` before starting, so the schema is
applied automatically. Readiness returning `database: reachable` confirms
migrations completed and the app connects to PostgreSQL.

From another device on the LAN, open `http://<pi-ip>:8080/`.

## 5. CasaOS integration (optional)

The stack is a plain Compose project, so it appears in CasaOS → Docker
once running. To install through the CasaOS UI instead of the CLI:
CasaOS → App Store → "Install from compose file" — paste the contents of
`deploy/docker-compose.yml`, set the environment variables (section 2) in
the UI, and adjust the build context paths to match where the repository
was cloned. The CLI flow in section 3 is the recommended path because it
keeps the source tree and `.env` together.

## 6. Updating

```bash
cd ~/autoshorts-studio
git pull
docker compose --project-directory . -f deploy/docker-compose.yml \
  --env-file .env up -d --build
```

Migrations run again automatically on startup. Data lives in the
`postgres_data` volume and survives rebuilds.

## 7. Backup and restore

```bash
# Backup
docker compose --project-directory . -f deploy/docker-compose.yml exec \
  postgres pg_dump -U autoshorts autoshorts_studio > backup_$(date +%F).sql

# Restore (into a fresh stack)
cat backup_2026-10-16.sql | docker compose --project-directory . \
  -f deploy/docker-compose.yml exec -T postgres \
  psql -U autoshorts -d autoshorts_studio
```

Media volumes (`media_cache`, `media_out`) do not exist yet; they are
added with the media pipeline in later milestones.

## 8. Troubleshooting

- `POSTGRES_PASSWORD must be set` — `.env` missing or the compose command
  omitted `--env-file .env`.
- `health/ready` returns `503 not_configured` — the backend container did
  not receive `DATABASE_URL`; check `docker compose config` output.
- Backend logs: `docker compose ... logs backend` (JSON lines, secrets
  redacted).
- Migration failure blocks startup on purpose; inspect
  `docker compose ... logs backend` for the failing migration.

## 9. Known limitations (verified 2026-10-16)

- The Compose file has been YAML/structure-validated but never executed
  (no Docker on the dev machine). First execution happens on the Pi.
- Only the frontend port is published; the API is reachable through the
  frontend proxy (`/api/*`), and PostgreSQL is reachable only inside the
  `studio-net` Docker network.

## 10. Media pipeline and automation (M7–M11, added 2026-10-17)

The backend image now ships ffmpeg/ffprobe (Debian package), the
DejaVu core fonts (subtitle burn-in via libass), OpenCV headless
(webcam detection), and yt-dlp (pinned in requirements.txt, invoked as
a subprocess — never imported). The container runs `alembic upgrade
head` on start, so pulling the new image applies migrations 0007–0010
automatically (`media_assets`, `media_inspections`, `transcripts`,
`clip_candidates`, `webcam_calibrations`, `rendered_clips`,
`corrected_transcripts`, `metadata_templates`, `clip_metadata`,
`published_videos`).

### Required environment additions

Nothing new is mandatory. Optional tuning (site settings or env):

- `WORKER_ENABLED=true` — REQUIRED for the autonomous pipeline
  (discovery, processing, rendering, publishing). Without it the API
  serves but no jobs run.
- `DOWNLOAD_RATE_LIMIT_KBPS` — yt-dlp `--limit-rate` for downloads.
- `CLIP_MIN_SECONDS` / `CLIP_MAX_SECONDS` — candidate window bounds.
- `PUBLISH_CHECK_INTERVAL_MINUTES` — schedule poll cadence (default 10).

### Operational controls (API)

- `PUT /api/channels/{id}/publishing` — daily target, publish times,
  auto-approve, `paused` (pause/resume the whole channel safely; jobs
  survive restarts and resume where they stopped).
- `PUT /api/sources/{id}/webcam-calibration` — manual webcam region
  (wins over detection) or a per-source confidence threshold.
- `POST /api/clips/{id}/approve` — approve generated metadata.
- `GET /api/channels/{id}/summary` — stage counts, stock, target.

### Verified recovery behavior (M12 fault injection)

- Worker restart: queued/running jobs are recovered via
  heartbeat-driven stale recovery; a half-finished media asset resumes
  at the failed stage (an explicit new `import_path` re-runs the
  download stage).
- Interrupted uploads: the resumable session URI is persisted; a
  retried publish continues on the same row instead of duplicating.
- LLM outage: jobs fail with recorded reasons and succeed on retry
  once a provider recovers (bounded fallback chain, ADR-011).
- Disk exhaustion: downloads are refused below `MIN_FREE_DISK_GB`;
  jobs stay queued and resume when space returns.
- OAuth expiry: access tokens refresh before use; a channel without
  valid credentials fails only its own publish jobs (isolation).

### Backup and restore (verified by tests)

```bash
# SQLite (dev/tests)
python tools/backup_database.py backup  --url URL --out backup.db.bak
python tools/backup_database.py restore --url URL --from backup.db.bak
python tools/backup_database.py verify  --url URL --against backup.db.bak

# PostgreSQL (Pi) — custom-format dump + verified restore
python tools/backup_database.py backup \
  --url postgresql://autoshorts_app:***@192.168.2.170:5432/autoshorts_studio \
  --out backup.dump
python tools/backup_database.py restore --url ... --from backup.dump
```

The `verify` subcommand compares core-table row counts between the
live database and the backup. Schedule backups with cron on the Pi
(e.g. daily at 04:00) and keep the media tree (`/mnt/usb/Autoshorts_Studio`)
backed up separately — the database does not contain video bytes.

### Content rights and safety gates

Every publish passes the guard chain in code: the source channel must
be `authorized` (rights record), metadata approved (or channel
auto-approve), render validated, and the clip never published before.
Uploads are private-first; visibility changes are always explicit.
Full autonomous publishing additionally requires the ROADMAP
cross-milestone rule: rights, quality, and recovery checks green.
