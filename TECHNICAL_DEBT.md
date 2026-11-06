# TECHNICAL_DEBT.md — VisionIQ v0.3.1

Prioritised debt found in the Phase 0 audit (2026-11-06, commit `13f6919`).
Severity is about user/security impact if left unfixed, not about code elegance.
Each item names the file(s) and a concrete fix. Full evidence is in `CODEBASE_AUDIT.md`.

## High

### H1. Password-reset token is returned in the API response — account takeover without email access
- **Where:** `backend/app/routers/auth.py: password_reset_request()` — returns `{"reset_token": raw}` for any registered email.
- **Impact:** anyone can reset anyone's password; no email access needed. This is the highest-severity open issue.
- **Fix:** stop returning the token. Add a real email sender (SMTP via env, or a pluggable `send_reset_email()` no-op in dev that logs the token server-side only), and gate the local-testing return behind an explicit `DEV_RETURN_RESET_TOKEN=1` env flag that defaults off and is refused when `ENV=production`. Add a test: reset-request response must not contain `reset_token` when the flag is off.

### H2. `create_all` and Alembic both own the schema — a fresh full-stack deploy breaks migrations
- **Where:** `backend/app/database.py: init_db()`, `backend/app/main.py` (called at import and on startup), `backend/alembic/env.py`.
- **Impact:** `create_all` creates the tables but not `alembic_version`; a later `alembic upgrade head` fails with "table already exists". There is no single supported path to a migrated production database.
- **Fix:** remove `create_all` from the app path (keep it only for tests via an explicit flag, or drop it entirely). Make `docker-compose.yml` backend run `alembic upgrade head` before `uvicorn` (entrypoint script), and add a CI job that runs migrations against a real Postgres service container. Document the one migration workflow in `DEPLOYMENT.md`.

### H3. Search never uses Qdrant — the vector index is write-only
- **Where:** `backend/app/services/retrieval.py: search_frames()` (Python scan over all captions) and `qdrant_search()` (zero callers, verified by grep).
- **Impact:** search cost is O(all captions) with N+1 lazy loads; latency and memory grow with the library; Qdrant adds operational cost for zero read benefit. Vector-store drift is silent (`try_qdrant_upsert()` swallows errors).
- **Fix:** make `search_frames()` query Qdrant first (with `user_id` as a payload filter) and fall back to the DB scan only when Qdrant is unconfigured/unavailable; log (not swallow) upsert failures; add a re-index CLI/script that rebuilds Qdrant from the DB. Add a regression test asserting search results match with and without Qdrant.

### H4. VLM integration is a client, not an integration — captions are templates
- **Where:** `backend/app/services/vlm.py: caption_scene()`; `backend/app/config.py: VLM_PROVIDER=fallback`.
- **Impact:** the platform's headline capability (multimodal understanding) does not exist in production behaviour; every caption is timing + detection metadata. Also: only the first frame per scene is captioned; no retry/timeout config; failure silently produces a template that falsely claims "no vision-language model was configured".
- **Fix:** Phase 1 of the upgrade plan (see `UPGRADE_PLAN.md`): Ollama health check + timeout/retry, structured JSON captions, per-scene multi-frame sampling, distinct `provider` values for `fallback` / `detection-only` / `vlm`, and a real end-to-end test with a local vision model. Do not mark this done until a real model run is observed.

### H5. Hand-rolled JWT (custom HMAC implementation, no `alg` check, no `iat`/`aud`/`iss`)
- **Status: FIXED in v0.11.0 (Phase 9, 2026-11-06).** PyJWT 2.10.1; `jwt.decode` enforces HS256, signature, `exp`/`iat`/`iss`/`aud`/`jti` (required claims). Tests: alg=none, tampered payload, expired, wrong iss/aud, missing claims — all 401. Pre-v0.11.0 tokens (no iss/aud/iat) are rejected; users re-login once.
- **Where:** `backend/app/security.py: create_token()`, `decode_token()`.
- **Impact:** correct today, but every future change risks a classic JWT vulnerability; no standard library review applies.
- **Fix:** replace with PyJWT (`PyJWT==2.x`), verify `alg == HS256` explicitly, add `iat`, `aud="visioniq"`, `iss="visioniq"`, and keep the existing `jti` revocation logic. Add tests for `alg=none`, tampered payload, expired token, wrong-secret token.

