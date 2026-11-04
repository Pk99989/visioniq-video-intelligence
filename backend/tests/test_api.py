"""End-to-end API tests (no mocks for the pipeline itself): a real ffmpeg
test video is uploaded, processed synchronously, then searched, chatted
with, summarised, event-evaluated and reported on. Run:
    SYNC_PROCESSING=1 python -m pytest tests/ -q
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["SYNC_PROCESSING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/visioniq_test.db"
os.environ["STORAGE_DIR"] = "/tmp/visioniq_test_storage"
os.environ["JWT_SECRET"] = "test-secret"

# Fresh DB/storage for every test session
import shutil

for p in ("/tmp/visioniq_test.db", "/tmp/visioniq_test_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from app.main import app  # noqa: E402

client = TestClient(app)


def make_video(path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=3:size=320x240:rate=10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True)


def auth_headers() -> dict:
    client.post("/api/v1/auth/register",
                json={"email": "tester@visioniq.test", "password": "password123"})
    r = client.post("/api/v1/auth/login",
                    json={"email": "tester@visioniq.test", "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_flow():
    headers = auth_headers()
    video_path = Path("/tmp/visioniq_sample.mp4")
    make_video(video_path)
    with video_path.open("rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers,
                        data={"title": "Sample"}, files={"file": ("sample.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    video = r.json()
    assert video["status"] == "ready", video
    assert video["duration_seconds"] is not None and abs(video["duration_seconds"] - 3.0) < 0.5
    vid = video["id"]

    r = client.get(f"/api/v1/videos/{vid}/scenes", headers=headers)
    assert r.status_code == 200 and len(r.json()) >= 1
    r = client.get(f"/api/v1/videos/{vid}/captions", headers=headers)
    assert r.status_code == 200 and len(r.json()) >= 1
    assert r.json()[0]["provider"] == "fallback"  # honest: no VLM configured in tests

    r = client.post("/api/v1/search", headers=headers,
                    json={"query": "scene", "video_id": vid, "top_k": 5})
    assert r.status_code == 200 and len(r.json()) >= 1
    assert r.json()[0]["timestamp_seconds"] >= 0

    r = client.post("/api/v1/chat", headers=headers,
                    json={"question": "What is in this video?", "video_id": vid})
    assert r.status_code == 200 and len(r.json()["citations"]) >= 1

    r = client.post("/api/v1/chat", headers=headers,
                    json={"question": "zzzzqqq no such thing in video", "video_id": vid})
    # Empty retrieval must not be papered over with a confident answer.
    assert r.status_code == 200
    assert "No video evidence" in r.json()["answer"]
    assert r.json()["citations"] == []

    r = client.get(f"/api/v1/videos/{vid}/summary", headers=headers)
    assert r.status_code == 200 and r.json()["scene_count"] >= 1

    r = client.post(f"/api/v1/videos/{vid}/events/evaluate", headers=headers,
                    json=[{"name": "long-scene", "rule_type": "scene_duration_gt",
                           "value": "0.5", "severity": "warning"}])
    assert r.status_code == 200
    r = client.get(f"/api/v1/videos/{vid}/events", headers=headers)
    assert r.status_code == 200

    r = client.post("/api/v1/reports", headers=headers,
                    json={"video_id": vid, "kind": "summary", "format": "pdf"})
    assert r.status_code == 201, r.text
    report_id = r.json()["id"]
    r = client.get(f"/api/v1/reports/{report_id}/download", headers=headers)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # Security: unauthenticated access is rejected, and a second user
    # cannot read the first user's video.
    assert client.get(f"/api/v1/videos/{vid}").status_code == 401
    client.post("/api/v1/auth/register",
                json={"email": "other@visioniq.test", "password": "password123"})
    r2 = client.post("/api/v1/auth/login",
                     json={"email": "other@visioniq.test", "password": "password123"})
    other = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert client.get(f"/api/v1/videos/{vid}", headers=other).status_code == 404

    r = client.delete(f"/api/v1/videos/{vid}", headers=headers)
    assert r.status_code == 204


def test_upload_validation():
    headers = auth_headers()
    r = client.post("/api/v1/videos/upload", headers=headers, data={"title": "bad"},
                    files={"file": ("evil.txt", b"not a video", "text/plain")})
    assert r.status_code == 400
