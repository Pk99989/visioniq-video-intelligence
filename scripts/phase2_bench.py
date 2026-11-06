"""Phase 2 benchmark (2026-11-06): measure adaptive sampling + dedupe on
real sample videos with the new pipeline, vs the old 1 fps baseline.

Old baseline (v0.3.1, 1 fps, no dedupe):
- bus 10 s: 10 frames, 1 scene, 50 detections (5/frame), ~9.1 s end-to-end (v0.3.1 live run)
- moving traffic 15 s: 15 frames, 61 detections (v0.3.0 on user's machine)

Run: SYNC_PROCESSING=1 python scripts/phase2_bench.py
Writes results to docs/benchmarks/2026-11-06-phase2.md (appended).
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/phase2bench/test.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/phase2bench/storage")
os.environ.setdefault("JWT_SECRET", "bench-secret")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("VLM_PROVIDER", "fallback")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import shutil

for p in ("/tmp/phase2bench/test.db", "/tmp/phase2bench/storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Caption, Detection, Frame, Scene  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

VIDEOS = [
    ("bus", "/home/hatch/workspace/your_files/sample-video-bus.mp4"),
    ("moving", "/home/hatch/workspace/your_files/sample-video-moving.mp4"),
]

client.post("/api/v1/auth/register", json={"email": "bench@test.com", "password": "password123"})
r = client.post("/api/v1/auth/login", json={"email": "bench@test.com", "password": "password123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

results = []
for name, path in VIDEOS:
    t0 = time.monotonic()
    with open(path, "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": name},
                        files={"file": (f"{name}.mp4", f, "video/mp4")})
    elapsed = time.monotonic() - t0
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert r.json()["status"] == "ready", r.json()
    db = SessionLocal()
    n_frames = db.query(Frame).filter_by(video_id=vid).count()
    n_scenes = db.query(Scene).filter_by(video_id=vid).count()
    n_det = db.query(Detection).filter_by(video_id=vid).count()
    labels = sorted({d.label for d in db.query(Detection).filter_by(video_id=vid).all()})
    caps = db.query(Caption).filter_by(video_id=vid).all()
    providers = sorted({c.provider for c in caps})
    db.close()
    results.append((name, Path(path).stat().st_size, elapsed, n_frames, n_scenes, n_det, labels, providers))
    print(f"{name}: {elapsed:.1f}s frames={n_frames} scenes={n_scenes} "
          f"detections={n_det} labels={labels} caption_providers={providers}")

print("\n--- summary ---")
for name, size, elapsed, n_frames, n_scenes, n_det, labels, providers in results:
    print(f"{name}: {elapsed:.1f}s, {n_frames} frames kept, {n_scenes} scenes, "
          f"{n_det} detections {labels}, captions: {providers}")
