# PROJECT_STATE — VisionIQ v0.2.0

- **Current phase**: Phase 2 complete (real models + hardening), verified 2026-11-05.
  v0.1.4 fixes (login 422 crash, video-page use() bug) are included.
- **Completed features**: auth + RBAC + per-user isolation; upload
  validation; ffprobe metadata; ffmpeg thumbnail/frames; OpenCV scene
  segmentation; fallback captions; hash embeddings; hybrid search;
  evidence-grounded RAG chat; hierarchical summaries; event rules +
  duplicate suppression + alerts; JSON/PDF reports; agent tool registry;
  MCP server (stdio + HTTP); Next.js frontend, 14 routes, build passes;
  docker-compose (full + laptop); GitHub Actions CI.
- **Phase 2 done (verified 2026-11-05, this machine, CPU only)**:
  YOLOv8n ONNX detection (bus.jpg: 4 persons + 1 bus, 0.88-0.90 conf,
  456-880 ms/frame, stable track_ids; bus video upload: 15 detections
  in DB, caption "Detected: bus, person"); FastEmbed embeddings
  (Recall@1 1.00 vs hash 0.67, MRR 1.00 vs 0.76, 12 queries);
  Qdrant collection creation + in-memory upsert/search; Alembic
  initial migration (12 tables, upgrade/downgrade verified);
  Celery/Redis worker (eager test + compose services); VLM client
  verified against a local mock Ollama/NIM server; benchmark suite
  with measured numbers in docs/benchmarks/2026-11-05.md.
- **Pending features**: a real VLM model run end to end (Ollama
  llava:7b / qwen2-vl:7b on the user's RTX 3050 — documented, not run
  here); sentence-transformers path (code present, needs torch, not
  tested here); ultralytics .pt + ByteTrack path (code present, torch
  install stalled on this machine and was stopped — ONNX is the
  tested path); Postgres live test of the Alembic migration (SQLite
  verified; Postgres needs Docker, not available here); Qdrant live
  server test (in-memory verified; server needs Docker); e2e browser
  tests; shadcn/ui full adoption; range/seek video streaming.
- **Files modified**: see git log (initial commit in this session).
- **Tests executed (2026-11-05, Phase 2, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` → **7 passed** (2 Phase 1
    full-flow tests + 5 Phase 2 tests: VLM mock, Qdrant in-memory,
    Celery eager, detection-unavailable, hash determinism).
  - Benchmark: hash Recall@1 0.67 / MRR 0.76; fastembed 1.00 / 1.00.
  - Detection smoke: bus video upload -> ready, 15 detections in DB.
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
