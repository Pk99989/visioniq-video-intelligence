# TASK_TRACKER

| # | Task | Status | Evidence |
|---|------|--------|----------|
| 1 | Study NVIDIA VSS reference (architecture only) | Done | ARCHITECTURE.md, README attribution |
| 2 | Backend: auth, upload, processing pipeline | Done | backend/app/*, pytest 2 passed |
| 3 | Backend: search, RAG, agent, events, reports | Done | backend/app/services/*, pytest full flow |
| 4 | MCP server (stdio + HTTP) | Done | mcp_server/server.py (tools = agent registry) |
| 5 | Frontend: 14 routes, real API integration | Done | `npm run build` passes, 16 pages |
| 6 | Docker (full + laptop) + CI | Done | docker-compose*.yml, .github/workflows/ci.yml |
| 7 | Docs (README, ARCHITECTURE, API, DB, DEPLOY, TESTING, SECURITY, TROUBLESHOOTING, CHANGELOG) | Done | root + docs/ |
| 8 | GitHub repo `visioniq-video-intelligence` | Blocked | `gh` not logged in on this machine — needs user's `gh auth login` or repo creation |
| 9 | Real YOLO detection end-to-end | Pending | Needs weights + ultralytics install |
| 10 | Real VLM (NIM/Ollama) end-to-end | Pending | Needs VLM_BASE_URL + model |
| 11 | Sentence-transformers embeddings + benchmarks | Pending | No benchmark numbers claimed yet |
| 12 | Qdrant live test + Postgres migrations (Alembic) | Pending | Code paths exist, not live-tested |
| 13 | Redis/Celery worker | Pending | In-process worker is the current implementation |
| 14 | E2E browser tests + benchmark suite | Pending | See TESTING.md |
