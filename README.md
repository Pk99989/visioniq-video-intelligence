# VisionIQ — Multimodal Video Intelligence and Agentic Search Platform

An independent implementation **inspired by** the architecture of NVIDIA's
Video Search and Summarization (VSS) blueprint (Apache-2.0, see
`docs/architecture/` for the attribution and what was *not* copied). No
NVIDIA source code is included here.

Upload a video, and VisionIQ extracts frames and scenes, captions them
with a real vision-language model, indexes them for semantic search,
answers questions with timestamp citations, summarises long videos
hierarchically, watches zones for events, and generates JSON/PDF
reports — through a deterministic agent and an MCP tool server.

**Current version: v0.14.0** (2026-11-06). Phases 0–12 of the upgrade
plan are done; see `PROJECT_STATE.md` for the full status and
`CHANGELOG.md` for what each version changed. Every number in this
file is measured — the method and the raw results live in
`docs/benchmarks/` and `TESTING.md`. Nothing here is a target or a
claim about hardware it has not run on.

## What it does

- **Ingest**: upload (mp4/mov/webm/mkv/avi, 500 MB cap, magic-byte
  checked) → ffprobe metadata → ffmpeg thumbnails/frames → OpenCV
  scene segmentation → adaptive sampling (0.2–2 fps) with histogram
  dedupe and scene merging → VLM captions → YOLOv8n detections with
  per-video tracking and trajectories → embeddings → Qdrant + DB.
- **Search**: Qdrant-first hybrid retrieval (0.6 cosine + 0.4 keyword
  + label/phrase boosts) with a DB-scan fallback when Qdrant is empty
  or unreachable. Filters: label, caption provider, time range.
- **RAG chat**: evidence-grounded answers with timestamp citations;
  below the 0.45 evidence floor the agent says "No video evidence"
  instead of guessing. Conversations persist, with follow-ups.
- **Agent**: 8 tools (`video_search`, `video_qa`, `video_summarize`,
  `detection_analytics`, `timeline_analysis`, `event_analysis`,
  `clip_retrieval`, `report_generation`) behind a deterministic
  multi-step planner — no LLM tool-calling loop (see
  `docs/adr/0001-agent-framework.md`). Exposed over REST and over MCP
  (stdio JSON-RPC + HTTP).
- **Events**: zones (enter/exit/dwell/loitering) evaluated over
  tracked detections, with evidence clips and optional VLM yes/no
  verification. Loitering is always reported as a candidate, never
  as verified.
- **Reports**: JSON/PDF summary, incident and timeline reports.
- **Frontend**: Next.js 14 + TypeScript + Tailwind, 16 routes
  (15 pages + not-found): dashboard, library, upload, processing,
  video player with seekable streaming, search with filters, chat,
  summaries, events, alerts, reports, settings, users. Chat history,
  SSE status stream with polling fallback, event timeline strip,
  trajectory toggle, clip download.

## Measured results (not targets)

| Area | Result | Where measured |
|---|---|---|
| Tests | 111 backend tests (105 unit / 3 integration / 2 vlm / 1 e2e); default run **108 passed, 1 skipped**; + 10 Vitest, + 1 Playwright e2e | `TESTING.md` |
| RAG eval, 54 questions, production config (Qdrant, no rerank, hash embeddings) | **R@1 0.37, R@5 0.66, MRR 0.48, faithfulness 1.0, relevance 0.95, negatives correct 0.38** | `docs/benchmarks/rag-eval-2026-11-06.md` |
| Detection vs hand-labelled boxes (IoU 0.5) | Bus image **P 0.80 / R 0.80**; traffic frame **P 0.67 / R 0.50**; **0 id switches** | `docs/benchmarks/2026-11-06-phase3.md` |
| Detection speed (CPU, this VM) | **219.8 ms/frame** warm; profiling a 120 s video: ONNX 54% of time @ 402 ms/frame, ffmpeg 25% | `docs/benchmarks/2026-11-06-phase10-profiling.md` |
| Adaptive sampling | Bus 10 s video: **3.0 s** processing (was 9.1 s), 5 frames (was 10) | `docs/benchmarks/2026-11-06-phase2.md` |
| Embeddings, 12 labelled pairs | FastEmbed (bge-small-en-v1.5) **R@1 1.00 / MRR 1.00** vs hash 0.67 / 0.76 | `docs/benchmarks/2026-11-05.md` |
| Real VLM end-to-end | moondream (CPU) captioned a real bus frame; search "bus" **0.865** | `docs/benchmarks/2026-11-06-vlm.md` |

Small test sets — the direction is the finding, not the exact number.
Run variance on the RAG eval is ±0.05 from non-deterministic VLM
captions.

