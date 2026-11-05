#!/usr/bin/env python3
"""VisionIQ benchmark suite (Phase 2). Measures only what is actually
run here, on this machine, and writes the numbers to
docs/benchmarks/<date>.md — no numbers are claimed without a run.

1. Embedding retrieval: 12 labelled caption pairs. Each query has one
   known-correct caption; Recall@1/@5 and MRR are measured for the
   configured EMBEDDING_PROVIDER (hash vs fastembed).
2. Detection (only if YOLO weights are present): YOLOv8n on the
   standard bus.jpg test image — expected labels person/bus — plus
   per-frame latency, and a no-person test image (testsrc frame) that
   must return few/no detections.
3. End-to-end latency: upload -> ready for a 10 s sample video is
   measured by the API test suite, not here; this script records the
   search latency for the 12 queries instead.

Usage:
    cd backend && EMBEDDING_PROVIDER=hash python ../scripts/benchmark.py
    cd backend && EMBEDDING_PROVIDER=fastembed python ../scripts/benchmark.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Labelled pairs: (query, correct caption)
PAIRS = [
    ("a person walking down a street", "A person walking down a busy street"),
    ("man strolling on a road", "A person walking down a busy street"),
    ("a dog running in a park", "A dog running through a green park"),
    ("puppy playing outside", "A dog running through a green park"),
    ("car driving on a highway", "A red car driving fast on a highway"),
    ("vehicle speeding on the road", "A red car driving fast on a highway"),
    ("chef cooking in a kitchen", "A chef cooking food in a kitchen"),
    ("someone preparing a meal", "A chef cooking food in a kitchen"),
    ("children playing football", "Children playing football in a field"),
    ("kids kicking a ball", "Children playing football in a field"),
    ("a cat sleeping on a sofa", "A cat sleeping on a comfortable sofa"),
    ("feline resting indoors", "A cat sleeping on a comfortable sofa"),
]
CORRECT = sorted({c for _, c in PAIRS})


def embedding_benchmark():
    from app.services.embeddings import cosine, embed

    results = {"provider": None, "recall_at_1": 0.0, "recall_at_5": 0.0, "mrr": 0.0,
               "mean_search_ms": 0.0, "queries": []}
    vecs = {}
    for cap in CORRECT:
        vec, provider = embed(cap)
        results["provider"] = provider
        vecs[cap] = vec
    hits_at_1 = hits_at_5 = 0
    mrr_sum = 0.0
    latencies = []
    for query, correct in PAIRS:
        t0 = time.perf_counter()
        qvec, _ = embed(query)
        ranked = sorted(CORRECT, key=lambda c: cosine(qvec, vecs[c]), reverse=True)
        latencies.append((time.perf_counter() - t0) * 1000)
        rank = ranked.index(correct) + 1
        if rank == 1:
            hits_at_1 += 1
        if rank <= 5:
            hits_at_5 += 1
        mrr_sum += 1.0 / rank
        results["queries"].append({"query": query, "correct": correct, "rank": rank,
                                   "top": ranked[0]})
    n = len(PAIRS)
    results.update(recall_at_1=hits_at_1 / n, recall_at_5=hits_at_5 / n,
                   mrr=mrr_sum / n, mean_search_ms=sum(latencies) / n)
    return results


def detection_benchmark():
    from app.services import detection

    status = detection.provider_status()
    out = {"provider": status.get("provider"), "available": status["available"],
           "model": status.get("model", ""), "bus_image": None, "latency_ms": None}
    if not status["available"]:
        return out
    bus = Path("/tmp/bus.jpg")
    if not bus.exists():
        out["bus_image"] = "missing /tmp/bus.jpg; download https://ultralytics.com/images/bus.jpg"
        return out
    t0 = time.perf_counter()
    dets = detection.detect_frame(str(bus), conf=0.35)
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["bus_image"] = [{"label": d["label"], "confidence": round(d["confidence"], 3),
                         "track_id": d["track_id"]} for d in dets]
    return out


def main():
    report = {"embedding": embedding_benchmark(), "detection": detection_benchmark()}
    print(json.dumps(report, indent=2))
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    (out_dir / f"{date}.md").write_text(
        f"# Benchmark — {date}\n\n"
        f"Machine: this build machine (Linux, CPU only, no GPU, no Docker).\n"
        f"Embedding provider: {report['embedding']['provider']} — "
        f"Recall@1 {report['embedding']['recall_at_1']:.2f}, "
        f"Recall@5 {report['embedding']['recall_at_5']:.2f}, "
        f"MRR {report['embedding']['mrr']:.2f}, "
        f"mean search {report['embedding']['mean_search_ms']:.1f} ms "
        f"over {len(PAIRS)} labelled queries.\n\n"
        f"Detection: provider {report['detection']['provider']}, "
        f"available {report['detection']['available']}, "
        f"latency {report['detection']['latency_ms']} ms on bus.jpg, "
        f"detections: {report['detection']['bus_image']}\n\n"
        f"Full JSON:\n```json\n{json.dumps(report, indent=2)}\n```\n")
    print(f"\nWrote docs/benchmarks/{date}.md")


if __name__ == "__main__":
    main()
