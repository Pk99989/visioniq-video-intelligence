"""Phase 1 VLM e2e (2026-11-06): upload a real video through the real
pipeline with VLM_PROVIDER=ollama / VLM_MODEL=moondream and print the
stored caption + provider. The model must be loaded in Ollama already
(or the first call pays the load time; VLM retries cover it).

Run: VLM_PROVIDER=ollama VLM_MODEL=moondream python scripts/vlm_e2e.py
Requires: ollama serve running, moondream pulled.
"""
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/vlm-e2e/test.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/vlm-e2e/storage")
os.environ.setdefault("JWT_SECRET", "vlm-e2e-secret")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("VLM_PROVIDER", os.environ.get("VLM_PROVIDER", "ollama"))
os.environ.setdefault("VLM_MODEL", os.environ.get("VLM_MODEL", "moondream"))
os.environ.setdefault("VLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("VLM_TIMEOUT_SECONDS", "300")
os.environ.setdefault("VLM_MAX_RETRIES", "2")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

for p in ("/tmp/vlm-e2e/test.db", "/tmp/vlm-e2e/storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Caption, Detection, Frame, Scene  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
client.post("/api/v1/auth/register", json={"email": "vlm@test.com", "password": "password123"})
r = client.post("/api/v1/auth/login", json={"email": "vlm@test.com", "password": "password123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

t0 = time.monotonic()
with open("/home/hatch/workspace/your_files/sample-video-bus.mp4", "rb") as f:
    r = client.post("/api/v1/videos/upload", headers=headers, data={"title": "bus-vlm"},
                    files={"file": ("bus.mp4", f, "video/mp4")})
elapsed = time.monotonic() - t0
print("upload status:", r.status_code, r.json().get("status"), f"in {elapsed:.1f}s")
assert r.status_code == 201 and r.json()["status"] == "ready", r.text
vid = r.json()["id"]

db = SessionLocal()
caps = db.query(Caption).filter_by(video_id=vid).all()
for c in caps:
    print(f"CAPTION provider={c.provider!r} model={c.model!r} text={c.text!r}")
print("frames:", db.query(Frame).filter_by(video_id=vid).count(),
      "scenes:", db.query(Scene).filter_by(video_id=vid).count(),
      "detections:", db.query(Detection).filter_by(video_id=vid).count())
# Search must return the VLM caption
r = client.post("/api/v1/search", headers=headers, json={"query": "bus"})
hits = r.json().get("results", r.json()) if isinstance(r.json(), dict) else r.json()
print("search 'bus':", r.status_code, [(h["score"], h["caption"][:80]) for h in hits[:2]])
db.close()
