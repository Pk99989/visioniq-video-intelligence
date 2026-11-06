# BENCHMARKS

Every measured number in VisionIQ, in one place, with the method,
the machine, and the date. Nothing in this file is a target. If a
number here disagrees with a per-phase note in `docs/benchmarks/`,
this file is the summary and the dated note is the raw record.

**Machine for all measurements below:** the dev VM — Linux, CPU
only, ~7.9 GB RAM, no GPU, no Docker. GPU numbers (RTX 3050) do not
exist yet; the laptop is the machine that will produce them.

**Reproduced for v1.0.0 (2026-11-06):** the embedding benchmark,
the detection benchmark and the Phase 2 sampling benchmark were
re-run on the v1.0.0 code and reproduced the baselines (see the
"v1.0.0" rows). The VLM e2e and the RAG eval test were re-run too —
see their rows below.

## 1. Embeddings — 12 labelled caption pairs

Method: `scripts/benchmark.py`. 12 queries, each with one
known-correct caption, 6 captions in the pool. Small test set — the
direction is the finding, not a production Recall@K claim.

| Provider | Recall@1 | Recall@5 | MRR | Mean search |
|---|---|---|---|---|
| hash (default) — 2026-11-05 | 0.67 | 0.92 | 0.76 | 0.4 ms |
| fastembed bge-small-en-v1.5 — 2026-11-05 | 1.00 | 1.00 | 1.00 | 9.4 ms |
| hash — **v1.0.0, 2026-11-06** | **0.67** | **0.92** | **0.76** | 0.5 ms |

## 2. Detection — hand-labelled ground truth, IoU ≥ 0.5

Method: `scripts/benchmark.py` (`GROUND_TRUTH` — boxes estimated
by viewing the images, normalised 0..1). YOLOv8n ONNX,
CPUExecutionProvider.

| Image | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| bus.jpg (810×1080) — 2026-11-06 | 0.80 | 0.80 | 4 | 1 | 1 |
| traffic frame (1280×720) — 2026-11-06 | 0.67 | 0.50 | 2 | 1 | 2 |
| bus.jpg — **v1.0.0, 2026-11-06** | **0.80** | **0.80** | 4 | 1 | 1 |
| traffic frame — **v1.0.0, 2026-11-06** | **0.67** | **0.50** | 2 | 1 | 2 |

Tracking: **0 id switches** on both videos; 16 tracks on the moving
video, dwell up to 7.5 s. Detection speed: **219.8 ms/frame** warm
CPU (Phase 3); a cold first frame measured 976.5 ms in the v1.0.0
re-run (includes model load). No face/identity recognition — out
of scope.

## 3. Adaptive sampling (Phase 2)

Method: `scripts/phase2_bench.py` — upload each sample video
through the real API (`SYNC_PROCESSING=1`), count stored
frames/scenes/detections, time the whole request. Baseline is the
v0.3.1 live run (1 fps, no dedupe).

| Video | Baseline | Phase 2 (2026-11-06) | **v1.0.0** |
|---|---|---|---|
| bus, 10 s | 9.1 s, 10 frames, 50 detections | 3.0 s, 5 frames, 25 detections | **2.6 s, 5 frames, 25 detections** |
| moving traffic, 15 s | 61 detections at 1 fps | 11.6 s, 27/30 frames, 106 detections | **10.4 s, 27 frames, 106 detections** |

Both videos segment to 1 scene (SCENE_THRESHOLD 30.0; the traffic
video has no hard cuts — known limitation).

## 4. Real VLM end-to-end (Phase 1)

Method: `scripts/vlm_e2e.py` / `tests/test_vlm_e2e.py` — upload the
10 s bus video through the real API, read the stored caption.
Model: **moondream** (1.86B params, Q4_0, 1.7 GB) via Ollama
0.40.15, CPU-only. `llava:7b` is the configured model for the
user's RTX 3050 and has **not run anywhere yet**.

| Run | Result |
|---|---|
| 2026-11-06 | Upload → ready in 17.5 s; caption provider=`ollama`, model=`moondream`, genuine description; search "bus" → **0.865** |
| v0.11.0 re-verification (replaced VM) | `tests/test_vlm_e2e.py` passed in 71.26 s |
| **v1.0.0** | `tests/test_vlm_e2e.py` **passed** (with `tests/test_rag_eval.py`, 2 passed in 4m38s) |

Structured-JSON compliance is model-dependent: moondream returned
JSON once and prose once. The caption pipeline accepts both (prose
becomes the description, provider stays `ollama`).

## 5. RAG evaluation — 54 questions

Method: `scripts/rag_eval.py` (full 4-config comparison) and
`tests/test_rag_eval.py` (the production config as a regression
test). Dataset: `backend/tests/data/rag_eval.jsonl` — 54 questions
(41 positive, 13 negative) over the three sample videos. Correct
hit = right video and timestamp within ±2 s. Corpus captions by
moondream via Ollama. Run-to-run variance ±0.05 from
non-deterministic VLM captions; differences below that are noise.

### Hash embeddings (default)

