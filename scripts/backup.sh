#!/usr/bin/env bash
# VisionIQ backup (Phase 7): Postgres dump + storage tarball + Qdrant
# snapshot, all under BACKUP_DIR/<timestamp>/ with a manifest of row
# counts so restore.sh can verify the restore.
#
# Usage:
#   DATABASE_URL=postgresql://visioniq:visioniq@localhost:5432/visioniq \
#   STORAGE_DIR=./backend/storage QDRANT_URL=http://localhost:6333 \
#   BACKUP_DIR=./backups scripts/backup.sh
#
# Requires: pg_dump, tar, curl. Exits non-zero on any failure.
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://visioniq:visioniq@localhost:5432/visioniq}"
STORAGE_DIR="${STORAGE_DIR:-./backend/storage}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-visioniq_frames}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

TS="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/$TS"
mkdir -p "$OUT"

echo "Backing up to $OUT"

# 1. Postgres (custom format, restorable with pg_restore).
pg_dump "$DATABASE_URL" -Fc -f "$OUT/postgres.dump"

# 2. Row counts for restore verification.
psql "$DATABASE_URL" -At -c \
  "SELECT 'videos=' || count(*) FROM videos
   UNION ALL SELECT 'frames=' || count(*) FROM frames
   UNION ALL SELECT 'captions=' || count(*) FROM captions
   UNION ALL SELECT 'detections=' || count(*) FROM detections
   UNION ALL SELECT 'events=' || count(*) FROM events
   UNION ALL SELECT 'users=' || count(*) FROM users" > "$OUT/row_counts.txt"

# 3. Uploaded videos / frames / clips.
tar -czf "$OUT/storage.tar.gz" -C "$(dirname "$STORAGE_DIR")" "$(basename "$STORAGE_DIR")"

# 4. Qdrant snapshot (best effort: search still works after a
# reindex from the restored DB, so a missing snapshot is a warning,
# not a failed backup).
if curl -fsS -X POST "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots" \
        -o "$OUT/qdrant_snapshot.json" 2>/dev/null; then
  SNAP_NAME="$(python3 -c "import json,sys; print(json.load(open('$OUT/qdrant_snapshot.json'))['result']['name'])" 2>/dev/null || true)"
  if [ -n "${SNAP_NAME:-}" ]; then
    curl -fsS "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots/$SNAP_NAME" \
      -o "$OUT/qdrant.snapshot" || echo "warning: could not download Qdrant snapshot" >&2
  fi
else
  echo "warning: Qdrant snapshot skipped (server unreachable?)" >&2
fi

echo "Backup complete: $OUT"
ls -lh "$OUT"
