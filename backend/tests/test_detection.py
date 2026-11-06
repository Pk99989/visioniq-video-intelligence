"""Phase 3 (v0.5.0) detection tests — per-video Tracker lifecycle,
calibration (conf/NMS/class filter/per-class thresholds), trajectory
summaries, and real-model checks on bus.jpg / traffic frame.

Tracker tests are synthetic (no model). Real-model tests need the
YOLO weights in backend/ and are skipped when absent.
Run: python -m pytest tests/test_detection.py -q
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_det.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_det_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-det")

from app.config import settings  # noqa: E402
from app.services import detection  # noqa: E402


def _box(x1, y1, x2, y2, label="person", conf=0.9):
    return {"label": label, "confidence": conf,
            "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
            "track_id": None}


def _iou(a, b):
    return detection._iou(a, b)


def test_tracker_keeps_id_for_same_object():
    t = detection.Tracker()
    d1 = t.update([_box(10, 10, 50, 80)], timestamp=0.0)
    d2 = t.update([_box(12, 11, 52, 81)], timestamp=0.5)
    assert d1[0]["track_id"] == d2[0]["track_id"] == 1


def test_tracker_new_id_for_different_label_and_new_object():
    t = detection.Tracker()
    d1 = t.update([_box(10, 10, 50, 80, "person"), _box(100, 100, 200, 200, "bus")],
                  timestamp=0.0)
    assert {d["track_id"] for d in d1} == {1, 2}
    # Same-label box far away (IoU ~0) is a new track, not a match.
    d2 = t.update([_box(300, 300, 340, 380, "person")], timestamp=0.5)
    assert d2[0]["track_id"] == 3


def test_tracker_retires_after_missed_budget():
    t = detection.Tracker(max_missed=2)
    t.update([_box(10, 10, 50, 80)], timestamp=0.0)
    t.update([], timestamp=0.5)   # missed 1
    t.update([], timestamp=1.0)   # missed 2
    t.update([], timestamp=1.5)   # missed 3 > budget -> retired
    assert len(t.finished) == 1 and t.finished[0]["track_id"] == 1
    # Reappearing object gets a NEW id (old track is dead).
    d = t.update([_box(10, 10, 50, 80)], timestamp=2.0)
    assert d[0]["track_id"] == 2


def test_tracker_retires_on_max_age():
    t = detection.Tracker(max_missed=100, max_age_seconds=1.0)
    t.update([_box(10, 10, 50, 80)], timestamp=0.0)
    t.update([_box(11, 10, 51, 80)], timestamp=0.5)
    t.update([_box(12, 10, 52, 80)], timestamp=1.5)  # age 1.5 > 1.0
    assert len(t.finished) == 1
    assert t.finished[0]["reason"] == "aged"


def test_trajectories_dwell_and_displacement():
    rows = [
        {"track_id": 1, "label": "bus", "timestamp_seconds": 0.0,
         "x1": 0, "y1": 0, "x2": 100, "y2": 50},
        {"track_id": 1, "label": "bus", "timestamp_seconds": 1.0,
         "x1": 10, "y1": 0, "x2": 110, "y2": 50},
        {"track_id": 1, "label": "bus", "timestamp_seconds": 2.0,
         "x1": 30, "y1": 0, "x2": 130, "y2": 50},
        {"track_id": 2, "label": "person", "timestamp_seconds": 0.5,
         "x1": 0, "y1": 0, "x2": 20, "y2": 40},
    ]
    trajs = detection.build_trajectories(rows)
    assert len(trajs) == 2
    bus = trajs[0]
    assert bus["label"] == "bus" and bus["dwell_seconds"] == 2.0
    assert bus["frames_seen"] == 3
    # Centres moved 50->60->80: displacement 10 + 20 = 30 px.
    assert bus["displacement_px"] == 30.0
    assert trajs[1]["dwell_seconds"] == 0.0  # seen once


def test_config_parsing():
    settings.YOLO_CLASS_CONF = "person:0.5, bus:0.3"
    assert settings.yolo_class_conf() == {"person": 0.5, "bus": 0.3}
    settings.YOLO_CLASSES = "bus, truck"
    assert settings.yolo_classes() == {"bus", "truck"}
    settings.YOLO_CLASSES = ""
    assert settings.yolo_classes() == set()
    settings.YOLO_CLASS_CONF = ""


WEIGHTS = Path(__file__).resolve().parent.parent / "yolov8n.onnx"
needs_weights = pytest.mark.skipif(not WEIGHTS.exists(), reason="no yolov8n.onnx")


@needs_weights
def test_real_model_bus_image_labels(monkeypatch):
    monkeypatch.setattr(settings, "YOLO_CLASSES", "")
    monkeypatch.setattr(settings, "YOLO_CLASS_CONF", "")
    dets = detection.detect_frame("/tmp/bus.jpg", tracker=detection.Tracker())
    labels = sorted({d["label"] for d in dets})
    assert "bus" in labels and "person" in labels, labels
    assert len(dets) >= 4


@needs_weights
def test_nms_collapses_overlapping_same_label_boxes(monkeypatch):
    """Two boxes of the same label overlapping heavily cannot both
    survive NMS (threshold YOLO_NMS)."""
    monkeypatch.setattr(settings, "YOLO_CLASSES", "")
    monkeypatch.setattr(settings, "YOLO_CLASS_CONF", "")
    dets = detection.detect_frame("/tmp/bus.jpg", tracker=detection.Tracker())
    for i, a in enumerate(dets):
        for b in dets[i + 1:]:
            if a["label"] == b["label"]:
                assert _iou(a, b) <= settings.YOLO_NMS + 0.05, (a, b)


@needs_weights
def test_class_allowlist_filters_labels(monkeypatch):
    monkeypatch.setattr(settings, "YOLO_CLASSES", "bus")
    monkeypatch.setattr(settings, "YOLO_CLASS_CONF", "")
    dets = detection.detect_frame("/tmp/bus.jpg", tracker=detection.Tracker())
    assert dets and all(d["label"] == "bus" for d in dets), dets
    monkeypatch.setattr(settings, "YOLO_CLASSES", "")


@needs_weights
def test_per_class_conf_threshold(monkeypatch):
    """person:0.99 removes all persons; bus survives at default conf."""
    monkeypatch.setattr(settings, "YOLO_CLASSES", "")
    monkeypatch.setattr(settings, "YOLO_CLASS_CONF", "person:0.99")
    dets = detection.detect_frame("/tmp/bus.jpg", tracker=detection.Tracker())
    assert all(d["label"] != "person" for d in dets), dets
    assert any(d["label"] == "bus" for d in dets), dets
    monkeypatch.setattr(settings, "YOLO_CLASS_CONF", "")


@needs_weights
def test_provider_status_reports_calibration_and_execution_provider():
    status = detection.provider_status()
    assert status["available"] is True
    assert status["conf"] == settings.YOLO_CONF
    assert status["nms"] == settings.YOLO_NMS
    assert status["execution_provider"] in ("CPUExecutionProvider",
                                            "CUDAExecutionProvider"), status
