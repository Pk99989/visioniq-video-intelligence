"""Shared test fixtures (Phase 9; the full conftest with auth/video
helpers is Phase 11's job).

Rate limiting (M5) is disabled for the whole test session: the suite
registers dozens of users from the single TestClient IP in under a
minute, which is exactly the abuse the register limiter targets — and
several test files register users in module-scoped fixtures, which run
before any function-scoped fixture could disable it. The dedicated
rate-limit tests in test_security.py re-enable it with monkeypatch
and run against a live Redis (skipped when Redis is down).

NOTE: settings is imported lazily inside the fixture, not at module
level — test modules set DATABASE_URL etc. via os.environ.setdefault
before they import the app, and importing app.config here first would
freeze the settings singleton with the default (non-test) values.
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _rate_limit_off():
    from app.config import settings

    old = settings.RATE_LIMIT_ENABLED
    settings.RATE_LIMIT_ENABLED = False
    yield
    settings.RATE_LIMIT_ENABLED = old
