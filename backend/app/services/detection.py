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

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/

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
_ultralytics_model = None
_last_tracks: list[dict] = []
_next_track_id = 1


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
    onnx = _find_weights(".onnx")
    if onnx is not None:
        try:
            import onnxruntime  # noqa: F401

            return {"provider": "yolo-onnx", "available": True,
                    "reason": "", "model": str(onnx)}
        except Exception as e:  # noqa: BLE001
            return {"provider": "yolo-onnx", "available": False,
                    "reason": f"onnxruntime not installed: {e}"}
    pt = _find_weights(".pt")
    if pt is not None:
        try:
            import ultralytics  # noqa: F401

            return {"provider": "yolo", "available": True,
                    "reason": "", "model": str(pt)}
        except Exception as e:  # noqa: BLE001
            return {"provider": "yolo", "available": False,
                    "reason": f"ultralytics not installed: {e}"}
    return {"provider": "unavailable", "available": False,
            "reason": "No YOLO weights found in backend/; run scripts/download_yolo.py "
                      "(yolov8n.onnx for onnxruntime, or yolov8n.pt for ultralytics)"}


def reset_tracker() -> None:
    global _last_tracks, _next_track_id
    _last_tracks = []
    _next_track_id = 1


def _iou(a: dict, b: dict) -> float:
    x1, y1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    x2, y2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    return inter / max(area_a + area_b - inter, 1e-6)


def _assign_track_ids(detections: list[dict]) -> list[dict]:
    global _last_tracks, _next_track_id
    used: set[int] = set()
    for d in detections:
        best, best_iou = None, 0.3
        for i, old in enumerate(_last_tracks):
            if i in used or old["label"] != d["label"]:
                continue
            score = _iou(d, old)
            if score > best_iou:
                best, best_iou = i, score
        if best is not None:
            d["track_id"] = _last_tracks[best]["track_id"]
            used.add(best)
        else:
            d["track_id"] = _next_track_id
            _next_track_id += 1
    _last_tracks = detections
    return detections


def _load_onnx():
    global _onnx_session
    if _onnx_session is not None:
        return _onnx_session
    path = _find_weights(".onnx")
    if path is None:
        return None
    import onnxruntime as ort

    _onnx_session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _onnx_session


def _detect_onnx(frame_path: str, conf: float) -> list[dict]:
    import cv2

    session = _load_onnx()
    if session is None:
        return []
    img = cv2.imread(frame_path)
    if img is None:
        return []
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
        if score < conf:
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
    indices = cv2.dnn.NMSBoxes(boxes, scores, conf, 0.45)
    out_dets = []
    for idx in indices.flatten():
        x, y, bw, bh = boxes[idx]
        out_dets.append({
            "label": COCO_LABELS[labels[idx]] if labels[idx] < len(COCO_LABELS) else str(labels[idx]),
            "confidence": float(scores[idx]),
            "x1": float(x), "y1": float(y), "x2": float(x + bw), "y2": float(y + bh),
            "track_id": None,
        })
    return _assign_track_ids(out_dets)


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


def detect_frame(frame_path: str, conf: float = 0.35) -> list[dict]:
    """Return [{label, confidence, x1, y1, x2, y2, track_id}] for one frame."""
    status = provider_status()
    if not status["available"]:
        return []
    if status["provider"] == "yolo-onnx":
        return _detect_onnx(frame_path, conf)
    return _detect_ultralytics(frame_path, conf)


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
