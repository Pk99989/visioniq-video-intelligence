"""Phase 6 (v0.8.0) zone event engine tests — entry/exit, dwell,
loitering candidates, evidence clips, zone CRUD, VLM verification.

Detections are seeded directly in the DB (exact pixel coordinates),
so the zone geometry is tested precisely without a full video
pipeline run. VLM verification uses a local mock HTTP server.

Run: python -m pytest tests/test_events.py -q
"""
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_events.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_events_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-events")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")

for p in ("/tmp/visioniq_test_events.db", "/tmp/visioniq_test_events_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Detection, Event, Frame, User, Video, Zone  # noqa: E402
from app.services import events as events_svc  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

ZONE = {"name": "door", "x1": 0.4, "y1": 0.0, "x2": 0.6, "y2": 1.0}


def _auth(email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _frame_file():
    """A real 640x480 JPEG so frame-size fallbacks also work."""
    import cv2
    import numpy as np

    p = Path("/tmp/visioniq_test_events_storage/frame.jpg")
    p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), np.zeros((480, 640, 3), dtype=np.uint8))
    return str(p)


def _seed_video(db, owner_id, duration=60.0):
    video = Video(owner_id=owner_id, title="Zones", original_filename="z.mp4",
                  file_path="/tmp/nonexistent.mp4", file_size_bytes=0,
                  duration_seconds=duration, width=640, height=480, status="ready")
    db.add(video)
    db.flush()
    frame_path = _frame_file()
    frames = {}
    for t in range(0, 61):
        f = Frame(video_id=video.id, timestamp_seconds=float(t), file_path=frame_path)
        db.add(f)
        db.flush()
        frames[t] = f.id
    db.commit()
    return video.id, frames


def _det(db, video_id, frame_id, ts, track_id, label, cx, cy, conf=0.9):
    """One detection whose centre is at normalised (cx, cy)."""
    w, h = 640.0, 480.0
    db.add(Detection(video_id=video_id, frame_id=frame_id, track_id=track_id,
                     label=label, confidence=conf,
                     x1=cx * w - 20, y1=cy * h - 20,
                     x2=cx * w + 20, y2=cy * h + 20,
                     timestamp_seconds=float(ts)))
    db.commit()


@pytest.fixture(scope="module")
def setup():
    h = _auth("events@test.com")
    db = SessionLocal()
    uid = db.query(User).filter_by(email="events@test.com").first().id
    video_id, frames = _seed_video(db, uid)
    # Track 1 (person): outside -> inside at t=5 -> outside at t=8.
    for t, cx in [(0, 0.1), (1, 0.1), (2, 0.1), (3, 0.1), (4, 0.1),
                  (5, 0.5), (6, 0.5), (7, 0.5), (8, 0.7), (9, 0.7)]:
        _det(db, video_id, frames[t], t, 1, "person", cx, 0.5)
    # Track 2 (person): enters at t=10, stays inside until t=20.
    for t in range(10, 21):
        _det(db, video_id, frames[t], t, 2, "person", 0.5, 0.5)
    # Track 3 (car): never enters the zone.
    for t in range(0, 10):
        _det(db, video_id, frames[t], t, 3, "car", 0.1, 0.5)
    db.close()
    return {"headers": h, "video_id": video_id}


def test_zone_entry_exit_dwell(setup, monkeypatch):
    monkeypatch.setattr(settings, "EVENT_DWELL_SECONDS", 2.0)
    monkeypatch.setattr(settings, "EVENT_LOITER_SECONDS", 30.0)
    db = SessionLocal()
    created = events_svc.evaluate_zones(db, setup["video_id"], [ZONE])
    # evaluate_zones commits, which expires the instances — snapshot
    # the fields before the session closes.
    rows = [(e.rule_name, round(e.timestamp_seconds, 1), e.track_id, e.zone_name,
             e.label, e.evidence_frame_id, e.evidence_clip_start,
             e.evidence_clip_end) for e in created]
    db.close()
    by_rule = {}
    for r in rows:
        by_rule.setdefault(r[0], []).append(r)
    # Track 1: enter at 5, dwell at 5+2=7, exit at 8.
    assert [r[1] for r in by_rule["zone_enter"]] == [5.0, 10.0]
    assert [r[1] for r in by_rule["zone_dwell"]] == [7.0, 12.0]
    assert [r[1] for r in by_rule["zone_exit"]] == [8.0]
    # Track 2 is still inside at its last detection: no exit invented.
    assert "zone_loitering" not in by_rule  # 30s threshold not reached
    # Track 3 (car, never in the zone) produced nothing.
    assert all(r[2] in (1, 2) for r in sum(by_rule.values(), []))
    # Provenance + evidence clip on the enter event.
    enter = [r for r in by_rule["zone_enter"] if r[2] == 1][0]
    assert enter[3] == "door" and enter[4] == "person"
    assert enter[5] is not None
    assert enter[6] == 3.0 and enter[7] == 8.0


def test_zone_loitering_candidate(setup, monkeypatch):
    monkeypatch.setattr(settings, "EVENT_DWELL_SECONDS", 2.0)
    monkeypatch.setattr(settings, "EVENT_LOITER_SECONDS", 4.0)
    db = SessionLocal()
    created = events_svc.evaluate_zones(db, setup["video_id"], [ZONE])
    # evaluate_zones commits, which expires the instances — snapshot
    # the fields before the session closes.
    rows = [(e.rule_name, round(e.timestamp_seconds, 1), e.track_id,
             e.severity, e.verified, e.description) for e in created]
    db.close()
    loiter = [r for r in rows if r[0] == "zone_loitering"]
    # Track 2 entered at 10 and stayed: loitering at 10+4=14.
    # Track 1 held only 3s: no loitering for it.
    assert len(loiter) == 1
    assert loiter[0][2] == 2
    assert loiter[0][1] == 14.0
    assert loiter[0][3] == "warning"
    assert loiter[0][4] is False  # candidate only, never auto-verified
    assert "Candidate only" in loiter[0][5]


