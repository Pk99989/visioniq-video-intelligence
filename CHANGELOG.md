# CHANGELOG

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
