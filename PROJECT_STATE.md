# PROJECT_STATE — VisionIQ v0.11.0

- **Current phase**: Phase 13 complete (GitHub + docs), verified
  2026-11-06. The repo is ready to push; the only missing step is
  the user's `gh auth login`. Phases 0–12 done: audit, real VLM
  (moondream, CPU), adaptive sampling, CV calibration, Qdrant-first
  RAG + 54-question eval, agent + MCP, event engine, DB/infra
  hardening, frontend upgrades, security hardening, observability,
  test expansion, production engineering. Next: Phase 14 benchmarks
  + v1.0.0 release.
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
- **v0.15.0 (Phase 13 GitHub + docs)**: README rewritten with
  only measured numbers; audit §11 doc drift fixed (ARCHITECTURE,
  DATABASE_SCHEMA, API_DOCUMENTATION regenerated from the live
  OpenAPI spec — 44 paths, DEPLOYMENT, TASK_TRACKER); git hygiene
  verified (no secrets tracked, largest file 148 KB). The repo is
  ready to push — blocked only on the user's `gh auth login`.
- **v0.14.0 (Phase 12 production engineering)**: non-root Docker
  images (backend `visioniq` user via entrypoint privilege drop,
  frontend multi-stage as `node`); healthchecks on all services;
  Qdrant pinned v1.20.0; entrypoint waits for Postgres/Redis/Qdrant
  (60 s each, skips SQLite/localhost, fails loudly); RELEASE.md
  checklist; git tags v0.1.0–v0.14.0. Verified natively (entrypoint:
  migrations, chown, uid-10001 import, fail path) and `docker
  compose config` on both files. NOT verified here: the
  clean-checkout `docker compose up` — this VM cannot run any
  container (kernel blocks iptables, bridge creation and network
  namespaces) and the daemon's Go TLS handshake to Docker Hub is
  filtered by the egress proxy (base images pulled with
  `scripts/docker_pull.py` instead). That step is pending on the
  user's Docker Desktop machine.
- **v0.13.0 (Phase 11 test expansion)**: shared conftest fixtures
  (client, auth_user, ready_video, bus_video, repo-local test images
  in tests/data/); markers unit (auto)/integration/vlm/e2e (105/3/2/1
  = 111 tests); RAG eval as a test (vlm, 54 questions, production
  config: R@5 0.66, MRR 0.48, faithfulness 1.0, relevance 0.95,
  negatives 0.38 — identical to the Phase 4 baseline); coverage 80%
  on app/services with a 70% CI gate; TESTING.md rewritten; two
  order bugs fixed (SYNC_PROCESSING in conftest, test_detection DB
  cleanup). 108 backend tests pass (+ 1 vlm skipped) + 10 Vitest +
  1 e2e re-verified on the current build.
- **v0.12.0 (Phase 10 observability)**: structured JSON logs
  (request_id/job_id on every line; request-ID middleware; job id via
  contextvar/Celery headers); `GET /metrics` (HTTP count/latency by
  route template, pipeline duration/jobs, detection/VLM/Qdrant
  latency, Celery queue depth -1=unknown, storage disk gauges,
  DB pool, GPU via nvidia-smi, process metrics); Prometheus + Grafana
  compose stack with a pre-provisioned 7-panel dashboard (configs
  parse — NOT run here, no Docker on this VM, no screenshot yet);
  profiling (120 s video: ONNX 54% @402 ms/frame CPU, ffmpeg 25%,
  NMS 8% — no code change); BUG FIXED: alembic's logging config was
  resetting the root level to WARNING and disabling uvicorn's loggers
  after migrations (run_migrations now re-applies logging config).
  108 backend tests pass (+ 6 observability) + 10 Vitest + 1 e2e.
