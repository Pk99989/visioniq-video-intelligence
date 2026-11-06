# CHANGELOG

## v0.7.0 — 2026-11-06 (Phase 5 agent + MCP)

- **8 tools:** added `detection_analytics` (counts by label, track count, dwell stats), `timeline_analysis` (scene-by-scene captions + detections), `report_generation` (same record as `POST /reports`, shared `create_report_record` service). Registry `agent.TOOLS` is the single source of truth, now with `inputSchema` per tool.
- **Multi-step planner:** `_plan` routes by intent keywords (deterministic, tested); a question matching several tools runs up to 3 in a fixed order and merges validated citations (`tool: "multi_step"`). Single-tool questions behave exactly as before.
- **LangGraph decision (ADR 0001):** LangGraph NOT adopted — tools are deterministic functions, state already persists in the DB, no LLM tool-calling loop exists; a 3-node graph would add dependency churn for no capability. Revisit if a tool ever needs free-form LLM planning.
- **MCP hardening:** `agent.run_tool` is the single entry point for agent + MCP; stdio preserves request ids on errors (-32700 malformed JSON, -32602 unknown tool/missing args, -32601 unknown method); HTTP returns 400 (not 500) for bad calls; `create_http_app()` factored out for tests. NO_PROXY fix in `_llm_synthesize` (audit M3, `trust_env=False`).
- **Retrieval fix (found by the MCP test):** an empty/drifted Qdrant index no longer makes search return nothing — the DB scan runs as the safety net and logs drift. Regression test added.
- **Tests:** 16 new (test_agent.py, test_mcp.py). Full suite: **63 tests pass** (plus 1 real-VLM e2e, run separately). RAG eval re-run after Phase 5: numbers within run-to-run noise (R@5 0.66, relevance 0.95, negatives 0.38); doc notes moondream non-determinism.

## v0.6.0 — 2026-11-06 (Phase 4 RAG upgrade)

- **Qdrant read path:** search now queries Qdrant first (owner-scoped payload filter, label/provider/timestamp/video filters) and enriches hits from the DB; on any Qdrant error it logs a warning and falls back to the DB scan. Upsert failures are logged, not swallowed. `scripts/reindex_qdrant.py` rebuilds the collection from the DB.
- **Filters in the API:** `POST /api/v1/search` accepts `label`, `provider`, `start_seconds`, `end_seconds`, `rerank`.
- **Cross-encoder reranker:** fastembed `TextCrossEncoder` (MiniLM-L-6-v2) behind `RERANKER_MODEL`, off by default; blends 0.5 hybrid + 0.5 normalised rerank score. Local-cache-first load (the hub API calls have no timeout and the proxy stalls them).
- **Query handling:** stopwords removed before keyword scoring (a test was relying on "this"/"is" overlap — fixed to a content question); synonyms expand only to labels actually detected in the video.
- **Evidence quality:** near-duplicate hits compressed (same caption, ±2 s), and the agent validates every citation against a real stored frame before answering.
- **Eval (54 questions, moondream captions):** `docs/benchmarks/rag-eval-2026-11-06.md` — Qdrant == DB scan (Recall@5 0.66, MRR 0.48), reranker slightly hurts (Recall@1 0.37→0.32 at 27× latency) so it stays off by default; faithfulness 1.0, relevance 0.95. Weak spot: negatives correct only 0.38 with hash embeddings.
- Full suite: **46 tests pass** (plus 1 real-VLM e2e, run separately).

## v0.5.0 — 2026-11-06 (Phase 3 computer vision)

