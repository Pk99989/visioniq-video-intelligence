# CHANGELOG

## v0.15.0 — 2026-11-06 (Phase 13 GitHub + docs)

- **README rewritten** for v0.14.0: what it does, a measured-results
  table (tests 108 pass, RAG eval R@5 0.66/MRR 0.48/faithfulness 1.0,
  detection P/R, adaptive sampling, embedding benchmark, real-VLM
  e2e), honest fallbacks (llava:7b not yet run anywhere, .pt/ByteTrack
  untested, reranker off by default, per-provider floor open), and
  the Docker-on-this-VM limitation. No invented numbers; every
  figure points at `docs/benchmarks/` or `TESTING.md`.
- **Doc drift fixed (M14, audit §11):** ARCHITECTURE.md (FastEmbed
  is the real model, hash is the fallback; Qdrant-first search;
  zones; observability); DATABASE_SCHEMA.md (all 16 tables with
  real columns, Qdrant payload indexes, Alembic-only migrations
  v1–v5); API_DOCUMENTATION.md (regenerated from the live OpenAPI
  spec — 44 paths, auth noted per route, signed-token routes
  explained); DEPLOYMENT.md (16 app tables + alembic_version);
  TASK_TRACKER.md (row 10 superseded by row 20, row 2 updated to
  the 108-test suite).
