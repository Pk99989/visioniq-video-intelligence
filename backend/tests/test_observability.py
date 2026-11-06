"""Observability tests (Phase 10, v0.12.0).

- /metrics serves real Prometheus counters after an upload + search.
- X-Request-ID is echoed on the response and honoured when supplied.
- The JSON log formatter emits parseable lines with request_id/job_id.
- Runtime gauges (disk, DB pool) are present; Celery queue depth is
  -1 (unknown) on the laptop profile instead of a misleading 0.
- METRICS_ENABLED=0 turns /metrics off (404).

Run: python -m pytest tests/test_observability.py -q
"""
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_obs2.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_obs2_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-obs")

import shutil

for p in ("/tmp/visioniq_test_obs2.db", "/tmp/visioniq_test_obs2_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.logging_config import (  # noqa: E402
    JsonFormatter, request_id_ctx, set_job_id, set_request_id)

client = TestClient(app, raise_server_exceptions=False)


def _auth(email="obs@test.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(headers):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", "/tmp/bus.jpg",
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", data={"title": "obs"},
                        files={"file": ("bus.mp4", f, "video/mp4")},
                        headers={**headers, "X-Request-ID": "obs-upload-1"})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()["id"]


def test_metrics_endpoint_serves_counters():
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    for name in ("visioniq_http_requests_total",
                 "visioniq_http_request_duration_seconds",
                 "visioniq_video_processing_duration_seconds",
                 "visioniq_video_processing_jobs_total",
                 "visioniq_detection_seconds",
                 "visioniq_qdrant_search_seconds",
                 "visioniq_storage_disk_free_bytes",
                 "visioniq_db_pool_size",
                 "process_resident_memory_bytes"):
        assert name in body, f"{name} missing from /metrics"


def test_request_id_echoed_and_honoured():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID"), "a request id must be minted"
    assert len(r.headers["X-Request-ID"]) >= 8
    r2 = client.get("/health", headers={"X-Request-ID": "client-supplied-42"})
    assert r2.headers["X-Request-ID"] == "client-supplied-42"


def _metric_value(body: str, name: str) -> float:
    """Value of a counter line `name 1.0` (no labels) or the sum over
    its labelled lines. Counters are process-global, so tests assert
    deltas, never absolute values."""
    total = 0.0
    found = False
    for line in body.splitlines():
        if line.startswith(name) and (" " in line or "\t" in line):
            total += float(line.rsplit(None, 1)[-1])
            found = True
    assert found, f"{name} missing from /metrics"
    return total


def _qdrant_live() -> bool:
    """True when a Qdrant server answers on localhost (the search
    only takes the Qdrant read path when QDRANT_URL is set)."""
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:6333/", timeout=2)
        return True
    except Exception:
        return False


def test_pipeline_metrics_after_upload_and_search(monkeypatch):
    h = _auth()
    before = client.get("/metrics").text
    jobs_before = _metric_value(before, "visioniq_video_processing_jobs_total{status=\"done\"}")
    dur_before = _metric_value(before, "visioniq_video_processing_duration_seconds_count")
    det_before = _metric_value(before, "visioniq_detection_seconds_count")
    qdrant_before = _metric_value(before, "visioniq_qdrant_search_seconds_count")
    vid = _upload(h)
    # Point search at the live Qdrant server when there is one, so
    # the read path is exercised (in CI's unit job there is no server
    # and search falls back to the DB scan — the counter then stays
    # flat and the assertion is skipped).
    if _qdrant_live():
        monkeypatch.setattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
    r = client.post("/api/v1/search", headers=h, json={"query": "bus"})
    assert r.status_code == 200, r.text
    body = client.get("/metrics").text
    assert _metric_value(body, "visioniq_video_processing_jobs_total{status=\"done\"}") == jobs_before + 1
    assert _metric_value(body, "visioniq_video_processing_duration_seconds_count") == dur_before + 1
    # At least one frame was detected (bus video).
    assert _metric_value(body, "visioniq_detection_seconds_count") > det_before
    if _qdrant_live():
        assert _metric_value(body, "visioniq_qdrant_search_seconds_count") > qdrant_before
    # Route template, not raw path, in the label (no per-video series).
    assert '/api/v1/videos/{video_id}' in body or 'route="/api/v1/videos/upload"' in body
    assert f'route="/api/v1/videos/{vid}"' not in body


def test_celery_queue_unknown_without_celery():
    body = client.get("/metrics").text
    assert "visioniq_celery_queue_depth -1.0" in body


def test_metrics_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_ENABLED", False)
    assert client.get("/metrics").status_code == 404
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    assert client.get("/metrics").status_code == 200


def test_json_formatter_emits_parseable_lines():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    lg = logging.getLogger("visioniq.test-format")
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    rid = set_request_id("fmt-req-9")
    jid = set_job_id(77)
    try:
        lg.info("hello %s", "world", extra={"video_id": 3})
        lg.warning("a warning")
    finally:
        request_id_ctx.reset(rid)
        from app.services.logging_config import job_id_ctx
        job_id_ctx.reset(jid)
    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
    assert len(lines) == 2
    first = lines[0]
    assert first["level"] == "INFO" and first["logger"] == "visioniq.test-format"
    assert first["msg"] == "hello world"
    assert first["request_id"] == "fmt-req-9" and first["job_id"] == 77
    assert first["video_id"] == 3
    assert "ts" in first and first["ts"].endswith("+00:00")
    assert lines[1]["request_id"] == "fmt-req-9"
    # After reset, a new record carries no request id.
    lg.info("after reset")
    last = json.loads(buf.getvalue().splitlines()[-1])
    assert "request_id" not in last
