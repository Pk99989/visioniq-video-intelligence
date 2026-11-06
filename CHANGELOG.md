# CHANGELOG

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
