"""Phase 5 (v0.7.0) agent tests — 8-tool registry, deterministic
multi-step planning, the three new tools, and owner scoping.

Run: python -m pytest tests/test_agent.py -q
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_agent.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_agent_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-agent")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

for p in ("/tmp/visioniq_test_agent.db", "/tmp/visioniq_test_agent_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

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
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", "/tmp/bus.jpg",
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": title},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()["id"]


def _db():
    return SessionLocal()


@pytest.fixture(scope="module")
def video():
    h = _auth("agent@test.com")
    return {"headers": h, "id": _upload(h)}


def test_registry_has_eight_tools_with_schemas():
    assert len(agent.TOOLS) == 8
    names = {t["name"] for t in agent.TOOLS}
    assert names == {"video_search", "video_qa", "video_summarize", "clip_retrieval",
                     "event_analysis", "detection_analytics", "timeline_analysis",
                     "report_generation"}
    for t in agent.TOOLS:
        assert t["inputSchema"]["type"] == "object"
        assert isinstance(t["inputSchema"]["required"], list)


def test_plan_single_and_multi_step():
    assert agent._plan("Is there a bus?") == ["video_qa"]
    assert agent._plan("Summarize the video") == ["video_summarize"]
    assert agent._plan("What events happened?") == ["event_analysis"]
    assert agent._plan("Show me the timeline") == ["timeline_analysis"]
    assert agent._plan("How many detections are there?") == ["detection_analytics"]
    assert agent._plan("Generate a report") == ["report_generation"]
    assert agent._plan("Summarize the video and find clips of the bus") == [
        "video_summarize", "clip_retrieval"]
    # "how many people" is a QA question (VLM caption), not analytics.
    assert agent._plan("How many people are in the video?") == ["video_qa"]


def test_detection_analytics_tool(video):
    db = _db()
    uid = db.query(User).filter_by(email="agent@test.com").first().id
    result = agent.run_tool("detection_analytics", db, {"video_id": video["id"]}, user_id=uid)
    db.close()
    assert result["detection_count"] >= 1
    assert "bus" in result["detections_by_label"]
    assert result["track_count"] >= 1
    assert "longest_dwell_seconds" in result


def test_timeline_analysis_tool(video):
    db = _db()
    uid = db.query(User).filter_by(email="agent@test.com").first().id
    result = agent.run_tool("timeline_analysis", db, {"video_id": video["id"]}, user_id=uid)
    db.close()
    assert result["scene_count"] >= 1
    assert result["timeline"][0]["captions"]
    assert "bus" in result["timeline"][0]["detections"]


def test_report_generation_tool(video):
    from app.config import settings

    db = _db()
    uid = db.query(User).filter_by(email="agent@test.com").first().id
    result = agent.run_tool("report_generation", db, {"video_id": video["id"]}, user_id=uid)
    db.close()
    assert result["report_id"] and result["download_url"].startswith("/api/v1/reports/")
    # Storage dir is the shared engine's (audit L12), not necessarily
    # this file's own STORAGE_DIR — read it from settings.
    path = Path(settings.STORAGE_DIR) / "reports" / str(video["id"]) / "report_summary.json"
    assert path.exists()


def test_multi_step_chat_combines_tools(video):
    r = client.post("/api/v1/chat", headers=video["headers"],
                    json={"question": "Summarize the video and find clips of the bus",
                          "video_id": video["id"]})
    assert r.status_code == 200
    body = r.json()
    assert body["tool"] == "multi_step"
    assert body["steps"] == ["video_summarize", "clip_retrieval"]
    assert "video_summarize" in body["answer"] and "clip_retrieval" in body["answer"]
    assert len(body["citations"]) >= 1


def test_single_step_chat_unchanged(video):
    r = client.post("/api/v1/chat", headers=video["headers"],
                    json={"question": "Is there a bus in the video?",
                          "video_id": video["id"]})
    assert r.status_code == 200
    assert r.json()["tool"] == "search_qa"
    assert r.json()["citations"]


def test_tools_are_owner_scoped(video):
    other = _auth("agent-other@test.com")
    db = _db()
    other_id = db.query(User).filter_by(email="agent-other@test.com").first().id
    result = agent.run_tool("detection_analytics", db, {"video_id": video["id"]},
                            user_id=other_id)
    db.close()
    assert result == {"error": "Video not found"}
    # The chat endpoint itself 404s on a video the caller cannot see.
    r = client.post("/api/v1/chat", headers=other,
                    json={"question": "Summarize the video", "video_id": video["id"]})
    assert r.status_code == 404


def test_agent_tools_endpoint_lists_eight(video):
    r = client.get("/api/v1/agent/tools", headers=video["headers"])
    assert r.status_code == 200 and len(r.json()) == 8
