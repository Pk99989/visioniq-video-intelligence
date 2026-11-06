# CODEBASE_AUDIT.md — VisionIQ Phase 0 Audit

- **Audited version:** v0.3.1, commit `13f6919` ("live infra tests, cross-user search/chat/MCP privacy fix, Playwright e2e")
- **Audit date:** 2026-11-06
- **Audit machine:** Linux, Python 3.12.3, Node v24.22.1, no Docker, no GPU. ffmpeg present (backend tests that shell out to it passed).
- **Method:** read-only inspection of every source file listed in §1, plus the test/build runs in §7. No code was modified. Docker Compose files were inspected statically only (Docker is not installed on this machine); the Playwright e2e test and the live Postgres/Qdrant/Redis runs were **not** re-run in this session — their last verified runs (2026-11-06) are recorded in `CHANGELOG.md` / `PROJECT_STATE.md` and are cited as such, not as this audit's observations.

## 1. Repository map

```
visioniq-video-intelligence/
├── backend/                 FastAPI app (app/), Alembic, tests/, Dockerfile
│   ├── app/main.py          entrypoint, CORS, login rate limit, startup recovery
│   ├── app/config.py        all settings from env vars (no secrets in code)
│   ├── app/database.py      SQLAlchemy engine/session, init_db() = create_all
│   ├── app/models.py        14 SQLAlchemy models
│   ├── app/schemas.py       Pydantic request/response contracts
│   ├── app/security.py      PBKDF2 + hand-rolled HMAC-SHA256 JWT, RBAC, revocation
│   ├── app/routers/         auth.py, videos.py, search_chat_reports.py
│   └── app/services/        worker, video_processing, detection, vlm,
│                            embeddings, retrieval, agent, events,
│                            summarization, clips, reports, celery_app
├── frontend/                Next.js 14.2.35 + TypeScript + Tailwind
│   ├── app/                 16 routes (see §3)
│   ├── components/          ui.tsx, FrameImage.tsx, SignOut.tsx, ThemeToggle.tsx
│   └── lib/api.ts           typed fetch wrapper, token from localStorage
├── mcp_server/server.py     MCP stdio JSON-RPC + HTTP, same 5 agent tools
├── docker-compose.yml       full stack: Postgres 16 + Qdrant + Redis + worker
├── docker-compose.laptop.yml  laptop profile: SQLite + in-process worker
├── .github/workflows/ci.yml backend pytest + frontend build
├── scripts/                 benchmark.py, download_yolo.py, run_dev.sh,
│                            generate_sample_video.sh
├── docs/                    benchmarks/2026-11-05.md, decisions/ (2 ADRs)
└── *.md                     README, ARCHITECTURE, PROJECT_STATE, TASK_TRACKER,
                             CHANGELOG, DATABASE_SCHEMA, API_DOCUMENTATION,
                             DEPLOYMENT, TESTING, SECURITY, TROUBLESHOOTING
```

Counts (excluding `.venv`, `node_modules`, `.next`): backend app ~2,100 lines Python, services ~1,600 lines, frontend ~800 lines TSX. `git remote` is empty — no GitHub remote exists. `backend/yolov8n.onnx` (13 MB, community export, gitignored) is present on this machine.

## 2. Backend architecture

### Routers (`backend/app/routers/`)

| Router | Endpoints | Notes |
|---|---|---|
| `auth.py` | register, login, logout, me, password-reset-request, password-reset, users (admin) | Register: email must contain `@`, password 8–128 chars (`schemas.py: RegisterIn`). Login returns JWT + user. Logout revokes by `jti` read from the raw `Authorization` header. |
| `videos.py` | upload, list, get, delete, retry, stream-url, stream, clip, detections, analytics, scenes, frames, frame image, annotated frame, captions, events evaluate/list, alerts list/acknowledge | Every video lookup goes through `_get_video()` → `video_visible_to()` (owner or admin), returning 404 cross-user. Upload streams to disk with a 500 MB cap. Stream honours `Range: bytes=` → 206, 416 on bad ranges. |
| `search_chat_reports.py` | search, agent/tools, chat, conversations list/get, summary, reports create/download | Search and chat are scoped to the logged-in user (v0.3.1 fix). Report download checks `owner_id`. |

### Services (`backend/app/services/`)

