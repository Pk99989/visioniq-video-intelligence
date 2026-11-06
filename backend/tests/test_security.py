"""Security tests (Phase 9, v0.11.0).

H1: the password-reset token must never be returned in the API
response by default — anyone could reset any account's password
with no email access. Only the explicit dev flag (and never in
production) returns it, so local tests can still exercise reset.

H5: PyJWT replaces the hand-rolled HMAC JWT — alg=none, alg
confusion, tampering, expiry, wrong issuer/audience and missing
claims are all rejected by the library, not by string splitting.

M13: refresh tokens rotate (httpOnly cookie); replaying a rotated
token revokes the whole token family.

M5: Redis-backed rate limits on login/register/reset-request (429).

Upload hardening: magic-byte sniffing, 413 size cap, filename
traversal, optional virus-scan hook.

SSRF: VLM_BASE_URL must not point at internal addresses.

Cross-user: every video-scoped route returns 404 to a non-owner.

Run: python -m pytest tests/test_security.py -q
"""
import base64
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import BUS_JPG, TRAFFIC_JPG

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_test_sec.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_test_sec_storage")
os.environ.setdefault("JWT_SECRET", "test-secret-sec")

import shutil

for p in ("/tmp/visioniq_test_sec.db", "/tmp/visioniq_test_sec_storage"):
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import RefreshToken, User  # noqa: E402
from app.services.vlm import validate_vlm_base_url  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _auth(email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(headers, title="Sec bus"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(BUS_JPG),
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "/tmp/bus3.mp4"],
                   check=True)
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=headers, data={"title": title},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201 and r.json()["status"] == "ready", r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def two_users():
    h_a = _auth("sec-a@test.com")
    h_b = _auth("sec-b@test.com")
    vid = _upload(h_a)
    # One event + one alert on the video, so those routes have a target.
    r = client.post(f"/api/v1/videos/{vid}/events/evaluate", headers=h_a,
                    json=[{"name": "long-scene", "rule_type": "scene_duration_gt",
                           "value": "1", "severity": "warning"}])
    assert r.status_code == 200, r.text
    return {"a": h_a, "b": h_b, "video_id": vid}


# ---------------------------------------------------------------- H1

def test_reset_token_not_returned_by_default(monkeypatch):
    """H1: default response must not contain reset_token."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", False)
    monkeypatch.setattr(settings, "ENV", "development")
    _auth("sec@test.com")
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "sec@test.com"})
    assert r.status_code == 200, r.text
    assert "reset_token" not in r.json(), r.json()
    assert r.json()["detail"].startswith("If that email is registered")


def test_reset_token_not_returned_for_unknown_email(monkeypatch):
    """Same response shape for unregistered emails (no enumeration)."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", False)
    r = client.post("/api/v1/auth/password-reset-request",
                    json={"email": "nobody@test.com"})
    assert r.status_code == 200, r.text
    assert "reset_token" not in r.json()


def test_reset_token_never_returned_in_production(monkeypatch):
    """Even the dev flag is refused when ENV=production."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", True)
    monkeypatch.setattr(settings, "ENV", "production")
    _auth("sec2@test.com")
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "sec2@test.com"})
    assert r.status_code == 200, r.text
    assert "reset_token" not in r.json()


def test_reset_token_returned_only_with_dev_flag(monkeypatch):
    """Dev flag on + non-production: token returned (local testing)."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", True)
    monkeypatch.setattr(settings, "ENV", "development")
    _auth("sec3@test.com")
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "sec3@test.com"})
    assert r.status_code == 200 and "reset_token" in r.json(), r.text
    assert len(r.json()["reset_token"]) >= 32