def test_zone_evaluate_is_idempotent(setup, monkeypatch):
    monkeypatch.setattr(settings, "EVENT_DWELL_SECONDS", 2.0)
    monkeypatch.setattr(settings, "EVENT_LOITER_SECONDS", 4.0)
    db = SessionLocal()
    before = db.query(Event).filter_by(video_id=setup["video_id"]).count()
    events_svc.evaluate_zones(db, setup["video_id"], [ZONE])
    after = db.query(Event).filter_by(video_id=setup["video_id"]).count()
    db.close()
    assert after == before, "re-running the zone engine must not duplicate events"


def test_zone_crud_api(setup):
    h, vid = setup["headers"], setup["video_id"]
    r = client.post(f"/api/v1/videos/{vid}/zones", headers=h, json=ZONE)
    assert r.status_code == 201, r.text
    zid = r.json()["id"]
    r = client.get(f"/api/v1/videos/{vid}/zones", headers=h)
    assert any(z["id"] == zid for z in r.json())
    # Invalid geometry is rejected, not stored.
    bad = dict(ZONE, x1=0.6, x2=0.4)
    assert client.post(f"/api/v1/videos/{vid}/zones", headers=h, json=bad).status_code == 422
    out = dict(ZONE, x1=1.5)
    assert client.post(f"/api/v1/videos/{vid}/zones", headers=h, json=out).status_code == 422
    # Evaluate through the API: zone already exists, events re-created
    # only if the suppression window allows (fresh video would create).
    r = client.post(f"/api/v1/videos/{vid}/events/evaluate-zones", headers=h)
    assert r.status_code == 200, r.text
    assert all("evidence_clip_url" in e for e in r.json())
    r = client.delete(f"/api/v1/videos/{vid}/zones/{zid}", headers=h)
    assert r.status_code == 200
    r = client.get(f"/api/v1/videos/{vid}/zones", headers=h)
    assert all(z["id"] != zid for z in r.json())


def test_zone_api_owner_scoped(setup):
    h2 = _auth("events-other@test.com")
    vid = setup["video_id"]
    assert client.get(f"/api/v1/videos/{vid}/zones", headers=h2).status_code == 404
    assert client.post(f"/api/v1/videos/{vid}/zones", headers=h2, json=ZONE).status_code == 404
    assert client.post(f"/api/v1/videos/{vid}/events/evaluate-zones",
                       headers=h2).status_code == 404


class _YesHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"choices": [{"message": {"content": "YES"}}]}).encode())

    def log_message(self, *a):
        pass


class _NoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"choices": [{"message": {"content": "NO"}}]}).encode())

    def log_message(self, *a):
        pass


def _mock_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_vlm_verify_yes_marks_verified(setup, monkeypatch):
    server, url = _mock_server(_YesHandler)
    monkeypatch.setattr(settings, "VLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "VLM_BASE_URL", url)
    monkeypatch.setattr(settings, "VLM_MODEL", "test-vlm")
    monkeypatch.setattr(settings, "VLM_MAX_RETRIES", 0)
    monkeypatch.setattr(settings, "VLM_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(settings, "VLM_RETRY_BACKOFF_SECONDS", 0.01)
    db = SessionLocal()
    event = (db.query(Event).filter_by(video_id=setup["video_id"], rule_name="zone_enter",
                                       track_id=1).first())
    verified, message = events_svc.verify_event(db, event)
    assert verified is True
    assert "confirmed" in message
    db.refresh(event)
    assert event.verified is True
    server.shutdown()
    db.close()


def test_vlm_verify_no_leaves_unverified(setup, monkeypatch):
    server, url = _mock_server(_NoHandler)
    monkeypatch.setattr(settings, "VLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "VLM_BASE_URL", url)
    monkeypatch.setattr(settings, "VLM_MODEL", "test-vlm")
    monkeypatch.setattr(settings, "VLM_MAX_RETRIES", 0)
    monkeypatch.setattr(settings, "VLM_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(settings, "VLM_RETRY_BACKOFF_SECONDS", 0.01)
    db = SessionLocal()
    event = (db.query(Event).filter_by(video_id=setup["video_id"], rule_name="zone_dwell",
                                       track_id=2).first())
    verified, message = events_svc.verify_event(db, event)
    assert verified is False
    assert "did not confirm" in message
    db.refresh(event)
    assert event.verified is False
    assert "did not confirm" in event.description
    server.shutdown()
    db.close()


def test_verify_exit_and_fallback_not_verified(setup, monkeypatch):
    monkeypatch.setattr(settings, "VLM_PROVIDER", "fallback")
    monkeypatch.setattr(settings, "VLM_BASE_URL", "")
    db = SessionLocal()
    exit_event = (db.query(Event).filter_by(video_id=setup["video_id"],
                                            rule_name="zone_exit").first())
    verified, message = events_svc.verify_event(db, exit_event)
    assert verified is False and "not VLM-verified" in message
    enter_event = (db.query(Event).filter_by(video_id=setup["video_id"],
                                             rule_name="zone_enter", track_id=2).first())
    verified, message = events_svc.verify_event(db, enter_event)
    assert verified is False and "No VLM configured" in message
    db.close()
    # Same through the API.
    h, vid = setup["headers"], setup["video_id"]
    r = client.post(f"/api/v1/videos/{vid}/events/{enter_event.id}/verify", headers=h)
    assert r.status_code == 200 and r.json()["verified"] is False
    assert client.post(f"/api/v1/videos/{vid}/events/999999/verify",
                       headers=h).status_code == 404
