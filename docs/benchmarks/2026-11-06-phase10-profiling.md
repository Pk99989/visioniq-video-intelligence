# Profiling — 2-minute video (Phase 10, 2026-11-06)

Method: `scripts/profile_processing.py` on a 120 s loop of the moving
traffic video (1280x720, 77 MB), CPU-only VM, `cProfile`. The video
processed to `ready`. Total wall time under the profiler: **84.1 s**
(cProfile adds overhead; the same video without the profiler runs
faster — the proportions below are the point, not the absolute time).

Adaptive sampling already caps the work: 120 s → 120 frames extracted,
8 deduped, 112 kept (1 fps, MAX_FRAMES=120).

## Hotspots (by own time)

| # | Where | Time | Share | Notes |
|---|-------|------|-------|-------|
| 1 | ONNX YOLO inference (`onnxruntime run`, 112 calls, 402 ms/frame) | 45.0 s | 54% | The model itself on CPU. No code fix: the lever is GPU (the user's RTX 3050) or a smaller model. |
| 2 | ffmpeg subprocess waits (`subprocess._wait`, 290 calls) | 20.8 s | 25% | Video decoding + frame extraction (probe, thumbnail, extract). Real work, not idle sleep. |
| 3 | NMS post-processing (numpy `argmax`, 940,800 calls) | 6.4 s cum. | 8% | Per-box argmax in the ONNX output decoding. Minor; a vectorised NMS would help a little, not attempted — the win is <10%. |
| 4 | Everything else (imread, resize, DB, embeddings, Qdrant) | ~12 s | 14% | No single hotspot. |

## Conclusion

No code change from this profile. The dominant cost is model
inference on CPU, which is a hardware lever (GPU), not a code
hotspot. The search-scan hotspot the plan anticipated is not in this
path — search is measured separately by the RAG eval (Phase 4) and
the Qdrant latency histogram (`visioniq_qdrant_search_seconds`).
The profile script is kept at `scripts/profile_processing.py` for
re-runs on the GPU machine.