| Metric | A: DB scan | B: DB + rerank | C: Qdrant (production) | D: Qdrant + rerank |
|---|---|---|---|---|
| recall_at_1 | 0.32 | 0.37 | 0.32 | 0.37 |
| recall_at_5 | 0.66 | 0.66 | 0.66 | 0.66 |
| precision_at_5 | 0.16 | 0.16 | 0.16 | 0.16 |
| mrr | 0.47 | 0.50 | 0.47 | 0.50 |
| mean_latency_ms | 7.1 | 190.1 | 11.0 | 202.0 |
| faithfulness | 1.0 | 1.0 | 1.0 | 1.0 |
| relevance_positives | 0.95 | 0.95 | 0.95 | 0.95 |
| negatives_correct | 0.38 | 0.38 | 0.38 | 0.38 |

### FastEmbed embeddings (bge-small-en-v1.5)

| Metric | A: DB scan | B: DB + rerank | C: Qdrant | D: Qdrant + rerank |
|---|---|---|---|---|
| recall_at_1 | 0.27 | 0.32 | 0.27 | 0.32 |
| recall_at_5 | 0.66 | 0.66 | 0.66 | 0.66 |
| precision_at_5 | 0.16 | 0.16 | 0.16 | 0.16 |
| mrr | 0.45 | 0.47 | 0.45 | 0.47 |
| mean_latency_ms | 35.8 | 422.7 | 68.2 | 424.5 |
| faithfulness | 1.0 | 1.0 | 1.0 | 1.0 |
| relevance_positives | 0.95 | 0.95 | 0.95 | 0.95 |
| negatives_correct | 0.15 | 0.15 | 0.15 | 0.15 |

### v1.0.0 re-run (production config C, hash, 2026-11-06)

| Metric | Value |
|---|---|
| recall_at_1 / recall_at_5 / precision_at_5 | **0.32 / 0.66 / 0.16** |
| mrr / mean_latency_ms | **0.47 / 203.2 ms** |
| faithfulness / relevance_positives / negatives_correct | **1.0 / 0.95 / 0.38** |

R@1 0.32 (vs 0.37 in Phase 11) and MRR 0.47 (vs 0.48) are within
the documented ±0.05 run variance from non-deterministic moondream
captions; R@5, faithfulness, relevance and negatives are identical
to the baseline. The regression test's thresholds (R@5 ≥ 0.60,
MRR ≥ 0.40, faithfulness ≥ 0.90, relevance ≥ 0.85, negatives ≥ 0.30)
all held.

### What the numbers mean

- **Qdrant is a faithful accelerator:** A and C are identical on
  both embedding runs. An earlier candidate-pool bug (Qdrant
  pre-selecting by weak vectors) is fixed by fetching 100 candidates
  before hybrid scoring.
- **The reranker does not earn its latency here:** on hash it is
  within run-to-run noise; on FastEmbed it slightly helps
  (R@1 0.27→0.32) at 6–12× latency. It stays off by default
  (`RERANKER_MODEL` empty).
- **The agent's 0.45 evidence floor is tuned for hash embeddings.**
  With FastEmbed, unrelated text scores higher, so false evidence
  gets through and negatives correct falls 0.38→0.15. The floor
  needs per-provider calibration — open follow-up, deliberately not
  tuned to this 54-question set.
- **Precision@5 0.16 is a metric artefact of single-scene videos:**
  every frame in the moving-traffic video shares one caption, so the
  top 5 are near-duplicate frames and the ±2 s correctness window
  only credits ~1 of them. Recall@5 is the meaningful number here.
- Latency: hash search ~7 ms, FastEmbed ~36–68 ms, rerank adds
  ~190–420 ms per query on this CPU. (The v1.0.0 re-run's 170.6 ms
  includes VLM answer synthesis for the positive questions, not
  just retrieval.)

Definitions: faithfulness = share of answers whose citations all
resolve to real stored frames. Relevance (positives) = share of
answers containing an expected keyword. Negatives correct = share
of negative questions refused with no evidence.

## 6. Profiling — 120 s video (Phase 10, 2026-11-06)

Method: `scripts/profile_processing.py` — 120 s loop of the moving
traffic video (1280×720, 77 MB), CPU-only, `cProfile`. Processed
to `ready` in 84.1 s under the profiler (cProfile adds overhead;
the proportions are the point, not the absolute time).

| Hotspot | Share |
|---|---|
| ONNX inference (402 ms/frame) | **54%** |
| ffmpeg subprocess waits (real decode work) | 25% |
| numpy NMS argmax | 8% |

No code change came from profiling: ONNX speed is a hardware
lever (GPU on the RTX 3050), not a code bug.

## 7. What is NOT measured yet

- **GPU numbers**: detection latency, VLM caption latency, and
  end-to-end processing time on the RTX 3050 — pending the user's
  machine.
- **Latency p50/p95 per endpoint** and peak RSS during a 10-minute
  ingest — proposed method in `TESTING.md`, not yet run.
- **Summary factual consistency** and **alert false-positive rate**
  — methods defined in `TESTING.md`, not yet measured.
- **Live Docker timings** — no container can run on this VM.
- **Sentence-transformers embeddings** and the **ultralytics .pt /
  ByteTrack** path — untested (torch install stalled on this VM).
