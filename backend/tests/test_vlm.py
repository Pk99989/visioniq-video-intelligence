"""Phase 1 (v0.4.0) VLM tests — structured JSON captions, retries,
malformed-output handling, provider tiers, health checks.

All tests use real local mock HTTP servers (no real model, no network).
The real-model end-to-end run lives in docs/benchmarks/ (Ollama) and in
the e2e test, not here.

Run: python -m pytest tests/test_vlm.py -q
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_vlm.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_vlm_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-vlm")

from app.config import settings  # noqa: E402
from app.services import vlm  # noqa: E402


def _make_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _set_vlm(provider, base_url, model="test-vlm", retries=2, timeout=10):
    settings.VLM_PROVIDER = provider
    settings.VLM_BASE_URL = base_url
    settings.VLM_MODEL = model
    settings.VLM_MAX_RETRIES = retries
    settings.VLM_TIMEOUT_SECONDS = timeout
    settings.VLM_RETRY_BACKOFF_SECONDS = 0.01


def _frame(tmp_path):
    p = tmp_path / "frame.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    return str(p)


def _scene():
    return {"index": 0, "start_seconds": 0.0, "end_seconds": 9.0}


class _JsonOK(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        payload = {"choices": [{"message": {"content": json.dumps({
            "description": "A busy street with a bus and people walking.",
            "objects": ["bus", "person"],
            "actions": ["walking"]})}}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = json.dumps({"data": [{"id": "test-vlm"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _FlakyThenOK(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        type(self).calls += 1
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if type(self).calls < 3:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = {"choices": [{"message": {"content": json.dumps({
            "description": "A street after retries.",
            "objects": ["bus"], "actions": []})}}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Malformed(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        # Not JSON at all — the client must use the raw text, not crash.
        payload = {"choices": [{"message": {"content": "A plain sentence, no JSON here."}}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Always500(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_structured_json_caption(tmp_path):
    server, url = _make_server(_JsonOK)
    try:
        _set_vlm("ollama", url)
        text, provider = vlm.caption_scene(_scene(), ["bus", "person"], _frame(tmp_path))
        assert provider == "ollama", provider
        assert "busy street" in text
        assert "Visible: bus, person" in text
        assert "Actions: walking" in text
        assert "Template" not in text
    finally:
        server.shutdown()


def test_retry_then_success(tmp_path):
    _FlakyThenOK.calls = 0
    server, url = _make_server(_FlakyThenOK)
    try:
        _set_vlm("ollama", url, retries=2)
        text, provider = vlm.caption_scene(_scene(), ["bus"], _frame(tmp_path))
        assert provider == "ollama", provider
        assert "after retries" in text
        assert _FlakyThenOK.calls == 3
    finally:
        server.shutdown()


def test_malformed_json_uses_raw_text(tmp_path):
    server, url = _make_server(_Malformed)
    try:
        _set_vlm("ollama", url)
        text, provider = vlm.caption_scene(_scene(), ["bus"], _frame(tmp_path))
        assert provider == "ollama", provider
        assert text == "A plain sentence, no JSON here."
    finally:
        server.shutdown()


def test_vlm_failure_falls_back_to_detection_tier(tmp_path):
    server, url = _make_server(_Always500)
    try:
        _set_vlm("ollama", url, retries=1)
        text, provider = vlm.caption_scene(_scene(), ["bus", "person"], _frame(tmp_path))
        assert provider == "detection", provider
        assert "Detected: bus, person" in text
        assert "Detection description" in text
        assert "Template caption" not in text
    finally:
        server.shutdown()


def test_no_vlm_no_detections_is_template(tmp_path):
    _set_vlm("fallback", "")
    text, provider = vlm.caption_scene(_scene(), [], _frame(tmp_path))
    assert provider == "fallback", provider
    assert "Template caption" in text


def test_health_ok_and_error():
    server, url = _make_server(_JsonOK)
    try:
        _set_vlm("ollama", url, model="test-vlm")
        h = vlm.check_health()
        assert h["status"] == "ok", h
        assert h["model"] == "test-vlm"
        assert "latency_ms" in h
    finally:
        server.shutdown()
    server, url = _make_server(_Always500)
    try:
        _set_vlm("ollama", url, model="test-vlm")
        h = vlm.check_health()
        assert h["status"] == "error", h
    finally:
        server.shutdown()
    _set_vlm("fallback", "")
    assert vlm.check_health()["status"] == "disabled"
