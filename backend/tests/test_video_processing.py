"""Phase 2 (v0.4.0) video-processing tests — adaptive sampling,
duplicate-frame removal, scene merging, representative frames.

Synthetic frames only (numpy + cv2); no video files needed.
Run: python -m pytest tests/test_video_processing.py -q
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_vp.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_vp_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-vp")

from app.config import settings  # noqa: E402
from app.services import video_processing as vp  # noqa: E402


def _frame_file(tmp_path, name, value):
    """A solid-colour frame; `value` 0-255. Identical values are
    near-identical frames; different values are different shots."""
    p = tmp_path / name
    cv2.imwrite(str(p), np.full((64, 64, 3), value, dtype=np.uint8))
    return str(p)


def _frames(tmp_path, values, fps=2.0):
    out = []
    for i, v in enumerate(values):
        out.append({"timestamp_seconds": round(i / fps, 3),
                    "path": _frame_file(tmp_path, f"f{i:02d}.jpg", v)})
    return out


def test_adaptive_fps():
    settings.ADAPTIVE_SAMPLING = True
    settings.MAX_FRAMES = 120
    assert vp.adaptive_fps(10.0) == 2.0       # short video: dense
    assert vp.adaptive_fps(60.0) == 2.0       # 120/60 = 2.0
    assert vp.adaptive_fps(120.0) == 1.0      # 120/120 = 1.0
    assert vp.adaptive_fps(600.0) == 0.2      # long video: sparse floor
    assert vp.adaptive_fps(3600.0) == 0.2
    settings.ADAPTIVE_SAMPLING = False
    settings.FRAME_FPS = 1.0
    assert vp.adaptive_fps(10.0) == 1.0       # disabled: fixed fps
    settings.ADAPTIVE_SAMPLING = True


def test_dedupe_drops_identical_frames_but_keeps_a_regular_cadence(tmp_path):
    # 5 identical frames 0.5s apart: keep t=0 and t=2.0 (max gap rule),
    # drop the three in between.
    frames = _frames(tmp_path, [128, 128, 128, 128, 128])
    kept, dropped = vp.dedupe_frames(frames)
    assert dropped == 3, [f["timestamp_seconds"] for f in kept]
    assert [f["timestamp_seconds"] for f in kept] == [0.0, 2.0]


def test_dedupe_keeps_different_frames(tmp_path):
    frames = _frames(tmp_path, [0, 128, 255, 64, 200])
    kept, dropped = vp.dedupe_frames(frames)
    assert dropped == 0 and len(kept) == 5


def test_scene_merge_joins_identical_adjacent_scenes(tmp_path):
    # Two "scenes" that look the same are one shot split by flicker.
    frames = _frames(tmp_path, [128] * 6)
    scenes = [{"index": 0, "start_seconds": 0.0, "end_seconds": 1.0,
               "frame_indices": [0, 1, 2]},
              {"index": 1, "start_seconds": 1.5, "end_seconds": 2.5,
               "frame_indices": [3, 4, 5]}]
    merged = vp._merge_similar_scenes(scenes, frames)
    assert len(merged) == 1
    assert merged[0]["frame_indices"] == [0, 1, 2, 3, 4, 5]
    assert merged[0]["end_seconds"] == 2.5


def test_scene_merge_keeps_real_cuts(tmp_path):
    frames = _frames(tmp_path, [0, 0, 0, 255, 255, 255])
    scenes = [{"index": 0, "start_seconds": 0.0, "end_seconds": 1.0,
               "frame_indices": [0, 1, 2]},
              {"index": 1, "start_seconds": 1.5, "end_seconds": 2.5,
               "frame_indices": [3, 4, 5]}]
    merged = vp._merge_similar_scenes(scenes, frames)
    assert len(merged) == 2


def test_representative_frame_is_middle():
    scene = {"frame_indices": [0, 1, 2, 3, 4]}
    assert vp.representative_index(scene) == 2
    assert vp.representative_index({"frame_indices": [7]}) == 7
