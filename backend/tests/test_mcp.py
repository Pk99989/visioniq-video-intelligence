"""Phase 5 (v0.7.0) MCP tests — stdio JSON-RPC and the HTTP transport,
including the hardening: request ids preserved on errors, -32602 for
unknown tools / missing arguments, -32700 for malformed JSON, 400
(not 500) from HTTP for bad calls, and cross-user scoping.

Run: python -m pytest tests/test_mcp.py -q
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import BUS_JPG, TRAFFIC_JPG

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_mcp.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_mcp_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-mcp")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

for p in ("/tmp/visioniq_test_mcp.db", "/tmp/visioniq_test_mcp_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "mcp_server"))
import server as mcp_server  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
MCP_HTTP = TestClient(mcp_server.create_http_app(), raise_server_exceptions=False)
SERVER = [sys.executable, str(Path(__file__).resolve().parent.parent.parent / "mcp_server" / "server.py")]


def _auth(email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["access_token"]


def _upload(headers, title="Bus"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(BUS_JPG),
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": title},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()["id"]


def _stdio(requests):
    """Run the stdio server with a list of JSON-RPC request dicts (or
    raw strings) and return the parsed response lines. The subprocess
    gets the test process's own DATABASE_URL explicitly: in a full
    suite run the shared engine is bound to whichever test module
    was imported first (audit L12), so inheriting the ambient env
    would point the subprocess at a different database."""
    from app.config import settings
    from app.database import engine

    text = "\n".join(r if isinstance(r, str) else json.dumps(r) for r in requests) + "\n"
    env = {**os.environ, "DATABASE_URL": str(engine.url),
           "STORAGE_DIR": str(settings.STORAGE_DIR)}
    out = subprocess.run(SERVER, input=text, capture_output=True, text=True,
                         timeout=60, env=env)
    assert out.returncode == 0, out.stderr
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def video():
    h, token = _auth("mcp@test.com")
    return {"headers": h, "token": token, "id": _upload(h)}


def test_stdio_initialize_and_tools_list():
    responses = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ])
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "visioniq"
    tools = responses[1]["result"]["tools"]
    assert len(tools) == 8
    assert {t["name"] for t in tools} == {
        "video_search", "video_qa", "video_summarize", "clip_retrieval",
        "event_analysis", "detection_analytics", "timeline_analysis",
        "report_generation"}


def test_stdio_search_and_qa(video):
    responses = _stdio([
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "video_search",
                    "arguments": {"query": "bus", "video_id": video["id"]}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "video_qa",
                    "arguments": {"question": "Is there a bus?",
                                  "video_id": video["id"]}}},
    ])
    hits = json.loads(responses[0]["result"]["content"][0]["text"])
    assert hits and hits[0]["video_id"] == video["id"]
    qa = json.loads(responses[1]["result"]["content"][0]["text"])
    assert qa["citations"]


def test_stdio_unknown_tool_and_missing_args_return_32602_with_id():
    responses = _stdio([
        {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
         "params": {"name": "video_search", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 13, "method": "unknown/method", "params": {}},
    ])
    assert responses[0]["id"] == 11 and responses[0]["error"]["code"] == -32602
    assert responses[1]["id"] == 12 and responses[1]["error"]["code"] == -32602
    assert "Missing required" in responses[1]["error"]["message"]
    assert responses[2]["id"] == 13 and responses[2]["error"]["code"] == -32601


def test_stdio_malformed_json_returns_32700():
    responses = _stdio(["{not json", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}])
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 3 and len(responses[1]["result"]["tools"]) == 8


def test_http_tools_list_and_call(video):
    r = MCP_HTTP.get("/tools", headers={"Authorization": f"Bearer {video['token']}"})
    assert r.status_code == 200 and len(r.json()) == 8
    r = MCP_HTTP.post("/tools/call", headers={"Authorization": f"Bearer {video['token']}"},
                      json={"name": "detection_analytics",
                            "arguments": {"video_id": video["id"]}})
    assert r.status_code == 200
    assert r.json()["detection_count"] >= 1
    r = MCP_HTTP.post("/tools/call", headers={"Authorization": f"Bearer {video['token']}"},
                      json={"name": "timeline_analysis",
                            "arguments": {"video_id": video["id"]}})
    assert r.status_code == 200 and r.json()["scene_count"] >= 1


def test_http_rejects_bad_calls_with_400_not_500(video):
    h = {"Authorization": f"Bearer {video['token']}"}
    r = MCP_HTTP.post("/tools/call", headers=h,
                      json={"name": "no_such_tool", "arguments": {}})
    assert r.status_code == 400
    r = MCP_HTTP.post("/tools/call", headers=h,
                      json={"name": "video_search", "arguments": {}})
    assert r.status_code == 400
    r = MCP_HTTP.post("/tools/call", headers=h, json={"arguments": {}})
    assert r.status_code == 400
    r = MCP_HTTP.get("/tools")
    assert r.status_code == 401


def test_http_cross_user_scoping(video):
    other_h, other_token = _auth("mcp-other@test.com")
    r = MCP_HTTP.post("/tools/call",
                      headers={"Authorization": f"Bearer {other_token}"},
                      json={"name": "video_search",
                            "arguments": {"query": "bus"}})
    assert r.status_code == 200
    assert all(hit["video_id"] != video["id"] for hit in r.json())
    r = MCP_HTTP.post("/tools/call",
                      headers={"Authorization": f"Bearer {other_token}"},
                      json={"name": "detection_analytics",
                            "arguments": {"video_id": video["id"]}})
    assert r.status_code == 200 and r.json() == {"error": "Video not found"}
