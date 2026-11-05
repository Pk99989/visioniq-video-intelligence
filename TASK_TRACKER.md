# TASK_TRACKER

| # | Task | Status | Evidence |
|---|------|--------|----------|
| 1 | Study NVIDIA VSS reference (architecture only) | Done | ARCHITECTURE.md, README attribution |
| 2 | Backend: auth, upload, processing pipeline | Done | backend/app/*, pytest 7 passed (2026-11-05) |
| 3 | Backend: search, RAG, agent, events, reports | Done | backend/app/services/*, pytest full flow |
| 4 | MCP server (stdio + HTTP) | Done | mcp_server/server.py (tools = agent registry) |
| 5 | Frontend: 14 routes, real API integration | Done | `npm run build` passes, 16 pages |
| 6 | Docker (full + laptop) + CI | Done | docker-compose*.yml, .github/workflows/ci.yml |
| 7 | Docs (README, ARCHITECTURE, API, DB, DEPLOY, TESTING, SECURITY, TROUBLESHOOTING, CHANGELOG) | Done | root + docs/ |
| 8 | GitHub repo `visioniq-video-intelligence` | Blocked | `gh` not logged in on this machine — needs user's `gh auth login` or repo creation |
| 9 | Real YOLO detection end-to-end | Done (ONNX) | yolov8n.onnx + onnxruntime: bus.jpg 4 persons + 1 bus, 0.88-0.90 conf; bus video: 15 detections in DB; ultralytics .pt path untested (torch install stalled) |
| 10 | Real VLM (NIM/Ollama) end-to-end | Partial | Client verified against local mock server; no real vision model run here — Ollama llava:7b documented for user's RTX 3050 |
| 11 | Real embeddings + benchmarks | Done (FastEmbed) | fastembed bge-small-en-v1.5: Recall@1 1.00 vs hash 0.67, MRR 1.00 vs 0.76 (12 queries); sentence-transformers path present, untested (needs torch) |
| 12 | Qdrant test + Alembic migrations | Done (in-memory/SQLite) | Qdrant collection + in-memory upsert/search verified; Alembic initial migration upgrade/downgrade verified on SQLite; live Postgres/Qdrant server tests need Docker |
| 13 | Redis/Celery worker | Done | celery_app + redis/worker compose services; eager task test passes; laptop default stays in_process |
| 14 | Benchmark suite | Done | scripts/benchmark.py + docs/benchmarks/2026-11-05.md; e2e browser tests still pending |

| 15 | Range streaming + signed video URLs | Done | 206/416/signed-token tests pass |
| 16 | Clip retrieval (ffmpeg) + Search download button | Done | 0-2s clip verified as real mp4 |
| 17 | Detections + analytics + annotated frames | Done | Bus video: bus+person, >=5 detections |
| 18 | Logout revocation + password reset | Done | Token 401 after logout; reset single-use verified |
| 19 | Alembic migration v2 | Done | upgrade/downgrade verified on SQLite |
| 20 | Real VLM model run (Ollama llava:7b) | Pending | Needs Ollama on user's RTX 3050 |
| 21 | E2E browser tests | Pending | Playwright not run here |
