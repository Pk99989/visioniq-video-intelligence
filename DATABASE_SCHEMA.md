# DATABASE_SCHEMA

PostgreSQL in production, SQLite on a laptop — same SQLAlchemy models
(`backend/app/models.py`). Indexes on owner/video foreign keys and on
video status. Every vector, frame, caption and detection carries
`video_id` + `timestamp_seconds` so citations always resolve.

| Table | Key columns |
|---|---|
| users | id, email (unique), password_hash (PBKDF2), role (user/admin) |
| videos | id, owner_id → users, title, file_path, thumbnail_path, duration_seconds, width, height, file_size_bytes, status (uploaded/processing/ready/failed), error_message |
| processing_jobs | id, video_id, status (queued/running/done/failed), attempts, error_message |
| scenes | id, video_id, index, start_seconds, end_seconds |
| frames | id, video_id, scene_id, timestamp_seconds, file_path, embedding_json (384-d) |
| captions | id, video_id, frame_id, scene_id, timestamp_seconds, text, provider, model |
| detections | id, video_id, frame_id, track_id, label, confidence, x1, y1, x2, y2, timestamp_seconds |
| events | id, video_id, rule_name, severity, title, description, timestamp_seconds, verified, evidence_frame_id |
| alerts | id, event_id, video_id, severity, message, acknowledged |
| conversations | id, user_id, video_id, title |
| messages | id, conversation_id, role (user/assistant), content, citations_json |
| reports | id, video_id, owner_id, kind (summary/incident/timeline), file_path, format (json/pdf) |

Qdrant (optional): collection `visioniq_frames`, point id = frame id,
vector = frame embedding, payload = {video_id, timestamp_seconds, caption}.

**Migrations note (honest)**: v0.1.0 creates tables with SQLAlchemy
`create_all` on startup. Alembic migration files are a Phase 2 item
(TASK_TRACKER #12); do not run `create_all` against a production Postgres
database you intend to migrate later without snapshotting the schema first.