### H6. No admin provisioning path
- **Status: FIXED in v0.11.0 (Phase 9, 2026-11-06).** `scripts/make_admin.py <email> [--create] [--password]` promotes or creates an admin; tested end to end (admin can list users, non-admin gets 403 — see test_security.py::test_make_admin_script).
- **Where:** everywhere / nowhere — no code assigns `role="admin"` (verified by grep); `backend/app/routers/auth.py: list_users()` is admin-only and therefore unreachable on a fresh deploy.
- **Impact:** user management and any future admin tooling cannot be used without manual DB edits.
- **Fix:** add a one-time `scripts/make_admin.py <email>` CLI (or `ADMIN_EMAILS` env seeding on first start), plus a test that an admin can list users and a non-admin gets 403.

## Medium

### M1. No connection pooling / stale-connection protection for Postgres
- **Where:** `backend/app/database.py: create_engine(...)` — no `pool_pre_ping`, `pool_size`, `pool_recycle`.
- **Fix:** `pool_pre_ping=True`, explicit `pool_size`/`max_overflow` from env, `pool_recycle=1800`. Add a test that survives a Postgres restart (or at least a `SELECT 1` health probe in `/health`).

### M2. Token validation duplicated; stream auth bypasses the standard dependency
- **Where:** `backend/app/security.py: get_current_user()` vs `backend/app/routers/videos.py: _bearer_user()`.
- **Fix:** extract a single `authenticate_token(db, raw_token) -> User` helper used by both; the stream path calls it after resolving the signed-URL token.

### M3. NO_PROXY workaround triplicated, and missing in the agent's LLM call
- **Where:** `backend/app/services/embeddings.py`, `backend/app/services/retrieval.py` (inline save/override/restore), `backend/app/services/vlm.py` (`trust_env=False`), `backend/app/services/agent.py: _llm_synthesize()` (bare `httpx.post` — same crash risk).
- **Fix:** one shared helper (e.g. `backend/app/services/http_client.py: safe_httpx_client()` returning an `httpx.Client(trust_env=False)`), used by all four call sites. Add a test that constructs each client with a hostile `NO_PROXY` set.

### M4. RevokedToken / PasswordResetToken tables grow forever
- **Where:** `backend/app/models.py: RevokedToken`, `PasswordResetToken`; no cleanup anywhere.
- **Fix:** delete expired rows on login/logout (cheap `DELETE WHERE expires_at < now()`), plus a periodic cleanup (Celery beat or startup sweep). Add a test asserting expired rows are removed.

### M5. Rate limiting is in-memory, login-only, per-process
- **Status: FIXED in v0.11.0 (Phase 9, 2026-11-06).** Redis-backed fixed windows (login 10/min per IP+email, register/reset 5/min per IP, 429 beyond; `RATE_LIMIT_ENABLED=0` disables). The old in-memory middleware was REMOVED, not kept for the laptop profile — the Redis limiter fails open without Redis, which is the documented tradeoff (SECURITY.md). Test: 11th wrong login is 429, another account unaffected.
- **Where:** `backend/app/main.py: login_rate_limit()`.
- **Impact:** resets on restart; useless across replicas; register and password-reset-request are unlimited.
- **Fix:** move to Redis-backed limits (already a dependency in the full stack) or a shared store; add limits for register (e.g. 10/h/IP) and password-reset-request (e.g. 5/h/IP); keep the in-memory limiter only for the SQLite laptop profile. Add tests.

### M6. `datetime.utcnow()` used in 15 places (deprecated, naive datetimes)
- **Where:** `backend/app/models.py` (all `default=datetime.utcnow`), `security.py`, `worker.py`, `auth.py`.
- **Fix:** switch to `datetime.now(timezone.utc)` / SQLAlchemy `func.now()` or timezone-aware defaults. Mechanical change; do it with the JWT work (H5) since token expiry math touches the same code.

### M7. Pipeline has no resumability; retry re-runs everything
- **Where:** `backend/app/services/worker.py: process_video()`.
- **Impact:** a 10-minute video that fails at the caption step re-does extraction, detection and embedding on retry; long videos are expensive to retry.
- **Fix:** per-stage checkpoints in `processing_jobs` (or a `stage` column on videos): skip stages whose outputs already exist. At minimum, make detection/embedding idempotent per frame (skip frames that already have detections/embeddings).

### M8. Detection is CPU-only, unbatched, unconfigured
- **Where:** `backend/app/services/detection.py: _load_onnx()` (`CPUExecutionProvider`), `detect_frame(conf=0.35)`, NMS 0.45.
- **Impact:** 456–880 ms/frame measured; ~60–100 s of detection per 120-frame video; the RTX 3050 GPU is never used; confidence/NMS/class filters are hardcoded.
- **Fix:** try `CUDAExecutionProvider` with CPU fallback; expose `YOLO_CONF`, `YOLO_NMS`, `YOLO_CLASSES` in config; batch frames per inference where the model allows; measure and record per-frame latency in `/health` or a metrics endpoint.