- **Detection calibration:** `YOLO_CONF`, `YOLO_NMS`, `YOLO_CLASSES` allow-list, per-class confidence overrides (`YOLO_CLASS_CONF="person:0.5,bus:0.3"`), `YOLO_MIN_TRACK_IOU`, `YOLO_TRACK_MAX_MISSED`, `YOLO_TRACK_MAX_AGE_SECONDS`, `YOLO_EXECUTION_PROVIDERS` (CUDA tried first, CPU fallback). All env-overridable, all reported by `/health` under `detection`.
- **Per-video Tracker:** replaces the module-global greedy tracker — track ids are stable within a video and isolated between videos. Tracks retire after 5 missed frames or 120 s max age. 11 tests in `tests/test_detection.py` (lifecycle, expiry, NMS, class filter, per-class conf).
- **Trajectories:** new `GET /videos/{id}/trajectories` (owner-scoped) — per track: label, first/last seen, dwell time, frames seen, displacement, centre-point path. Verified live on the moving-traffic video: 16 tracks, dwell up to 7.5 s; cross-user returns 404.
- **Detection metrics (measured, hand-labelled GT, IoU>=0.5):** bus.jpg P 0.80 / R 0.80; traffic frame P 0.67 / R 0.50; track stability 0 id switches over 3 repeated frames; mean per-frame latency 219.8 ms warm on CPU. GPU latency still unmeasured (needs the RTX 3050). See `docs/benchmarks/2026-11-06-phase3.md`. No face/identity recognition anywhere.
- Full suite: **38 tests pass** (plus 1 real-VLM e2e, run separately).

## v0.4.0 — 2026-11-06 (Phase 0 audit, Phase 1 real VLM, Phase 2 adaptive sampling, H1 security fix)

- **Phase 0 audit:** `CODEBASE_AUDIT.md`, `TECHNICAL_DEBT.md`, `UPGRADE_PLAN.md` — read-only audit of v0.3.1 (11 backend tests + frontend build re-run). Found 6 High / 17 Medium / 14 Low debt items. Headline: password-reset token returned in API response (H1), search never uses Qdrant (H3), VLM was a client not an integration (H4), `create_all` vs Alembic conflict (H2).
- **Phase 1 — real VLM end-to-end (verified with a real model):** `vlm.py` rewritten — structured JSON captions (description/objects/actions), retries with exponential backoff, per-attempt timeout, `/health/vlm` probe, structured inference logs, three honest caption tiers (`ollama` / `detection` / `fallback`). Moondream (1.86B) via Ollama 0.40.15 captioned a real bus frame on this CPU-only VM: provider=`ollama`, search "bus" 0.865. `llava:7b` remains the GPU-machine model for the user's RTX 3050. 6 mock tests + 1 real-model e2e test (`tests/test_vlm_e2e.py`, skipped unless `VISIONIQ_VLM_E2E=1`). Found + fixed: model-name matching must accept Ollama tags (`moondream` vs `moondream:latest`).
- **Phase 2 — adaptive sampling + dedupe:** `video_processing.py` — adaptive fps (2.0 for short videos → 0.2 floor for long), histogram dedupe (keeps 1 frame per 2 s on static shots), scene merging on representative-frame similarity, representative (middle) frame used for captions. Benchmark: bus 10 s — 5 frames (was 10), 3.0 s (was 9.1 s), same labels; moving 15 s — 27/30 frames, 106 detections. See `docs/benchmarks/2026-11-06-phase2.md`.
- **H1 security fix:** password-reset token is no longer returned in the API response by default — anyone could reset any account with no email access. Returned only with explicit `DEV_RETURN_RESET_TOKEN=1` and never when `ENV=production`. New `tests/test_security.py` (4 tests).
- Full suite: **28 tests pass** (27 unit + 1 real-VLM e2e).

## v0.3.1 — 2026-11-06 (live infrastructure tests + privacy fix)

- **Live Postgres verified:** Alembic migrations run against real
  PostgreSQL 16.15 (upgrade head → 15 tables, downgrade base, upgrade
  head again). Found + fixed: `requirements.txt` had no Postgres
  driver, so the full-stack backend could not connect at all —
  added `psycopg2-binary==2.9.10`.
