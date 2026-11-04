# PROJECT_STATE — VisionIQ v0.1.0

- **Current phase**: Phase 1 complete (working end-to-end core). Phase 2
  (real models + Postgres/Qdrant hardening) is pending and listed below.
- **Completed features**: auth + RBAC + per-user isolation; upload
  validation; ffprobe metadata; ffmpeg thumbnail/frames; OpenCV scene
  segmentation; fallback captions; hash embeddings; hybrid search;
  evidence-grounded RAG chat; hierarchical summaries; event rules +
  duplicate suppression + alerts; JSON/PDF reports; agent tool registry;
  MCP server (stdio + HTTP); Next.js frontend, 14 routes, build passes;
  docker-compose (full + laptop); GitHub Actions CI.
- **Pending features**: real YOLO weights download + detection benchmark;
  real VLM (Cosmos/Nemotron via NIM or Ollama vision model) end-to-end
  test; sentence-transformers embedding benchmark; Qdrant live test;
  PostgreSQL migration files (Alembic — currently tables are created by
  SQLAlchemy `create_all`, see DATABASE_SCHEMA.md); Redis/Celery queue
  replacing the in-process worker; light/dark theme toggle is implemented
  (ThemeToggle) but defaults to dark; shadcn/ui component library is
  represented by small local ui components, not the full shadcn package;
  e2e browser tests; benchmark suite (Recall@K, faithfulness, etc. —
  no numbers are claimed yet, see TESTING.md).
- **Files modified**: see git log (initial commit in this session).
- **Tests executed (2026-11-04, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` → **2 passed**.
    Full flow: register/login, upload a real 3 s ffmpeg test video,
    status `ready`, scenes + fallback captions present, search hit,
    chat with citations, no-evidence answer for a nonsense query,
    summary, event evaluation, PDF report download (`%PDF` header),
    401 unauthenticated, 404 cross-user, invalid upload 400, delete 204.
  - Frontend: `npm run build` (Next 14.2.35) → **compiled successfully,
    16 pages**.
- **Known bugs / limitations**:
  - Next.js 14.2.18 was replaced by 14.2.35 after npm flagged a security
    vulnerability in 14.2.18.
  - Video streaming in the browser goes through an authenticated blob
    fetch (the `<video>` tag cannot send a bearer token) — works, but
    range/seek streaming is not yet implemented.
  - Hash embeddings match keywords, not semantics; Recall@K numbers
    would be meaningless until a real embedding model is enabled.
  - GitHub remote is NOT created: `gh` is not logged in on this machine.
    Local git repo is initialised; see DEPLOYMENT.md for the two commands
    to create/push `visioniq-video-intelligence`.
- **Environment configuration**: this machine — Python 3.12 venv,
  ffmpeg 8.1.2, Node 24, no Docker, no GPU. Target machine — Windows 11,
  WSL2 Ubuntu 24.04, RTX 3050, 16 GB RAM.
- **Exact next steps**:
  1. On the user's WSL machine: `docker compose -f docker-compose.laptop.yml up --build`,
     upload a real video, confirm the flow in the browser.
  2. `gh auth login` then create the GitHub repo and push.
  3. Enable a real VLM (Ollama vision model or NVIDIA NIM) and a real
     embedding model, then run the benchmark suite in TESTING.md.
  4. Add Alembic migrations and a Redis/Celery worker (Phase 2).
