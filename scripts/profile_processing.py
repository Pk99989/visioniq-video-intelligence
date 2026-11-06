"""Profile the pipeline on a 2-minute video (Phase 10, item 3).

Usage:
    DATABASE_URL=sqlite:////tmp/visioniq_profile.db \
    STORAGE_DIR=/tmp/visioniq_profile_storage SYNC_PROCESSING=1 \
    python -m cProfile -o /tmp/profile.out scripts/profile_processing.py
    python -c "import pstats; pstats.Stats('/tmp/profile.out').sort_stats('cumulative').print_stats(25)"

The script uploads nothing — it inserts a video row pointing at a
file and runs process_video directly, so the profile covers probe,
frames, dedupe, scenes, detection, captions and embeddings.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402  (runs migrations)
from app.models import ProcessingJob, Video  # noqa: E402
from app.services import worker  # noqa: E402


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/moving-2min.mp4"
    db = SessionLocal()
    video = Video(owner_id=1, title="profile-2min", original_filename="moving-2min.mp4",
                  file_path=src, file_size_bytes=Path(src).stat().st_size)
    db.add(video)
    db.commit()
    db.refresh(video)
    db.add(ProcessingJob(video_id=video.id, status="queued"))
    db.commit()
    video_id = video.id
    db.close()
    print(f"profiling video {video_id} ({src})")
    worker.process_video(video_id)
    db = SessionLocal()
    v = db.get(Video, video_id)
    print(f"status={v.status} duration={v.duration_seconds}s error={v.error_message}")
    db.close()


if __name__ == "__main__":
    main()
