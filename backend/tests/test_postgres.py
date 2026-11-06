"""Phase 7 (v0.9.0) Postgres/infra tests.

- test_migrations_apply_on_postgres / test_pool_config are
  `integration`: they need a live Postgres (CI service container, or
  a local server). They skip when it is unreachable.
- test_recovery_grace_period / test_prune_expired_tokens are unit
  tests on the shared SQLite engine.

Run: python -m pytest tests/test_postgres.py -q
     python -m pytest tests/test_postgres.py -q -m integration
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_pg.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_pg_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-pg")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402,F401  (runs Alembic migrations at import)
from app.models import PasswordResetToken, ProcessingJob, RevokedToken, User, Video  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.services import worker  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
PG_URL = os.environ.get(
    "VISIONIQ_TEST_POSTGRES_URL",
    "postgresql://visioniq:visioniq@127.0.0.1:5432/visioniq_test")


def _pg_available():
    """Is the Postgres server reachable (checked against the postgres
    maintenance DB — the scratch visioniq_test DB may not exist yet)?"""
    try:
        import psycopg2

        url = PG_URL.rsplit("/", 1)[0] + "/postgres"
        conn = psycopg2.connect(url, connect_timeout=3)
        conn.close()
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip"
        return False


def _pg(sql, db="postgres"):
    import psycopg2

    url = PG_URL.rsplit("/", 1)[0] + "/" + db
    conn = psycopg2.connect(url, connect_timeout=3)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall() if cur.description else []
    finally:
        conn.close()


@pytest.mark.integration
def test_migrations_apply_on_postgres():
    """Alembic up to head on a scratch Postgres, indexes present,
    downgrade one step + upgrade again (reversibility)."""
    if not _pg_available():
        pytest.skip("no live Postgres at " + PG_URL)
    _pg("DROP DATABASE IF EXISTS visioniq_test")
    _pg("CREATE DATABASE visioniq_test")
    env = {**os.environ, "DATABASE_URL": PG_URL}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    tables = {row[0] for row in _pg(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'", "visioniq_test")}
    for expected in ("users", "videos", "frames", "captions", "detections",
                     "events", "zones", "processing_jobs", "revoked_tokens",
                     "password_reset_tokens", "alembic_version"):
        assert expected in tables, f"missing table {expected}"
    indexes = {row[0] for row in _pg(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public'", "visioniq_test")}
    for expected in ("ix_captions_video_id_timestamp_seconds",
                     "ix_detections_video_id_timestamp_seconds",
                     "ix_frames_video_id_timestamp_seconds"):
        assert expected in indexes, f"missing index {expected}"
    cols = {row[0] for row in _pg(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='processing_jobs'", "visioniq_test")}
    assert "celery_task_id" in cols
    # Reversibility: one step down (drops the v4 indexes) and back up.
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "-1"],
                       cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    _pg("DROP DATABASE IF EXISTS visioniq_test")


@pytest.mark.integration
def test_pool_config():
    """Postgres engine gets a bounded QueuePool; SQLite keeps its
    single-connection default. Checked in a subprocess so the test
    process's own (SQLite) engine is untouched."""
    if not _pg_available():
        pytest.skip("no live Postgres at " + PG_URL)
    code = (
        "import sys; sys.path.insert(0, '.');"
        "from app.database import engine;"
        "print(type(engine.pool).__name__,"
        " getattr(engine.pool, 'size', lambda: None)(),"
        " getattr(engine.pool, '_pre_ping', None))"
    )
    env = {**os.environ, "DATABASE_URL": PG_URL}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith("QueuePool"), r.stdout
    assert str(settings.DB_POOL_SIZE) in r.stdout, r.stdout
    assert "True" in r.stdout, r.stdout  # pool_pre_ping on for Postgres
    env_sqlite = {**os.environ, "DATABASE_URL": "sqlite:////tmp/visioniq_test_pool.db"}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env_sqlite,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # SQLite file DBs also use a QueuePool by default in SQLAlchemy,
    # but without the Postgres settings: no pre-ping, default size.
    assert "QueuePool" in r.stdout, r.stdout
    assert r.stdout.strip().endswith("False"), r.stdout


def _user_id(db, email):
    row = db.query(User).filter_by(email=email).first()
    return row.id if row else None


def test_recovery_grace_period():
    """M11: a job that went stale before the grace period is failed;
    a job updated minutes ago is left alone (still in flight)."""
    db = SessionLocal()
    uid = _user_id(db, "pg-grace@test.com")
    if uid is None:
        db.add(User(email="pg-grace@test.com", password_hash="x"))
        db.flush()
        uid = _user_id(db, "pg-grace@test.com")
    now = datetime.utcnow()
    old_video = Video(owner_id=uid, title="old", original_filename="o.mp4",
                      file_path="/tmp/o.mp4", file_size_bytes=1, status="processing")
    new_video = Video(owner_id=uid, title="new", original_filename="n.mp4",
                      file_path="/tmp/n.mp4", file_size_bytes=1, status="processing")
    db.add_all([old_video, new_video])
    db.flush()
    old_job = ProcessingJob(video_id=old_video.id, status="running",
                            updated_at=now - timedelta(hours=1))
    new_job = ProcessingJob(video_id=new_video.id, status="running",
                            updated_at=now - timedelta(minutes=1))
    db.add_all([old_job, new_job])
    db.commit()
    recovered = worker.recover_stuck_jobs(db)
    assert recovered == 1
    db.refresh(old_job)
    db.refresh(new_job)
    db.refresh(old_video)
    db.refresh(new_video)
    assert old_job.status == "failed"
    assert old_video.status == "failed"
    assert new_job.status == "running"
    assert new_video.status == "processing"
    db.close()


def test_prune_expired_tokens():
    """M4: expired revoked tokens and used/expired reset tokens are
    removed; a still-valid revoked token survives."""
    db = SessionLocal()
    uid = _user_id(db, "pg-prune@test.com")
    if uid is None:
        db.add(User(email="pg-prune@test.com", password_hash="x"))
        db.flush()
        uid = _user_id(db, "pg-prune@test.com")
    now = datetime.utcnow()
    # Rows from an earlier run of this test survive in the shared
    # test DB (valid-1 is kept by design) — clear them first.
    db.query(RevokedToken).filter(RevokedToken.jti.in_(["expired-1", "valid-1"])).delete(
        synchronize_session=False)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash.in_(["used-1", "expired-1"])).delete(
        synchronize_session=False)
    db.commit()
    db.add_all([
        RevokedToken(jti="expired-1", user_id=uid,
                     expires_at=now - timedelta(hours=1)),
        RevokedToken(jti="valid-1", user_id=uid,
                     expires_at=now + timedelta(hours=1)),
        PasswordResetToken(user_id=uid, token_hash="used-1",
                           expires_at=now + timedelta(hours=1), used=True),
        PasswordResetToken(user_id=uid, token_hash="expired-1",
                           expires_at=now - timedelta(hours=1), used=False),
    ])
    db.commit()
    # Assert on this test's own rows only: the shared test DB may
    # hold leftover tokens from other test files (audit L12).
    pruned = auth_router.prune_expired_tokens(db)
    assert pruned >= 3
    assert db.query(RevokedToken).filter_by(jti="expired-1").first() is None
    assert db.query(RevokedToken).filter_by(jti="valid-1").first() is not None
    assert db.query(PasswordResetToken).filter_by(token_hash="used-1").first() is None
    assert db.query(PasswordResetToken).filter_by(token_hash="expired-1").first() is None
    db.close()