| Service | What it does | Key facts |
|---|---|---|
| `worker.py` | `dispatch()` routes by `WORKER_MODE` (sync / celery / in-process BackgroundTasks); `process_video()` runs the whole pipeline; `recover_stuck_jobs()` marks interrupted jobs failed on restart | One video at a time per worker by convention only — see §10. Detection runs per scene, captions per scene (first frame only), one shared embedding per scene. |
| `video_processing.py` | ffprobe metadata, ffmpeg thumbnail + 1 fps frame extraction (`FRAME_FPS`, capped `MAX_FRAMES=120`), OpenCV mean-colour scene segmentation (`SCENE_THRESHOLD=30.0`) | Frame timestamps are computed as `index / FRAME_FPS`, assuming ffmpeg emits exactly that rate. Videos longer than 120 s are silently truncated to the first 120 frames. `frame_brightness()` is dead code (no callers). |
| `detection.py` | YOLOv8n ONNX (onnxruntime, CPU) preferred; ultralytics `.pt` + ByteTrack second; greedy IoU tracker (same label, IoU > 0.3) with module-global state; `annotate_frame()` draws boxes | Confidence default 0.35, NMS 0.45, both hardcoded in `detect_frame()` / `_detect_onnx()` — no env config, no class filter. ONNX session is CPU-only (`CPUExecutionProvider`); the RTX 3050 GPU is never used. Tracker has no track expiry / lifecycle. |
| `vlm.py` | `caption_scene()` → OpenAI-compatible `/chat/completions` (providers `openai_compatible` / `nvidia_nim` / `ollama`) or template fallback, provider recorded per caption | One frame per scene (the first). No retry, no timeout config (fixed 120 s), no structured JSON output, no health check (health reports the provider *name* only, not reachability). On VLM failure the caption silently becomes a template that claims "no vision-language model was configured" — misleading when a VLM *was* configured but errored. |
| `embeddings.py` | `hash` (default, deterministic), `fastembed` (BAAI/bge-small-en-v1.5, 384-d), `sentence_transformers` (all-MiniLM-L6-v2, needs torch) | Any model failure falls back to hash silently. `_fastembed_failed` is a process-lifetime latch: one transient download failure disables FastEmbed until restart. `embed()` re-reads `EMBEDDING_PROVIDER` from `os.environ` on every call instead of using `settings` consistently. |
| `retrieval.py` | `search_frames()` — hybrid 0.6·cosine + 0.4·keyword + exact-phrase boost, scored **in Python over all captions**; Qdrant upsert/search helpers | **Qdrant is write-only**: `qdrant_search()` has no callers; search never consults Qdrant, it scans the DB. `try_qdrant_upsert()` swallows all errors (`False`), so vector-store drift is silent. The `NO_PROXY` workaround is duplicated here and in `embeddings.py` (see §9). |
| `agent.py` | Keyword intent routing (`summar` / `event` / `clip` / else QA), evidence-grounded answers, 0.45 score floor for QA, optional LLM synthesis | Not LangGraph — it is a hand-rolled `if/elif` router despite the "LangGraph-shaped" docstring; `langgraph` is not a dependency. `_llm_synthesize()` uses bare `httpx.post` (no `trust_env=False`, so the same NO_PROXY crash fixed in `vlm.py` can hit here) and excludes the `ollama` provider, while `vlm.py` includes it. No conversation memory is passed to the agent (docstring claims it is; `chat()` stores turns but never feeds them back). |
| `events.py` | Rule types `scene_duration_gt` / `caption_keyword` / `detection_label`; 30 s duplicate-suppression bucket; `verified` only on detection confidence ≥ 0.80 | `_already_fired()` loads **all** events for the video+rule on every candidate check (O(E) per check). No ROI, dwell time, entry/exit, or trajectory features. |
| `summarization.py` | Scene captions → per-scene sentences → chronological summary (short/medium/long) | Sentence splitting is naive `text.split(". ")` — breaks on decimals/abbreviations. No LLM summarisation path. |
| `clips.py` | ffmpeg re-encode clip (libx264 + aac, `+faststart`), cached by `clip_{start}-{end}.mp4` | `subprocess.run(cmd, check=True)` has **no timeout** — a stuck ffmpeg hangs the request forever. Clip cache is never evicted. |
| `reports.py` | JSON + PDF (reportlab) reports: summary, timeline, events | PDF has no detections/captions detail. `Paragraph` receives unescaped user content (video titles). |
| `celery_app.py` | Celery app (Redis broker), `visioniq.process_video`, max_retries=2, countdown 10, acks_late, prefetch 1 | No task time limits (soft/hard), no dead-letter queue, no `result_expires` — results accumulate in Redis. Task id is discarded at dispatch, so jobs cannot be tracked/revoked. |

