"""Phase 7 (v0.9.0) Celery reliability tests (M10).

- test_celery_time_limits_config: pure config, no services.
- test_task_failure_marks_job_failed: calls the task_failure handler
  directly — no worker, no Redis.
- test_poison_video_no_stuck_running: `integration`, needs Redis
  (the broker) — runs the Celery path with task_always_eager so no
  live worker is needed. A video whose file does not exist must end
  'failed' with its Celery task id stored, never stuck 'running'.

Run: python -m pytest tests/test_celery_reliability.py -q
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_celery.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_celery_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-celery")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0")

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402,F401  (runs Alembic migrations at import)
from app.models import ProcessingJob, User, Video  # noqa: E402
from app.services import worker  # noqa: E402
from app.services.celery_app import _mark_job_failed, celery_app, process_video_task  # noqa: E402


def _redis_available():
    try:
        import redis

        return redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2).ping()
    except Exception:  # noqa: BLE001 - any failure means "skip"
        return False


def test_celery_time_limits_config():
    """M10: a video job is bounded — soft limit asks the worker to
    stop cleanly, hard limit kills it; results expire after 24 h."""
    assert celery_app.conf.task_soft_time_limit == 1800
    assert celery_app.conf.task_time_limit == 2100
    assert celery_app.conf.result_expires == 86400
    assert celery_app.conf.task_acks_late is True


def test_task_failure_marks_job_failed():
    """M10 dead-letter path: a task that dies outside process_video's
    own try/except (worker crash, hard time limit) still leaves the
    DB job 'failed' with a reason instead of stuck 'running'."""
    db = SessionLocal()
    user = db.query(User).filter_by(email="celery-fail@test.com").first()
    if user is None:
        db.add(User(email="celery-fail@test.com", password_hash="x"))
        db.flush()
        user = db.query(User).filter_by(email="celery-fail@test.com").first()
    video = Video(owner_id=user.id, title="crash", original_filename="c.mp4",
                  file_path="/tmp/c.mp4", file_size_bytes=1, status="processing")
    db.add(video)
    db.flush()
    job = ProcessingJob(video_id=video.id, status="running")
    db.add(job)
    db.commit()
    _mark_job_failed(sender=process_video_task, task_id="task-123",
                     args=(video.id,), exception=RuntimeError("worker lost"))
    db.refresh(job)
    db.refresh(video)
    assert job.status == "failed"
    assert "task-123" in job.error_message and "worker lost" in job.error_message
    assert video.status == "failed"
    db.close()


@pytest.mark.integration
def test_poison_video_no_stuck_running(monkeypatch):
    """A video whose file is missing: dispatch through the Celery
    path (eager, no live worker) must end 'failed' with the task id
    stored — never stuck 'running'."""
    if not _redis_available():
        pytest.skip("no live Redis at 127.0.0.1:6379")
    monkeypatch.setattr(settings, "SYNC_PROCESSING", False)
    monkeypatch.setattr(settings, "WORKER_MODE", "celery")
    celery_app.conf.task_always_eager = True
    try:
        db = SessionLocal()
        user = db.query(User).filter_by(email="celery-poison@test.com").first()
        if user is None:
            db.add(User(email="celery-poison@test.com", password_hash="x"))
            db.flush()
            user = db.query(User).filter_by(email="celery-poison@test.com").first()
        video = Video(owner_id=user.id, title="poison", original_filename="p.mp4",
                      file_path="/tmp/does-not-exist.mp4", file_size_bytes=1,
                      status="uploaded")
        db.add(video)
        db.flush()
        job = ProcessingJob(video_id=video.id, status="queued")
        db.add(job)
        db.commit()
        vid = video.id
        db.close()
        worker.dispatch(vid)
        db = SessionLocal()
        job = (db.query(ProcessingJob).filter_by(video_id=vid)
               .order_by(ProcessingJob.id.desc()).first())
        video = db.get(Video, vid)
        assert video.status == "failed"
        assert job.status == "failed"
        assert job.celery_task_id, "dispatch must store the Celery task id"
        assert job.error_message
        db.close()
    finally:
        celery_app.conf.task_always_eager = False
