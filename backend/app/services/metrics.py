"""Prometheus metrics (Phase 10).

/metrics serves the default prometheus_client REGISTRY (which already
includes process CPU/RSS, GC and Python info) plus VisionIQ counters,
histograms and gauges. Runtime gauges (disk, DB pool, Celery queue
depth, GPU) are refreshed at scrape time by refresh_runtime_gauges()
so a scrape always shows the current value without a background
poller. Every refresh is best-effort: a failed probe logs a warning
and leaves the last value in place instead of breaking /metrics.

Cardinality: the HTTP histogram is labelled by route template
(e.g. /api/v1/videos/{video_id}), never by raw path, so a video id
cannot create a new time series per request.
"""
import logging
import shutil
import subprocess
import time

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

from ..config import settings
from ..database import engine

logger = logging.getLogger("visioniq.metrics")

HTTP_REQUESTS = Counter(
    "visioniq_http_requests_total", "HTTP requests by method, route and status",
    ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "visioniq_http_request_duration_seconds", "HTTP request latency by method and route",
    ["method", "route"])
VIDEO_PROCESSING_DURATION = Histogram(
    "visioniq_video_processing_duration_seconds",
    "End-to-end pipeline time per video (probe to ready/failed)")
VIDEO_JOBS = Counter(
    "visioniq_video_processing_jobs_total", "Finished pipeline jobs by outcome",
    ["status"])
DETECTION_DURATION = Histogram(
    "visioniq_detection_seconds", "Per-frame YOLO inference time")
VLM_DURATION = Histogram(
    "visioniq_vlm_caption_seconds", "VLM caption call latency by provider",
    ["provider"])
QDRANT_SEARCH_DURATION = Histogram(
    "visioniq_qdrant_search_seconds", "Qdrant vector search latency (read path)")
CELERY_QUEUE_DEPTH = Gauge(
    "visioniq_celery_queue_depth", "Tasks waiting in the Celery broker (best effort; -1 when unknown)")
STORAGE_DISK_FREE = Gauge(
    "visioniq_storage_disk_free_bytes", "Free bytes on the volume holding STORAGE_DIR")
STORAGE_DISK_TOTAL = Gauge(
    "visioniq_storage_disk_total_bytes", "Total bytes on the volume holding STORAGE_DIR")
DB_POOL_SIZE = Gauge(
    "visioniq_db_pool_size", "DB connection pool size (0 when the engine has no pool)")
DB_POOL_CHECKED_OUT = Gauge(
    "visioniq_db_pool_checked_out", "DB connections currently checked out")
GPU_UTILIZATION = Gauge(
    "visioniq_gpu_utilization_percent", "GPU utilisation from nvidia-smi (absent without a GPU)")


def observe_http(method: str, route: str, status: int, duration: float) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(duration)


def _refresh_disk() -> None:
    try:
        usage = shutil.disk_usage(settings.STORAGE_DIR)
        STORAGE_DISK_FREE.set(usage.free)
        STORAGE_DISK_TOTAL.set(usage.total)
        free_pct = 100.0 * usage.free / usage.total if usage.total else 0.0
        if free_pct < settings.STORAGE_WARN_FREE_PCT:
            logger.warning("storage disk only %.1f%% free (%d bytes left)",
                           free_pct, usage.free)
    except Exception as e:  # noqa: BLE001 - a failed probe must not break /metrics
        logger.warning("disk usage probe failed: %s", e)


def _refresh_db_pool() -> None:
    try:
        pool = engine.pool
        DB_POOL_SIZE.set(pool.size() if hasattr(pool, "size") else 0)
        DB_POOL_CHECKED_OUT.set(pool.checkedout() if hasattr(pool, "checkedout") else 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("DB pool probe failed: %s", e)


def _refresh_celery_queue() -> None:
    """Queue depth via Celery inspect. Needs Redis; on the laptop
    profile (in_process worker) there is no broker to ask, so the
    gauge stays at -1 (unknown) instead of a misleading 0."""
    if settings.WORKER_MODE != "celery":
        CELERY_QUEUE_DEPTH.set(-1)
        return
    try:
        from .celery_app import celery_app

        insp = celery_app.control.inspect(timeout=2)
        reserved = insp.reserved() or {}
        depth = sum(len(tasks) for tasks in reserved.values())
        CELERY_QUEUE_DEPTH.set(depth)
    except Exception as e:  # noqa: BLE001
        logger.warning("Celery queue probe failed: %s", e)
        CELERY_QUEUE_DEPTH.set(-1)


def _refresh_gpu() -> None:
    """nvidia-smi when a GPU exists; silently absent otherwise (this
    VM and CPU-only laptops have no GPU)."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            GPU_UTILIZATION.set(float(proc.stdout.strip().splitlines()[0]))
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        pass  # No GPU — the gauge simply never appears.


def refresh_runtime_gauges() -> None:
    _refresh_disk()
    _refresh_db_pool()
    _refresh_celery_queue()
    _refresh_gpu()


def generate_metrics() -> bytes:
    from prometheus_client import generate_latest

    refresh_runtime_gauges()
    return generate_latest(REGISTRY)