### Config & data layer

- `config.py`: all settings from env with defaults. Notable defaults: `JWT_SECRET="dev-only-change-me-in-production"`, `JWT_EXPIRE_MINUTES=1440` (24 h), `FRAME_FPS=1.0`, `MAX_FRAMES=120`, `EMBEDDING_PROVIDER=hash`, `VLM_PROVIDER=fallback`, `WORKER_MODE=in_process`. `WORKER_CONCURRENCY` is defined but **never read anywhere**.
- `database.py`: `create_engine(DATABASE_URL)` with **no pool settings** (`pool_size`, `max_overflow`, `pool_pre_ping` all default) — no stale-connection protection for Postgres. `init_db()` runs `Base.metadata.create_all()` at import time in `main.py` **and** on startup; Alembic migrations exist separately. Running `alembic upgrade head` after `create_all` has already created the tables will fail with "table already exists" — the two schema paths are unreconciled (see `DATABASE_SCHEMA.md` warning, and §11).
- `models.py`: 14 tables — users, videos, processing_jobs, scenes, frames, captions, detections, events, alerts, conversations, messages, reports, revoked_tokens, password_reset_tokens. Indexes exist on FKs and `videos.status`; there is **no index on `captions.video_id + timestamp`**, `detections(video_id, timestamp)` (separate single-column indexes only), or `frames.video_id + timestamp_seconds` — the exact columns the read paths filter/sort by. `embedding_json` stores 384 floats as JSON text per frame (no pgvector, no native vector column).
- Migrations (`backend/alembic/versions/`): `9524b65e228a` initial schema (12 tables), `c7c48adc1ccd` revoked + password-reset tokens. `alembic/env.py` takes the URL from settings and uses `NullPool`. No migration for any later change; no test in CI runs Alembic against Postgres (CI uses SQLite).

## 3. Frontend architecture

Next.js 14.2.35, React 18, Tailwind 3.4, TypeScript 5.5. 17 routes (verified by build, §7): `/` dashboard, `/login`, `/forgot`, `/library`, `/upload`, `/processing`, `/search`, `/chat`, `/summary`, `/events`, `/alerts`, `/reports`, `/settings`, `/users`, `/video/[id]` (dynamic), plus `/_not-found`.

- `lib/api.ts`: single `api()` fetch wrapper; token from `localStorage` (`visioniq_token`); 422 detail lists stringified (v0.1.4 fix). No token refresh, no request timeout, no retry. `frameImageUrl()` is misleadingly named — it returns the video *stream* URL, not a frame URL (frame images go through `FrameImage.tsx` blob fetches).
- `components/ui.tsx`: Card/Button/Input/Empty/Loading/ErrorBox. `Loading` is plain text — no skeletons. No error boundaries anywhere.
- `app/video/[id]/page.tsx`: polls all six endpoints every 3 s while processing; signed stream URL with blob fallback; click-to-seek scenes/captions/detections; detections list capped at 20 in the UI. The polling timer's stop condition reads `video` state inside `setVideo`, which is fragile but works.
- `app/processing/page.tsx`: refetches every 5 s, retry button for failed videos.
- `app/chat/page.tsx`: single-shot Q&A; it **never sends `conversation_id`**, so every question creates a new `Conversation` row — there is no conversation-history UI at all, even though `GET /api/v1/conversations` exists (no frontend caller — verified by grep).
- `app/search/page.tsx`: query + optional video dropdown (loaded lazily on first search), score + detections per hit, "Download clip (±2s)" button, frame thumbnails.
- `app/settings/page.tsx`: read-only; shows API URL + signed-in user; no editable settings.
- `app/users/page.tsx`: admin-only list; shows 403 text for non-admins. There is **no way to create an admin** through the UI or API (see §6).
- `components/FrameImage.tsx`: blob-fetches each frame image with the token. The cleanup closure captures a stale `url` (initially `null`), so `URL.revokeObjectURL` is effectively never called for the created object URL — blob URLs leak for the page lifetime.
- No frontend tests exist (no jest/vitest/playwright config under `frontend/`). `any` is used pervasively (`chat`, `summary`, `events`, `settings` pages). No pagination anywhere (dashboard slices 10 client-side; detections/alerts/events lists are unbounded).