- **GitHub readiness checked:** .gitignore covers .env/.venv/
  node_modules/.next/storage/*.db/*.onnx/*.pt/.coverage; no .env,
  .db or model file is tracked; no secrets in history (the only
  JWT_SECRET hits are doc examples and test fixtures); largest
  tracked file is 148 KB. The repo is ready to push — the only
  missing step is the user's `gh auth login` (see DEPLOYMENT.md).

## v0.14.0 — 2026-11-06 (Phase 12 production engineering)

- **Non-root images (M15 fixed):** backend runs as the `visioniq` user — the entrypoint runs as root only to wait for services, apply migrations and fix the storage volume's ownership (named volumes from pre-0.14 root images are root-owned), then drops to `visioniq` via runuser. Frontend is a multi-stage build (deps/builder/runner) running as the built-in `node` user.
- **Healthchecks:** backend `/health` (python urllib — no curl in the slim image), frontend `/login` (wget), Postgres `pg_isready`, Redis `ping`, Qdrant `/healthz`; backend/worker `depends_on` all three with `service_healthy`; `restart: unless-stopped` on every service in both compose files.
- **Qdrant pinned** to v1.20.0 (was `:latest`).
- **Entrypoint waits:** waits up to 60 s per service (Postgres/Redis via TCP, Qdrant via HTTP) before migrations; skips SQLite/localhost (laptop profile); fails loudly (exit 1) when a service never appears — the container then restarts and retries. Verified natively: waits skipped for SQLite, migrations applied, storage chowned to `visioniq`, app imports as uid 10001, fail path returns after the timeout.
- **RELEASE.md** checklist (tests → Docker from a clean checkout → tag → zip) and **git tags** for every release (v0.1.0–v0.14.0).
- **Honest limitation:** Docker cannot run containers on this VM at all — the kernel blocks iptables, bridge creation and network-namespace setup, and the egress proxy stalls the daemon's Go TLS handshake to Docker Hub. The daemon is installed (data-root on /home, `--iptables=false --bridge=none`), base images were pulled with a new `scripts/docker_pull.py` (Python/OpenSSL registry client + `docker load`) and `docker compose config` validates both files, but the clean-checkout `docker compose up` verification must happen on the user's machine (Docker Desktop, where bridge networking works). See RELEASE.md.

## v0.13.0 — 2026-11-06 (Phase 11 test expansion)

- **Shared fixtures (L12 fixed):** `tests/conftest.py` now has `client`, `auth_user` (uuid email, id resolved from the DB), `ready_video`, `bus_video` (per-test tmp_path), `bus_jpg`/`traffic_jpg` from repo-local `tests/data/` (the /tmp images kept being wiped by VM restarts — now committed), `db_session`. test_observability.py migrated to them as proof. Two order bugs found and fixed while doing this: (1) conftest sets `SYNC_PROCESSING=1` before any test module loads — a module importing the app without it froze the settings singleton with async processing (uploads stayed "uploaded"); (2) test_detection.py never deleted its DB, so a password changed by test_phase3 persisted across runs.
- **Markers:** `unit` (auto-applied by conftest to any test with no other marker), `integration`, `vlm` (test_vlm_e2e.py + test_rag_eval.py), `e2e`. Counts: 105 unit, 3 integration, 2 vlm, 1 e2e = 111 backend tests.
- **RAG eval as a test:** `tests/test_rag_eval.py` (vlm) runs the 54-question dataset against the production config and asserts R@5 ≥ 0.60, MRR ≥ 0.40, faithfulness ≥ 0.90, relevance ≥ 0.85, negatives ≥ 0.30. Measured 2026-11-06: **R@1 0.37, R@5 0.66, P@5 0.16, MRR 0.48, latency 170.6 ms, faithfulness 1.0, relevance 0.95, negatives 0.38** — identical to the Phase 4 baseline. Runs in ~2–4 min on CPU; the full 4-config comparison stays in `scripts/rag_eval.py`.
- **Coverage gate:** measured **80% on `app/services`** (weakest: embeddings.py 44% — fastembed/sentence-transformers paths need model downloads/torch). `requirements-dev.txt` (pytest-cov); CI unit job now runs `--cov=app.services --cov-fail-under=70`.
- **TESTING.md rewritten:** markers, fixtures, L12 rules, suites by phase, coverage.
- Full suite: **108 backend tests pass (+ 1 vlm RAG eval, skipped without VISIONIQ_VLM_E2E=1)** + 10 Vitest + 1 Playwright e2e (re-verified against the current build: backend :8001 + rebuilt frontend :3000, 14.9 s).

## v0.12.0 — 2026-11-06 (Phase 10 observability)

- **Structured JSON logs:** one JSON object per line on stdout (`ts`/`level`/`logger`/`msg`/`request_id`/`job_id` + scalar extras). Request-ID middleware mints or honours `X-Request-ID` and echoes it on the response; the pipeline binds `job_id` (and the upload request's id — via contextvar in-process, via Celery task headers in celery mode) to every log line. `LOG_FORMAT=text` for human-readable dev logs; `PYTHONUNBUFFERED=1` in the Dockerfile so lines flush immediately. **Bug found and fixed while doing this:** alembic's logging config (from `alembic.ini`) replaces the root handlers, sets the root level to WARNING, and disables all loggers not named in the file — after a migration run, no app INFO log and no uvicorn access log was ever emitted. `run_migrations()` now re-applies the logging config after every upgrade (re-enabling the disabled loggers and routing uvicorn's loggers through the JSON handler).
- **Prometheus metrics:** `GET /metrics` — HTTP request count + latency histogram (labelled by route template, never raw path), pipeline duration + jobs by outcome, per-frame detection latency, VLM caption latency by provider, Qdrant search latency, Celery queue depth (`-1` = unknown on the laptop profile, never a misleading 0), storage disk free/total with a warning below `STORAGE_WARN_FREE_PCT`, DB pool gauges, GPU utilisation from `nvidia-smi` when present, plus the default process/GC metrics. `METRICS_ENABLED=0` turns it off. Unauthenticated by design (documented: restrict at the reverse proxy in production).
- **Prometheus + Grafana stack:** `docker-compose.observability.yml` (Prometheus + Grafana with the VisionIQ dashboard pre-provisioned: request rate, p95 latency, processing duration, jobs by outcome, detection/VLM/Qdrant latency, queue depth, storage, RSS). Honest status: configs parse, but no Docker on this VM, so the stack has not been run here and there is no dashboard screenshot yet (Phase 12 item).
- **Profiling:** `scripts/profile_processing.py` + results in `docs/benchmarks/2026-11-06-phase10-profiling.md` — 120 s video: ONNX inference 54% (402 ms/frame on CPU, a hardware lever, not a code hotspot), ffmpeg decode 25%, NMS argmax 8%. No code change from the profile.
- **Docs:** `docs/OBSERVABILITY.md` (logs, metrics table, stack, profiling). `.env.example` gains LOG_LEVEL/LOG_FORMAT/METRICS_ENABLED/STORAGE_WARN_FREE_PCT.
- Full suite: **108 backend tests pass** (+ 6 new observability tests) + 10 Vitest + 1 e2e + 1 real-VLM e2e.

## v0.11.0 — 2026-11-06 (Phase 9 security hardening)

- **H5 — PyJWT migration:** the hand-rolled HMAC JWT is gone. `PyJWT==2.10.1` enforces HS256, signature, `exp`/`iat`/`iss="visioniq"`/`aud="visioniq"`/`jti` (required claims). Pre-v0.11.0 tokens are rejected (users re-login once). Tests: alg=none, tampered payload, expired, wrong iss/aud, missing claims — all 401.
- **H6 — admin provisioning:** `scripts/make_admin.py <email> [--create] [--password]` promotes or creates an admin from the server shell (no self-service admin signup). Tested end to end, including admin listing users.
- **M5 — Redis rate limits:** fixed windows — login 10/min per IP+email, register and password-reset-request 5/min per IP (429 beyond). Fails open without Redis (laptop profile); `RATE_LIMIT_ENABLED=0` disables. The old in-memory login-only middleware was removed. Test: 11th wrong login is 429, another account unaffected.
- **M13 — refresh tokens:** access tokens now live 60 min (was 24 h); renewal uses a rotating opaque refresh token (SHA-256-hashed in new `refresh_tokens` table, Alembic v5), sent as an httpOnly cookie (SameSite=Lax, Secure in production, 7 days). Replay of a rotated token revokes the whole token family. Logout revokes both tokens. Frontend retries once on 401 via `/api/v1/auth/refresh`.
- **Upload hardening:** magic-byte sniffing (mp4/mov `ftyp`, webm/mkv EBML, avi `RIFF`/`AVI `) rejects renamed files before anything is written; optional `CLAMSCAN_CMD` virus-scan hook (non-zero exit rejects the upload). 413 size cap already existed and is now tested.
- **VLM SSRF guard:** `validate_vlm_base_url()` at startup for real VLM providers — localhost / `127.0.0.1` / `host.docker.internal` allowed, any other host must resolve to a public IP (private/loopback/link-local/multicast refused, including the 169.254.169.254 metadata endpoint).
- **Tests:** `tests/test_security.py` expanded from 4 to 22 tests — H1 reset-token rules + single-use, all JWT attacks, refresh rotation + replay + logout revocation + pruning, cross-user 404 on every video-scoped route (video, detections, frames, annotated frames, events, alerts, trajectories, analytics, captions, scenes, summary, stream-url, clip, zones, evaluate, retry, delete, verify, acknowledge, chat), rate-limit 429, magic bytes, 413, filename traversal, scan hook, SSRF cases, make_admin script. New `tests/conftest.py` (session-scoped: rate limiting off for the suite — module fixtures register users before any function fixture could disable it).
- Full suite: **102 backend tests pass** (+ 1 real-VLM e2e re-verified on the replaced VM: moondream caption, Ollama reinstalled) + 10 Vitest + 1 Playwright e2e.

## v0.10.0 — 2026-11-06 (Phase 8 frontend upgrades)

- **Backend pagination (L10):** `limit`/`offset` (with `X-Total-Count`) on `GET /api/v1/videos`, detections, frames, events, alerts — list shape unchanged. New owner-scoped `GET /api/v1/stats` (video counts, detections by label, duration, storage, events, avg processing time).
- **Chat history (M12):** conversations sidebar + thread view + follow-ups with `conversation_id` in the UI; the chat endpoint passes the last 6 prior turns to the agent, which uses them in the LLM synthesis prompt and expands follow-up questions with the previous user question for retrieval (evidence floor unchanged). New `tests/test_phase8_backend.py` (6 tests: pagination, stats + cross-user isolation, SSE stream, conversation persistence, LLM prompt receives history).
- **SSE status stream:** `GET /api/v1/videos/{id}/status-stream` (signed stream token, JWT in query, or Bearer) emits status every 2 s and closes on ready/failed; the video page uses it with the 3 s polling fallback; the processing page stops polling once nothing is processing.
- **Search filters:** label, provider, time window, and top_k (10/20/50) surfaced in the UI (Phase 4 API filters).
- **Video page:** event timeline strip (clickable markers), trajectory toggle (annotated frames via `FrameImage` `annotated` prop), clip download with start/end inputs.
- **Robustness:** loading skeletons + `ErrorBoundary` (layout-wide), `FrameImage` blob-URL leak fixed (L7 — URL tracked in a ref and revoked on change/unmount), library/events pagination, dashboard stats cards.
- **Frontend tests:** Vitest 3 + Testing Library (10 tests: `lib/api.ts` error stringification/auth header/pagination helper, `components/ui.tsx` skeletons/error boundary). Playwright e2e extended: search filters, chat history reopen, dashboard stats, video clip download, 360 px no-overflow check — full flow passes live.
- Full suite: **81 backend tests pass** (3 integration skipped — this VM was replaced and Postgres/Redis are not installed here; CI runs them), **10 Vitest pass**, **1 e2e pass**, frontend build green.

## v0.9.0 — 2026-11-06 (Phase 7 DB/infra hardening)

- **Alembic-only schema (H2):** the app no longer calls `create_all` anywhere on its path — `run_migrations()` (alembic upgrade head) runs at import and at startup, and `backend/entrypoint.sh` runs migrations before the server in Docker (verified end-to-end on a scratch DB). Migration v4 adds composite indexes `captions/detections/frames(video_id, timestamp_seconds)` + `processing_jobs.celery_task_id`.
- **Postgres pooling (M1):** bounded pool (size 5, overflow 10, timeout 30s, recycle 1800s, pre-ping) for Postgres URLs; SQLite keeps its default. Also fixed a latent crash: SQLAlchemy 2.x maps bare `postgresql://` to the psycopg3 driver, which isn't installed — the app now normalises it to `postgresql+psycopg2://` (one helper used by the engine, alembic env, and the migration runner).
- **Backup/restore (tested):** `scripts/backup.sh` (pg_dump + storage tarball + Qdrant snapshot + row-count manifest) and `scripts/restore.sh` (restores into a target DB + storage dir, verifies every row count, exits non-zero on mismatch). Tested live: seeded 1 video / 2 frames / 2 captions / 2 detections / 1 event / 1 user, backed up, restored into `visioniq_restore` — all counts matched.
- **Qdrant payload indexes:** `ensure_qdrant_collection` now creates indexes on `owner_id`, `video_id`, `timestamp_seconds` (idempotent, also repairs older collections); `reindex_qdrant` applies them too. Verified live: all three indexed, 41 points.
- **Celery reliability (M10/M11):** soft/hard time limits (1800s/2100s), `result_expires` 24h, dispatch stores the Celery task id on the job, `task_failure` signal handler marks the DB job failed when a task dies outside the pipeline (worker crash, hard limit). Startup recovery now only fails jobs untouched for `RECOVERY_GRACE_SECONDS` (10 min) — a recently queued job is left alone.
- **Token pruning (M4):** `prune_expired_tokens` (expired revoked JWTs, used/expired reset tokens) runs at startup.
- **CI integration job:** Postgres 16 / Redis 7 / Qdrant 1.20.0 service containers + `pytest -m integration`; `integration` marker added to pytest.ini. New tests: `test_postgres.py` (migrations on live Postgres incl. downgrade/upgrade reversibility, pool config in a subprocess, recovery grace, token pruning) and `test_celery_reliability.py` (time-limit config, task_failure handler, poison video via eager Celery ends failed with task id stored). Full suite: **78 tests pass** (plus 1 real-VLM e2e, run separately).

## v0.8.0 — 2026-11-06 (Phase 6 event engine)

- **Zones/ROI:** `zones` table + Alembic migration v3 (also adds `zone_name`, `track_id`, `label`, `evidence_clip_start/end` to events; verified up/down/up on a scratch DB). API: `POST/GET/DELETE /videos/{id}/zones` (owner-scoped, geometry validated 0..1, x1<x2, y1<y2).
- **Zone engine:** `evaluate_zones` watches track centres against zones — `zone_enter` / `zone_exit` on boundary crossings, `zone_dwell` after `EVENT_DWELL_SECONDS` (default 5s) continuous presence, `zone_loitering` after `EVENT_LOITER_SECONDS` (default 30s) as a *candidate* (verified=False, "Candidate only — needs VLM verification"). One event per stay; a track still inside at its last detection gets no invented exit. Suppression key extended with zone_name/track_id so zones/tracks don't suppress each other.
- **Evidence clips:** every zone event carries a clip window `[ts-2s, ts+3s]` (configurable, clamped to the video) served by the existing `GET /videos/{id}/clip` endpoint; responses include `evidence_clip_url`.
- **VLM verification:** `POST /videos/{id}/events/{event_id}/verify` asks the VLM a yes/no question about the evidence frame (`vlm.ask_yes_no`, new shared `_ask_vlm` retry helper). YES marks verified; NO annotates the description and leaves it unverified; exit events are reported as not VLM-verifiable (a frame cannot confirm an absence); no VLM configured leaves it unverified with a clear reason.
- **Tests:** 8 new in `tests/test_events.py` (seeded detections, exact geometry). Full suite: **71 tests pass** (plus 1 real-VLM e2e, run separately). Fixed along the way: an edit had dropped `evaluate_rules`' return value (test_full_flow caught it).

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