### M9. All frames in a scene share one caption vector
- **Where:** `backend/app/services/worker.py` (one `embed(caption_text)` per scene, assigned to every frame in the scene) and `retrieval.py` (per-frame Qdrant upsert of the same vector).
- **Impact:** "frame-level" search is really scene-level; Qdrant stores up to 120 duplicate vectors per video.
- **Fix:** embed per frame (or per sampled frame) once real VLM captions exist; until then, upsert one point per *scene* (or per caption) instead of per frame, and say so in the docs.

### M10. Celery has no time limits, no dead-letter handling, task ids are discarded
- **Where:** `backend/app/services/celery_app.py`, `backend/app/services/worker.py: dispatch()`.
- **Fix:** set `task_soft_time_limit` / `task_time_limit` (e.g. 1800 s / 2100 s for a video job), `result_expires=86400`, store the Celery task id on `ProcessingJob`, add a failed-task path that marks the job failed (today a worker crash can leave a job `running` until backend restart recovery).

### M11. Startup recovery can fail a legitimately queued Celery job
- **Where:** `backend/app/services/worker.py: recover_stuck_jobs()` — marks *all* `running`/`queued` jobs failed at backend startup.
- **Impact:** in celery mode, a job queued in the DB but not yet picked up by the worker is marked failed if the backend restarts in between.
- **Fix:** only recover jobs whose `updated_at` is older than a grace period (e.g. 10 min), or reconcile against the Celery result backend before failing them.

### M12. Frontend: no conversation-history UI; chat creates a new conversation per question
- **Where:** `frontend/app/chat/page.tsx` (never sends `conversation_id`), no frontend caller of `GET /api/v1/conversations`.
- **Fix:** add a conversations sidebar/list on the chat page, send `conversation_id` on follow-ups, and pass prior turns to the agent (see audit §2, agent.py — memory is stored but never fed back).

### M13. Frontend token in `localStorage`, no refresh flow
- **Status: FIXED in v0.11.0 (Phase 9, 2026-11-06).** Short-lived access token (60 min) + rotating httpOnly refresh cookie (7 days, SHA-256-hashed in DB, replay revokes the whole token family). Frontend retries once on 401 via /auth/refresh. Residual: the access token itself still lives in localStorage (short-lived now); moving it out is a future item.
- **Where:** `frontend/lib/api.ts: getToken()`.
- **Impact:** XSS can steal the token; users are forced to re-login every 24 h.
- **Fix (medium effort, needs care):** short-lived access token + httpOnly refresh cookie, or at minimum a silent re-login prompt before expiry. Do not attempt without the H5 JWT work.

### M14. Docs are stale in at least 8 places (see audit §11)
- **Where:** `README.md`, `PROJECT_STATE.md`, `ARCHITECTURE.md`, `DATABASE_SCHEMA.md`, `API_DOCUMENTATION.md`, `DEPLOYMENT.md`, `TESTING.md`, `SECURITY.md`.
- **Fix:** single docs pass as part of Phase 13; add a CI check that fails if `PROJECT_STATE.md` still contains the phrases that are known-stale after each release (cheap grep guard), or at least update the docs in the same commit as the feature.

