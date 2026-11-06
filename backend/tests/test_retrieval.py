"""Phase 4 (v0.6.0) retrieval tests — Qdrant read path with an
in-memory client, owner scoping, filters, DB fallback, compression,
citation validation, and query expansion.

Run: python -m pytest tests/test_retrieval.py -q
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_ret.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_ret_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-ret")
os.environ.setdefault("QDRANT_URL", ":memory:")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

for p in ("/tmp/visioniq_test_ret.db", "/tmp/visioniq_test_ret_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Caption, Frame  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.retrieval import (compress_hits, expand_query_terms,  # noqa: E402
                                    search_frames, validate_citations)

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _fresh_qdrant():
    """A fresh in-memory Qdrant per test (points otherwise leak across
    tests through the cached client)."""
    retrieval._qdrant_clients.clear()
    retrieval._reranker = None
    retrieval._reranker_failed = False
    yield
    retrieval._qdrant_clients.clear()


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


def test_qdrant_read_path_returns_hits(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    h = _auth("ret1@test.com")
    vid = _upload(h)
    db = _db()
    uid = _user_id(db, "ret1@test.com")
    hits = search_frames(db, "bus", user_id=uid, top_k=5)
    db.close()
    assert hits, "Qdrant read path returned nothing"
    assert all(x["video_id"] == vid for x in hits)
    assert hits[0]["score"] > 0.5
    assert "bus" in hits[0]["caption"].lower() or "bus" in hits[0]["detections"]


def _user_id(db, email):
    from app.models import User

    return db.query(User).filter_by(email=email).first().id


def test_qdrant_owner_scoping(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    h1 = _auth("ret-a@test.com")
    h2 = _auth("ret-b@test.com")
    vid_a = _upload(h1, "AliceBus")
    _upload(h2, "BobBus")
    db = _db()
    alice_id = _user_id(db, "ret-a@test.com")
    hits = search_frames(db, "bus", user_id=alice_id, top_k=10)
    assert hits and all(x["video_id"] == vid_a for x in hits)
    bob_id = _user_id(db, "ret-b@test.com")
    hits = search_frames(db, "bus", user_id=bob_id, top_k=10)
    assert hits and all(x["video_id"] != vid_a for x in hits)
    db.close()


def test_filters_label_provider_timestamp(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    h = _auth("ret-f@test.com")
    vid = _upload(h)
    db = _db()
    uid = _user_id(db, "ret-f@test.com")
    # Label filter: only frames detecting a bus.
    hits = search_frames(db, "street", user_id=uid, label="bus", top_k=10)
    assert hits and all("bus" in x["detections"] for x in hits)
    # Provider filter: captions here are the detection tier.
    hits = search_frames(db, "street", user_id=uid, provider="detection", top_k=10)
    assert hits and all(x["provider"] == "detection" for x in hits)
    # Timestamp window that excludes everything.
    hits = search_frames(db, "bus", user_id=uid, start_seconds=100.0, top_k=10)
    assert hits == []
    # Video-scoped search.
    hits = search_frames(db, "bus", user_id=uid, video_id=vid, top_k=10)
    assert hits and all(x["video_id"] == vid for x in hits)
    db.close()


def test_qdrant_failure_falls_back_to_db_scan(monkeypatch):
    # Dead Qdrant address: search must still work via the DB scan.
    monkeypatch.setattr(settings, "QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    h = _auth("ret-fb@test.com")
    _upload(h)
    db = _db()
    uid = _user_id(db, "ret-fb@test.com")
    hits = search_frames(db, "bus", user_id=uid, top_k=5)
    db.close()
    assert hits, "DB fallback returned nothing after Qdrant failure"
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")


def test_empty_qdrant_index_falls_back_to_db_scan(monkeypatch):
    """Regression (Phase 5): a Qdrant that is configured but holds no
    points — fresh in-memory client, or a restarted server with a
    wiped volume — must not make search return nothing when the DB
    has matching captions. The DB scan is the safety net."""
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    retrieval._qdrant_clients.clear()  # fresh, empty in-memory client
    h = _auth("ret-empty@test.com")
    _upload(h)
    # The upload upserted into the (now cleared) client; search sees
    # an empty index and must fall back.
    retrieval._qdrant_clients.clear()
    db = _db()
    uid = _user_id(db, "ret-empty@test.com")
    hits = search_frames(db, "bus", user_id=uid, top_k=5)
    db.close()
    assert hits, "empty Qdrant index made search return nothing"
    assert all(x["video_id"] is not None for x in hits)


def test_compress_hits_dedupes_same_moment():
    hits = [
        {"video_id": 1, "frame_id": 1, "timestamp_seconds": 1.0, "score": 0.9,
         "caption": "a bus on the street", "detections": ["bus"]},
        {"video_id": 1, "frame_id": 2, "timestamp_seconds": 1.5, "score": 0.8,
         "caption": "a bus on the street", "detections": ["bus"]},
        {"video_id": 1, "frame_id": 3, "timestamp_seconds": 5.0, "score": 0.7,
         "caption": "a bus on the street", "detections": ["bus"]},
        {"video_id": 2, "frame_id": 9, "timestamp_seconds": 1.0, "score": 0.6,
         "caption": "a bus on the street", "detections": ["bus"]},
    ]
    out = compress_hits(hits)
    assert len(out) == 3  # 1.0s + 5.0s (same video) + other video
    assert out[0]["frame_id"] == 1 and out[1]["frame_id"] == 3


def test_validate_citations_drops_bogus_frames(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_URL", ":memory:")
    h = _auth("ret-v@test.com")
    vid = _upload(h)
    db = _db()
    frame = db.query(Frame).filter_by(video_id=vid).first()
    good = {"video_id": vid, "frame_id": frame.id,
            "timestamp_seconds": frame.timestamp_seconds, "caption": "x"}
    bad_id = {"video_id": vid, "frame_id": 999999, "timestamp_seconds": 0.0}
    bad_time = {"video_id": vid, "frame_id": frame.id, "timestamp_seconds": 999.0}
    bad_video = {"video_id": vid + 100, "frame_id": frame.id,
                 "timestamp_seconds": frame.timestamp_seconds}
    out = validate_citations(db, [good, bad_id, bad_time, bad_video])
    assert out == [good]
    db.close()


def test_expand_query_terms_only_for_labels_present():
    terms = expand_query_terms("vehicle on the road", {"bus", "car"})
    assert "bus" in terms and "car" in terms
    assert "train" not in terms  # not detected here
    terms = expand_query_terms("vehicle", set())
    assert terms == {"vehicle"}


def test_rerank_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_MODEL", "")
    hits = [{"caption": "a bus", "score": 0.9}, {"caption": "a car", "score": 0.8}]
    assert retrieval.rerank_hits("bus", hits) == hits
