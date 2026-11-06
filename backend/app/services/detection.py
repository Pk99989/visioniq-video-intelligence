"""Object detection adapter (YOLO-compatible) + tracking.

Two real backends, in priority order:

1. ``yolo-onnx`` — ``yolov8n.onnx`` + onnxruntime. No torch, ~12 MB
   weights, CPU-friendly. This is the laptop default for Phase 2.
   Run ``scripts/download_yolo.py`` to fetch the weights.
2. ``yolo`` (ultralytics) — ``yolov8n.pt`` + ultralytics, with its
   built-in ByteTracker (``model.track(persist=True)``).

If neither backend is available, ``detect()`` honestly returns no
detections with provider="unavailable" instead of inventing boxes.
The ONNX path uses a small greedy IoU tracker (same label, IoU > 0.3)
so track_ids are stable across consecutive frames in one video;
call ``reset_tracker()`` at the start of a new video.
"""
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
# (detection.py lives in backend/app/services/ — parent.parent is
# backend/app, NOT backend. The old parent.parent made YOLO weights
# findable only when the process cwd happened to be backend/.)

COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]

_onnx_session = None
_onnx_provider = None
_ultralytics_model = None


class Tracker:
    """Per-video greedy IoU tracker (Phase 3).

    One Tracker instance lives for one video — no module-global state,
    so two videos processed in parallel cannot steal each other's
    track ids (the old global tracker could). A track survives while
    it is re-seen with IoU >= min_iou and the same label; it retires
    when it goes unseen for more than max_missed consecutive frames,
    or when its age exceeds max_age_seconds. Retired tracks are kept
    in `finished` so trajectories (birth/death, dwell, path) can be
    built after processing.
    """

    def __init__(self, min_iou=None, max_missed=None, max_age_seconds=None):
        from ..config import settings

        self.min_iou = settings.YOLO_MIN_TRACK_IOU if min_iou is None else min_iou
        self.max_missed = settings.YOLO_TRACK_MAX_MISSED if max_missed is None else max_missed
        self.max_age_seconds = (settings.YOLO_TRACK_MAX_AGE_SECONDS
                                if max_age_seconds is None else max_age_seconds)
        self._next_id = 1
        self._active: dict[int, dict] = {}
        self.finished: list[dict] = []

    def update(self, detections: list[dict], timestamp: float | None = None) -> list[dict]:
        ts = float(timestamp) if timestamp is not None else 0.0
        used: set[int] = set()
        for d in detections:
            best, best_iou = None, self.min_iou
            for tid, track in self._active.items():
                if tid in used or track["label"] != d["label"]:
                    continue
                score = _iou(d, track["box"])
                if score > best_iou:
                    best, best_iou = tid, score
            if best is not None:
                d["track_id"] = best
                used.add(best)
                track = self._active[best]
                track["box"] = d
                track["missed"] = 0
                track["last_seen"] = ts
                track["positions"].append(_centre(d, ts))
                # Max-age retirement applies even to a track seen this
                # frame: a track must not live forever. The current
                # detection starts a fresh track instead.
                if timestamp is not None and ts - track["first_seen"] > self.max_age_seconds:
                    track["reason"] = "aged"
                    self.finished.append(track)
                    del self._active[best]
                    used.discard(best)
                    d["track_id"] = self._next_id
                    self._next_id += 1
                    self._active[d["track_id"]] = {
                        "track_id": d["track_id"], "label": d["label"],
                        "box": d, "missed": 0, "first_seen": ts, "last_seen": ts,
                        "positions": [_centre(d, ts)],
                    }
            else:
                d["track_id"] = self._next_id
                self._next_id += 1
                self._active[d["track_id"]] = {
                    "track_id": d["track_id"], "label": d["label"],
                    "box": d, "missed": 0, "first_seen": ts, "last_seen": ts,
                    "positions": [_centre(d, ts)],
                }
        # Age / miss expiry for tracks not seen this frame.
        for tid in list(self._active):
            if tid in used:
                continue
            track = self._active[tid]
            track["missed"] += 1
            age = ts - track["first_seen"] if timestamp is not None else 0.0
            if track["missed"] > self.max_missed or (timestamp is not None
                                                      and age > self.max_age_seconds):
                track["reason"] = "missed" if track["missed"] > self.max_missed else "aged"
                self.finished.append(track)
                del self._active[tid]
        return detections

    def trajectories(self) -> list[dict]:
        """All tracks (active + finished) as trajectory summaries."""
        out = []
        for track in list(self._active.values()) + self.finished:
            out.append(_trajectory_summary(track))
        return sorted(out, key=lambda t: t["first_seen_seconds"])


def _centre(d: dict, ts: float) -> dict:
    return {"t": ts, "x": (d["x1"] + d["x2"]) / 2, "y": (d["y1"] + d["y2"]) / 2,
            "w": d["x2"] - d["x1"], "h": d["y2"] - d["y1"]}


