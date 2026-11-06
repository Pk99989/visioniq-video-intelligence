# Architecture

## Reference and independence

Inspired by NVIDIA AI Blueprint for Video Search and Summarization (VSS):
GPU-accelerated reference architecture combining vision-language models
(VLMs such as Cosmos), LLMs (Nemotron), RAG, and NIM microservices for
video search, visual Q&A, alert verification, clip retrieval and long-video
summarization, with an MCP-based agent layer. Source:
https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization
(Apache-2.0, public, default branch `develop` at time of study).

VisionIQ re-implements that *shape* independently, at laptop scale:
no NVIDIA code, models, or assets are copied. Where NVIDIA's stack uses
DeepStream/NIM microservices on enterprise GPUs, VisionIQ uses ffmpeg +
OpenCV + a lazy YOLO adapter + an OpenAI-compatible VLM client, so it
runs on an RTX 3050 / 16 GB machine and falls back to CPU.

## System diagram (text)

```
User ──► Next.js frontend ──► FastAPI backend ──► SQLite / PostgreSQL
                                   │                    (16 tables: users, videos,
                                   ├─► ffmpeg/ffprobe    scenes, frames, captions,
                                   ├─► OpenCV scenes     detections, events, zones,
                                   ├─► YOLO adapter      alerts, conversations,
                                   │      (ONNX, lazy)    messages, reports,
                                   ├─► VLM provider ──►  revoked/refresh/reset
                                   │      (Ollama / OpenAI-  tokens)
                                   │       compatible / fallback)
                                   ├─► embeddings ──► fastembed bge-small-en-v1.5
                                   │      (384-d; hash is the deterministic fallback)
                                   ├─► vector store ──► Qdrant-first (payload-filtered,
                                   │      DB-scan fallback) / DB JSON
                                   ├─► agent tools ──► MCP server (stdio + HTTP)
                                   └─► observability ──► JSON logs (request_id/job_id),
                                          /metrics (Prometheus), Grafana stack
```

## Request flows

1. **Ingest**: upload (validated, size-capped, magic-byte checked) →
   `ProcessingJob(queued)` → background pipeline (Celery worker in the
   full stack, in-process on the laptop profile) → metadata, thumbnail,
   frames (adaptive fps + histogram dedupe + scene merge), scenes,
   VLM captions, YOLO detections with per-video tracking, embeddings,
   Qdrant upsert → status `ready`/`failed`. Stuck jobs are recovered
   on restart; explicit retry exists.
2. **Search**: query → fastembed (or hash fallback) embedding +
   keyword overlap + label/phrase boosts → Qdrant-first retrieval
   with payload filter (owner_id is the privacy boundary), DB-scan
   fallback when Qdrant is empty, drifted or unreachable → dedupe
   (same video/caption within 2 s) → citation validation against
   stored frames → top-K frames with timestamps.
3. **RAG chat**: intent routing (summarise/events/clips/QA) → retrieval
   (min score 0.45 for QA) → template or LLM synthesis from retrieved
   captions only → answer + citations stored in conversations/messages.
   Follow-ups carry the last 6 turns.
4. **Events**: user zones (enter/exit/dwell 5 s/loitering 30 s, the
   last always a candidate, never verified) evaluated over tracked
   detections, plus caption rules → duplicate suppression (30 s
   bucket) → Event + Alert rows with evidence clips. Events are
   verified only on high-confidence detection (≥0.80) or a real VLM
   yes/no check.
5. **Reports**: summary + timeline + events → JSON or PDF (reportlab).

## Hardware optimisation (RTX 3050 / 16 GB)

- 1 fps sampling, 120-frame cap (`FRAME_FPS`, `MAX_FRAMES`); adaptive
  sampling (0.2–2 fps) with dedupe keeps short videos fast.
- One video at a time per worker (`WORKER_CONCURRENCY=1`).
- Lazy model loading: YOLO and FastEmbed load only on use.
- Docker resource limits (2 CPU / 4 GB) in both compose files; images
  run as non-root users (backend `visioniq`, frontend `node`).
- Temporary files live under `storage/` per video and are deleted with
  the video (secure deletion).

## Decisions

See `docs/decisions/` — notably `001-laptop-first.md` (SQLite + hash
embeddings + fallback VLM as defaults, with swap-in points for real
models) and `002-no-invented-evidence.md` (fallbacks are labelled, never
presented as model output).
