#!/bin/sh
# VisionIQ backend entrypoint (Phase 7 / H2, hardened Phase 12):
# wait for the services the app needs, apply Alembic migrations
# before starting the server (the running schema always matches the
# code), fix the storage volume's ownership, then drop to the
# non-root `visioniq` user for the server/worker. Exits non-zero if
# migrations fail — the container must not start against a stale
# schema.
set -e
# The script lives in /app in the image and in backend/ in the repo;
# resolve the app root from the script's own location.
cd "$(dirname "$0")"
STORAGE_DIR="${STORAGE_DIR:-$(pwd)/storage}"
echo "VisionIQ: waiting for services..."

# Phase 12: wait for each configured service (TCP connect, 60 s
# each). A service is skipped when its URL is empty, SQLite, or
# localhost — the laptop profile (SQLite + in-process) has nothing
# to wait for. Python is used for the probes: the slim image has no
# nc / pg_isready / redis-cli / curl.
python3 - <<'PYEOF'
import os
import socket
import sys
import time
import urllib.parse
import urllib.request


def wait_tcp(name, host, port, timeout=60):
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        print(f"VisionIQ: {name} is local ({host or 'unset'}) — no wait")
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=5):
                print(f"VisionIQ: {name} reachable at {host}:{port}")
                return
        except OSError:
            time.sleep(2)
    print(f"VisionIQ: ERROR: {name} not reachable at {host}:{port} after {timeout}s", file=sys.stderr)
    sys.exit(1)


def wait_http(name, url, timeout=60):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        print(f"VisionIQ: {name} is local ({host or 'unset'}) — no wait")
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/", timeout=5) as resp:
                resp.read(1)
            print(f"VisionIQ: {name} reachable at {url}")
            return
        except Exception:
            time.sleep(2)
    print(f"VisionIQ: ERROR: {name} not reachable at {url} after {timeout}s", file=sys.stderr)
    sys.exit(1)


db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("postgresql"):
    p = urllib.parse.urlparse(db_url)
    wait_tcp("postgres", p.hostname, p.port or 5432)
broker = os.environ.get("CELERY_BROKER_URL", "")
if broker.startswith("redis"):
    p = urllib.parse.urlparse(broker)
    wait_tcp("redis", p.hostname, p.port or 6379)
qdrant = os.environ.get("QDRANT_URL", "")
if qdrant:
    wait_http("qdrant", qdrant)
PYEOF

echo "VisionIQ: applying database migrations..."
python3 -m alembic upgrade head
echo "VisionIQ: migrations done."

# The storage volume may be root-owned (named volumes created by the
# pre-0.14 root images keep their old ownership). The server runs as
# `visioniq` and must be able to write uploads, frames and clips.
mkdir -p "$STORAGE_DIR"
chown -R visioniq:visioniq "$STORAGE_DIR" 2>/dev/null || \
    echo "VisionIQ: warning: could not chown $STORAGE_DIR (running as non-root?)"

echo "VisionIQ: starting as user visioniq: $*"
exec runuser -u visioniq -- "$@"
