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
