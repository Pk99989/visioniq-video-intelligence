"""Phase 8 (v0.10.0) backend tests — pagination (L10), /stats,
chat history (M12), SSE status stream.

Run: python -m pytest tests/test_phase8_backend.py -q
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import BUS_JPG, TRAFFIC_JPG

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_p8.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_p8_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-p8")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

for p in ("/tmp/visioniq_test_p8.db", "/tmp/visioniq_test_p8_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.services import agent  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _auth(email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(headers, title="Bus"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(BUS_JPG),
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": title},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def setup():
    h = _auth("p8@test.com")
    vid = _upload(h)
    return {"headers": h, "video_id": vid}


def test_videos_pagination(setup):
    h = setup["headers"]
    r = client.get("/api/v1/videos?limit=1&offset=0", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert int(r.headers["x-total-count"]) >= 1
    total = int(r.headers["x-total-count"])
    r2 = client.get(f"/api/v1/videos?limit=1&offset={total}", headers=h)
    assert r2.json() == []
    # Validation: limit above the max and negative offset are rejected.
    assert client.get("/api/v1/videos?limit=101", headers=h).status_code == 422
    assert client.get("/api/v1/videos?offset=-1", headers=h).status_code == 422


def test_detections_events_frames_pagination(setup):
    h, vid = setup["headers"], setup["video_id"]
    r = client.get(f"/api/v1/videos/{vid}/detections?limit=2&offset=0", headers=h)
    assert r.status_code == 200
    total = int(r.headers["x-total-count"])
    assert total > 0 and len(r.json()) == min(2, total)
    r = client.get(f"/api/v1/videos/{vid}/frames?limit=1&offset=0", headers=h)
    assert r.status_code == 200 and int(r.headers["x-total-count"]) >= 1
    r = client.get(f"/api/v1/videos/{vid}/events?limit=5&offset=0", headers=h)
    assert r.status_code == 200 and "x-total-count" in r.headers
    r = client.get(f"/api/v1/videos/{vid}/alerts?limit=5&offset=0", headers=h)
    assert r.status_code == 200 and "x-total-count" in r.headers


def test_stats_endpoint(setup):
    h, vid = setup["headers"], setup["video_id"]
    r = client.get("/api/v1/stats", headers=h)
    assert r.status_code == 200
    s = r.json()
    assert s["videos_total"] >= 1 and s["videos_ready"] >= 1
    assert s["detections_total"] > 0
    assert any(x["label"] == "bus" for x in s["detections_by_label"])
    assert s["total_storage_bytes"] > 0
    assert s["total_duration_seconds"] > 0
    # A second user with no videos sees only their own (empty) stats.
    h2 = _auth("p8-other@test.com")
    s2 = client.get("/api/v1/stats", headers=h2).json()
    assert s2["videos_total"] == 0 and s2["detections_total"] == 0
    assert client.get("/api/v1/stats").status_code == 401


def test_sse_status_stream(setup):
    h, vid = setup["headers"], setup["video_id"]
    token = h["Authorization"].split(" ", 1)[1]
    with client.stream("GET", f"/api/v1/videos/{vid}/status-stream?token={token}") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        first = next(r.iter_lines())
        assert first.startswith("data: ")
        payload = json.loads(first[len("data: "):])
        assert payload["status"] == "ready"
    # No token at all: 401.
    assert client.get(f"/api/v1/videos/{vid}/status-stream").status_code == 401
    # Cross-user: 404 (video not visible), not a leak.
    h2 = _auth("p8-sse-other@test.com")
    token2 = h2["Authorization"].split(" ", 1)[1]
    assert client.get(f"/api/v1/videos/{vid}/status-stream?token={token2}").status_code == 404


def test_chat_followup_keeps_conversation(setup):
    h, vid = setup["headers"], setup["video_id"]
    r = client.post("/api/v1/chat", headers=h,
                    json={"question": "Is there a bus?", "video_id": vid})
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]
    r2 = client.post("/api/v1/chat", headers=h,
                     json={"question": "What colour is it?", "video_id": vid,
                           "conversation_id": conv_id})
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == conv_id
    conv = client.get(f"/api/v1/conversations/{conv_id}", headers=h).json()
    assert len(conv["messages"]) == 4  # user, assistant, user, assistant
    assert conv["messages"][1]["content"]  # first answer stored
    assert conv["messages"][2]["content"] == "What colour is it?"
    convs = client.get("/api/v1/conversations", headers=h).json()
    assert any(c["id"] == conv_id for c in convs)


class _CaptureLLM(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _CaptureLLM.seen.append(json.loads(self.rfile.read(n)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"choices": [{"message": {"content": "The bus is blue."}}]}).encode())

    def log_message(self, *a):
        pass


def test_llm_synthesis_receives_history(setup, monkeypatch):
    """M12: when an LLM provider is configured, the prior turns reach
    the synthesis prompt — follow-ups resolve in context."""
    server = HTTPServer(("127.0.0.1", 0), _CaptureLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(settings, "VLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(settings, "VLM_BASE_URL", url)
    monkeypatch.setattr(settings, "VLM_MODEL", "test-llm")
    monkeypatch.setattr(settings, "VLM_API_KEY", "")
    _CaptureLLM.seen.clear()
    db = SessionLocal()
    uid = db.query(User).filter_by(email="p8@test.com").first().id
    history = [{"role": "user", "content": "Is there a bus in the video?"},
               {"role": "assistant", "content": "Yes, a blue bus at 1.0s."}]
    result = agent.answer_question(db, "What colour is it?",
                                   video_id=setup["video_id"], user_id=uid,
                                   history=history)
    db.close()
    server.shutdown()
    assert result["answer"] == "The bus is blue."
    assert len(_CaptureLLM.seen) == 1
    prompt = _CaptureLLM.seen[0]["messages"][0]["content"]
    assert "Is there a bus in the video?" in prompt
    assert "blue bus at 1.0s" in prompt
    assert "What colour is it?" in prompt
