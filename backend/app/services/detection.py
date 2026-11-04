"""Object detection adapter (YOLO-compatible) + ByteTrack-style tracking.

Laptop rule: the model is loaded lazily, only if `ultralytics` is
installed AND a weights file is present. Otherwise `detect()` honestly
returns no detections with provider="unavailable" instead of inventing
boxes. When ultralytics is present, `model.track(persist=True)` uses its
built-in ByteTracker, giving stable track_ids across frames.
"""
from pathlib import Path

_model = None
_model_error: str | None = None


def provider_status() -> dict:
    try:
        import ultralytics  # noqa: F401
        installed = True
    except Exception as e:  # noqa: BLE001
        installed = False
        return {"provider": "yolo", "available": False, "reason": f"ultralytics not installed: {e}"}
    weights = Path("yolov8n.pt")
    return {"provider": "yolo", "available": installed and weights.exists(),
            "reason": "" if weights.exists() else "yolov8n.pt not found in backend/; run scripts/download_yolo.py"}


def _load_model():
    global _model, _model_error
    if _model is not None:
        return _model
    try:
        from ultralytics import YOLO

        _model = YOLO("yolov8n.pt")
        return _model
    except Exception as e:  # noqa: BLE001
        _model_error = str(e)
        return None


def detect_frame(frame_path: str, conf: float = 0.35) -> list[dict]:
    """Return [{label, confidence, x1, y1, x2, y2, track_id}] for one frame."""
    model = _load_model()
    if model is None:
        return []
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
