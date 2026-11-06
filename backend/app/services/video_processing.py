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


def adaptive_fps(duration_seconds: float) -> float:
    """Frames per second for a video of this length. Adaptive mode keeps
    the total frame count near MAX_FRAMES: short videos get denser
    sampling (up to ADAPTIVE_FPS_MAX), long videos sparser sampling
    (down to ADAPTIVE_FPS_MIN). Disabled mode returns FRAME_FPS."""
    if not settings.ADAPTIVE_SAMPLING or not duration_seconds or duration_seconds <= 0:
        return settings.FRAME_FPS
    fps = settings.MAX_FRAMES / duration_seconds
    return max(settings.ADAPTIVE_FPS_MIN, min(settings.ADAPTIVE_FPS_MAX, fps))


def extract_frames(video_path: Path, out_dir: Path, duration_seconds: float | None = None) -> tuple[list[dict], float]:
    """Extract at the adaptive fps, capped at MAX_FRAMES.
    Returns ([{timestamp, path}], fps_used)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if duration_seconds is None:
        try:
            duration_seconds = probe_video(video_path)["duration_seconds"]
        except Exception:
            duration_seconds = 0.0
    fps = adaptive_fps(duration_seconds or 0.0)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
         "-vf", f"fps={fps}", "-q:v", "5", str(out_dir / "frame_%04d.jpg")],
        check=False, timeout=600,
    )
    files = sorted(out_dir.glob("frame_*.jpg"))[: settings.MAX_FRAMES]
    return ([{"timestamp_seconds": round(i / fps, 3), "path": str(p)}
             for i, p in enumerate(files)], fps)


def frame_histogram(path: str):
    """Normalised 32-bin grayscale histogram, or None if unreadable."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    hist = cv2.calcHist([img], [0], None, [32], [0, 256])
    cv2.normalize(hist, hist)
    return hist


def hist_similarity(h1, h2) -> float:
    """Histogram correlation in [0, 1]; 1.0 = identical distribution."""
    if h1 is None or h2 is None:
        return 0.0
    return float(max(0.0, min(1.0, cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))))


def dedupe_frames(frames: list[dict]) -> tuple[list[dict], int]:
    """Drop near-duplicate consecutive frames. A frame is dropped only
    when it looks almost identical to the last kept frame AND less than
    DEDUPE_MAX_GAP_SECONDS have passed since it, so a static shot still
    keeps a frame every couple of seconds. Returns (kept, dropped)."""
    if not frames:
        return [], 0
    kept, dropped = [frames[0]], 0
    last_hist = frame_histogram(frames[0]["path"])
    for f in frames[1:]:
        hist = frame_histogram(f["path"])
        gap = f["timestamp_seconds"] - kept[-1]["timestamp_seconds"]
        if (hist_similarity(last_hist, hist) >= settings.DEDUPE_SIMILARITY
                and gap < settings.DEDUPE_MAX_GAP_SECONDS):
            dropped += 1
            continue
        kept.append(f)
        last_hist = hist
    return kept, dropped


def representative_index(scene: dict) -> int:
    """Most representative frame of a scene: the middle one. The first
    frame of a cut is often a fade/blur; the middle is the most stable."""
    idx = scene["frame_indices"]
    return idx[len(idx) // 2]


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
    return _merge_similar_scenes(scenes, frames)


def _merge_similar_scenes(scenes: list[dict], frames: list[dict]) -> list[dict]:
    """Scene similarity detection: merge adjacent scenes whose
    representative frames look the same. A flicker or a brief lighting
    change can split one continuous shot into two scenes; merging on
    representative-frame similarity repairs that without hiding real
    cuts (a real cut changes the picture)."""
    if len(scenes) < 2:
        return scenes
    merged = [dict(scenes[0])]
    for s in scenes[1:]:
        prev, rep_prev = merged[-1], frames[representative_index(merged[-1])]["path"]
        rep_cur = frames[representative_index(s)]["path"]
        sim = hist_similarity(frame_histogram(rep_prev), frame_histogram(rep_cur))
        if sim >= settings.SCENE_MERGE_SIMILARITY:
            prev["end_seconds"] = s["end_seconds"]
            prev["frame_indices"] = prev["frame_indices"] + s["frame_indices"]
            continue
        s = dict(s, index=len(merged))
        merged.append(s)
    return merged


def frame_brightness(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return float(img.mean()) if img is not None else 0.0
