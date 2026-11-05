"""Celery worker (Phase 2). Broker/result backend are Redis by default
(CELERY_BROKER_URL / CELERY_RESULT_BACKEND). The laptop profile keeps
WORKER_MODE=in_process, so Redis is never required to start the app;
set WORKER_MODE=celery in the full docker-compose stack to use this.

Run a worker with:
    celery -A app.services.celery_app.celery_app worker --loglevel=info
"""
from celery import Celery

from ..config import settings

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
)


@celery_app.task(bind=True, max_retries=2, name="visioniq.process_video")
def process_video_task(self, video_id: int):
    from . import worker

    try:
        worker.process_video(video_id)
    except Exception as exc:  # noqa: BLE001 - Celery retries, then the
        # pipeline itself already records the failure in the DB.
        raise self.retry(exc=exc, countdown=10)
