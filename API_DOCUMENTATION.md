# API_DOCUMENTATION

Base URL: `http://localhost:8000`. Interactive docs: `/docs` (OpenAPI).
All `/api/v1/*` routes except register/login require
`Authorization: Bearer <JWT>`.

## Auth
- `POST /api/v1/auth/register` {email, password≥8} → 201 User
- `POST /api/v1/auth/login` → {access_token, user}
- `GET /api/v1/auth/me` → User
- `GET /api/v1/auth/users` (admin only)

## Videos
- `POST /api/v1/videos/upload` (multipart: title, file) → 201 Video
  (mp4/mov/webm/mkv/avi, ≤ MAX_UPLOAD_MB, default 500 MB)
- `GET /api/v1/videos`, `GET /api/v1/videos/{id}`, `DELETE /api/v1/videos/{id}`
- `POST /api/v1/videos/{id}/retry`
- `GET /api/v1/videos/{id}/stream` (authenticated video bytes)
- `GET /api/v1/videos/{id}/scenes|frames|captions|events|alerts`
- `GET /api/v1/videos/{id}/frames/{frame_id}/image`
- `POST /api/v1/videos/{id}/events/evaluate` [{name, rule_type, value, severity}]
  rule_type ∈ {scene_duration_gt, caption_keyword, detection_label}
- `POST /api/v1/videos/{id}/alerts/{alert_id}/acknowledge`

## Search / chat / summaries / reports
- `POST /api/v1/search` {query, video_id?, top_k, min_score} → SearchHit[]
  (video_id, frame_id, timestamp_seconds, score, caption, detections)
- `GET /api/v1/agent/tools`
- `POST /api/v1/chat` {question, video_id?, conversation_id?}
  → {conversation_id, answer, citations, tool, confidence}
- `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}`
- `GET /api/v1/videos/{id}/summary?length=short|medium|long`
- `POST /api/v1/reports` {video_id, kind, format} → 201 + download_url
- `GET /api/v1/reports/{id}/download`
- `GET /health` → {status, vlm_provider, detection:{available, reason}}

## Errors
400 validation / 401 missing-invalid token / 403 admin-only /
404 not found or not yours (cross-user access returns 404, not 403,
so account existence is not leaked) / 413 oversize / 429 login rate limit.