## 4. MCP server (`mcp_server/server.py`)

- Two transports, one `call_tool(name, args, user=None)`: stdio JSON-RPC and HTTP (default port 8001, **collides with nothing in the repo but note the backend dev server also historically used 8001 in tests**).
- HTTP `_auth()` validates the JWT and loads the `User`; tools are scoped to that user (v0.3.1 fix). `video_summarize` returns `{"error": "Video not found"}` cross-user.
- **stdio transport is unscoped by design** (`user=None`): any local MCP client gets unfiltered access to all users' videos. The code comments this as "local operator" trust — acceptable for a local tool, but it means the stdio server must never be exposed on a network, and there is no auth on stdio at all.
- `call_tool` does no input validation beyond `int(...)` casts: `video_search` requires `args["query"]` (KeyError → 500 via the stdio error path / HTTP 500), `top_k` is cast but not bounded (a caller can pass `top_k=100000`), `video_qa` requires `args["question"]`.
- No tests cover the MCP server (not in `backend/tests/`, not in CI).

## 5. Docker & CI

- `docker-compose.yml` (full stack): Postgres 16, Qdrant (`qdrant/qdrant:latest` — **unpinned**), Redis 7-alpine, backend, worker, frontend. Issues: Postgres password is the literal `visioniq` in the file; Qdrant has **no healthcheck** and the backend does not `depends_on` it; the backend runs `uvicorn` directly with **no Alembic migration step** (comment says run it manually) while `create_all` runs at startup — see §2 data-layer conflict; no `HEALTHCHECK` in either Dockerfile; both images run as **root**; no restart policy on any service.
- `docker-compose.laptop.yml`: SQLite + in-process worker; `JWT_SECRET` defaults to `dev-only-change-me-in-production` if unset — a shipped weak default.
- `backend/Dockerfile` (`python:3.12-slim` + ffmpeg, pip retries): fine. `frontend/Dockerfile` (`node:20-alpine`, `npm ci` with long timeouts): fine.
- `.github/workflows/ci.yml`: backend job installs ffmpeg, `pip install -r requirements.txt`, runs `pytest tests/ -q` on SQLite (e2e file present but skips without `VISIONIQ_E2E=1`); frontend job runs `npm ci && npm run build`. **No Postgres/Qdrant/Redis services in CI**, so no integration test ever runs in CI. No lint, no typecheck, no security scan.

## 6. Auth & authorisation — what is good, what is not

Good (verified by reading the code and by `tests/test_privacy.py`, which passed in §7): per-video ownership checks on every video/frame/report route; search/chat/MCP scoped to the logged-in user since v0.3.1; PBKDF2 200k iterations; logout revocation via `jti`; password-reset tokens stored as SHA-256 hashes, single-use, 1 h expiry; login rate limit (30/min/IP); Pydantic validation on JSON bodies; upload extension allow-list + streaming size cap; files stored per-video-id, never by user-supplied path.

Issues (see TECHNICAL_DEBT.md for severities):

