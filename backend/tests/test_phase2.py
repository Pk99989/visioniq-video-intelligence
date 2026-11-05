"""Phase 2 tests — all verified without a GPU, Docker, or a real VLM.

* VLM: an OpenAI-compatible mock HTTP server (httpx MockTransport is
  not used; a real local server is started so the client code path,
  including base64 image upload, is exercised end to end).
* Qdrant: in-memory client, collection creation + upsert + search.
* Celery: task.apply() runs synchronously (eager) without Redis.
* Embeddings: hash is deterministic; fastembed is exercised only when
  EMBEDDING_PROVIDER=fastembed is set AND the model downloads — the
  benchmark script, not this suite, measures it.
* Detection: provider_status() is honest when no weights are present;
  the ONNX path is exercised in the benchmark when weights exist.
Run: SYNC_PROCESSING=1 python -m pytest tests/test_phase2.py -q
"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_storage")
os.environ.setdefault("JWT_SECRET", "test-secret")


class _MockVLM(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = (b'{"choices": [{"message": {"content": '
                b'"A busy street with people and a bus."}}]}')
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def test_vlm_openai_compatible_mock(tmp_path):
    """A real Ollama/NIM-style /chat/completions server returns a caption."""
    from app.services import vlm

    server = HTTPServer(("127.0.0.1", 0), _MockVLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    # Monkeypatch settings for this test only.
    vlm.settings.VLM_PROVIDER = "ollama"
    vlm.settings.VLM_BASE_URL = f"http://127.0.0.1:{port}"
    vlm.settings.VLM_MODEL = "llava"
    try:
        text, provider = vlm.caption_scene(
            {"index": 0, "start_seconds": 0.0, "end_seconds": 1.0}, [], str(frame))
        assert provider == "ollama", provider
        assert "busy street" in text
    finally:
        server.shutdown()
        vlm.settings.VLM_PROVIDER = "fallback"
        vlm.settings.VLM_BASE_URL = ""


def test_qdrant_in_memory():
    from app.config import settings
    from app.services import retrieval
    from app.services.embeddings import hash_embedding

    settings.QDRANT_URL = ":memory:"
    try:
        assert retrieval.ensure_qdrant_collection() is True
        vec = hash_embedding("a person walking in a street")
        assert retrieval.try_qdrant_upsert(1, vec, {"video_id": 1}) is True
        hits = retrieval.qdrant_search(vec, top_k=5)
        assert len(hits) >= 1
        assert hits[0].id == 1
        assert hits[0].score > 0.9
    finally:
        settings.QDRANT_URL = ""


def test_celery_task_eager():
    from app.services.celery_app import celery_app, process_video_task

    celery_app.conf.task_always_eager = True
    try:
        # Unknown video id: process_video returns silently, task succeeds.
        result = process_video_task.apply(args=[999999])
        assert result.successful()
    finally:
        celery_app.conf.task_always_eager = False


def test_detection_unavailable_without_weights(tmp_path, monkeypatch):
    from app.services import detection

    monkeypatch.setattr(detection, "_find_weights", lambda suffix: None)
    status = detection.provider_status()
    assert status["available"] is False
    assert detection.detect_frame(str(tmp_path / "x.jpg")) == []


def test_hash_embedding_deterministic():
    from app.services.embeddings import cosine, hash_embedding

    a = hash_embedding("person walking street")
    b = hash_embedding("person walking street")
    c = hash_embedding("quantum physics lecture")
    assert a == b
    assert len(a) == 384
    assert cosine(a, b) == 1.0
    assert cosine(a, c) < cosine(a, b)
