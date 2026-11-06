"""Phase 1 VLM end-to-end test — real model, skipped unless
VISIONIQ_VLM_E2E=1 and Ollama is reachable with the configured model.

Same flow as scripts/vlm_e2e.py: upload → frame extraction → VLM
caption → embeddings → search. Asserts the stored caption has
provider='ollama' (a real model caption, never a template) and that
search returns it.

Run (model must be loaded or loadable within the VLM timeout):
  VISIONIQ_VLM_E2E=1 VLM_PROVIDER=ollama VLM_MODEL=moondream \
    VLM_BASE_URL=http://localhost:11434/v1 \
    python -m pytest tests/test_vlm_e2e.py -q
"""
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_vlm_e2e.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_vlm_e2e_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-vlm-e2e")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

import httpx  # noqa: E402

VLM_BASE = os.environ.get("VLM_BASE_URL", "http://localhost:11434/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "moondream")

# Phase 11: the vlm marker (the whole file needs a real model).
pytestmark = pytest.mark.vlm

needs_vlm = pytest.mark.skipif(
    os.environ.get("VISIONIQ_VLM_E2E") != "1",
    reason="real-VLM e2e only runs with VISIONIQ_VLM_E2E=1")


def _vlm_reachable() -> bool:
    try:
        # trust_env=False: this VM's NO_PROXY has bracketed IPv6
        # entries that httpx rejects (same crash as retrieval.py).
        with httpx.Client(trust_env=False, timeout=10) as client:
            r = client.get(f"{VLM_BASE}/models")
        models = [m.get("id") for m in r.json().get("data", [])]
        # Ollama tags models ("moondream:latest"); bare names match too.
        return any(m == VLM_MODEL or m.startswith(VLM_MODEL + ":") for m in models)
    except Exception:
        return False


@needs_vlm
def test_vlm_e2e_real_model():
    if not _vlm_reachable():
        pytest.skip(f"model {VLM_MODEL!r} not listed at {VLM_BASE}/models")
    for p in ("/tmp/visioniq_test_vlm_e2e.db", "/tmp/visioniq_test_vlm_e2e_storage"):
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    os.environ["VLM_PROVIDER"] = "ollama"
    os.environ["VLM_MODEL"] = VLM_MODEL
    os.environ["VLM_BASE_URL"] = VLM_BASE

    from fastapi.testclient import TestClient  # noqa: E402

    from app.database import SessionLocal  # noqa: E402
    from app.main import app  # noqa: E402
    from app.models import Caption  # noqa: E402

    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/v1/auth/register",
                json={"email": "vlme2e@test.com", "password": "password123"})
    r = client.post("/api/v1/auth/login",
                    json={"email": "vlme2e@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    video = Path(__file__).resolve().parent.parent.parent / "your_files" / "sample-video-bus.mp4"
    if not video.exists():
        video = Path("/tmp/bus3.mp4")
    with open(video, "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers,
                        data={"title": "vlm-e2e"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    db = SessionLocal()
    caps = db.query(Caption).filter_by(video_id=r.json()["id"]).all()
    db.close()
    assert caps, "no captions stored"
    assert any(c.provider == "ollama" for c in caps), \
        f"no real VLM caption stored: {[(c.provider, c.text[:60]) for c in caps]}"
    assert any("bus" in c.text.lower() for c in caps), "caption does not mention the bus"
    r = client.post("/api/v1/search", headers=headers, json={"query": "bus"})
    assert r.status_code == 200 and r.json(), r.text
    assert r.json()[0]["score"] > 0.5
