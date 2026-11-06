# PROJECT_STATE — VisionIQ v0.10.0

- **Current phase**: Phase 8 complete (frontend upgrades), verified 2026-11-06.
  Phases 0–7 done: audit, real VLM (moondream, CPU), adaptive sampling,
  CV calibration, Qdrant-first RAG + 54-question eval, agent + MCP,
  event engine, DB/infra hardening. Next: Phase 9 security hardening.
- **Completed features**: auth + RBAC + per-user isolation; upload
  validation; ffprobe metadata; ffmpeg thumbnails/frames; OpenCV scene
  segmentation; real VLM captions (Ollama moondream verified, llava:7b
  configured for the user's RTX 3050); adaptive fps + frame dedupe +
  scene merge; YOLOv8n ONNX detection with per-video tracking and
  trajectories (hand-labelled GT: bus P/R 0.80/0.80); FastEmbed + hash
  embeddings; Qdrant-first hybrid search with filters (label/provider/
  time) and reranker (off by default); evidence-grounded RAG chat with
  conversation memory (M12); hierarchical summaries; event rules +
  zone engine (enter/exit/dwell/loitering, evidence clips, VLM verify);
  JSON/PDF reports; 8-tool deterministic agent + MCP server (stdio +
  HTTP); Alembic-only schema (migrations run at import/startup and in
  the Docker entrypoint); Postgres pooling; tested backup/restore;
  Qdrant payload indexes; Celery reliability (time limits, task ids,
  failure handler, recovery grace); token pruning; CI unit + integration
  jobs; Next.js frontend, 15 routes, build passes; Vitest frontend
  tests; Playwright e2e (13-step flow incl. chat history, search
  filters, 360 px check); docker-compose (full + laptop); GitHub
  Actions CI.
- **v0.4.0 (Phase 0–2 + H1)**: audit docs; real VLM integration
  (structured JSON captions, retries, 3 provider tiers, /health/vlm);
  moondream verified end to end (bus caption provider='ollama', search
  0.865); adaptive sampling (bus 10 s: 3.0 s, was 9.1 s); password-reset
  token no longer returned in API responses. 28 backend tests.
- **v0.5.0 (Phase 3 CV)**: YOLO calibration (conf/NMS/classes/per-class
  conf/track IoU/missed/age/CUDA-first, in /health), per-video Tracker,
  GET /videos/{id}/trajectories (16 tracks on moving video, dwell up to
  7.5 s). 38 backend tests.
- **v0.6.0 (Phase 4 RAG)**: Qdrant-first search (owner filter, 100-point
  pool, DB fallback), filters, stopwords, expansion only to detected
  labels, cross-encoder reranker (off by default), evidence compression
  + citation validation, reindex script. 54-question eval: R@5 0.66,
  MRR 0.48, faithfulness 1.0, relevance 0.95, negatives correct 0.38
  (open follow-up: per-provider evidence-floor calibration). 46 tests.
- **v0.7.0 (Phase 5 agent + MCP)**: deterministic multi-step planner
  (max 3 tools, merged validated citations), 8 tools with inputSchema,
  ADR 0001 (LangGraph not adopted), MCP hardening (error codes, HTTP
  400), empty-Qdrant fallback fix. 63 tests.
- **v0.8.0 (Phase 6 events)**: zones table + Alembic v3, zone CRUD API,
  evaluate_zones (enter/exit/dwell 5 s/loitering 30 s candidate),
  evidence clip windows, VLM verify endpoint. 71 tests.
- **v0.9.0 (Phase 7 infra)**: Alembic-only schema, Postgres pooling
  (5/10/30 s/1800 s, pre-ping) + postgresql:// → psycopg2 fix, tested
  backup/restore (all row counts matched), Qdrant payload indexes,
  Celery limits + failure handler + recovery grace 600 s, token pruning,
  CI integration job. 78 tests.
- **v0.10.0 (Phase 8 frontend)**: backend pagination (limit/offset +
  X-Total-Count) on videos/detections/frames/events/alerts; GET
  /api/v1/stats (owner-scoped dashboard analytics); chat history —
  conversations sidebar, follow-ups with conversation_id, prior turns
  passed to the agent (LLM synthesis prompt + follow-up query expansion);
  SSE status stream with polling fallback (video page); search filters
  (label/provider/time/top_k); library/events pagination; dashboard
  stats cards; video page event timeline strip, trajectory toggle
  (annotated frames), clip download; skeletons + ErrorBoundary;
  FrameImage blob-URL leak fixed (L7); Vitest (10 tests: api.ts +
  ui.tsx); Playwright e2e extended (search filters, chat history reopen,
  dashboard stats, video clip download, 360 px no-overflow). 81 backend
  tests pass (+ 1 real-VLM e2e, run separately) + 10 Vitest + 1 e2e.
- **Pending features**: a real VLM run on the user's RTX 3050
  (llava:7b — documented, not run here); sentence-transformers path
  (code present, needs torch, not tested here); ultralytics .pt +
  ByteTrack path (code present, torch install stalled — ONNX is the
  tested path); shadcn/ui full adoption; per-provider evidence-floor
  calibration (Phase 4 open follow-up).
- **Files modified**: see git log.
- **Tests executed (2026-11-06, v0.10.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **81 passed, 3 skipped** (integration tests skip: this VM was
    replaced and Postgres/Redis are not installed yet — CI runs them
    against service containers; they passed on the previous VM).
  - Frontend: `npm test` (Vitest) → **10 passed**; `npm run build`
    (Next 14.2.35) → **compiled successfully, 16 routes**.
  - E2E browser: `VISIONIQ_E2E=1 pytest tests/test_e2e_browser.py -q`
    → **1 passed** (Chromium vs live frontend + in-process backend:
    register → upload → ready → search "bus" → label filter →
    clip download → "airplane" no matches → chat + follow-up →
    reopen conversation → dashboard stats → video clip download →
    360 px no-overflow → sign out).
  - Live infra (previous VM, 2026-11-06): Postgres 16.15 migrations
    (15 tables, up/down/up); Qdrant 1.20.0 server upsert/search;
    Redis 7.0.15 + Celery worker processed a real upload in 9.1 s
    (50 detections). Qdrant restarted on this VM from ~/tmp/qdrant
    (1.20.0, 41 points intact).
- **Known bugs / limitations**:
  - GitHub remote is NOT created: `gh` is not logged in on this machine.
    Local git repo is initialised; see DEPLOYMENT.md for the two commands
    to create/push `visioniq-video-intelligence`.
  - Hash embeddings match keywords, not semantics; FastEmbed is the
    semantic option (set EMBEDDING_PROVIDER=fastembed).
  - The agent's 0.45 evidence floor is tuned for hash embeddings; with
    FastEmbed it admits false evidence (per-provider calibration open).
  - /tmp is tmpfs and clears between sessions: test fixtures
    (/tmp/bus.jpg, /tmp/traffic-frame.jpg) must be recreated from the
    sample videos if a run fails with "No such file".
  - This VM was replaced 2026-11-06: Postgres/Redis/Ollama are not
    installed here yet (Qdrant survived in ~/tmp and was restarted).
    Integration tests skip cleanly without them.
- **Environment configuration**: this machine — Python 3.12 venv,
  ffmpeg, Node 24, no Docker, no GPU. Target machine — Windows 11,
  WSL2 Ubuntu 24.04, RTX 3050, 16 GB RAM.
- **Exact next steps**:
  1. Phase 9: security hardening (PyJWT migration H5, admin provisioning
     H6, Redis rate limits M5, token storage M13, upload magic-byte
     sniffing, expanded test_security.py).
  2. On the user's WSL machine: `docker compose -f docker-compose.laptop.yml up --build`,
     upload a real video, confirm the flow in the browser.
  3. `gh auth login` then create the GitHub repo and push.
  4. Run llava:7b on the user's RTX 3050 and confirm real VLM captions.
