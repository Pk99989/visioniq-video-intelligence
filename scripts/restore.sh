#!/usr/bin/env bash
# VisionIQ restore (Phase 7): restore a backup.sh directory into a
# TARGET database + storage dir, then verify row counts against the
# backup manifest. Qdrant is rebuilt from the restored DB with
# scripts/reindex_qdrant.py (the snapshot in the backup is a fallback
# for a bare-metal Qdrant restore; reindex is the tested path).
#
# Usage:
#   scripts/restore.sh <backup-dir> <target-database-url> [target-storage-dir]
# Example (scratch restore used to test a backup):
#   scripts/restore.sh ./backups/20261106-120000 \
#     postgresql://visioniq:visioniq@localhost:5432/visioniq_restore \
#     /tmp/visioniq_restore_storage
#
# Exits non-zero if any row count differs.
set -euo pipefail

BACKUP_DIR="${1:?usage: restore.sh <backup-dir> <target-database-url> [target-storage-dir]}"
TARGET_URL="${2:?usage: restore.sh <backup-dir> <target-database-url> [target-storage-dir]}"
TARGET_STORAGE="${3:-/tmp/visioniq_restore_storage}"

[ -f "$BACKUP_DIR/postgres.dump" ] || { echo "no postgres.dump in $BACKUP_DIR" >&2; exit 1; }
[ -f "$BACKUP_DIR/row_counts.txt" ] || { echo "no row_counts.txt in $BACKUP_DIR" >&2; exit 1; }

DB_NAME="$(python3 -c "from urllib.parse import urlparse; print(urlparse('$TARGET_URL').path.lstrip('/'))")"
# Admin connection for DROP/CREATE DATABASE. Defaults to the target
# credentials against the postgres database — that works when the
# app role is a superuser (docker-compose: POSTGRES_USER=visioniq)
# or has CREATEDB. Otherwise set PG_ADMIN_URL to a superuser URL.
ADMIN_URL="${PG_ADMIN_URL:-$(python3 -c "from urllib.parse import urlparse, urlunparse; u=urlparse('$TARGET_URL'); print(urlunparse(u._replace(path='/postgres')))")}"

echo "Restoring $BACKUP_DIR into $TARGET_URL"
psql "$ADMIN_URL" -c "DROP DATABASE IF EXISTS \"$DB_NAME\"" >/dev/null
psql "$ADMIN_URL" -c "CREATE DATABASE \"$DB_NAME\"" >/dev/null
pg_restore -d "$TARGET_URL" --no-owner --no-privileges "$BACKUP_DIR/postgres.dump"

if [ -f "$BACKUP_DIR/storage.tar.gz" ]; then
  rm -rf "$TARGET_STORAGE"
  mkdir -p "$(dirname "$TARGET_STORAGE")"
  tar -xzf "$BACKUP_DIR/storage.tar.gz" -C "$(dirname "$TARGET_STORAGE")"
  echo "Storage restored to $TARGET_STORAGE"
fi

echo "Verifying row counts..."
FAILED=0
while IFS='=' read -r table expected; do
  actual="$(psql "$TARGET_URL" -At -c "SELECT count(*) FROM $table")"
  if [ "$actual" = "$expected" ]; then
    echo "  $table: $actual (ok)"
  else
    echo "  $table: expected $expected, got $actual (MISMATCH)" >&2
    FAILED=1
  fi
done < "$BACKUP_DIR/row_counts.txt"

if [ "$FAILED" -ne 0 ]; then
  echo "Restore verification FAILED" >&2
  exit 1
fi
echo "Restore verified: all row counts match."
echo "Next: rebuild Qdrant from the restored DB with"
echo "  DATABASE_URL=$TARGET_URL python scripts/reindex_qdrant.py"
