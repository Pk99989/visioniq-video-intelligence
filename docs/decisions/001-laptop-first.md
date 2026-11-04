# ADR 001 — Laptop-first defaults, with swap-in points

**Context**: target hardware is RTX 3050 / 16 GB; NVIDIA's validated VSS
deployment needs enterprise GPUs.

**Decision**: defaults are SQLite, in-process worker, 1 fps / 120 frames,
hash embeddings, fallback VLM captions, no YOLO unless weights exist.
Every default has a documented swap-in: `DATABASE_URL` → Postgres,
`QDRANT_URL` → Qdrant, `EMBEDDING_PROVIDER` → sentence-transformers,
`VLM_PROVIDER` → OpenAI-compatible/NIM/Ollama, `backend/yolov8n.pt` →
YOLO detection + ByteTrack.

**Consequence**: the platform runs end-to-end on a laptop today, and
each swap-in is a config change + a benchmark run, not a rewrite.
