# VisionIQ — Multimodal Video Intelligence and Agentic Search Platform

An independent implementation **inspired by** the architecture of NVIDIA's
Video Search and Summarization (VSS) blueprint (Apache-2.0, see
`docs/architecture/` for the attribution and what was *not* copied). No
NVIDIA source code is included here.

Upload a video, and VisionIQ extracts frames and scenes, captions them,
indexes them for semantic search, answers questions with timestamp
citations, summarises long videos hierarchically, evaluates configurable
event rules, and generates JSON/PDF reports — through a LangGraph-shaped
agent and an MCP tool server.

## What is new in v0.2.0 — Phase 2 (verified, 2026-11-05, CPU only)

- **Real detection:** YOLOv8n ONNX — `python scripts/download_yolo.py`, then
  Detection shows `yolo-onnx / available: true` in `/health`. Verified on
  bus.jpg (4 persons + 1 bus, 0.88–0.90 confidence).
- **Real embeddings:** `EMBEDDING_PROVIDER=fastembed` (BAAI/bge-small-en-v1.5,
  384-d). Measured on 12 labelled queries: Recall@1 1.00 vs 0.67 for hash.
- **Qdrant, Alembic, Celery:** collection is created before upsert;
  `alembic upgrade head` (12 tables); Celery worker in the full stack.
- **VLM:** client verified against a mock Ollama/NIM server. To use a real
  model on the RTX 3050: `ollama pull llava:7b`, then
  `VLM_PROVIDER=ollama VLM_BASE_URL=http://localhost:11434/v1 VLM_MODEL=llava:7b`.

## What actually works in v0.1.0 (verified, 2026-11-04)

- Auth (PBKDF2 + JWT), RBAC (user/admin), per-user video isolation —
  tested: a second user gets 404 on another user's video.
- Upload with format + 500 MB size validation, ffprobe metadata,
  ffmpeg thumbnails, 1 fps frame extraction (capped at 120 frames),
  scene segmentation by frame-change, background processing, failed-job
  recovery on restart, explicit retry.
- Search: hybrid keyword + embedding cosine, reranked, with timestamps
  and frame evidence. Default embedding is a deterministic hash embedding
  (laptop-safe); `EMBEDDING_PROVIDER=sentence_transformers` swaps in a
  real model when installed.
- RAG chat: evidence-grounded answers with citations; below a score
  floor the agent says "No video evidence" instead of guessing.
- Summaries (short/medium/long), event rules with duplicate suppression,
  alerts + acknowledgement, JSON/PDF reports.
- Agent tools (`video_search`, `video_qa`, `video_summarize`,
  `clip_retrieval`, `event_analysis`) via REST and via the MCP server
  (`mcp_server/server.py`, stdio JSON-RPC and HTTP).
- Frontend: Next.js 14 + TypeScript + Tailwind, 14 routes covering auth,
  dashboard, library, upload, processing, player with timestamp seeking,
  search, chat, summaries, events, alerts, reports, settings, users.
  `npm run build` passes (16 pages).

## What is deliberately a fallback, not a claim

- **VLM captions**: `VLM_PROVIDER=fallback` (default) produces template
  captions from scene timing + detections, labelled `provider=fallback`.
  Real captions need `VLM_PROVIDER=openai_compatible|nvidia_nim|ollama`
  plus `VLM_BASE_URL` (and a key for NIM/OpenAI). See `SECURITY.md` —
  never put a key in the repo.
- **Object detection**: YOLO via `ultralytics` is lazy-loaded only if
  installed *and* `backend/yolov8n.pt` exists (`scripts/download_yolo.py`).
  Without it, `/health` reports `available: false` and no boxes are
  invented. ByteTrack tracking activates through ultralytics' tracker
  when the model is present.
- **Qdrant**: optional. Without `QDRANT_URL`, vectors live in the
  database (JSON per frame) and search still works. With it, frames are
  also upserted to Qdrant.
- **PostgreSQL/Redis**: SQLite is the laptop default; set `DATABASE_URL`
  for Postgres (see `docker-compose.yml`). Redis is reserved for a
  future queue; the current worker is in-process (1 video at a time).

## Quickstart — laptop (recommended, Windows 11 + WSL2 Ubuntu 24.04)

```bash
cp .env.example .env   # set JWT_SECRET
docker compose -f docker-compose.laptop.yml up --build
# frontend http://localhost:3000  ·  backend http://localhost:8000  ·  docs http://localhost:8000/docs
```

Without Docker:

```bash
bash scripts/run_dev.sh
# or manually: backend venv + uvicorn, frontend npm install && npm run dev
```

Full stack (Postgres + Qdrant): `docker compose up --build` (see `DEPLOYMENT.md`).

## Smoke test

```bash
bash scripts/generate_sample_video.sh sample.mp4
# Register at http://localhost:3000/login, upload sample.mp4,
# then search "scene" and ask the chat "What is in this video?"
```

## Layout

```
visioniq/
  frontend/            Next.js 14, TypeScript, Tailwind
  backend/             FastAPI app (app/routers, app/services, app/models)
  mcp_server/          MCP stdio + HTTP tool server
  database/            see DATABASE_SCHEMA.md (migrations: see note there)
  infrastructure/      docker/ (see docker-compose*.yml at root)
  tests/               backend tests live in backend/tests/
  scripts/             sample video, YOLO download, dev runner
  docs/                architecture, decisions, deployment
```

## Docs

`ARCHITECTURE.md` · `PROJECT_STATE.md` · `TASK_TRACKER.md` ·
`DATABASE_SCHEMA.md` · `API_DOCUMENTATION.md` · `DEPLOYMENT.md` ·
`TESTING.md` · `SECURITY.md` · `TROUBLESHOOTING.md` · `CHANGELOG.md`

## Licence

This project's own code is MIT (see `LICENSE`, to be added on first
release if you choose otherwise). NVIDIA's VSS blueprint is Apache-2.0
and is referenced, not redistributed.
