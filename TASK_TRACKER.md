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
| 12 | Qdrant test + Alembic migrations | Done (live server) | Qdrant 1.20.0 server upsert/search verified 2026-11-06 (bus 1.000); Alembic upgrade/downgrade/upgrade on live Postgres 16.15, 15 tables; psycopg2-binary added to requirements (was missing) |
| 13 | Redis/Celery worker | Done (live) | Real worker + Redis 7.0.15 processed a real bus-video upload in 9.1 s → ready, 50 detections, 10 Qdrant points; laptop default stays in_process |
| 14 | Benchmark suite | Done | scripts/benchmark.py + docs/benchmarks/2026-11-05.md |

| 15 | Range streaming + signed video URLs | Done | 206/416/signed-token tests pass |
| 16 | Clip retrieval (ffmpeg) + Search download button | Done | 0-2s clip verified as real mp4 |
| 17 | Detections + analytics + annotated frames | Done | Bus video: bus+person, >=5 detections |
| 18 | Logout revocation + password reset | Done | Token 401 after logout; reset single-use verified |
| 19 | Alembic migration v2 | Done | upgrade/downgrade verified on SQLite |
| 20 | Real VLM model run (Ollama llava:7b) | Pending | Needs Ollama on user's RTX 3050 |
| 21 | E2E browser tests | Done | Playwright + Chromium vs live frontend/backend/worker: register → upload → ready → search 0.847 → clip mp4 → logout, 1 passed 2026-11-06; skipped unless VISIONIQ_E2E=1 |
| 22 | Privacy: cross-user search/chat/MCP leak | Done (fixed 2026-11-06) | search_frames()/answer_question() + MCP tools now scoped to the logged-in user (admins see all); regression test tests/test_privacy.py passes; Qdrant NO_PROXY crash in retrieval.py fixed with the embeddings.py pattern |