1. **Password-reset token returned in the API response** (`routers/auth.py: password_reset_request`): anyone can request a reset for any email and receive the raw token in the response, then reset that account's password — full account takeover with no email access. The docstring says "for local testing", but there is no flag, no email service, and no way to disable it. This is the highest-severity open issue in the codebase.
2. **Hand-rolled JWT** (`security.py`): custom HMAC-SHA256 JWT instead of PyJWT. It is correctly signed and expiry-checked, but it has no `iat`, no `aud`/`iss`, does not verify the `alg` header, and any future change risks a classic JWT bug. `decode_token` also swallows all exceptions.
3. **No admin provisioning path**: nothing in the codebase ever assigns `role="admin"` (verified by grep). The only way to get an admin is a manual DB edit. `/users` (admin-only) is therefore unreachable in a fresh deployment.
4. **RevokedToken / PasswordResetToken tables are never pruned**: every logout and every reset request adds a row forever; no cleanup job, no expiry-based delete.
5. **Rate limiting is in-memory and login-only** (`main.py`): per-process dict, resets on restart, useless across replicas; register and password-reset-request have no limit (account-enumeration via timing is mitigated, but reset-token spam is unbounded).
6. **JWT in `localStorage`** (`frontend/lib/api.ts`): any XSS can steal the token; no httpOnly-cookie alternative, no refresh-token rotation (24 h expiry, user must re-login).
7. **Weak shipped defaults**: `JWT_SECRET` default `dev-only-change-me-in-production` (config + laptop compose); Postgres password `visioniq` in `docker-compose.yml`.
8. **No refresh tokens, no session listing, no "log out everywhere"**.
9. **Upload validation is extension-only**: no MIME/magic-byte sniffing (admitted in `SECURITY.md`); a renamed executable passes the extension check and is then rejected only by ffprobe failure — but the file is already written to disk first.
10. **CORS** allows `http://localhost:3000` only — correct for laptop, but hardcoded; `allow_methods`/`allow_headers` are `*`.

## 7. Test results — actually run in this audit session

Environment: this machine (Python 3.12.3, Node v24.22.1), repo at commit `13f6919`, no code changed.

| Check | Command | Result |
|---|---|---|
| Backend unit/integration suite | `cd backend && .venv/bin/python -m pytest tests/ -q --ignore=tests/test_e2e_browser.py` | **11 passed, 48 warnings, 43.16 s.** Breakdown: `test_api.py` 2 (full flow, upload validation), `test_phase2.py` 5 (VLM mock, Qdrant in-memory, Celery eager, detection-unavailable, hash determinism), `test_phase3.py` 3 (range/signed streaming, clip/detections/analytics/annotated, logout/reset), `test_privacy.py` 1 (cross-user search/chat isolation). Warnings are mostly `DeprecationWarning: datetime.datetime.utcnow()` (15 call sites) plus a pytest mark warning. |
| Frontend build | `cd frontend && npm run build` | **Passed.** 17 routes: 16 static (○) + 1 dynamic (ƒ `/video/[id]`). First Load JS shared 87.3 kB. No TypeScript or lint errors surfaced by the build. |

**Not re-run in this session** (cited from `CHANGELOG.md` / `PROJECT_STATE.md`, last verified 2026-11-06 by the parent session): Playwright e2e browser test (1 passed, needs live frontend + backend + Celery worker); live Postgres 16.15 migrations (15 tables, up/down/up); live Qdrant 1.20.0 server upsert/search; live Redis 7.0.15 + Celery worker processing a real upload in 9.1 s. Baseline numbers from the master prompt (bus search 0.847, traffic video 61 detections, FastEmbed Recall@1 1.00, hash 0.67) were **not** re-measured in this audit — they come from `docs/benchmarks/2026-11-05.md` (12 labelled queries, 6-caption pool) and the 2026-11-05/06 session notes.

Test coverage gaps (verified by inspection, not by a coverage tool): no MCP tests, no frontend tests, no rate-limit tests, no upload-size-cap test, no VLM timeout/retry tests, no Celery failure/retry tests, no Postgres-specific tests (CI uses SQLite only), no concurrency tests, no test for `recover_stuck_jobs`, no test for the `create_all` vs Alembic conflict.

## 8. Unfinished modules

