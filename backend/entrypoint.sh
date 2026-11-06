#!/bin/sh
# VisionIQ backend entrypoint (Phase 7 / H2): apply Alembic migrations
# before starting the server, so the running schema always matches
# the code. Exits non-zero if migrations fail — the container must
# not start against a stale schema.
set -e
cd /app
echo "VisionIQ: applying database migrations..."
python3 -m alembic upgrade head
echo "VisionIQ: migrations done, starting server."
exec "$@"
