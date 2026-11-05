"""Phase 3 tests: range streaming + signed URLs, clip extraction,
detections/analytics/annotated frames, logout revocation, password reset.
Run: SYNC_PROCESSING=1 python -m pytest tests/test_phase3.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test3.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test3_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-phase3")

import shutil

for p in ("/tmp/visioniq_test3.db", "/tmp/visioniq_test3_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _auth(email="p3@test.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["access_token"]


def _upload_bus_video(headers):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", "/tmp/bus.jpg",
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": "Bus3"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ready", r.json()
    return r.json()["id"]


def test_range_streaming_and_signed_url():
    headers, _ = _auth()
    vid = _upload_bus_video(headers)
    # Full stream: 200
    r = client.get(f"/api/v1/videos/{vid}/stream", headers=headers)
    assert r.status_code == 200, r.text
    assert int(r.headers["content-length"]) > 10000
    # Range: 206 with Content-Range
    r = client.get(f"/api/v1/videos/{vid}/stream", headers={**headers, "Range": "bytes=0-99"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"].startswith("bytes 0-99/")
    assert len(r.content) == 100
    assert r.headers["accept-ranges"] == "bytes"
    # Invalid range: 416
    r = client.get(f"/api/v1/videos/{vid}/stream", headers={**headers, "Range": "bytes=99999999-"})
    assert r.status_code == 416
    # Signed URL works with no bearer token
    r = client.get(f"/api/v1/videos/{vid}/stream-url", headers=headers)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert "token=" in url
    r = client.get(url)  # no headers
    assert r.status_code == 200, r.text
    r = client.get(url, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    # Tampered token: 401
    r = client.get(f"/api/v1/videos/{vid}/stream?token={url.split('token=')[1]}x")
    assert r.status_code == 401
    # No auth at all: 401
    assert client.get(f"/api/v1/videos/{vid}/stream").status_code == 401


def test_clip_detections_analytics_annotated():
    headers, _ = _auth("p3b@test.com")
    vid = _upload_bus_video(headers)
    # Detections: bus + person present
    r = client.get(f"/api/v1/videos/{vid}/detections", headers=headers)
    assert r.status_code == 200, r.text
    labels = {d["label"] for d in r.json()}
    assert "bus" in labels and "person" in labels, labels
    assert len(r.json()) >= 5
    # Analytics
    r = client.get(f"/api/v1/videos/{vid}/analytics", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["detection_count"] >= 5
    assert r.json()["detections_by_label"]["bus"] >= 1
    assert r.json()["scene_count"] >= 1
    # Clip 0-2s: real mp4, ~2s
    r = client.get(f"/api/v1/videos/{vid}/clip?start=0&end=2", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 5000
    # Clip validation
    assert client.get(f"/api/v1/videos/{vid}/clip?start=2&end=1", headers=headers).status_code == 400
    assert client.get(f"/api/v1/videos/{vid}/clip?start=0&end=99", headers=headers).status_code == 400
    # Cross-user clip: 404
    other, _ = _auth("p3c@test.com")
    assert client.get(f"/api/v1/videos/{vid}/clip?start=0&end=2", headers=other).status_code == 404
    # Annotated frame
    frames = client.get(f"/api/v1/videos/{vid}/frames", headers=headers).json()
    fid = frames[0]["id"]
    r = client.get(f"/api/v1/videos/{vid}/frames/{fid}/annotated", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 1000


def test_logout_revocation_and_password_reset():
    headers, token = _auth("p3d@test.com")
    # Token works
    assert client.get("/api/v1/videos", headers=headers).status_code == 200
    # Logout revokes it
    r = client.post("/api/v1/auth/logout", headers=headers)
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/videos", headers=headers).status_code == 401
    # Password reset: request -> reset -> new password works, old fails
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "p3d@test.com"})
    assert r.status_code == 200 and "reset_token" in r.json(), r.text
    reset_token = r.json()["reset_token"]
    # Wrong token fails
    assert client.post("/api/v1/auth/password-reset",
                       json={"token": "wrong", "new_password": "newpassword123"}).status_code == 400
    r = client.post("/api/v1/auth/password-reset",
                    json={"token": reset_token, "new_password": "newpassword123"})
    assert r.status_code == 200, r.text
    # Token is single-use
    assert client.post("/api/v1/auth/password-reset",
                       json={"token": reset_token, "new_password": "another123"}).status_code == 400
    # Old password fails, new works
    assert client.post("/api/v1/auth/login",
                       json={"email": "p3d@test.com", "password": "password123"}).status_code == 401
    r = client.post("/api/v1/auth/login",
                    json={"email": "p3d@test.com", "password": "newpassword123"})
    assert r.status_code == 200, r.text
    # Unknown email: still 200, no token leaked
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "nobody@test.com"})
    assert r.status_code == 200 and "reset_token" not in r.json()
