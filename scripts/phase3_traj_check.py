"""Phase 3 trajectories check (2026-11-06): upload the moving-traffic
video, then GET /trajectories and print the track summaries.
Run: SYNC_PROCESSING=1 python scripts/phase3_traj_check.py
"""
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/phase3traj/test.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/phase3traj/storage")
os.environ.setdefault("JWT_SECRET", "traj-secret")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("VLM_PROVIDER", "fallback")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

for p in ("/tmp/phase3traj/test.db", "/tmp/phase3traj/storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
client.post("/api/v1/auth/register", json={"email": "traj@test.com", "password": "password123"})
r = client.post("/api/v1/auth/login", json={"email": "traj@test.com", "password": "password123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

t0 = time.monotonic()
with open("/home/hatch/workspace/your_files/sample-video-moving.mp4", "rb") as f:
    r = client.post("/api/v1/videos/upload", headers=headers, data={"title": "moving-traj"},
                    files={"file": ("moving.mp4", f, "video/mp4")})
print(f"upload: {r.status_code} {r.json().get('status')} in {time.monotonic()-t0:.1f}s")
vid = r.json()["id"]
r = client.get(f"/api/v1/videos/{vid}/trajectories", headers=headers)
print("trajectories status:", r.status_code, "count:", len(r.json()))
for t in r.json():
    print(f"  track {t['track_id']} {t['label']}: {t['first_seen_seconds']}s -> "
          f"{t['last_seen_seconds']}s, dwell {t['dwell_seconds']}s, "
          f"frames {t['frames_seen']}, displacement {t['displacement_px']}px")
# Cross-user: another user must get 404, not the trajectories.
client.post("/api/v1/auth/register", json={"email": "other@test.com", "password": "password123"})
r2 = client.post("/api/v1/auth/login", json={"email": "other@test.com", "password": "password123"})
h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
r = client.get(f"/api/v1/videos/{vid}/trajectories", headers=h2)
print("cross-user trajectories status (expect 404):", r.status_code)