- **v0.11.0 (Phase 9 security)**: PyJWT 2.10.1 (HS256, exp/iat/iss/aud/
  jti enforced; pre-v0.11.0 tokens rejected); `scripts/make_admin.py`;
  Redis rate limits (login 10/min per IP+email, register/reset 5/min
  per IP, 429; fails open without Redis; old in-memory middleware
  removed); rotating httpOnly refresh cookies (60-min access tokens,
  replay revokes the token family, Alembic v5); upload magic-byte
  sniffing + optional `CLAMSCAN_CMD` scan hook; VLM SSRF guard at
  startup (localhost/host.docker.internal/public IPs only); SECURITY.md
  rewritten; audit debts H5/H6/M5/M13 fixed. 102 backend tests pass
  (+ 1 real-VLM e2e re-verified on the replaced VM: Ollama reinstalled,
  moondream caption) + 10 Vitest + 1 e2e.
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
- **Tests executed (2026-11-06, v0.15.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **108 passed, 1 skipped** (re-run at close-out; docs + version
    bump only).
  - Frontend: `npm run build` → compiled successfully, **16 routes**
    (15 pages + not-found) — the README's "16 pages" was corrected
    to this.
  - API doc: regenerated from the live OpenAPI spec — **44 paths**,
    auth noted per route.
  - Git hygiene: .gitignore covers .env/.venv/node_modules/.next/
    storage/*.db/*.onnx/*.pt/.coverage; no .env/.db/model file
    tracked; no secrets in history; largest tracked file 148 KB.
- **Tests executed (2026-11-06, v0.14.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **108 passed, 1 skipped** (re-run at close-out; version bump only).
  - Entrypoint (native, from a clean copy): waits skipped for
    SQLite, migrations applied (188,416-byte DB), storage chowned to
    `visioniq`, app imports as uid 10001, version 0.13.0 shown
    (bumped to 0.14.0 after the test); wait fail path returns False
    after the timeout. Two test artifacts found, not code bugs:
    `/tmp`'s tmpfs has broken ownership semantics (root cannot write
    a visioniq-owned file there — the test DB moved into the storage
    volume, as the laptop profile does) and the VM's gateway answers
    every outbound TCP connect, so a real dead-host wait test is
    impossible here.
  - Compose: `docker compose config` on both files → valid.
  - Docker runtime: **cannot run on this VM** — `docker run` and
    `docker build` fail at sandbox creation ("operation not
    permitted" on the network namespace). Base images
    python:3.12-slim and node:20-alpine were pulled with
    `scripts/docker_pull.py` and `docker load`ed (the daemon's Go
    TLS handshake is filtered by the egress proxy; OpenSSL clients
    work).
- **Tests executed (2026-11-06, v0.13.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **108 passed, 1 skipped** (the vlm RAG eval skips without
    VISIONIQ_VLM_E2E=1).
  - Markers: `-m unit` collects 105, `-m vlm` 2, `-m "not e2e and
    not vlm"` 108.
  - Coverage: `--cov=app.services` → **80%** (gate 70% in CI).
  - RAG eval test: `VISIONIQ_VLM_E2E=1 pytest tests/test_rag_eval.py
    -q` → **1 passed** (1m44s–3m49s; R@1 0.37, R@5 0.66, P@5 0.16,
    MRR 0.48, latency 170.6 ms, faithfulness 1.0, relevance 0.95,
    negatives 0.38 — matches the Phase 4 baseline exactly).
  - E2E browser: `VISIONIQ_E2E=1 pytest tests/test_e2e_browser.py -q`
    → **1 passed** (14.9 s) against the current build (backend :8001
    v0.13.0 + frontend :3000 rebuilt with the right API URL — the
    first attempt failed because the frontend was built pointing at
    :8000, where nothing listens).
  - Frontend: `npm test` (Vitest) → **10 passed**; `npm run build`
    (Next 14.2.35) → **compiled successfully, 16 routes**.
- **Tests executed (2026-11-06, v0.12.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **108 passed** (incl. 6 observability tests: /metrics counters
    after upload+search, request-ID echo, JSON formatter fields,
    Celery queue -1, METRICS_ENABLED=0 → 404).
  - Live smoke (uvicorn :8002, sync processing): `/metrics` serves
    real counters after an upload (`jobs_total{status="done"} 1`,
    detection count 2); pipeline log line carries
    `request_id` + `job_id`; `X-Request-ID` echoed.
  - Profiling: 120 s video processed to ready; cProfile top: ONNX
    45.0 s (54%), ffmpeg waits 20.8 s (25%), NMS argmax 6.4 s (8%).
  - Frontend: `npm test` (Vitest) → **10 passed**; `npm run build`
    (Next 14.2.35) → **compiled successfully, 16 routes**.
- **Tests executed (2026-11-06, v0.11.0, this machine — Linux, no Docker, no GPU)**:
  - Backend: `pytest backend/tests/ -q` (excl. e2e + vlm e2e) →
    **102 passed** (incl. 22 security tests: JWT attacks, refresh
    rotation/replay, cross-user 404 on every video route, rate-limit
    429, magic bytes, 413, filename traversal, scan hook, SSRF,
    make_admin).
  - Real-VLM e2e: `VISIONIQ_VLM_E2E=1 pytest tests/test_vlm_e2e.py -q`
    → **1 passed** (moondream, 71 s incl. model load; Ollama
    reinstalled on the replaced VM — the first install was killed
    before llama-server landed, so inference 500'd; full reinstall
    fixed it, systemd service stopped+disabled, `ollama serve` as
    root).
  - Frontend: `npm test` (Vitest) → **10 passed**; `npm run build`
    (Next 14.2.35) → **compiled successfully, 16 routes**.
  - E2E browser: `VISIONIQ_E2E=1 pytest tests/test_e2e_browser.py -q`
    → **1 passed** (Chromium vs live frontend + in-process backend:
    register → upload → ready → search "bus" → label filter →
    clip download → "airplane" no matches → chat + follow-up →
    reopen conversation → dashboard stats → video clip download →
    360 px no-overflow → sign out).
  - Live infra (this VM, 2026-11-06): Postgres 16 + Redis 7
    reinstalled (Azure apt mirror — the default cogentco mirror
    stalls), Qdrant 1.20.0 restarted from ~/tmp/qdrant, Ollama
    0.40.15 reinstalled with moondream blobs intact in ~/.ollama/models.
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
  1. Phase 14: benchmark suite consolidation (`BENCHMARKS.md`) +
     v1.0.0 release + final report + zip.
  2. On the user's machine: `gh auth login`, create the GitHub repo
     and push (`git push origin main --tags`).
  3. On the user's WSL machine: verify the clean-checkout start —
     `docker compose -f docker-compose.laptop.yml up --build -d`,
     all services healthy, upload a real video, confirm the flow.
  4. Run llava:7b on the user's RTX 3050 and confirm real VLM captions.