| Module / feature | State | Evidence |
|---|---|---|
| Real VLM end-to-end | **Not done.** Client exists; no real vision-model inference has run anywhere. | `vlm.py` `caption_scene()`; TASK_TRACKER #10/#20 "Partial/Pending"; `.env.example` documents Ollama steps. |
| ByteTrack / ultralytics `.pt` path | Code present, **never tested** (torch install stalled on this machine). | `detection.py: _detect_ultralytics()`; TASK_TRACKER #9. |
| sentence-transformers embeddings | Code present, **never tested** (needs torch). | `embeddings.py: _sentence_transformers()`; TASK_TRACKER #11. |
| Admin provisioning | No path at all (see §6.3). | Grep: no `role="admin"` assignment in `backend/app`. |
| Conversation history UI | Backend endpoints exist; **no frontend caller**. | Grep: "conversations" absent from `frontend/`. Chat page creates a new conversation per question. |
| LangGraph agent | Docstring says "LangGraph-shaped"; it is `if/elif` keyword routing. `langgraph` is not a dependency. | `agent.py`. No intent classification, planning, tool selection, verification, or multi-step workflows. |
| Tools 6–8 (detection_analytics, timeline_analysis, report_generation) | **Do not exist** as agent/MCP tools. Only 5 tools exist (`agent.py: TOOLS`). | `agent.py: TOOLS`, `mcp_server/server.py`. |
| Zone/ROI, dwell time, entry/exit, loitering, unattended-object detection | **Do not exist.** | `events.py` has only 3 rule types; `detection.py` has no zones or trajectories. |
| Observability | **Nothing**: no structured logs, request IDs, metrics, Prometheus/Grafana, GPU/memory monitoring. | Grep: no `prometheus`, `structlog`, `logging` config in `backend/app`; only `print()` in `worker.py` recovery. |
| Cross-encoder reranking, query rewriting/expansion, context compression | **Do not exist.** Reranking is the weighted-sum score itself. | `retrieval.py: search_frames()`. |
| RAG evaluation dataset (≥50 Qs) | **Does not exist.** Only the 12-pair embedding benchmark. | `scripts/benchmark.py` (12 pairs, 6 captions). |
| Backup/restore | Documented as "back up the volumes" in `DEPLOYMENT.md`; no scripts, no tested restore. | No backup files/scripts in repo. |
| Frontend a11y, skeletons, error boundaries, pagination | **Do not exist.** | `components/ui.tsx`; pages listed in §3. |
| `shadcn/ui` adoption | Listed as pending in PROJECT_STATE; not present. | No shadcn files in `frontend/`. |

## 9. Duplicated code

1. **NO_PROXY workaround, 3 sites, no shared helper**: `embeddings.py` (~L48–68) and `retrieval.py` (~L74–90) each inline the save/override/restore dance for `NO_PROXY`/`no_proxy`. `vlm.py` solves the same problem differently (`trust_env=False`). `agent.py: _llm_synthesize()` solves it **not at all** (bare `httpx.post`).
2. **Token validation, 2 implementations**: `security.get_current_user()` vs `videos.py: _bearer_user()` — same decode + revocation + user-load logic, hand-duplicated because the stream endpoint can't use the `Depends` version.
3. **`decode_token` result handling** repeated in `auth.py: logout()` and `mcp_server/server.py: _auth()`.
4. **Search-hit shaping** in three places: `retrieval.search_frames()` builds the hit dict; `agent.py` clip branch rebuilds `{video_id, start_seconds, end_seconds, caption}` from it; `mcp_server/server.py: clip_retrieval` rebuilds the same shape again.
5. **"Admin sees all, else owner-only"** logic is spelled out per-endpoint (`videos.py`, `search_chat_reports.py`, `retrieval.py`, `agent.py`, `mcp_server/server.py`) instead of one query helper.
6. **Test upload helper** duplicated across `test_phase3.py`, `test_privacy.py` (ffmpeg bus-video build + upload) with slightly different temp paths; each test file also repeats its own env setup / DB cleanup preamble.

## 10. Performance bottlenecks (measured where known, estimated otherwise)