def test_reset_token_single_use(monkeypatch):
    """A reset token works once; a second use is rejected."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", True)
    monkeypatch.setattr(settings, "ENV", "development")
    email = f"sec-reuse-{uuid.uuid4().hex[:6]}@test.com"
    _auth(email)
    token = client.post("/api/v1/auth/password-reset-request",
                        json={"email": email}).json()["reset_token"]
    r = client.post("/api/v1/auth/password-reset",
                    json={"token": token, "new_password": "newpassword123"})
    assert r.status_code == 200, r.text
    r2 = client.post("/api/v1/auth/password-reset",
                     json={"token": token, "new_password": "anotherpass123"})
    assert r2.status_code == 400
    # And the new password works.
    r3 = client.post("/api/v1/auth/login", json={"email": email, "password": "newpassword123"})
    assert r3.status_code == 200


# ---------------------------------------------------------------- H5

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_jwt_alg_none_rejected(two_users):
    """alg=none: a token with no signature must not authenticate."""
    h = two_users["a"]
    token = h["Authorization"].split(" ", 1)[1]
    header, payload, _sig = token.split(".")
    none_header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    forged = f"{none_header}.{payload}."
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_jwt_tampered_payload_rejected(two_users):
    """Changing one character of the payload invalidates the signature."""
    h = two_users["a"]
    token = h["Authorization"].split(" ", 1)[1]
    header, payload, sig = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["role"] = "admin"
    forged = f"{header}.{_b64(json.dumps(data).encode())}.{sig}"
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_jwt_expired_rejected():
    """An expired token (exp in the past) is rejected."""
    import jwt

    now = datetime.utcnow()
    expired = jwt.encode(
        {"sub": "1", "email": "x@test.com", "role": "user", "jti": "expired-1",
         "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1),
         "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        settings.JWT_SECRET, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_jwt_wrong_issuer_audience_rejected():
    """A token minted for another issuer/audience is rejected."""
    import jwt

    now = datetime.utcnow()
    for iss, aud in (("attacker", settings.JWT_AUDIENCE),
                     (settings.JWT_ISSUER, "attacker")):
        token = jwt.encode(
            {"sub": "1", "email": "x@test.com", "role": "user", "jti": "wrong-1",
             "iat": now, "exp": now + timedelta(hours=1), "iss": iss, "aud": aud},
            settings.JWT_SECRET, algorithm="HS256")
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


def test_jwt_missing_claims_rejected():
    """A token without jti/iat (like the old hand-rolled tokens) is
    rejected — the upgrade invalidates pre-PyJWT tokens."""
    import jwt

    now = datetime.utcnow()
    token = jwt.encode(
        {"sub": "1", "email": "x@test.com", "role": "user",
         "exp": now + timedelta(hours=1),
         "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE},
        settings.JWT_SECRET, algorithm="HS256")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_revoked_token_rejected(two_users):
    """Logout revokes the access token; reuse is 401."""
    email = f"sec-revoke-{uuid.uuid4().hex[:6]}@test.com"
    h = _auth(email)
    r = client.post("/api/v1/auth/logout", headers=h)
    assert r.status_code == 200
    r2 = client.get("/api/v1/auth/me", headers=h)
    assert r2.status_code == 401


# ---------------------------------------------------------------- M13

def test_refresh_rotates_and_replay_revokes_family():
    """Login sets an httpOnly refresh cookie; refresh rotates it; a
    replay of the old token revokes the whole family."""
    email = f"sec-refresh-{uuid.uuid4().hex[:6]}@test.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    old_cookie = r.cookies.get("visioniq_refresh")
    assert old_cookie, "login must set the refresh cookie"
    assert "httponly" in r.headers.get("set-cookie", "").lower()
    r2 = client.post("/api/v1/auth/refresh", cookies={"visioniq_refresh": old_cookie})
    assert r2.status_code == 200, r2.text
    new_cookie = r2.cookies.get("visioniq_refresh")
    assert new_cookie and new_cookie != old_cookie
    # The new access token works.
    tok = r2.json()["access_token"]
    assert client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    # Replay the old refresh token: 401 and the family is revoked,
    # so even the new token is dead.
    r3 = client.post("/api/v1/auth/refresh", cookies={"visioniq_refresh": old_cookie})
    assert r3.status_code == 401
    r4 = client.post("/api/v1/auth/refresh", cookies={"visioniq_refresh": new_cookie})
    assert r4.status_code == 401


def test_logout_revokes_refresh_cookie():
    email = f"sec-logout-{uuid.uuid4().hex[:6]}@test.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    cookie = r.cookies.get("visioniq_refresh")
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=h,
                       cookies={"visioniq_refresh": cookie}).status_code == 200
    assert client.post("/api/v1/auth/refresh",
                       cookies={"visioniq_refresh": cookie}).status_code == 401


def test_prune_removes_expired_refresh_tokens():
    db = SessionLocal()
    user = db.query(User).filter_by(email="sec-a@test.com").first()
    from app.security import hash_token
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token("prune-me"),
                        expires_at=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    from app.routers.auth import prune_expired_tokens
    removed = prune_expired_tokens(db)
    assert removed >= 1
    assert db.query(RefreshToken).filter_by(token_hash=hash_token("prune-me")).first() is None
    db.close()


# ---------------------------------------------------------------- cross-user

def test_cross_user_every_video_route(two_users):
    """A non-owner gets 404 (never another user's data) on every
    video-scoped route."""
    h_b, vid = two_users["b"], two_users["video_id"]
    db = SessionLocal()
    from app.models import Alert, Event
    event = db.query(Event).filter_by(video_id=vid).first()
    alert = db.query(Alert).filter_by(video_id=vid).first()
    frame_id = None
    from app.models import Frame
    frame = db.query(Frame).filter_by(video_id=vid).first()
    frame_id = frame.id if frame else 0
    db.close()
    checks = [
        ("GET", f"/api/v1/videos/{vid}", None),
        ("GET", f"/api/v1/videos/{vid}/detections", None),
        ("GET", f"/api/v1/videos/{vid}/frames", None),
        ("GET", f"/api/v1/videos/{vid}/frames/{frame_id}/image", None),
        ("GET", f"/api/v1/videos/{vid}/frames/{frame_id}/annotated", None),
        ("GET", f"/api/v1/videos/{vid}/events", None),
        ("GET", f"/api/v1/videos/{vid}/alerts", None),
        ("GET", f"/api/v1/videos/{vid}/trajectories", None),
        ("GET", f"/api/v1/videos/{vid}/analytics", None),
        ("GET", f"/api/v1/videos/{vid}/captions", None),
        ("GET", f"/api/v1/videos/{vid}/scenes", None),
        ("GET", f"/api/v1/videos/{vid}/summary", None),
        ("GET", f"/api/v1/videos/{vid}/stream-url", None),
        ("GET", f"/api/v1/videos/{vid}/clip?start=0&end=1", None),
        ("GET", f"/api/v1/videos/{vid}/zones", None),
        ("POST", f"/api/v1/videos/{vid}/zones",
         {"name": "x", "x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}),
        ("POST", f"/api/v1/videos/{vid}/events/evaluate",
         [{"name": "x", "rule_type": "scene_duration_gt", "value": "1", "severity": "info"}]),
        ("POST", f"/api/v1/videos/{vid}/events/evaluate-zones", []),
        ("POST", f"/api/v1/videos/{vid}/retry", None),
        ("DELETE", f"/api/v1/videos/{vid}", None),
    ]
    if event is not None:
        checks.append(("POST", f"/api/v1/videos/{vid}/events/{event.id}/verify", None))
    if alert is not None:
        checks.append(("POST", f"/api/v1/videos/{vid}/alerts/{alert.id}/acknowledge", None))
    for method, path, body in checks:
        r = client.request(method, path, headers=h_b,
                           json=body if body is not None else None)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code} (want 404)"
    # Chat scoped to someone else's video: 404, not an answer.
    r = client.post("/api/v1/chat", headers=h_b,
                    json={"question": "Is there a bus?", "video_id": vid})
    assert r.status_code == 404
    # Stats are owner-scoped: user B sees zero of user A's videos.
    s = client.get("/api/v1/stats", headers=h_b).json()
    assert s["videos_total"] == 0 and s["detections_total"] == 0
    # And user A still sees their own video (the DELETE above failed).
    assert client.get(f"/api/v1/videos/{vid}", headers=two_users["a"]).status_code == 200


# ---------------------------------------------------------------- M5

def _redis_available():
    try:
        import redis

        c = redis.Redis.from_url("redis://127.0.0.1:6379/0",
                                 socket_connect_timeout=2, socket_timeout=2)
        c.ping()
        c.close()
        return True
    except Exception:
        return False


def test_login_rate_limit_429(monkeypatch):
    """11 wrong-password logins for one email in a minute: the 11th
    is 429. A different email is unaffected (per-email bucket)."""
    if not _redis_available():
        pytest.skip("no live Redis at 127.0.0.1:6379")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MINUTE", 10)
    email = f"sec-rl-{uuid.uuid4().hex[:6]}@test.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    for i in range(10):
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401, f"attempt {i}: {r.status_code}"
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "wrong-password"})
    assert r.status_code == 429, r.text
    # A different account from the same IP still logs in.
    other = f"sec-rl2-{uuid.uuid4().hex[:6]}@test.com"
    client.post("/api/v1/auth/register", json={"email": other, "password": "password123"})
    r2 = client.post("/api/v1/auth/login", json={"email": other, "password": "password123"})
    assert r2.status_code == 200, r2.text


# ---------------------------------------------------------------- uploads

def test_upload_rejects_wrong_magic_bytes(two_users):
    """A .txt renamed to .mp4 fails the magic-byte check (400)."""
    h = two_users["a"]
    r = client.post("/api/v1/videos/upload", headers=h, data={"title": "fake"},
                    files={"file": ("video.mp4", b"this is plain text, not a video",
                                    "video/mp4")})
    assert r.status_code == 400, r.text
    assert "magic" in r.text.lower()


def test_upload_size_cap_413(two_users, monkeypatch):
    """MAX_UPLOAD_MB=0: even a real video exceeds the cap (413)."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)
    h = two_users["a"]
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=h, data={"title": "big"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 413, r.text


def test_upload_filename_traversal_is_safe(two_users):
    """A filename full of ../ is stored as a plain DB string; the file
    itself lands as original.mp4 inside the video's own directory."""
    h = two_users["a"]
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=h, data={"title": "trav"},
                        files={"file": ("../../../evil.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    db = SessionLocal()
    from app.models import Video
    video = db.get(Video, vid)
    assert video is not None
    assert ".." not in video.file_path
    assert Path(video.file_path).is_relative_to(settings.STORAGE_DIR)
    assert Path(video.file_path).name == "original.mp4"
    db.close()


def test_upload_scan_hook_rejects(two_users, monkeypatch):
    """CLAMSCAN_CMD= false (always fails) rejects the upload; true
    (always passes) lets it through."""
    monkeypatch.setattr(settings, "CLAMSCAN_CMD", "false")
    h = two_users["a"]
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=h, data={"title": "scan"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 400, r.text
    assert "virus scan" in r.text.lower()
    monkeypatch.setattr(settings, "CLAMSCAN_CMD", "true")
    with open("/tmp/bus3.mp4", "rb") as f:
        r = client.post("/api/v1/videos/upload", headers=h, data={"title": "scan2"},
                        files={"file": ("bus.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- SSRF

def test_vlm_url_ssrf_guard():
    """Localhost and public IPs are fine; metadata/private IPs and
    non-http schemes are refused."""
    for ok in ("http://localhost:11434/v1", "http://127.0.0.1:11434/v1",
               "http://host.docker.internal:11434/v1", "http://8.8.8.8/v1"):
        validate_vlm_base_url(ok)
    for bad in ("http://169.254.169.254/latest/meta-data/",
                "http://10.0.0.5:11434/v1", "http://192.168.1.1:11434/v1",
                "http://172.16.0.9:11434/v1", "http://127.0.0.2:11434/v1",
                "ftp://example.com/v1", "not-a-url", "http://"):
        with pytest.raises(ValueError, match="VLM_BASE_URL"):
            validate_vlm_base_url(bad)


# ---------------------------------------------------------------- H6

def test_make_admin_script(tmp_path):
    """scripts/make_admin.py: unknown email fails without --create,
    --create makes an admin, a second run says already admin."""
    from app.database import engine as test_engine

    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "make_admin.py"
    # The subprocess must use the same database the test process's
    # engine points at. Test files disagree about DATABASE_URL in the
    # process env (shared-engine quirk, audit L12), so take the URL
    # from the engine itself instead of os.environ.
    env = dict(os.environ, DATABASE_URL=str(test_engine.url))
    email = f"sec-admin-{uuid.uuid4().hex[:6]}@test.com"
    r = subprocess.run([sys.executable, str(script), email],
                       capture_output=True, text=True, env=env, cwd=str(script.parent.parent))
    assert r.returncode == 2 and "no account" in r.stderr
    r = subprocess.run([sys.executable, str(script), email, "--create",
                        "--password", "adminpass123"],
                       capture_output=True, text=True, env=env, cwd=str(script.parent.parent))
    assert r.returncode == 0, r.stderr
    assert "created admin" in r.stdout
    db = SessionLocal()
    user = db.query(User).filter_by(email=email).first()
    assert user is not None and user.role == "admin"
    db.close()
    # The new admin can log in and list users.
    r2 = client.post("/api/v1/auth/login",
                     json={"email": email, "password": "adminpass123"})
    assert r2.status_code == 200
    h = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert client.get("/api/v1/auth/users", headers=h).status_code == 200
    r = subprocess.run([sys.executable, str(script), email],
                       capture_output=True, text=True, env=env, cwd=str(script.parent.parent))
    assert r.returncode == 0 and "already an admin" in r.stdout
