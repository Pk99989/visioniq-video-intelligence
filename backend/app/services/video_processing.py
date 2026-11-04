"""Video processing: ffprobe metadata, ffmpeg thumbnails/frames, and
scene segmentation by frame-to-frame mean-colour change (OpenCV).

This is intentionally CPU-friendly: 1 fps by default, capped frames, and
no model is loaded here. Detection/VLM run as separate, lazy steps.
"""
import json
import subprocess
from pathlib import Path

import cv2

from ..config import settings


def probe_video(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if out.returncode != 0:
        raise ValueError(f"ffprobe failed: {out.stderr[:500]}")
    data = json.loads(out.stdout or "{}")
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or stream.get("duration") or 0.0)
    return {
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0) or None,
        "height": int(stream.get("height") or 0) or None,
    }


def make_thumbnail(video_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(video_path),
         "-vframes", "1", "-q:v", "4", str(out_path)],
        check=False, timeout=120,
    )
    if not out_path.exists():  # very short videos: fall back to first frame
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
             "-vframes", "1", "-q:v", "4", str(out_path)],
            check=False, timeout=120,
        )
    return out_path


def extract_frames(video_path: Path, out_dir: Path) -> list[dict]:
    """Extract at FRAME_FPS, capped at MAX_FRAMES. Returns [{timestamp, path}]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
         "-vf", f"fps={settings.FRAME_FPS}", "-q:v", "5", str(out_dir / "frame_%04d.jpg")],
        check=False, timeout=600,
    )
    files = sorted(out_dir.glob("frame_*.jpg"))[: settings.MAX_FRAMES]
    return [{"timestamp_seconds": round(i / settings.FRAME_FPS, 3), "path": str(p)}
            for i, p in enumerate(files)]


def segment_scenes(frames: list[dict]) -> list[dict]:
    """Scene boundaries where mean-colour change exceeds SCENE_THRESHOLD.

    A new scene starts at the first frame and at every large change.
    Returns [{index, start_seconds, end_seconds, frame_indices}].
    """
    if not frames:
        return []
    means, boundaries = [], [0]
    prev = None
    for i, f in enumerate(frames):
        img = cv2.imread(f["path"])
        if img is None:
            means.append(None)
            continue
        mean = img.mean(axis=(0, 1))
        means.append(mean)
        if prev is not None and abs(mean - prev).mean() > settings.SCENE_THRESHOLD:
            boundaries.append(i)
        prev = mean
    scenes = []
    for idx, start_i in enumerate(boundaries):
        end_i = boundaries[idx + 1] - 1 if idx + 1 < len(boundaries) else len(frames) - 1
        scenes.append({
            "index": idx,
            "start_seconds": frames[start_i]["timestamp_seconds"],
            "end_seconds": frames[end_i]["timestamp_seconds"],
            "frame_indices": list(range(start_i, end_i + 1)),
        })
    return scenes


def frame_brightness(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return float(img.mean()) if img is not None else 0.0
