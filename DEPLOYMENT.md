# DEPLOYMENT

## Laptop (recommended first run — Windows 11 + WSL2 Ubuntu 24.04)

Prerequisites: Docker Desktop with WSL2 integration, or Docker Engine in WSL.

```bash
cp .env.example .env   # set a real JWT_SECRET
docker compose -f docker-compose.laptop.yml up --build
```

Frontend http://localhost:3000 · backend http://localhost:8000 · API docs /docs.
Shutdown: `docker compose -f docker-compose.laptop.yml down`
(volumes persist storage; add `-v` to wipe them).

## Full stack

```bash
docker compose up --build
```

Adds PostgreSQL (`DATABASE_URL` is set in the compose file) and Qdrant
(`QDRANT_URL=http://qdrant:6333`). Set `JWT_SECRET` in `.env` first —
the full compose file refuses to start without it.

## Without Docker

```bash
bash scripts/run_dev.sh
```

Requires ffmpeg + ffprobe on PATH, Python 3.12, Node 20.

## GitHub (blocked on this machine, two commands on yours)

`gh` was not logged in here, so no remote was created. On your machine:

```bash
cd visioniq-video-intelligence
gh auth login
gh repo create visioniq-video-intelligence --public --source=. --remote=origin --push
```

Or create the repo at github.com/new named `visioniq-video-intelligence`,
then: `git remote add origin <url> && git push -u origin main`.
Never force-push without explicit authorisation.

## Production notes

- Set `JWT_SECRET` to a long random value; rotate if ever leaked.
- Put the backend behind HTTPS (reverse proxy) — JWTs are bearer tokens.
- Use PostgreSQL + Qdrant compose, not the laptop profile, and back up
  the `backend_storage`, `pgdata` and `qdrantdata` volumes.
- Resource limits are in the compose files (2 CPU / 4 GB per backend);
  raise them only if you have headroom — the RTX 3050 / 16 GB target
  does not.