- **Live Qdrant server verified:** Qdrant 1.20.0 binary, collection
  created by `ensure_qdrant_collection`, 2 points upserted, search
  returns bus 1.000 / car 0.089. Found + fixed: `retrieval.py`
  crashed on this VM's bracketed-IPv6 `NO_PROXY` (`InvalidURL:
  Invalid port ':1]'`, same bug as embeddings.py) — the Qdrant
  client is now built with a temporary plain-localhost `NO_PROXY`,
  same pattern as FastEmbed.
- **Live Redis + Celery verified:** real worker (Redis 7.0.15 broker)
  received `visioniq.process_video`, processed a real bus-video
  upload in 9.1 s → status ready, 50 detections (bus + person),
  search "bus" returns 1 hit, 10 vectors in the live Qdrant
  collection `visioniq_e2e`.
- **Playwright e2e browser tests added + passing:**
  `tests/test_e2e_browser.py` drives Chromium through the real
  frontend: register → upload → wait for the Celery worker → search
  "bus" (Score 0.847) → video page Detections → clip download (mp4)
  → sign out. Skipped unless `VISIONIQ_E2E=1` with live servers.
- **Security fix — cross-user search/chat leak:** `/search` returned
  captions from ALL users because `search_frames()` had no owner
  filter; the agent chat and MCP tools had the same leak. Fixed:
  `search_frames()`/`answer_question()` take `user_id` and join
  `Video.owner_id`; the API passes the logged-in user (admins see
  all); MCP HTTP tools now resolve the JWT to a user and scope every
  tool, and `video_summarize` returns `{"error": "Video not found"}`
  for another user's video. Regression test
  `tests/test_privacy.py`: two users, each uploads a bus video —
  search/chat as Alice only ever sees Alice's video, clip of Bob's
  video is 404.
- Tests: **11 passed** (10 Phase 1-3 + privacy) + **1 e2e passed**.

## v0.3.0 — 2026-11-05 (Phase 3: advanced level)

- **Range streaming:** GET /stream now honours `Range: bytes=` with 206
  Partial Content + Content-Range, and GET /stream-url returns a
  5-minute signed URL so the <video> tag can seek natively instead of
  a blob fetch. Verified: 200 full, 206 bytes=0-99 (100 bytes),
  416 invalid range, signed URL works without a bearer token, tampered
  token 401, no auth 401.
- **Clip retrieval:** GET /videos/{id}/clip?start=&end= cuts an mp4
  clip with ffmpeg (re-encode, 0-120 s). Verified on a bus video:
  0-2 s clip is a real mp4; start>=end and end>duration return 400;
  cross-user 404. Search page has a "Download clip (±2s)" button.
- **Detections + analytics:** GET /detections (label, confidence,
  track_id, box, timestamp), GET /analytics (counts by label, scenes,
  frames, captions), GET /frames/{id}/annotated (boxes drawn on the
  frame). Video page shows a Detections card with top labels.
  Verified on bus video: bus + person present, >=5 detections.
- **Auth hardening:** JWTs carry a jti; POST /auth/logout revokes the
  token (verified: token 401 after logout); password reset with
  single-use hashed tokens, 1-hour expiry (verified: wrong token 400,
  reuse 400, old password fails, new password works, unknown email
  still returns 200 with no token).
- **Alembic migration v2:** revoked_tokens + password_reset_tokens
  (upgrade/downgrade verified on SQLite).
- Tests: 10 passed (7 Phase 1-2 + 3 Phase 3).

## v0.2.1 — 2026-11-05 (video page auto-refresh)

- Video page now polls every 3s while a video is processing, so scenes,
  captions and frames appear as the pipeline writes them instead of
  showing an empty Captions box if you opened the page early. The
  pipeline writes scenes + frames first, captions only after detection,
  so that order is what the empty box was.
- Captions section now shows "No captions yet (video may still be
  processing...)" instead of a blank box.

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
