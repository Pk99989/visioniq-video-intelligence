"""Clip extraction (Phase 3): cut a [start, end] segment out of a
processed video with ffmpeg and return the clip file path.

Re-encoding (libx264 + aac) is used instead of stream copy: -c copy
on a non-keyframe start produces a clip that starts with frozen
frames or fails in some players. For the short clips VisionIQ makes
(2-10 s) the re-encode costs a few seconds and is accurate.
"""
import subprocess
from pathlib import Path

from ..config import settings


def extract_clip(video_path: Path, video_id: int, start: float, end: float) -> Path:
    if start < 0 or end <= start:
        raise ValueError("end must be greater than start, and start must be >= 0")
    duration = end - start
    out_dir = settings.STORAGE_DIR / "clips" / str(video_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"clip_{start:.1f}-{end:.1f}.mp4"
    if out.exists():
        return out
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(video_path),
           "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
