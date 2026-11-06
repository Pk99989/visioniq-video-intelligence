"""Security tests (Phase 9, started 2026-11-06 with the H1 fix).

H1: the password-reset token must never be returned in the API
response by default — anyone could reset any account's password
with no email access. Only the explicit dev flag (and never in
production) returns it, so local tests can still exercise reset.

Run: python -m pytest tests/test_security.py -q
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from app.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)


def _register(email="sec@test.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})


def test_reset_token_not_returned_by_default(monkeypatch):
    """H1: default response must not contain reset_token."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", False)
    monkeypatch.setattr(settings, "ENV", "development")
    _register()
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
    _register("sec2@test.com")
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "sec2@test.com"})
    assert r.status_code == 200, r.text
    assert "reset_token" not in r.json()


def test_reset_token_returned_only_with_dev_flag(monkeypatch):
    """Dev flag on + non-production: token returned (local testing)."""
    monkeypatch.setattr(settings, "DEV_RETURN_RESET_TOKEN", True)
    monkeypatch.setattr(settings, "ENV", "development")
    _register("sec3@test.com")
    r = client.post("/api/v1/auth/password-reset-request", json={"email": "sec3@test.com"})
    assert r.status_code == 200 and "reset_token" in r.json(), r.text
    assert len(r.json()["reset_token"]) >= 32
