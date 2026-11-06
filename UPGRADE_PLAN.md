# UPGRADE_PLAN.md — VisionIQ v0.3.1 → v1.0.0

- **Baseline:** v0.3.1, commit `13f6919`, audited 2026-11-06 (see `CODEBASE_AUDIT.md`, `TECHNICAL_DEBT.md`).
- **Target hardware:** Windows 11 + WSL2 Ubuntu 24.04, RTX 3050, 16 GB RAM, free-first. All phases must keep the laptop profile working.
- **Rules (from the master prompt):** do not rebuild from scratch; do not remove working features; do not invent functionality or benchmarks; do not mark a phase done until it has been run and observed; if blocked by hardware/credentials, document and continue with a verified alternative.

## Already done in v0.3.1 — do NOT redo

These items from the master prompt's "known outstanding work" were completed and verified on 2026-11-06 (see `CHANGELOG.md`):

| Item | Evidence |
|---|---|
| Live PostgreSQL testing | Alembic upgrade/downgrade/upgrade on Postgres 16.15, 15 tables |
| Live Qdrant testing | Qdrant 1.20.0 server upsert + search (bus 1.000) |
| Redis/Celery integration testing | Real worker + Redis 7.0.15 processed a real upload in 9.1 s, 50 detections, 10 Qdrant points |
| Browser end-to-end testing | Playwright test passes: register → upload → search 0.847 → clip download → logout |
| Cross-user privacy | Search/chat/MCP scoped to the logged-in user; `tests/test_privacy.py` regression test |

What remains genuinely open from that list: **Ollama VLM end-to-end** and **GitHub publication**. Everything else in the plan below is new work, hardening, or extension.

## Phase 0 — Audit (DONE, this document set)

- [x] Full codebase inspection, test runs, debt register, upgrade plan.
- Outputs: `CODEBASE_AUDIT.md`, `TECHNICAL_DEBT.md`, this file.
- Exit criteria: three files at repo root, every claim traceable to a file or an observed run. **Met 2026-11-06.**

## Phase 1 — Complete multimodal video understanding (HIGHEST PRIORITY)

**Goal:** replace template captions with genuine VLM scene understanding, with an honest provider distinction.

