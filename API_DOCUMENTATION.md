# API_DOCUMENTATION

Generated from the live app's OpenAPI spec (v0.14.0, 44 paths) —
run the app and open `/docs` for the interactive version, or dump
the spec with the snippet at the bottom. Every route below exists in
the code; "auth" means a Bearer JWT is required (60-min access
token, refresh via `/auth/refresh`). All video-scoped routes are
owner-scoped: another user's video returns 404, not 403 (see
`SECURITY.md`).

Base: `http://localhost:8000` (laptop/full stack) · prefix `/api/v1`
unless noted.

## Auth

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /api/v1/auth/register | public | email + password (≥8 chars); rate-limited 5/min per IP |
| POST | /api/v1/auth/login | public | returns access token + sets httpOnly `visioniq_refresh` cookie; rate-limited 10/min per IP+email |
| POST | /api/v1/auth/refresh | public | rotates the refresh cookie; replay of a revoked token revokes the whole family |
| POST | /api/v1/auth/logout | auth | revokes access + refresh tokens, clears the cookie |
| GET | /api/v1/auth/me | auth | current user |
| GET | /api/v1/auth/users | auth | admin only |
| POST | /api/v1/auth/password-reset-request | public | rate-limited 5/min per IP; the token is never returned in the response (dev flag only, off by default) |
| POST | /api/v1/auth/password-reset | public | single-use token, 1 h expiry |

## Videos

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | /api/v1/videos | auth | paginated (`limit`/`offset`, `X-Total-Count`) |
| POST | /api/v1/videos/upload | auth | mp4/mov/webm/mkv/avi, 500 MB, magic-byte checked |
| GET | /api/v1/videos/{video_id} | auth | |
| DELETE | /api/v1/videos/{video_id} | auth | deletes files + DB rows + Qdrant points |
| POST | /api/v1/videos/{video_id}/retry | auth | re-queue a failed job |
| GET | /api/v1/videos/{video_id}/stream-url | auth | 5-min signed URL for the player |
| GET | /api/v1/videos/{video_id}/stream | token | Range streaming (206/416) via the signed `?token=` — no Bearer header; the token is the auth |
| GET | /api/v1/videos/{video_id}/status-stream | token | SSE status; same signed-token auth, polling fallback in the UI |
| GET | /api/v1/videos/{video_id}/clip?start=&end= | auth | 0–120 s ffmpeg clip download |
| GET | /api/v1/videos/{video_id}/scenes | auth | |
| GET | /api/v1/videos/{video_id}/frames | auth | paginated |
| GET | /api/v1/videos/{video_id}/frames/{frame_id}/image | auth | |
| GET | /api/v1/videos/{video_id}/frames/{frame_id}/annotated | auth | frame with detection boxes drawn |
| GET | /api/v1/videos/{video_id}/captions | auth | |
| GET | /api/v1/videos/{video_id}/detections | auth | paginated |
| GET | /api/v1/videos/{video_id}/analytics | auth | label counts, confidence stats |
| GET | /api/v1/videos/{video_id}/trajectories | auth | per-track paths (Phase 3) |
| GET | /api/v1/videos/{video_id}/summary | auth | short/medium/long hierarchical summary |
| GET | /api/v1/videos/{video_id}/alerts | auth | paginated |
| POST | /api/v1/videos/{video_id}/alerts/{alert_id}/acknowledge | auth | |

## Search, chat, agent

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /api/v1/search | auth | hybrid Qdrant-first; filters: `label`, `provider`, `start`, `end`, `top_k` (10/20/50) |
| POST | /api/v1/chat | auth | evidence-grounded RAG; `conversation_id` continues a thread |
| GET | /api/v1/conversations | auth | chat history |
| GET | /api/v1/conversations/{conversation_id} | auth | one thread |
| GET | /api/v1/agent/tools | auth | the 8-tool registry with input schemas |
| GET | /api/v1/stats | auth | owner-scoped counts (admin sees all) |

## Events and zones

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | /api/v1/videos/{video_id}/events | auth | paginated |
| POST | /api/v1/videos/{video_id}/events/evaluate | auth | caption-rule evaluation |
| POST | /api/v1/videos/{video_id}/events/evaluate-zones | auth | zone state machine over tracked detections |
| POST | /api/v1/videos/{video_id}/events/{event_id}/verify | auth | VLM yes/no verification (zone_exit is not verifiable) |
| GET | /api/v1/videos/{video_id}/zones | auth | |
| POST | /api/v1/videos/{video_id}/zones | auth | coords 0..1, x1<x2, y1<y2 (else 422) |
| DELETE | /api/v1/videos/{video_id}/zones/{zone_id} | auth | |

## Reports

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /api/v1/reports | auth | kind: summary/incident/timeline; format: json/pdf |
| GET | /api/v1/reports/{report_id}/download | auth | |

## Health, metrics

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | /health | public | `{"status": "ok", "version", "vlm_provider", "embedding_provider", "worker_mode", "detection_available", ...}` |
| GET | /health/vlm | public | VLM provider reachability |
| GET | /metrics | public | Prometheus metrics (unauthenticated by design — restrict at a reverse proxy in production) |

## Errors

400 validation / 401 missing-invalid token / 403 admin-only /
404 not found or not yours (cross-user access returns 404, not 403,
so account existence is not leaked) / 413 oversize / 429 login rate
limit.

## Dumping the spec

```python
import os
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/visioniq_openapi.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/visioniq_openapi_storage")
os.environ.setdefault("JWT_SECRET", "openapi-dump")
from app.main import app
import json
json.dump(app.openapi(), open("openapi.json", "w"), indent=1)
```

Run this from `backend/` with the venv active. If this document and
`/docs` disagree, `/docs` is right — regenerate this file from the
spec and commit both.
