# CHANGELOG

## v0.2.0 — 2026-11-05 (Phase 2: real models + hardening)

- Real detection: YOLOv8n via onnxruntime (`yolov8n.onnx`, no torch).
  Verified on bus.jpg: 4 persons + 1 bus, confidence 0.88-0.90,
  plausible boxes, track_ids stable across frames; end-to-end upload
  of a bus video stores 15 detections (5/frame x 3 frames) and the
  caption now reads "Detected: bus, person". Ultralytics .pt path kept
  as an option (ByteTrack) but NOT tested on this machine — torch
  install was stopped after it stalled (see PROJECT_STATE).
- Real embeddings: FastEmbed BAAI/bge-small-en-v1.5 (384-d, onnxruntime,
  ~65 MB). Benchmark (12 labelled queries): Recall@1 1.00, MRR 1.00
  vs hash 0.67 / 0.76. Set EMBEDDING_PROVIDER=fastembed.
- Qdrant: collection is now created before upsert (was missing);
  verified with in-memory client (upsert + search, top hit score >0.9).
- Alembic: initial migration (12 tables), upgrade head / downgrade
  base / upgrade head verified on SQLite.
- Celery/Redis worker: `app.services.celery_app`, WORKER_MODE=celery,
  redis + worker services in docker-compose.yml; eager task test passes.
- VLM: OpenAI-compatible client verified against a real local mock
  server (Ollama/NIM shape); fixed httpx proxy crash (trust_env=False)
  and the same NO_PROXY issue in FastEmbed loading.
- Benchmark suite: scripts/benchmark.py, results in docs/benchmarks/2026-11-05.md.
- /health now reports embedding_provider and worker_mode; version 0.2.0.
- Still fallback: VLM captions (no real vision model run here — Ollama
  llava:7b is documented for the user's RTX 3050, not tested here).

## v0.1.0 — 2026-11-04 (initial working release)

- FastAPI backend: auth, upload, processing pipeline, search, RAG chat,
  agent tools, summaries, events/alerts, reports (JSON/PDF), MCP server.
- Next.js 14 frontend: 14 routes, real API integration, dark/light toggle.
- Docker Compose (full + laptop profiles), GitHub Actions CI.
- Docs: README, ARCHITECTURE, PROJECT_STATE, TASK_TRACKER,
  DATABASE_SCHEMA, API_DOCUMENTATION, DEPLOYMENT, TESTING, SECURITY,
  TROUBLESHOOTING.
- Verified: backend pytest 2 passed, frontend `npm run build` passes.
- Known limitations: fallback VLM captions, YOLO weights not bundled,
  hash embeddings by default, no Alembic migrations yet, no GitHub
  remote yet (gh not logged in on the build machine).