1. **Ollama integration, for real.** Install Ollama + `llava:7b` (fallback `qwen2-vl:7b`) on the RTX 3050 machine. Add a VLM health check (`GET /health` reports `vlm_reachable: true/false` + model + latency of a probe call) — today health reports only the provider *name*.
2. **Structured captions.** `vlm.py`: request JSON (`objects`, `actions`, `setting`, `description`) with a strict schema; validate with Pydantic; on malformed output, retry once with a repair prompt, then fall back and record `provider="vlm-failed"` (never label a failure as "no VLM configured"). Keep three distinct provider values: `fallback` (template), `detection` (detection-derived), `vlm` (+ model name in `Caption.model`, which already exists).
3. **Frame-to-VLM processing.** Caption more than the first frame per scene: sample up to N frames per scene (config `VLM_FRAMES_PER_SCENE`, default 3) and merge; cap total VLM calls per video (`VLM_MAX_CALLS_PER_VIDEO`) so a 10-minute video cannot take an hour.
4. **Timeouts, retries, logs.** Configurable `VLM_TIMEOUT_SECONDS` (default 120), `VLM_MAX_RETRIES` (default 2, exponential backoff), and per-call inference logging (video/scene, model, latency, tokens if reported, outcome) to a `vlm_calls` log or structured logs — no prompt text containing user data in logs.
5. **End-to-end test.** `tests/test_vlm_e2e.py`: upload → frame extraction → VLM → structured captions → embeddings → Qdrant → search → RAG answer, against a *real* local Ollama model (marked integration, skipped without `VISIONIQ_VLM_E2E=1` + reachable Ollama). Keep the existing mock-server test for CI.
- **Depends on:** a machine with Ollama (user's laptop). **If blocked:** run against a local mock only for the plumbing, and mark the phase "code complete, model run pending" — do not claim it done.
- **Fixes debt:** H4, M3 (shared HTTP client for the VLM call).
- **Exit criteria:** a real `llava:7b` (or compatible) caption observed in the DB with `provider="ollama"`, search returning it, and the e2e test passing against the real model.

## Phase 2 — Advanced video intelligence

**Goal:** stop processing every frame uniformly; make sampling scene-aware.

1. **Adaptive frame sampling.** `video_processing.py`: sample densely at scene boundaries, sparsely inside stable scenes (config `FRAME_FPS`, `SCENE_SAMPLE_FPS`, `BOUNDARY_WINDOW_SECONDS`). Keep `MAX_FRAMES` but make truncation explicit: videos longer than the cap get a warning in `error_message`/UI instead of silent truncation.
2. **Scene similarity + duplicate removal.** Perceptual-hash or embedding-similarity dedupe of near-identical frames within a scene before detection/VLM; record `duplicate_of_frame_id` or drop with a count.
3. **Scene-aware selection.** Keyframe = most representative frame per scene (highest detection count / sharpest), not always the first; VLM captions use keyframes.
4. **Temporal event grouping + object trajectories.** Group detections by track into trajectories (`track_id`, first/last seen, bounding-box path, duration); store a `trajectories` view derived from `detections` (no new table until proven necessary). Video-level event timeline endpoint already exists via events; wire trajectories into it.
- **Depends on:** Phase 1 (keyframe choice uses VLM/detection quality).
- **Fixes debt:** M7 (checkpointing helps here), M9 (per-frame vs per-scene embeddings — decide once, document it).
- **Exit criteria:** benchmark on the same 10 s bus video + a 2-minute video: frames processed, detections, and processing time all recorded; sampling reduces processed frames by a measured % with no loss of detected labels.

## Phase 3 — Advanced computer vision

**Goal:** make detection configurable, measurable, and honest about tracking.

1. **Config:** `YOLO_CONF`, `YOLO_NMS`, `YOLO_CLASSES` (allow-list), `YOLO_MIN_TRACK_IOU` in `config.py` + `.env.example`; surface them in `/health`.
2. **Track lifecycle:** replace the module-global greedy tracker with a per-video tracker object (no shared global state — fixes the concurrent-processing hazard), with track expiry (missed-frame budget) and a max track age; record track birth/death in the trajectory view from Phase 2.
3. **Detection filtering + calibration:** per-class confidence thresholds; duplicate suppression already handled by NMS — verify with a test (two overlapping boxes of the same label collapse to one).
4. **Metrics:** extend `scripts/benchmark.py` with a hand-labelled set (a few frames of bus.jpg / traffic video with ground-truth boxes): detection precision/recall at IoU ≥ 0.5, track ID switches, per-frame latency. **Do not claim face/identity recognition** — it is not implemented and is out of scope.
5. **GPU path:** try `CUDAExecutionProvider` with CPU fallback in `_load_onnx()`; measure per-frame latency CPU vs GPU on the RTX 3050 and record it.
- **Depends on:** Phase 2 (trajectories).
- **Fixes debt:** M8, M17 (delete or wire `WORKER_CONCURRENCY`).
- **Exit criteria:** benchmark numbers recorded in `docs/benchmarks/`; `.pt`/ByteTrack path either tested or explicitly dropped with a note.

## Phase 4 — Advanced multimodal RAG

**Goal:** retrieval that uses the vector store, filters, reranks, and is measured on a real dataset.

1. **Use Qdrant on the read path (H3).** `search_frames()` queries Qdrant first (payload filter `owner_id` / `video_id`), falls back to the DB scan when Qdrant is absent; log upsert failures; add a re-index script.
2. **Filters:** metadata filters (label, provider, video), timestamp-range filter, video/scene-scoped retrieval — all as API params, all owner-scoped.
3. **Reranking:** add a cross-encoder reranker behind a flag (`RERANKER_MODEL`, default off on laptop; use a small ONNX cross-encoder or `fastembed` rerank when available). Measure with/without.
4. **Query rewriting/expansion + context compression:** lightweight expansion (synonyms from detection labels present in the video) and dedupe of near-identical evidence before answering; citation validation (every citation must resolve to an existing frame + timestamp).
5. **Evaluation dataset (≥50 Qs).** Build `tests/data/rag_eval.jsonl`: 50+ questions over the sample videos with manually checked answers (expected video + timestamp ±2 s + expected answer gist). Measure Recall@1, Recall@5, Precision@5, MRR, retrieval latency, answer faithfulness (claims traceable to citations), answer relevance. Compare against the v0.3.0 baseline (the 12-pair benchmark) and record both.
- **Depends on:** Phase 1 (real captions change retrieval quality), H3.
- **Fixes debt:** H3, M9, L1.
- **Exit criteria:** `scripts/rag_eval.py` runs, writes `docs/benchmarks/rag-eval-<date>.md` with all seven metrics, baseline vs new side by side.

## Phase 5 — Advanced agentic AI

**Goal:** a real agent loop, not keyword routing — without adding a heavy framework unless it earns its place.

1. **Decide the framework on evidence.** Prototype LangGraph (dependency-light: `langgraph` + explicit state) vs extending the current router; pick LangGraph only if multi-step planning/verification demonstrably needs it. Record the decision in `docs/decisions/003-agent-framework.md`.
2. **Agent loop:** intent classification → query planning → tool selection → execution → result verification (citations resolve, scores above floor) → answer; error recovery (tool failure → retry once → degrade to "no evidence"); conversational context (feed prior turns from `conversations/messages` into the agent — currently stored but never used).
3. **Tools (8):** keep the existing 5; add `detection_analytics` (wraps `GET /analytics`), `timeline_analysis` (scenes + events + trajectories in one call), `report_generation` (wraps report creation). Every tool validates inputs (bounded `top_k`, existing `video_id`, owner check) and returns structured output.
4. **MCP hardening:** input validation in `call_tool()` (bounded `top_k`, required fields → clean 400-style errors, not 500s); stdio transport stays local-only and documented; HTTP tools already scoped (v0.3.1) — add MCP tests (`tests/test_mcp.py`, stdio + HTTP with two users).
5. **Human confirmation:** destructive/sensitive actions (delete video, acknowledge critical alert) require an explicit `confirm=true` parameter; the agent must ask, never assume.
- **Depends on:** Phase 4 (retrieval quality determines answer quality).
- **Fixes debt:** agent docstring honesty, M12 (conversation memory), MCP test gap.
- **Exit criteria:** multi-step query ("find the bus, then clip it, then summarise that scene") completes via the agent with verified citations; MCP tests pass with two users.

## Phase 6 — Real-time and advanced event analytics

**Goal:** an extensible event engine that distinguishes detection from inference.

1. **Zones/ROI:** per-video polygonal or rectangular zones (stored as JSON on a new `zones` table or on the rule); `zone_enter` / `zone_exit` events from track trajectories.
2. **Dwell time, movement, loitering:** from trajectories — dwell = last_seen − first_seen inside a zone; loitering candidate = dwell > threshold with low displacement; unattended-object candidate = track appears, person track leaves, object track persists (only when tracking is reliable — label it "candidate", never a definitive security claim).
3. **Event verification:** keep the ≥0.80 confidence rule; add optional VLM verification (Phase 1) that can upgrade an event, recorded as `verified_by: detection|vlm|none`.
4. **Alerting:** severity, 30 s suppression (keep), alert history endpoint (exists), evidence clips (link each event to a clip via the existing clip endpoint).
- **Depends on:** Phases 2–3 (trajectories, zones).
- **Fixes debt:** L5 (range-filtered suppression check).
- **Exit criteria:** on the traffic sample video, zone enter/exit + dwell events fire with correct timestamps; a "loitering candidate" is demonstrated as a candidate, with the wording audited for over-claiming.

## Phase 7 — Database and infrastructure (hardening)

**Goal:** Postgres as the verified production database; reliable workers; reconciled schema.

1. **Schema:** fix H2 (drop `create_all` from the app path; Alembic-only migrations; entrypoint runs `alembic upgrade head`; CI runs migrations against real Postgres). Add missing indexes (`captions(video_id, timestamp_seconds)`, `detections(video_id, timestamp_seconds)`, `frames(video_id, timestamp_seconds)`).
2. **Postgres:** connection pooling config (M1), backup/restore scripts (`scripts/backup.sh` / `restore.sh` for `pgdata` + `backend_storage` + `qdrantdata`) with a *tested* restore (restore to a scratch DB and verify row counts).
3. **Qdrant:** persistent storage (already a volume), payload indexes (`owner_id`, `video_id` — needed for filtered search in Phase 4), collection config documented, re-index script (Phase 4), recovery procedure documented.
4. **Redis/Celery:** time limits, `result_expires`, stored task ids, dead-letter/failed-task handling, startup-recovery grace period (M10, M11). Add a Celery failure test (poison video → job `failed`, no stuck `running`).
5. **Integration tests in CI:** Postgres/Qdrant/Redis service containers; `pytest -m integration` (new marker) running the live-infra checks that were manual in v0.3.1.
- **Depends on:** nothing (can run in parallel with Phases 1–2, but H2 blocks any "production-ready" claim).
- **Fixes debt:** H2, M1, M4, M10, M11, M16 (CI part).
- **Exit criteria:** `docker compose up` from a clean checkout runs migrations automatically and serves traffic; backup → wipe → restore verified; CI green with service containers.

## Phase 8 — Advanced frontend

**Goal:** usability and robustness, no redesign for its own sake.

1. **Chat history (M12):** conversations list + follow-ups with `conversation_id`.
2. **Search filters + pagination** (Phase 4 filters surfaced in UI; L10 backend pagination first).
3. **Dashboard analytics:** per-label detection totals, processing-time stats, storage use (new lightweight `/api/v1/stats` endpoint, owner-scoped).
4. **Video page:** event timeline strip, trajectory overlay toggle on annotated frames, clip download from the video page (not only search).
5. **Robustness:** error boundaries, loading skeletons (replace text `Loading`), empty states (mostly exist), accessible labels on icon-only controls, responsive check at 360 px width.
6. **Real-time updates:** replace polling with SSE for processing status (fallback to the current polling if SSE fails).
7. **Frontend tests:** add Vitest + Testing Library for `lib/api.ts` and `ui.tsx`, and extend the Playwright suite to the full 13-step workflow (register → … → logout → unauthorised-access-rejected).
- **Depends on:** Phases 4–6 for the data behind the new UI.
- **Fixes debt:** M12, L6, L7, L10.
- **Exit criteria:** Playwright suite covers all 13 master-prompt workflows; no page makes unbounded API calls.

## Phase 9 — Security hardening

**Goal:** close the known gaps before any public release.

1. **H1 first:** remove the reset token from the response (flag-gated dev fallback, off by default).
2. **H5:** PyJWT migration with `alg` verification, `iat`/`aud`/`iss`.
3. **H6:** admin provisioning CLI.
4. **M4/M5:** token-table pruning; Redis-backed rate limits for login/register/reset-request.
5. **M13:** token storage/refresh decision (httpOnly refresh cookie vs short-lived access token).
6. **Upload hardening:** magic-byte sniffing (in addition to extension), plus a ClamAV-style scan hook documented as optional.
7. **Automated security tests:** `tests/test_security.py` — cross-user access on *every* route (videos, clips, reports, conversations, embeddings, frames, events, alerts), `alg=none` JWT, tampered JWT, expired JWT, revoked JWT, reset-token reuse, rate-limit 429, oversized upload 413, path traversal in filenames, SSRF check on `VLM_BASE_URL` (must not accept internal metadata IPs — document the allow-list approach).
8. **Docs:** update `SECURITY.md` (remove the stale "JWTs are not revoked on logout" line; document the reset-token policy, the stdio-MCP trust boundary, and the disclosure process).
- **Depends on:** H1/H5 should land before GitHub publication (Phase 13) — a public repo with a known account-takeover flaw is not acceptable.
- **Fixes debt:** H1, H5, H6, M4, M5, M13.
- **Exit criteria:** `tests/test_security.py` green; no High-severity item from `TECHNICAL_DEBT.md` remains open.

## Phase 10 — Observability and performance

**Goal:** measure before optimising; make the system debuggable in production.

1. **Structured logs:** `structlog` or stdlib `logging` with JSON formatter, request IDs (middleware, propagated to worker via Celery headers), processing job IDs in every pipeline log line.
2. **Metrics:** `/metrics` (Prometheus client) — API latency histogram, processing duration, detection/VLM inference latency, queue depth (Celery inspect), failed-job count, Qdrant search latency, DB pool stats. `docker-compose.observability.yml` with Prometheus + Grafana + a starter dashboard (optional profile, not in the laptop default).
3. **Profiling:** run the Phase 2 benchmark with `py-spy` / `cProfile` on a 2-minute video; fix the top 1–2 hotspots only (likely the search scan and per-frame ONNX calls — both already scheduled in Phases 3–4).
4. **Resource monitoring:** GPU utilisation (nvidia-smi, when present), RSS per worker, disk use of `storage/` (with a warning threshold).
- **Depends on:** Phases 2–4 (the things being measured should exist first).
- **Exit criteria:** `/metrics` serves real counters after a video upload; a Grafana dashboard screenshot exists in the repo (only if actually run).

## Phase 11 — Automated testing (expansion)

**Goal:** the test pyramid the master prompt asks for, with a clean mock/real split.

1. **Markers:** `unit` (default, SQLite, mocks allowed), `integration` (needs live Postgres/Qdrant/Redis — CI service containers), `e2e` (existing `VISIONIQ_E2E=1` browser test), `vlm` (needs real Ollama).
2. **New suites:** `test_security.py` (Phase 9), `test_mcp.py` (Phase 5), `test_vlm_e2e.py` (Phase 1), `test_postgres.py` (migrations + pooling, Phase 7), `test_celery_reliability.py` (failure/retry/dead-letter, Phase 7), `test_rag_eval.py` (Phase 4 dataset), frontend Vitest (Phase 8), Playwright 13-step workflow (Phase 8).
3. **Shared fixtures:** `tests/conftest.py` (L12) — one client/auth/video helper for all files.
4. **Coverage gate:** `pytest --cov` with a modest threshold (e.g. 70% on `app/services`) enforced in CI; report, don't game it.
- **Depends on:** each phase's own tests land with that phase.
- **Exit criteria:** `pytest -m "not e2e and not vlm"` green in CI with service containers; the 13-step browser workflow green locally.

## Phase 12 — Production engineering

**Goal:** a boring, reliable deployment.

1. **Docker:** non-root users, healthchecks, pinned Qdrant image, `restart: unless-stopped` (M15); multi-stage frontend build (standalone output) to shrink the image.
2. **Startup:** entrypoint runs `alembic upgrade head`, waits for Postgres/Redis/Qdrant health, then starts uvicorn; graceful shutdown (SIGTERM → drain in-flight requests, stop accepting new uploads).
3. **Single startup command:** document one command for laptop (`docker compose -f docker-compose.laptop.yml up --build`) and one for full stack (`docker compose up --build`), both verified from a clean checkout.
4. **Release management:** semantic versioning, `CHANGELOG.md` per release, git tags (`v1.0.0`), a `RELEASE.md` checklist (tests, docs, backup, migration dry-run).
- **Depends on:** Phase 7 (migrations) and Phase 9 (security) — production engineering without those is premature.
- **Exit criteria:** clean-checkout `docker compose up --build` serves traffic with zero manual steps; `docker compose down -v && docker compose up --build` reproduces it.

## Phase 13 — GitHub and documentation

**Goal:** a public repo that survives technical review.

1. **Unblock the remote:** user runs `gh auth login` on their machine, then `gh repo create visioniq-video-intelligence --public --source=. --remote=origin --push` (commands already in `DEPLOYMENT.md`). Never force-push.
2. **Docs pass (M14):** fix every item in audit §11; rewrite `README.md` to the master prompt's required contents (overview, features, screenshots, architecture diagram, stack, install, demo workflow, API, benchmarks, limitations, roadmap) using **only verified screenshots and numbers** (bus search 0.847, traffic 61 detections, FastEmbed Recall@1 1.00 — all already measured; add Phase 1/4 numbers only after they are measured).
3. **Screenshots:** take real screenshots of dashboard, video page with detections, search, chat — from the running laptop app, not mockups.
4. **CI:** extend as in M16 (services, lint, typecheck, audit). Add a docs-freshness check for the known-stale phrases.
5. **Hygiene:** verify no secrets, no private videos, no weights in git (`git ls-files` audit before first push; `.gitignore` already covers `.env`, `*.db`, `*.onnx`, `*.pt`, `storage/`).
- **Depends on:** Phase 9 (security) — do not publish with H1 open.
- **Exit criteria:** public repo live, README complete, CI green on `main`.

## Phase 14 — Performance evaluation

**Goal:** a repeatable benchmark suite with honest numbers.

1. **Extend `scripts/benchmark.py`** (or a new `scripts/benchmark_full.py`): template vs VLM captions (quality judged against the hand-labelled set, plus caption latency); hash vs FastEmbed vs sentence-transformers; keyword vs dense vs hybrid; rerank on/off; baseline vs improved RAG (Phase 4 dataset); CPU vs GPU detection (Phase 3).
2. **Report:** processing time, inference time, search latency, retrieval accuracy, memory, GPU use, detection precision/recall — all from actual runs on the RTX 3050 laptop, written to `docs/benchmarks/<date>.md`. Never fabricate; where a run is impossible, say so.
3. **Consolidate `BENCHMARKS.md`** at repo root summarising all runs with dates, hardware, and config.
- **Depends on:** Phases 1–4 (the things being compared must exist).
- **Exit criteria:** `BENCHMARKS.md` exists with at least one full comparison run per axis, all dated and reproducible from the scripts in the repo.

## Sequencing and versioning

| Order | Phase | Version | Gate |
|---|---|---|---|
| 0 | Audit | — (this set) | Files at repo root |
| 1 | VLM end-to-end | v0.4.0 | Real `llava:7b` caption observed + e2e test |
| 2 | Security hardening (H1, H5, H6 first) | v0.4.1 | `test_security.py` green; no High debt open |
| 3 | Infra hardening (H2, H3, pooling, CI services) | v0.5.0 | Clean-checkout compose up + migrations auto-run |
| 4 | Video intelligence + CV | v0.6.0 | Sampling + trajectory benchmarks recorded |
| 5 | RAG upgrade + eval dataset | v0.7.0 | `rag_eval.py` with 7 metrics, baseline vs new |
| 6 | Agent + MCP + events | v0.8.0 | 8 tools, multi-step workflow, MCP tests |
| 7 | Frontend + observability | v0.9.0 | 13-step Playwright green, `/metrics` live |
| 8 | Production + docs + GitHub | v1.0.0 | Public repo, release checklist, benchmarks |

Notes on ordering: security (Phase 9) is pulled forward to step 2 because H1 blocks publication; infra (Phase 7) is pulled forward to step 3 because H2 blocks any production claim. The master prompt's numeric phase order is preserved in the phase sections above; the table is the execution order. If Ollama is blocked (no GPU access, no model download), Phase 1 proceeds with plumbing + mock tests and is marked "code complete, model run pending" — the version does not advance past v0.4.0-rc until a real model run is observed.

## Final delivery checklist (v1.0.0)

- [ ] Complete source, frontend + backend, Docker deployment (one command)
- [ ] Genuine VLM integration (real model run observed, not mocked)
- [ ] Advanced multimodal retrieval (Qdrant read path, filters, reranking, eval dataset)
- [ ] Evidence-grounded RAG (citation validation, faithfulness measured)
- [ ] LangGraph agent (or a documented decision not to use it) + 8 tools + MCP
- [ ] Object detection/tracking with measured precision/recall + trajectories
- [ ] Event analytics (zones, dwell, loitering candidates, verified events)
- [ ] Secure auth (H1/H5/H6 closed, security tests green)
- [ ] Postgres + Qdrant + Redis/Celery verified (already done in v0.3.1; re-verify after refactors)
- [ ] Automated tests (unit/integration/e2e/vlm/security) + benchmarks
- [ ] Screenshots, architecture docs, professional README, public GitHub repo
- [ ] Final engineering report with five statuses per item: IMPLEMENTED / TESTED / VERIFIED / BENCHMARKED / DEPLOYED, and every incomplete item listed separately
