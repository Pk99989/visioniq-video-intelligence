"""Shared test fixtures (Phase 9 rate-limit switch; Phase 11 shared
helpers + repo-local fixtures, audit L12).

L12 (shared test engine): every test file imports the app once and
the first import wins the engine's DATABASE_URL, so fixtures must
never hardcode a user id or a database path. Helpers here resolve
everything through the API or through SessionLocal on the live
engine, and every auth helper uses a fresh uuid email so files that
share one process (and one DB) cannot collide.

Rate limiting (M5) is disabled for the whole test session: the suite
registers dozens of users from the single TestClient IP in under a
minute, which is exactly the abuse the register limiter targets — and
several test files register users in module-scoped fixtures, which run
before any function-scoped fixture could disable it. The dedicated
rate-limit tests in test_security.py re-enable it with monkeypatch
and run against a live Redis (skipped when Redis is down).

NOTE: settings and the app are imported lazily inside the fixtures,
not at module level — test modules set DATABASE_URL etc. via
os.environ.setdefault before they import the app, and importing
app.config here first would freeze the settings singleton with the
default (non-test) values.

Markers: any test with no integration/e2e/vlm marker is auto-marked
`unit` (pytest_collection_modifyitems below), so `pytest -m unit`
runs the fast SQLite suite and `pytest -m "not e2e and not vlm"`
matches the CI unit job.
"""
import subprocess
import uuid
from pathlib import Path

import pytest

# Phase 11 (L12): SYNC_PROCESSING=1 for every test run, set here —
# conftest is imported before any test module, so the settings
# singleton cannot be frozen with the default (async) value by a
# module like test_detection.py that imports the app without setting
# it first. Before this, the suite only passed when collection order
# happened to import a SYNC_PROCESSING-setting file first.
import os

os.environ.setdefault("SYNC_PROCESSING", "1")

DATA_DIR = Path(__file__).resolve().parent / "data"
BUS_JPG = DATA_DIR / "bus.jpg"
TRAFFIC_JPG = DATA_DIR / "traffic-frame.jpg"


def pytest_collection_modifyitems(items):
    """Auto-mark unmarked tests as unit (see module docstring)."""
    for item in items:
        marks = {m.name for m in item.iter_markers()}
        if not marks & {"integration", "e2e", "vlm"}:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session", autouse=True)
def _rate_limit_off():
    from app.config import settings

    old = settings.RATE_LIMIT_ENABLED
    settings.RATE_LIMIT_ENABLED = False
    yield
    settings.RATE_LIMIT_ENABLED = old


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """backend/tests/data — repo-local test images (bus.jpg,
    traffic-frame.jpg). These used to live in /tmp and were wiped by
    VM restarts; they are committed now."""
    assert BUS_JPG.exists(), "backend/tests/data/bus.jpg missing"
    assert TRAFFIC_JPG.exists(), "backend/tests/data/traffic-frame.jpg missing"
    return DATA_DIR


@pytest.fixture(scope="session")
def bus_jpg(fixtures_dir) -> Path:
    return fixtures_dir / "bus.jpg"


@pytest.fixture(scope="session")
def traffic_jpg(fixtures_dir) -> Path:
    return fixtures_dir / "traffic-frame.jpg"


@pytest.fixture()
def bus_video(tmp_path, bus_jpg) -> Path:
    """A 3 s bus video built from the repo-local frame (replaces the
    old /tmp/bus3.mp4, which was rebuilt by every file that needed
    it). One per test, in that test's tmp_path."""
    out = tmp_path / "bus3.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(bus_jpg),
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                   check=True)
    return out


@pytest.fixture()
def client():
    """A TestClient for the app. The app is imported lazily (see
    module docstring) — the test module's own DATABASE_URL
    setdefaults win, and the engine is whatever the process already
    built."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def auth_user(client):
    """Register a fresh user (uuid email — no collisions across files
    sharing one DB) and return {"email", "headers", "user_id"}.
    user_id is resolved from the DB, never hardcoded (L12)."""
    from app.database import SessionLocal
    from app.models import User

    email = f"user-{uuid.uuid4().hex[:8]}@visioniq.test"
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    db = SessionLocal()
    try:
        user_id = db.query(User).filter_by(email=email).first().id
    finally:
        db.close()
    return {"email": email,
            "headers": {"Authorization": f"Bearer {token}"},
            "user_id": user_id}


@pytest.fixture()
def ready_video(client, auth_user, bus_video):
    """Upload the bus video for auth_user; returns the video dict
    (status == "ready", sync processing)."""
    with open(bus_video, "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=auth_user["headers"],
                        data={"title": "bus"}, files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()


@pytest.fixture()
def db_session():
    """A SessionLocal on the live engine (the one the process built).
    For assertions that need the DB, not the API."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
