"""Celery worker (Phase 2, hardened Phase 7 / M10). Broker/result
backend are Redis by default (CELERY_BROKER_URL /
CELERY_RESULT_BACKEND). The laptop profile keeps
WORKER_MODE=in_process, so Redis is never required to start the app;
set WORKER_MODE=celery in the full docker-compose stack to use this.

Run a worker with:
    celery -A app.services.celery_app.celery_app worker --loglevel=info

Reliability (M10): a video job has a soft time limit (1800 s — the
worker is asked to stop cleanly) and a hard limit (2100 s — the
worker is killed). Results expire after 24 h. The task id is stored
on ProcessingJob by dispatch (see worker.py). When a task fails for
good — worker crash, hard time limit, retries exhausted — the
task_failure handler below marks the DB job failed, so no video is
left stuck at 'processing' with no record of why.
"""
import logging

from celery import Celery
from celery.signals import task_failure

from ..config import settings

logger = logging.getLogger("visioniq.celery")

celery_app = Celery(
    "visioniq",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_soft_time_limit=1800,
    task_time_limit=2100,
    result_expires=86400,
)


@task_failure.connect
def _mark_job_failed(sender=None, task_id=None, args=None, exception=None, **kwargs):
    """Dead-letter path (M10): the task died outside process_video's
    own try/except (worker crash, hard time limit, retries exhausted).
    Record it on the DB job so the video is 'failed' with a reason
    instead of stuck 'running'. Never raises — a handler failure must
    not mask the original one."""
    if sender is None or getattr(sender, "name", "") != "visioniq.process_video":
        return
    video_id = args[0] if args else None
    if video_id is None:
        return
    try:
        from datetime import datetime

        from ..database import SessionLocal
        from ..models import ProcessingJob, Video

        db = SessionLocal()
        try:
            job = (db.query(ProcessingJob).filter_by(video_id=video_id)
                   .order_by(ProcessingJob.id.desc()).first())
            if job and job.status in ("running", "queued"):
                job.status = "failed"
                job.error_message = (f"Celery task {task_id} failed: "
                                     f"{type(exception).__name__}: {exception}")
                job.updated_at = datetime.utcnow()
            video = db.get(Video, video_id)
            if video and video.status == "processing":
                video.status = "failed"
                video.error_message = job.error_message if job else str(exception)[:1000]
            db.commit()
        finally:
            db.close()
        logger.error("celery task %s failed for video %s: %s", task_id, video_id, exception)
    except Exception:  # noqa: BLE001 - handler must never raise
        logger.exception("celery task_failure handler failed for video %s", video_id)


@celery_app.task(bind=True, max_retries=2, name="visioniq.process_video")
def process_video_task(self, video_id: int):
    from . import worker

    try:
        worker.process_video(video_id)
    except Exception as exc:  # noqa: BLE001 - Celery retries, then the
        # pipeline itself already records the failure in the DB.
        raise self.retry(exc=exc, countdown=10)
