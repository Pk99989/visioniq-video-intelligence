# Observability (Phase 10, v0.12.0)

## Logs — structured JSON

Every log line is one JSON object on stdout:

```json
{"ts": "2026-11-06T11:09:14.824659+00:00", "level": "INFO",
 "logger": "visioniq.worker",
 "msg": "video=1 duration=3.0s fps=2.00 frames_extracted=6 deduped=4 kept=2",
 "request_id": "upload-req-2", "job_id": 1}
```

- `request_id`: set by the request-ID middleware. A client-supplied
  `X-Request-ID` header is honoured (tracing across services);
  otherwise a fresh id is minted and echoed on the response.
- `job_id`: set by the pipeline for the duration of a processing job.
  The upload request's id travels with the job — via the contextvar
  in-process, via Celery task headers in celery mode — so a job's log
  lines trace back to the request that started it.
- `LOG_FORMAT=text` switches to human-readable lines (local dev).
  `LOG_LEVEL` sets the level (default `INFO`).
- Run the server with `PYTHONUNBUFFERED=1` (the Dockerfile and
  `entrypoint.sh` do this) so log lines flush immediately when stdout
  is redirected to a file; otherwise Python block-buffers stdout.
- Known quirk, fixed in v0.12.0: alembic's logging config (from
  `alembic.ini`) replaces the root logger's handlers, sets the root
  level to WARNING, and disables all loggers not named in the file —
  after a migration run, no app INFO log and no uvicorn access log
  would ever be emitted. `run_migrations()` now re-applies the
  structured logging config after every upgrade, including re-enabling
  the disabled loggers and routing uvicorn's loggers through the JSON
  handler.

## Metrics — `/metrics` (Prometheus)

`GET /metrics` serves the default `prometheus_client` registry (which
already includes process CPU/RSS, GC and Python info) plus:

| Metric | Type | What it measures |
|---|---|---|
| `visioniq_http_requests_total{method,route,status}` | counter | Requests. `route` is the route template (`/api/v1/videos/{video_id}`), never the raw path — a video id cannot create a time series per request. |
| `visioniq_http_request_duration_seconds{method,route}` | histogram | API latency. |
| `visioniq_video_processing_duration_seconds` | histogram | End-to-end pipeline time per video. |
| `visioniq_video_processing_jobs_total{status}` | counter | Finished jobs (`done` / `failed`). |
| `visioniq_detection_seconds` | histogram | Per-frame YOLO inference time. |
| `visioniq_vlm_caption_seconds{provider}` | histogram | VLM caption call latency. |
| `visioniq_qdrant_search_seconds` | histogram | Qdrant vector search latency (read path). |
| `visioniq_celery_queue_depth` | gauge | Tasks waiting in the Celery broker. `-1` = unknown (laptop profile has no broker; a misleading `0` is never reported). |
| `visioniq_storage_disk_free_bytes` / `_total_bytes` | gauges | Free/total bytes on the storage volume. A warning is logged when free space drops below `STORAGE_WARN_FREE_PCT` (default 10%). |
| `visioniq_db_pool_size` / `_checked_out` | gauges | DB pool state (best effort). |
| `visioniq_gpu_utilization_percent` | gauge | From `nvidia-smi` when a GPU exists; absent otherwise. |

`/metrics` is unauthenticated by design — Prometheus needs to reach
it without a user token. In production, restrict it at the reverse
proxy or firewall to the monitoring network. `METRICS_ENABLED=0`
turns it off entirely (404).

## Prometheus + Grafana

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
# Prometheus: http://localhost:9090  |  Grafana: http://localhost:3001 (admin/admin)
```

The Grafana dashboard (`observability/grafana/dashboards/visioniq.json`)
is pre-provisioned: HTTP request rate, latency p95, processing
duration p50/p95, jobs by outcome, detection/VLM/Qdrant mean latency,
Celery queue depth, storage free, process RSS.

**Honest status:** the stack files are provided and the config parses,
but there is no Docker on this VM, so Prometheus/Grafana have not been
run here and there is no dashboard screenshot yet. That is a Phase 12
item (verify from a clean checkout with Docker).

## Profiling

`scripts/profile_processing.py` runs the pipeline on a video under
`cProfile`. Results for a 120 s video are in
`docs/benchmarks/2026-11-06-phase10-profiling.md`: ONNX inference on
CPU is 54% of the time (402 ms/frame) — a hardware lever (GPU), not a
code hotspot — and ffmpeg decoding is 25%. No code change came out of
the profile.
