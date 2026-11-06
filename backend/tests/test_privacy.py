"""Privacy regression tests: search, chat and agent tools must never leak
one user's videos to another user.

Found by the Playwright e2e test (2026-11-06): /search returned captions
from ALL users because search_frames() had no owner filter, so the first
search hit belonged to another user and its clip download 404'd. The fix
scopes search_frames()/answer_question() and the MCP tools to the
logged-in user (admins see all, as with video_visible_to).

Run: SYNC_PROCESSING=1 python -m pytest tests/test_privacy.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import BUS_JPG, TRAFFIC_JPG

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_privacy.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_privacy_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-privacy")

import shutil

for p in ("/tmp/visioniq_privacy.db", "/tmp/visioniq_privacy_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _auth(email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload_bus_video(headers):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(BUS_JPG),
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus_privacy.mp4"],
                   check=True)
    with open("/tmp/bus_privacy.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": "Bus"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ready", r.json()
    return r.json()["id"]


def test_search_and_chat_do_not_leak_across_users():
    alice = _auth("alice@test.com")
    bob = _auth("bob@test.com")
    vid_alice = _upload_bus_video(alice)
    vid_bob = _upload_bus_video(bob)
    assert vid_alice != vid_bob

    # Search as Alice: only her own video's hits.
    r = client.post("/api/v1/search", headers=alice, json={"query": "bus", "top_k": 20})
    assert r.status_code == 200, r.text
    assert r.json(), "Alice should find her own video"
    assert {h["video_id"] for h in r.json()} == {vid_alice}

    # Search as Bob: only his own video's hits.
    r = client.post("/api/v1/search", headers=bob, json={"query": "bus", "top_k": 20})
    assert r.status_code == 200, r.text
    assert {h["video_id"] for h in r.json()} == {vid_bob}

    # Chat as Alice must not cite Bob's video.
    r = client.post("/api/v1/chat", headers=alice, json={"question": "is there a bus?"})
    assert r.status_code == 200, r.text
    cited = {c["video_id"] for c in r.json().get("citations", [])}
    assert cited <= {vid_alice}, f"chat leaked Bob's video: {cited}"

    # Alice cannot clip Bob's video (ownership check, 404).
    r = client.get(f"/api/v1/videos/{vid_bob}/clip?start=0&end=2", headers=alice)
    assert r.status_code == 404, r.text
