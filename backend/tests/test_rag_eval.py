"""RAG evaluation as a regression test (Phase 11; the eval itself is
Phase 4, scripts/rag_eval.py + tests/data/rag_eval.jsonl).

Runs the 54-question dataset against the production config (Qdrant
read path, no reranker) on the real corpus (three sample videos with
real moondream captions) and asserts the measured quality does not
regress below the 2026-11-06 baseline (R@5 0.66, MRR 0.48,
faithfulness 1.0, relevance 0.95, negatives 0.38 — see
docs/benchmarks/rag-eval-2026-11-06.md). Thresholds are set below
the baseline to allow for moondream's run-to-run caption variance
(about ±0.05), not to pass a broken system.

Slow on CPU (~10 min: 3 videos with VLM captions + 54 questions,
each positive answer calls the VLM once). Runs only with
VISIONIQ_VLM_E2E=1 and a reachable Ollama + Qdrant; the full
4-config comparison (A/B/C/D) stays in scripts/rag_eval.py.
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_rag.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_rag_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-rag")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("VLM_PROVIDER", "ollama")
os.environ.setdefault("VLM_MODEL", "moondream")
os.environ.setdefault("VLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("VLM_TIMEOUT_SECONDS", "300")
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")

import shutil

for p in ("/tmp/visioniq_test_rag.db", "/tmp/visioniq_test_rag_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

import pytest  # noqa: E402

pytestmark = pytest.mark.vlm

needs_vlm = pytest.mark.skipif(
    os.environ.get("VISIONIQ_VLM_E2E") != "1",
    reason="RAG eval needs a real VLM (VISIONIQ_VLM_E2E=1)")

# Thresholds: below the 2026-11-06 baseline, above a broken system.
THRESHOLDS = {
    "recall_at_5": 0.60,
    "mrr": 0.40,
    "faithfulness": 0.90,
    "relevance_positives": 0.85,
    "negatives_correct": 0.30,
}


def _load_eval_module():
    """Load scripts/rag_eval.py as a module (it is a script, not a
    package — its helpers are reused here instead of duplicated)."""
    path = (Path(__file__).resolve().parent.parent.parent
            / "scripts" / "rag_eval.py")
    spec = importlib.util.spec_from_file_location("rag_eval_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reachable(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/", timeout=5) as resp:
            resp.read()
        return True
    except Exception:
        return False


@needs_vlm
def test_rag_eval_production_config():
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.database import SessionLocal
    from app.main import app
    from app.models import User

    if not _reachable("http://localhost:11434"):
        pytest.skip("Ollama unreachable at http://localhost:11434")
    if not _reachable(os.environ["QDRANT_URL"]):
        pytest.skip(f"Qdrant unreachable at {os.environ['QDRANT_URL']}")

    rag_eval = _load_eval_module()
    items = rag_eval._load_dataset()
    assert len(items) == 54, f"dataset changed: {len(items)} questions"
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/v1/auth/register",
                json={"email": "rageval@test.com", "password": "password123"})
    r = client.post("/api/v1/auth/login",
                    json={"email": "rageval@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    t0 = time.monotonic()
    video_ids, providers = rag_eval._build_corpus(client, headers)
    print(f"\ncorpus ready in {time.monotonic() - t0:.0f}s: {providers}")
    assert "ollama" in providers, "no real VLM captions in the corpus"

    db = SessionLocal()
    user_id = db.query(User).filter_by(email="rageval@test.com").first().id
    # _run_config mutates the settings singleton (QDRANT_URL,
    # RERANKER_MODEL) — restore both afterwards so later tests in
    # the same process are unaffected.
    old_qdrant, old_rerank = settings.QDRANT_URL, settings.RERANKER_MODEL
    try:
        result = rag_eval._run_config(
            db, user_id, video_ids, items, use_qdrant=True, use_rerank=False,
            label="C: Qdrant, no rerank")
    finally:
        settings.QDRANT_URL, settings.RERANKER_MODEL = old_qdrant, old_rerank
        db.close()
    print(f"\nRAG eval (production config): {result}")
    for key, minimum in THRESHOLDS.items():
        assert result[key] >= minimum, f"{key} {result[key]} < {minimum} (full: {result})"
