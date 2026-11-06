# DATABASE_SCHEMA

PostgreSQL in production, SQLite on a laptop — same SQLAlchemy models
(`backend/app/models.py`). Indexes on owner/video foreign keys and on
video status, plus composite indexes on captions/detections/frames
(video_id, timestamp_seconds) (migration v4). Every vector, frame,
caption and detection carries `video_id` + `timestamp_seconds` so
citations always resolve.

**16 application tables + `alembic_version` = 17 tables total.**

| Table | Key columns |
|---|---|
| users | id, email (unique), password_hash (PBKDF2), role (user/admin), created_at |
| videos | id, owner_id → users, title, original_filename, file_path, thumbnail_path, duration_seconds, width, height, file_size_bytes, status (uploaded/processing/ready/failed), error_message, created_at |
| processing_jobs | id, video_id, status (queued/running/done/failed), attempts, celery_task_id, error_message, created_at, updated_at |
| scenes | id, video_id, index, start_seconds, end_seconds |
| frames | id, video_id, scene_id, timestamp_seconds, file_path, embedding_json (384-d) |
| captions | id, video_id, frame_id, scene_id, timestamp_seconds, text, provider, model |
| detections | id, video_id, frame_id, track_id, label, confidence, x1, y1, x2, y2, timestamp_seconds |
| events | id, video_id, rule_name, severity, title, description, timestamp_seconds, verified, evidence_frame_id, zone_name, track_id, label, evidence_clip_start, evidence_clip_end, created_at |
| zones | id, video_id, name, x1, y1, x2, y2 (normalised 0..1), created_at |
| alerts | id, event_id, video_id, severity, message, acknowledged, created_at |
| conversations | id, user_id, video_id, title, created_at |
| messages | id, conversation_id, role (user/assistant), content, citations_json, created_at |
| revoked_tokens | id, jti, user_id, expires_at, created_at |
| refresh_tokens | id, user_id, token_hash (SHA-256 only), expires_at, revoked_at, created_at |
| password_reset_tokens | id, user_id, token_hash (SHA-256 only), expires_at, used, created_at |
| reports | id, video_id, owner_id, kind (summary/incident/timeline), file_path, format (json/pdf), created_at |

Qdrant (optional): collection `visioniq_frames`, point id = frame id,
vector = frame embedding, payload = {owner_id, video_id,
timestamp_seconds, caption, label, provider}. Payload indexes on
owner_id, video_id and timestamp_seconds (created idempotently at
startup). The owner_id payload filter is the search privacy boundary.

**Migrations (current, Phase 7):** Alembic-only. The backend
entrypoint (and `app.main` at import) runs `alembic upgrade head`
before serving; `create_all` is no longer used. Five migrations:

- v1 (initial): the original 12 tables.
- v2: `revoked_tokens` + `password_reset_tokens`.
- v3: `zones` + event columns (zone_name, track_id, label,
  evidence_clip_start/end).
- v4: composite indexes + `processing_jobs.celery_task_id`.
- v5: `refresh_tokens`.

Backup/restore: `scripts/backup.sh` / `scripts/restore.sh`
(pg_dump -Fc + storage tarball + Qdrant snapshot + row counts;
restore verifies the counts). Tested live 2026-11-06 with all row
counts matching.