### M15. Dockerfiles run as root; no healthchecks; Qdrant unpinned and unchecked
- **Status: FIXED in v0.14.0 (Phase 12, 2026-11-06).** Backend Dockerfile: non-root `visioniq` user (entrypoint runs as root only to wait for services, apply migrations and fix the storage volume's ownership, then drops to `visioniq` via runuser); HEALTHCHECK on /health (python urllib, no curl in slim). Frontend: multi-stage build (deps/builder/runner), runner as built-in `node` user, HEALTHCHECK on /login (wget). Qdrant pinned to v1.20.0 with a healthcheck on /healthz; backend/worker `depends_on` qdrant (service_healthy); `restart: unless-stopped` on all services in both compose files. Verified on this VM with host networking (bridge/iptables are blocked here — see RELEASE.md).
- **Where:** `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`.
- **Fix:** add `USER` (non-root) to both images; add `HEALTHCHECK` (backend: `/health`, frontend: `/`); pin `qdrant/qdrant:<version>`; add a Qdrant healthcheck and make backend `depends_on` it; add `restart: unless-stopped` to services.

### M16. CI runs only SQLite unit tests; no integration, lint, typecheck, or security scan
- **Where:** `.github/workflows/ci.yml`.
- **Fix:** add Postgres/Qdrant/Redis service containers and a `pytest -m integration` job; add `ruff` + `mypy` (backend) and `tsc --noEmit` + `eslint` (frontend); add a dependency scan (`pip-audit` / `npm audit`).

### M17. `WORKER_CONCURRENCY` config is dead; `frame_brightness()` is dead code
- **Where:** `backend/app/config.py:55` (never read), `backend/app/services/video_processing.py: frame_brightness()` (no callers).
- **Fix:** either wire `WORKER_CONCURRENCY` into the Celery worker concurrency (full stack) and document it, or delete it; delete `frame_brightness()`.

## Low

### L1. `qdrant_search()` is dead code in the read path
- **Where:** `backend/app/services/retrieval.py: qdrant_search()`; also imports `Filter` but never uses it.
- **Fix:** wire it in as part of H3, or delete it. Remove the unused import either way.

### L2. Inline `import json` inside `chat()`
- **Where:** `backend/app/routers/search_chat_reports.py:54`.
- **Fix:** move to the module top.

### L3. `summarization.py` splits sentences on `". "`
- **Where:** `backend/app/services/summarization.py: summarize_video()`.
- **Fix:** use a proper sentence splitter or split on caption boundaries instead of punctuation heuristics.

### L4. Clip extraction has no timeout; clip cache never evicted
- **Where:** `backend/app/services/clips.py:27`, `extract_clip()`.
- **Fix:** add `timeout=300` to the ffmpeg call; add a cache-eviction sweep (e.g. delete clips older than 7 days, or cap `storage/clips` size).

### L5. `events._already_fired()` is O(all events) per candidate
- **Where:** `backend/app/services/events.py`.
- **Fix:** query with a time-range filter (`timestamp_seconds BETWEEN bucket_start AND bucket_end`) instead of loading all events.

### L6. Video page polls 6 endpoints every 3 s; processing page polls forever
- **Where:** `frontend/app/video/[id]/page.tsx`, `frontend/app/processing/page.tsx`.
- **Fix:** stop the processing-page interval when no video is in `uploaded`/`processing`; consider SSE/websocket for status updates (Phase 8).

### L7. `FrameImage` blob-URL leak (stale closure in cleanup)
- **Where:** `frontend/components/FrameImage.tsx`.
- **Fix:** capture the created object URL in a ref and revoke that exact URL in cleanup.

### L8. Report PDF receives unescaped user content; PDF has no detections detail
- **Where:** `backend/app/services/reports.py: write_pdf_report()`.
- **Fix:** escape XML-special chars in titles (reportlab `Paragraph` parses markup); add a detections section to the report data.

### L9. `main.py` uses deprecated `@app.on_event("startup")`; `init_db()` runs at import
- **Where:** `backend/app/main.py`.
- **Fix:** migrate to `lifespan` handlers; remove the import-time `init_db()` (keep it behind the startup event / test fixtures) so importing the app does not touch the database.

### L10. No pagination on list endpoints
- **Where:** `GET /api/v1/videos`, `get_detections()`, `get_events()`, `get_alerts()` (all unbounded).
- **Fix:** add `limit`/`offset` query params (defaults that match current UI needs) and paginate the frontend lists.

### L11. `download_yolo.py` falls back to downloading `.pt` via ultralytics on ONNX failure
- **Where:** `scripts/download_yolo.py`.
- **Fix:** fail loudly instead of silently switching artefacts; the two weights have different runtime requirements (torch) and the fallback surprises laptop users.

### L12. Test helpers duplicated across test files
- **Status: FIXED in v0.13.0 (Phase 11, 2026-11-06).** Shared `tests/conftest.py`: `client`, `auth_user` (uuid email, id resolved from DB), `ready_video`, `bus_video` (per-test tmp_path), `bus_jpg`/`traffic_jpg` from repo-local `tests/data/` (the /tmp images kept being wiped by VM restarts), `db_session`. test_observability.py migrated to the shared fixtures as proof. Two order bugs found and fixed while doing this: (1) conftest now sets SYNC_PROCESSING=1 before any test module loads — a module importing the app without it froze the settings singleton with async processing; (2) test_detection.py never deleted its DB, so a password changed by test_phase3 persisted across runs.
- **Where:** `backend/tests/test_phase3.py`, `test_privacy.py` (ffmpeg bus-video build + upload), plus per-file env/DB setup preambles.
- **Fix:** extract a shared `tests/conftest.py` with fixtures (app client, auth headers, bus video).

### L13. `settings.py` style: `embed()` reads `EMBEDDING_PROVIDER` from `os.environ` per call
- **Where:** `backend/app/services/embeddings.py: embed()`.
- **Fix:** read once from `settings` (consistent with every other setting).

### L14. `STORAGE_DIR` is created at config import time
- **Where:** `backend/app/config.py` (bottom: `settings.STORAGE_DIR.mkdir(...)`).
- **Fix:** create lazily on first use, so importing config never touches the filesystem.