## What is deliberately a fallback, not a claim

- **VLM captions**: `VLM_PROVIDER=fallback` (default) produces template
  captions from scene timing + detections, labelled `provider=fallback`.
  Real captions need `VLM_PROVIDER=ollama` (or an OpenAI-compatible
  endpoint) plus `VLM_BASE_URL` and a model. Verified with moondream on
  CPU; `llava:7b` is the configured model for the RTX 3050 and has
  **not yet run anywhere** — that step is still open.
- **Object detection**: YOLOv8n ONNX (`backend/yolov8n.onnx`, downloaded
  per machine with `scripts/download_yolo.py`). Without it, `/health`
  reports `available: false` and no boxes are invented. The
  Ultralytics `.pt` / ByteTrack path exists but is **untested**
  (torch install stalled on the dev VM). No face or identity
  recognition — out of scope.
- **Embeddings**: `EMBEDDING_PROVIDER=fastembed` is the real model
  (BAAI/bge-small-en-v1.5, 384-d); `hash` is the deterministic fallback
  used by the test suite. The 0.45 evidence floor is tuned for hash
  embeddings; per-provider calibration is an open follow-up.
- **Reranker**: off by default — it was within noise on the 54-question
  eval at 27× the latency.
- **Qdrant**: optional. Without `QDRANT_URL`, search runs against the
  database and still works. With it, search is Qdrant-first with a
  DB-scan fallback.
- **PostgreSQL/Redis**: SQLite is the laptop default; set `DATABASE_URL`
  for Postgres. Redis + Celery is the full-stack worker; the laptop
  profile processes in-process.

## Security (verified by tests, not by assertion)

- PyJWT with issuer/audience/expiry/jti enforced; pre-v0.11.0 tokens
  are invalid by design. Access tokens 60 min; rotating httpOnly
  refresh cookies (7 days) — replaying a revoked refresh token revokes
  the whole token family. Logout revokes access + refresh tokens.
- Rate limits (Redis, fails open): login 10/min per IP+email,
  register/reset 5/min per IP.
- Uploads: magic-byte sniffing before the file is written; optional
  `CLAMSCAN_CMD` hook. VLM base URL is validated at startup (SSRF
  guard). Cross-user access returns 404 on every video-scoped route
  (22 security tests, including a parametrised sweep of all of them).
- See `SECURITY.md` for the full list and the known gaps.

## Quickstart — laptop (recommended, Windows 11 + WSL2 Ubuntu 24.04)

```bash
cp .env.example .env   # set a real JWT_SECRET
docker compose -f docker-compose.laptop.yml up --build -d
docker compose -f docker-compose.laptop.yml ps   # both services healthy
curl localhost:8000/health
# frontend http://localhost:3000  ·  backend http://localhost:8000  ·  docs http://localhost:8000/docs
```

Full stack (Postgres + Qdrant + Redis/Celery): `docker compose up --build -d`
(see `DEPLOYMENT.md`). Without Docker: `bash scripts/run_dev.sh`
(requires ffmpeg + ffprobe on PATH, Python 3.12, Node 20).

**Note (2026-11-06):** the clean-checkout Docker start has been
verified for syntax (`docker compose config`) and the entrypoint has
been verified natively, but no container can run on the dev VM (its
kernel blocks Docker's networking), so the end-to-end Docker run is
still pending on a machine with Docker Desktop. See `RELEASE.md`.

## Smoke test

```bash
bash scripts/generate_sample_video.sh sample.mp4
# Register at http://localhost:3000/login, upload sample.mp4,
# then search "scene" and ask the chat "What is in this video?"
```

## Layout

```
visioniq/
  frontend/            Next.js 14, TypeScript, Tailwind
  backend/             FastAPI app (app/routers, app/services, app/models)
  mcp_server/          MCP stdio + HTTP tool server
  scripts/             sample video, YOLO download, dev runner, RAG eval, Docker pull helper
  docs/                architecture, ADRs, benchmarks, decisions
  observability/       Prometheus + Grafana compose stack and dashboard
```

## Docs

`ARCHITECTURE.md` · `PROJECT_STATE.md` · `TASK_TRACKER.md` ·
`DATABASE_SCHEMA.md` · `API_DOCUMENTATION.md` · `DEPLOYMENT.md` ·
`TESTING.md` · `SECURITY.md` · `TROUBLESHOOTING.md` · `CHANGELOG.md` ·
`RELEASE.md` · `docs/OBSERVABILITY.md`

## Licence

This project's own code is MIT (see `LICENSE`). NVIDIA's VSS blueprint
is Apache-2.0 and is referenced, not redistributed.
