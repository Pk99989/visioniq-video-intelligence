# TESTING

## What is run and verified (2026-11-04)

- Backend: `cd backend && SYNC_PROCESSING=1 DATABASE_URL="sqlite:////tmp/visioniq_test.db" STORAGE_DIR="/tmp/visioniq_test_storage" JWT_SECRET="test-secret" .venv/bin/python -m pytest tests/ -q`
  → **2 passed** (full flow + upload validation). The full-flow test uses
  a real ffmpeg test video, not a mocked pipeline.
- Frontend: `cd frontend && npm run build` → **passes, 16 pages**.
- CI: `.github/workflows/ci.yml` runs both on every push/PR.

## Benchmarks — not yet measured, do not quote numbers

The master prompt lists Recall@K, Precision@K, RAG faithfulness,
detection precision/recall, tracking quality, summary consistency,
alert false-positive rate, latency and memory. **None of these are
measured in v0.1.0**, and no such numbers appear in this repo. They
require (a) a real embedding model and VLM, (b) a labelled test set
with ground-truth timestamps, and (c) a YOLO model with weights.
Proposed method when those exist:

1. Build a small labelled set: 5–10 short videos, each with 5 known
   moments (query → expected timestamp ±2 s) and 3 known objects.
2. Search: Recall@5/Precision@5 = fraction of expected moments in the
   top 5 / fraction of top 5 that are correct.
3. RAG: faithfulness = fraction of answer claims traceable to a cited
   timestamp; report the no-evidence rate separately.
4. Detection: precision/recall against hand-labelled boxes at IoU ≥ 0.5.
5. Summaries: factual consistency = claims in the summary that appear
   in a scene caption, checked manually for the first release.
6. Alerts: false-positive rate = alerts fired / alerts evaluated on
   videos known to contain no event, per rule.
7. Report latency (p50/p95 per endpoint) and peak RSS during a
   10-minute video ingest, on the RTX 3050 laptop.

Until then, the only performance claims in this repo are the ones in
PROJECT_STATE.md (tests passed, build passed).

## Phase 2 results (2026-11-05, this machine, CPU only)

- `pytest backend/tests/ -q` → **7 passed** (Phase 1 full flow + Phase 2:
  VLM mock server, Qdrant in-memory, Celery eager, detection-unavailable,
  hash determinism).
- Benchmark (`scripts/benchmark.py`, 12 labelled queries):
  hash Recall@1 0.67 / MRR 0.76; fastembed Recall@1 1.00 / MRR 1.00.
- Detection: bus.jpg — 4 persons + 1 bus, confidence 0.88–0.90,
  456–880 ms/frame; bus video upload → ready, 15 detections in DB.
- Alembic: upgrade head / downgrade base / upgrade head on SQLite — 13 tables
  incl. alembic_version.
