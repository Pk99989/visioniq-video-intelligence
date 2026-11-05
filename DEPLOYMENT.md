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

## Phase 2 — real models, migrations, queue (v0.2.0)

**Detection (YOLOv8n ONNX, recommended on a laptop):**
```
python scripts/download_yolo.py        # downloads yolov8n.onnx (13 MB) into backend/
# then rebuild / restart; /health should show detection: yolo-onnx, available: true
```
Weights are NOT committed to git (see .gitignore) — download them on each
machine. The .pt + ultralytics path is an alternative (`--pt`), needs torch.

**Embeddings:** set `EMBEDDING_PROVIDER=fastembed` in `.env` (default is
still `hash`, no download). First use downloads ~65 MB (BAAI/bge-small-en-v1.5).

**Real VLM on the RTX 3050 (Ollama):**
```
ollama pull llava:7b        # or: ollama pull qwen2-vl:7b
# .env: VLM_PROVIDER=ollama, VLM_BASE_URL=http://localhost:11434/v1, VLM_MODEL=llava:7b
# In the full docker stack, the backend runs in a container, so use
# VLM_BASE_URL=http://host.docker.internal:11434/v1 instead.
```

**Migrations (Alembic):**
```
cd backend && alembic upgrade head     # 12 tables; downgrade base reverses it
```

**Celery worker (full stack only):** `docker compose up` now starts a
`worker` service (Redis broker). The laptop profile stays in-process
(`WORKER_MODE=in_process`). Locally: `celery -A app.services.celery_app.celery_app worker --loglevel=info`.

**Benchmarks:** `cd backend && EMBEDDING_PROVIDER=fastembed python ../scripts/benchmark.py`
— results in `docs/benchmarks/<date>.md`.
