"""Background processing pipeline. One video at a time per worker
(WORKER_CONCURRENCY=1 default, safe for a 16 GB laptop). Steps are
recorded in processing_jobs so a crash leaves a recoverable record
instead of a silently stuck video."""
import json
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import Caption, Detection, Frame, ProcessingJob, Scene, Video
from . import detection, embeddings, retrieval, video_processing, vlm


def _video_dir(video: Video) -> Path:
    return settings.STORAGE_DIR / "videos" / str(video.id)


def process_video(video_id: int) -> None:
    db: Session = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if not video:
            return
        job = db.query(ProcessingJob).filter_by(video_id=video_id).order_by(ProcessingJob.id.desc()).first()
        if job:
            job.status, job.attempts = "running", job.attempts + 1
        video.status = "processing"
        db.commit()

        vdir = _video_dir(video)
        meta = video_processing.probe_video(Path(video.file_path))
        video.duration_seconds, video.width, video.height = (
            meta["duration_seconds"], meta["width"], meta["height"])
        video.thumbnail_path = str(video_processing.make_thumbnail(
            Path(video.file_path), vdir / "thumbnail.jpg"))

        frames = video_processing.extract_frames(Path(video.file_path), vdir / "frames")
        scenes = video_processing.segment_scenes(frames)
        scene_rows = {}
        for s in scenes:
            row = Scene(video_id=video.id, index=s["index"],
                        start_seconds=s["start_seconds"], end_seconds=s["end_seconds"])
            db.add(row)
            db.flush()
            scene_rows[s["index"]] = row
        frame_rows = []
        for i, f in enumerate(frames):
            scene_idx = next((s["index"] for s in scenes if i in s["frame_indices"]), 0)
            row = Frame(video_id=video.id, scene_id=scene_rows[scene_idx].id if scene_rows else None,
                        timestamp_seconds=f["timestamp_seconds"], file_path=f["path"])
            db.add(row)
            db.flush()
            frame_rows.append((i, row))
        db.commit()

        yolo_available = detection.provider_status()["available"]
        for s in scenes:
            scene_row = scene_rows[s["index"]]
            first_i, first_row = next(((i, r) for i, r in frame_rows if i in s["frame_indices"]), (0, frame_rows[0][1]))
            det_labels: list[str] = []
            if yolo_available:
                for i, row in frame_rows:
                    if i not in s["frame_indices"]:
                        continue
                    for d in detection.detect_frame(row.file_path):
                        det_labels.append(d["label"])
                        db.add(Detection(video_id=video.id, frame_id=row.id, track_id=d["track_id"],
                                         label=d["label"], confidence=d["confidence"],
                                         x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"],
                                         timestamp_seconds=row.timestamp_seconds))
            caption_text, provider = vlm.caption_scene(s, det_labels, first_row.file_path)
            db.add(Caption(video_id=video.id, frame_id=first_row.id, scene_id=scene_row.id,
                           timestamp_seconds=first_row.timestamp_seconds,
                           text=caption_text, provider=provider, model=settings.VLM_MODEL or None))
            vec, emb_provider = embeddings.embed(caption_text)
            for i, row in frame_rows:
                if i in s["frame_indices"]:
                    row.embedding_json = json.dumps(vec)
                    retrieval.try_qdrant_upsert(row.id, vec, {
                        "video_id": video.id, "timestamp_seconds": row.timestamp_seconds,
                        "caption": caption_text})
            db.commit()

        video.status = "ready"
        if job:
            job.status, job.updated_at = "done", datetime.utcnow()
        db.commit()
    except Exception as e:  # noqa: BLE001 - pipeline must record its own failure
        db.rollback()
        video = db.get(Video, video_id)
        job = db.query(ProcessingJob).filter_by(video_id=video_id).order_by(ProcessingJob.id.desc()).first()
        if video:
            video.status, video.error_message = "failed", str(e)[:1000]
        if job:
            job.status, job.error_message, job.updated_at = "failed", str(e)[:1000], datetime.utcnow()
        db.commit()
    finally:
        db.close()


def recover_stuck_jobs(db: Session) -> int:
    """Startup recovery: jobs left running/queued by a crash are marked
    failed (with a clear message) so the user can retry them explicitly
    instead of watching a video stuck at 'processing' forever."""
    stuck = db.query(ProcessingJob).filter(ProcessingJob.status.in_(["running", "queued"])).all()
    for job in stuck:
        job.status = "failed"
        job.error_message = "Recovered after restart: job was interrupted. Use retry to re-run it."
        video = db.get(Video, job.video_id)
        if video and video.status == "processing":
            video.status = "failed"
            video.error_message = job.error_message
    db.commit()
    return len(stuck)