1. **Search is a full Python scan** (`retrieval.py: search_frames()`): loads *all* captions (+ their frames, embeddings, detections via lazy relationships — N+1 queries) and scores them in Python. Cost grows linearly with library size; Qdrant is never consulted on the read path, so the vector index bought nothing for latency. No measurement exists beyond the 12-query benchmark (mean search 9.4 ms fastembed / 0.4 ms hash on a 6-caption pool — meaningless at scale).
2. **Detection is one frame per ONNX inference, CPU-only**: 456–880 ms/frame measured on bus.jpg. A 120-frame video costs ~60–100 s of detection alone, plus 1 fps ffmpeg extraction and per-frame JPEG writes. No batching, no GPU provider, no frame skipping.
3. **Pipeline is strictly sequential per video** (`worker.py: process_video()`): probe → thumbnail → extract all frames → segment → write all scene/frame rows → per scene: detect every frame, caption, embed, upsert. A failure late in the pipeline discards nothing (rows are committed per scene) but the video is marked `failed` and a retry re-runs *everything* — no resumability, no per-stage checkpoint.
4. **Per-frame embedding duplication**: every frame in a scene gets the *same* caption vector (and the same Qdrant upsert). For a 120-frame video this is up to 120 identical vectors — wasted storage and it makes "frame-level" search a fiction; retrieval granularity is really scene-level.
5. **N+1 query patterns**: `worker.py` scene/frame assignment (`next(... if i in s["frame_indices"])` inside loops, list membership scans); `events._already_fired()` re-queries all events per candidate; `search_frames()` touches `cap.frame`, `frame.embedding()`, `frame.detections` per caption via lazy loading.
6. **Frontend polling**: video page fires 6 API calls every 3 s while processing; processing page fires 1 call every 5 s forever (no stop when all videos are ready/failed). No websockets/SSE.
7. **No DB connection pooling config** (`database.py`): default SQLAlchemy pool, no `pool_pre_ping`; a Postgres restart leaves stale connections until the process restarts.
8. **Clip extraction re-encodes every time** (except the exact same start/end cache hit) with no timeout (`clips.py:27`) and unbounded cache growth.
9. **`init_db()` at import** (`main.py`): every import of the app module touches the DB (creates tables + `STORAGE_DIR`), which makes unit-test collection and CLI tools (Alembic env, MCP server) implicitly depend on a writable database.

## 11. Documentation drift (verified, not assumed)

These docs contradict the code or each other; they need a pass before any public release:

- `README.md`: "Redis is reserved for a future queue; the current worker is in-process" — false since v0.2.0 (Celery worker exists, verified live in v0.3.1). "16 pages" — the build now reports 17 routes. Layout section lists `database/` and `infrastructure/docker/` directories that **do not exist** in the repo. "ByteTrack tracking activates through ultralytics' tracker when the model is present" — the `.pt` path is untested.
- `PROJECT_STATE.md`: "Video streaming in the browser goes through an authenticated blob fetch … range/seek streaming is not yet implemented" — false since v0.3.0 (signed URLs + Range). "Exact next steps: 4. Add Alembic migrations and a Redis/Celery worker (Phase 2)" — done. "Alembic migration v2 (14 tables total)" vs "15 tables" elsewhere — inconsistent (14 app tables + `alembic_version` = 15).
- `ARCHITECTURE.md` diagram: embeddings listed as "hash (default) / sentence-transformers" — omits FastEmbed, the actual Phase 2 real model. Request flow 2 says "hash/sentence embedding" — same omission.
- `DATABASE_SCHEMA.md`: table list omits `revoked_tokens` and `password_reset_tokens`; the "Migrations note" says Alembic is a Phase 2 item / warns against `create_all` — both stale now that migrations exist and `create_all` still runs.
- `API_DOCUMENTATION.md`: missing Phase 3 endpoints (`stream-url`, `clip`, `detections`, `analytics`, `frames/{id}/annotated`, `logout`, `password-reset-request`, `password-reset`).
- `DEPLOYMENT.md:81`: "alembic upgrade head # 12 tables" — stale (15 tables now).
- `TESTING.md`: top section still reports the 2026-11-04 run ("2 passed"); Phase 2 section says "13 tables incl. alembic_version" (stale). No mention of the privacy test or e2e test.
- `SECURITY.md`: "Known gaps: JWTs are not revoked on logout" — false since v0.3.0 (logout revocation exists and is tested). The password-reset-token-in-response issue (§6.1) is not mentioned at all.
- `TASK_TRACKER.md`: row 10 and row 20 both track "Real VLM" (duplicate rows, Partial vs Pending). Row 2 says "pytest 7 passed" (stale — 11 now).

## 12. Verdict

v0.3.1 is a coherent, honest, working laptop-scale platform: the core loop (upload → process → search → chat → clip → report) is real, tested (11 backend tests + 1 e2e, both re-verified or recorded as noted in §7), and the per-user isolation fix from v0.3.1 is sound. The single most important gap is the VLM: every caption in production today is a template, so "multimodal understanding" is currently detection metadata + keyword search, not vision. The single most important *risk* is the password-reset token returned in the API response (§6.1). The largest *structural* risks are the `create_all` vs Alembic conflict, the Python-scan search path that ignores Qdrant, and the absence of any observability. Everything else in the master prompt's Phases 1–14 is incremental work on top of this base — no rebuild is needed, but Phases 1 (VLM), 9 (security) and 7 (infra) should come before feature expansion.
