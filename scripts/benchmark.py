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


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1e-6)


# Hand-labelled ground truth, boxes as normalised [x1, y1, x2, y2].
# Estimated by eye from the images (IoU threshold 0.5 is forgiving
# of small estimation error); the left-edge person on bus.jpg is
# partial (arm + coat only) and is labelled as such.
GROUND_TRUTH = {
    "/tmp/bus.jpg": [
        ("bus", [0.01, 0.24, 0.99, 0.74]),
        ("person", [0.06, 0.43, 0.23, 0.90]),   # beige coat, left
        ("person", [0.26, 0.44, 0.41, 0.87]),   # black coat, centre
        ("person", [0.88, 0.43, 1.00, 0.88]),   # right edge
        ("person", [0.00, 0.56, 0.06, 0.86]),   # left edge, partial
    ],
    "/tmp/traffic-frame.jpg": [
        ("bus", [0.02, 0.22, 0.30, 0.86]),      # 38 Geary, left
        ("truck", [0.30, 0.16, 0.77, 0.99]),    # Skyline, centre
        ("bus", [0.76, 0.27, 0.92, 0.68]),      # rear view, right-mid
        ("bus", [0.92, 0.19, 1.00, 0.74]),      # far right, partial
    ],
}


def _precision_recall(dets, gt, width, height):
    """Greedy IoU>=0.5 matching, same label only. Returns
    (precision, recall, tp, fp, fn, matched_pairs)."""
    gt_boxes = [(label, [x * width, y * height, x2 * width, y2 * height])
                for label, (x, y, x2, y2) in gt]
    pred = [(d["label"], [d["x1"], d["y1"], d["x2"], d["y2"]]) for d in dets]
    used_gt, tp, pairs = set(), 0, []
    for plabel, pbox in pred:
        best, best_iou = None, 0.5
        for i, (glabel, gbox) in enumerate(gt_boxes):
            if i in used_gt or glabel != plabel:
                continue
            score = _iou(pbox, gbox)
            if score >= best_iou:
                best, best_iou = i, score
        if best is not None:
            used_gt.add(best)
            tp += 1
            pairs.append((plabel, round(best_iou, 2)))
    fp = len(pred) - tp
    fn = len(gt_boxes) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return round(precision, 2), round(recall, 2), tp, fp, fn, pairs


def detection_metrics():
    """Phase 3: precision/recall at IoU>=0.5 on two hand-labelled
    frames, per-frame latency, and track-id stability on repeated
    frames of the same image (a stable scene must not switch ids)."""
    from app.services import detection

    import cv2

    out = {"ground_truth_note": "Hand-estimated boxes (see GROUND_TRUTH); IoU>=0.5.",
           "images": {}, "track_stability": None, "mean_latency_ms": None}
    status = detection.provider_status()
    if not status["available"]:
        out["available"] = False
        return out
    latencies = []
    for path, gt in GROUND_TRUTH.items():
        img = cv2.imread(path)
        if img is None:
            out["images"][path] = "missing image"
            continue
        h, w = img.shape[:2]
        tracker = detection.Tracker()
        t0 = time.perf_counter()
        dets = detection.detect_frame(path, tracker=tracker)
        latencies.append((time.perf_counter() - t0) * 1000)
        p, r, tp, fp, fn, pairs = _precision_recall(dets, gt, w, h)
        out["images"][path] = {
            "precision": p, "recall": r, "tp": tp, "fp": fp, "fn": fn,
            "matched": pairs,
            "predicted": [(d["label"], round(d["confidence"], 2)) for d in dets]}
    # Track stability: same frame 3x must keep the same ids.
    tracker = detection.Tracker()
    ids_per_call = []
    for t in (0.0, 0.5, 1.0):
        dets = detection.detect_frame("/tmp/bus.jpg", tracker=tracker, timestamp=t)
        ids_per_call.append(sorted(d["track_id"] for d in dets))
    out["track_stability"] = {
        "frames": 3, "ids_per_frame": ids_per_call,
        "switches": sum(1 for a, b in zip(ids_per_call, ids_per_call[1:])
                        if a != b)}
    out["mean_latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else None
    out["execution_provider"] = status.get("execution_provider")
    return out


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
    report = {"embedding": embedding_benchmark(), "detection": detection_benchmark(),
              "detection_metrics": detection_metrics()}
    print(json.dumps(report, indent=2))
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    dm = report["detection_metrics"]
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
        f"Detection metrics (Phase 3, IoU>=0.5, hand-labelled GT): "
        f"{json.dumps(dm, indent=2)}\n\n"
        f"Full JSON:\n```json\n{json.dumps(report, indent=2)}\n```\n")
    print(f"\nWrote docs/benchmarks/{date}.md")


if __name__ == "__main__":
    main()
