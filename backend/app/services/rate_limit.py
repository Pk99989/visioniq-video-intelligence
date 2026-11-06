"""Fixed-window rate limiting (Phase 9, M5) for the auth endpoints.

Redis-backed: one INCR per attempt, the key expires after the window
(60 s). When Redis is unreachable the limiter FAILS OPEN and logs a
warning — the laptop profile runs without Redis, and locking every
user out because a cache is down is worse than no limit. Production
deployments run Redis (docker-compose), so the limit is live there.

Buckets:
- login: per client IP + per email (10/min default) — this stops
  credential stuffing against one account without locking out other
  users behind the same NAT.
- register / password-reset-request: per client IP (5/min default).
"""
import logging

from fastapi import Request

from ..config import settings

logger = logging.getLogger("visioniq.rate_limit")

_WINDOW_SECONDS = 60


def _redis():
    """A short-lived Redis client, or None when Redis is not there.
    Imported lazily so this module loads without a Redis server."""
    try:
        import redis

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL,
                                      socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return None


def _client_ip(request: Request) -> str:
    # Only the direct peer is trusted (no X-Forwarded-For parsing —
    # a client can forge that header). Behind a trusted reverse proxy
    # the peer is the proxy, so per-IP buckets are coarser there;
    # per-email login buckets still apply.
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request, bucket: str, limit: int) -> bool:
    """True when the attempt is allowed, False when the bucket is full.
    Fails open (True) when the limiter is disabled or Redis is
    unreachable."""
    if not settings.RATE_LIMIT_ENABLED:
        return True
    client = _redis()
    if client is None:
        logger.warning("rate limit unavailable (no Redis) — allowing %s", bucket)
        return True
    key = f"rl:{bucket}"
    try:
        count = client.incr(key)
        if count == 1:
            client.expire(key, _WINDOW_SECONDS)
        return count <= limit
    except Exception as e:  # noqa: BLE001 - fail open, don't break auth
        logger.warning("rate limit check failed for %s (%s) — allowing", bucket, e)
        return True
    finally:
        try:
            client.close()
        except Exception:
            pass


def login_bucket(request: Request, email: str) -> str:
    return f"login:{_client_ip(request)}:{email.strip().lower()}"


def ip_bucket(request: Request, route: str) -> str:
    return f"{route}:{_client_ip(request)}"