def _trajectory_summary(track: dict) -> dict:
    positions = track["positions"]
    first = positions[0]["t"]
    last = positions[-1]["t"]
    displacement = 0.0
    for a, b in zip(positions, positions[1:]):
        displacement += ((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5
    return {
        "track_id": track["track_id"], "label": track["label"],
        "first_seen_seconds": first, "last_seen_seconds": last,
        "dwell_seconds": round(last - first, 3),
        "frames_seen": len(positions),
        "displacement_px": round(displacement, 1),
        "path": positions,
    }


def build_trajectories(detections: list[dict]) -> list[dict]:
    """Build trajectory summaries from stored Detection rows (dicts with
    track_id, label, timestamp_seconds, x1..y2). Same shape as
    Tracker.trajectories(), so the API can serve it from the DB."""
    by_track: dict[int, dict] = {}
    for d in sorted(detections, key=lambda r: r["timestamp_seconds"]):
        tid = d.get("track_id")
        if tid is None:
            continue
        track = by_track.setdefault(tid, {
            "track_id": tid, "label": d["label"], "box": d,
            "first_seen": d["timestamp_seconds"], "last_seen": d["timestamp_seconds"],
            "positions": []})
        track["last_seen"] = d["timestamp_seconds"]
        track["positions"].append(_centre(d, d["timestamp_seconds"]))
    return sorted((_trajectory_summary(t) for t in by_track.values()),
                  key=lambda t: t["first_seen_seconds"])


# Backwards-compatible module default tracker (used when detect_frame
# is called without one, e.g. in tests). Prefer passing a Tracker.
_default_tracker = Tracker()


def reset_tracker() -> None:
    """Reset the module default tracker. Prefer a fresh Tracker() per
    video; this exists for the old call sites and tests."""
    global _default_tracker
    _default_tracker = Tracker()


def _candidate_paths() -> list[Path]:
    from ..config import settings

    out: list[Path] = []
    if settings.YOLO_MODEL_PATH:
        out.append(Path(settings.YOLO_MODEL_PATH))
    for name in ("yolov8n.onnx", "yolov8n.pt"):
        out.append(BASE_DIR / name)
        out.append(Path.cwd() / name)
    return out


def _find_weights(suffix: str) -> Path | None:
    for p in _candidate_paths():
        if p.suffix == suffix and p.exists():
            return p
    return None


def provider_status() -> dict:
    """Detection capability + calibration, for /health. Includes the
    configured thresholds and the ONNX execution provider that actually
    loaded (CUDA when a GPU is present, CPU otherwise)."""
    from ..config import settings

    calibration = {"conf": settings.YOLO_CONF, "nms": settings.YOLO_NMS,
                   "classes": sorted(settings.yolo_classes()),
                   "class_conf": settings.yolo_class_conf(),
                   "min_track_iou": settings.YOLO_MIN_TRACK_IOU,
                   "track_max_missed": settings.YOLO_TRACK_MAX_MISSED,
                   "track_max_age_seconds": settings.YOLO_TRACK_MAX_AGE_SECONDS}
    onnx = _find_weights(".onnx")
    if onnx is not None:
        try:
            import onnxruntime  # noqa: F401

            return {"provider": "yolo-onnx", "available": True,
                    "reason": "", "model": str(onnx),
                    "execution_provider": _onnx_provider,
                    **calibration}
        except Exception as e:  # noqa: BLE001
            return {"provider": "yolo-onnx", "available": False,
                    "reason": f"onnxruntime not installed: {e}", **calibration}
    pt = _find_weights(".pt")
    if pt is not None:
        try:
            import ultralytics  # noqa: F401

            return {"provider": "yolo", "available": True,
                    "reason": "", "model": str(pt), **calibration}
        except Exception as e:  # noqa: BLE001
            return {"provider": "yolo", "available": False,
                    "reason": f"ultralytics not installed: {e}", **calibration}
    return {"provider": "unavailable", "available": False,
            "reason": "No YOLO weights found in backend/; run scripts/download_yolo.py "
                      "(yolov8n.onnx for onnxruntime, or yolov8n.pt for ultralytics)",
            **calibration}


def _iou(a: dict, b: dict) -> float:
    x1, y1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    x2, y2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    return inter / max(area_a + area_b - inter, 1e-6)


def _load_onnx():
    """Load the ONNX session, trying the configured execution providers
    in order (CUDA first when listed, CPU as the fallback). Records
    which provider actually loaded so /health can report it honestly."""
    global _onnx_session, _onnx_provider
    if _onnx_session is not None:
        return _onnx_session
    path = _find_weights(".onnx")
    if path is None:
        return None
    from ..config import settings

    import onnxruntime as ort

    wanted = [p.strip() for p in settings.YOLO_EXECUTION_PROVIDERS.split(",") if p.strip()]
    available = set(ort.get_available_providers())
    for name in wanted:
        provider = {"CUDA": "CUDAExecutionProvider", "CPU": "CPUExecutionProvider"}.get(name, name)
        if provider not in available:
            continue
        try:
            _onnx_session = ort.InferenceSession(str(path), providers=[provider])
            _onnx_provider = provider
            return _onnx_session
        except Exception:
            continue
    # Last resort: let onnxruntime pick its default.
    _onnx_session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    _onnx_provider = "CPUExecutionProvider"
    return _onnx_session


def _detect_onnx(frame_path: str, conf: float, tracker: "Tracker | None",
                 timestamp: float | None = None) -> list[dict]:
    """ONNX inference + NMS + per-class filtering + track assignment.

    Confidence is per class: max(global conf, YOLO_CLASS_CONF[label]).
    The class allow-list (YOLO_CLASSES) drops unwanted labels before
    NMS. NMS threshold comes from YOLO_NMS. Track ids come from the
    per-video Tracker passed in (or the module default)."""
    from ..config import settings

    import cv2

    session = _load_onnx()
    if session is None:
        return []
    img = cv2.imread(frame_path)
    if img is None:
        return []
    class_conf = settings.yolo_class_conf()
    allowed = settings.yolo_classes()
    h, w = img.shape[:2]
    size = 640
    blob = cv2.resize(img, (size, size))
    blob = blob[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    blob = np.expand_dims(blob, 0)
    out = session.run(None, {session.get_inputs()[0].name: blob})[0][0]  # (84, 8400)
    out = out.T  # (8400, 84): x, y, w, h, class scores...
    # Coordinate convention differs by export: the official Ultralytics
    # export gives xywh in 0..640 pixels, the common "web" export gives
    # xywh normalised 0..1. Detect it from the data, don't assume.
    normalised = float(np.max(out[:, :4])) <= 2.0 if len(out) else True
    sx = w if normalised else w / size
    sy = h if normalised else h / size
    boxes, scores, labels = [], [], []
    for row in out:
        cls_scores = row[4:]
        cls = int(np.argmax(cls_scores))
        score = float(cls_scores[cls])
        label = COCO_LABELS[cls] if cls < len(COCO_LABELS) else str(cls)
        if allowed and label not in allowed:
            continue
        if score < max(conf, class_conf.get(label, 0.0)):
            continue
        cx, cy, bw, bh = (float(v) for v in row[:4])
        x1 = (cx - bw / 2) * sx
        y1 = (cy - bh / 2) * sy
        x2 = (cx + bw / 2) * sx
        y2 = (cy + bh / 2) * sy
        boxes.append([x1, y1, x2 - x1, y2 - y1])
        scores.append(score)
        labels.append(cls)
    if not boxes:
        return []
    indices = cv2.dnn.NMSBoxes(boxes, scores, conf, settings.YOLO_NMS)
    out_dets = []
    for idx in indices.flatten():
        x, y, bw, bh = boxes[idx]
        out_dets.append({
            "label": COCO_LABELS[labels[idx]] if labels[idx] < len(COCO_LABELS) else str(labels[idx]),
            "confidence": float(scores[idx]),
            "x1": float(x), "y1": float(y), "x2": float(x + bw), "y2": float(y + bh),
            "track_id": None,
        })
    return (tracker or _default_tracker).update(out_dets, timestamp)


def _detect_ultralytics(frame_path: str, conf: float) -> list[dict]:
    global _ultralytics_model
    if _ultralytics_model is None:
        from ultralytics import YOLO

        path = _find_weights(".pt")
        if path is None:
            return []
        _ultralytics_model = YOLO(str(path))
    model = _ultralytics_model
    results = model.track(frame_path, persist=True, conf=conf, verbose=False)
    out = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            xyxy = box.xyxy[0].tolist()
            out.append({
                "label": model.names[int(box.cls[0])],
                "confidence": float(box.conf[0]),
                "x1": float(xyxy[0]), "y1": float(xyxy[1]),
                "x2": float(xyxy[2]), "y2": float(xyxy[3]),
                "track_id": int(box.id[0]) if box.id is not None else None,
            })
    return out


def detect_frame(frame_path: str, conf: float | None = None,
                 tracker: "Tracker | None" = None,
                 timestamp: float | None = None) -> list[dict]:
    """Return [{label, confidence, x1, y1, x2, y2, track_id}] for one frame.

    conf defaults to settings.YOLO_CONF. Pass a per-video Tracker so
    track ids are stable within that video and isolated from others;
    without one the module default tracker is used."""
    from ..config import settings

    status = provider_status()
    if not status["available"]:
        return []
    conf = settings.YOLO_CONF if conf is None else conf
    # Phase 10: per-frame inference latency.
    import time

    from . import metrics

    start = time.perf_counter()
    try:
        if status["provider"] == "yolo-onnx":
            return _detect_onnx(frame_path, conf, tracker, timestamp)
        return _detect_ultralytics(frame_path, conf)
    finally:
        metrics.DETECTION_DURATION.observe(time.perf_counter() - start)


def annotate_frame(frame_path: str, detections: list[dict], out_path: str) -> str:
    import cv2

    img = cv2.imread(frame_path)
    if img is None:
        return frame_path
    for d in detections:
        x1, y1, x2, y2 = int(d["x1"]), int(d["y1"]), int(d["x2"]), int(d["y2"])
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, f"{d['label']} {d['confidence']:.2f}", (x1, max(15, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.imwrite(out_path, img)
    return out_path
