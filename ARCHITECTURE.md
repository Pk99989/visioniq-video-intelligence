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
                                   │                    (users, videos, scenes,
                                   ├─► ffmpeg/ffprobe    frames, captions, detections,
                                   ├─► OpenCV scenes     events, alerts, conversations,
                                   ├─► YOLO adapter      messages, reports)
                                   │      (lazy, optional)
                                   ├─► VLM provider ──► fallback template
                                   │      (OpenAI-compatible / NIM / Ollama)
                                   ├─► embeddings ──► hash (default) / sentence-transformers
                                   ├─► vector store ──► DB JSON (default) / Qdrant (optional)
                                   └─► agent tools ──► MCP server (stdio + HTTP)
```

## Request flows

1. **Ingest**: upload (validated, size-capped) → `ProcessingJob(queued)` →
   background pipeline → metadata, thumbnail, frames, scenes, captions,
   embeddings, detections (if YOLO present) → status `ready`/`failed`.
2. **Search**: query → hash/sentence embedding + keyword overlap →
   combined score, reranked, top-K → frames with timestamps.
3. **RAG chat**: intent routing (summarise/events/clips/QA) → retrieval
   (min score 0.45 for QA) → template or LLM synthesis from retrieved
   captions only → answer + citations stored in conversations/messages.
4. **Events**: user rules → evaluation over scenes/captions/detections →
   duplicate suppression (30 s bucket) → Event + Alert rows.
   Verified only on high-confidence detection (≥0.80) or a real VLM check.
5. **Reports**: summary + timeline + events → JSON or PDF (reportlab).

## Hardware optimisation (RTX 3050 / 16 GB)

- 1 fps sampling, 120-frame cap (`FRAME_FPS`, `MAX_FRAMES`).
- One video at a time per worker (`WORKER_CONCURRENCY=1`).
- Lazy model loading: YOLO and sentence-transformers load only on use.
- Docker resource limits (2 CPU / 4 GB) in both compose files.
- Temporary files live under `storage/` per video and are deleted with
  the video (secure deletion).

## Decisions

See `docs/decisions/` — notably `001-laptop-first.md` (SQLite + hash
embeddings + fallback VLM as defaults, with swap-in points for real
models) and `002-no-invented-evidence.md` (fallbacks are labelled, never
presented as model output).
