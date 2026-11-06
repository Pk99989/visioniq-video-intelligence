"""VisionIQ API entrypoint. Startup: run Alembic migrations (the only
schema path — H2), recover jobs left running by a crash, prune expired
auth tokens, validate the VLM URL against the SSRF allow-list (Phase 9).
Auth rate limiting is Redis-backed in the auth router (M5); there is no
in-memory login middleware any more (removed in v0.11.0 — it only
covered /login and reset on every restart).
Phase 10: structured JSON logs (LOG_FORMAT), a request-ID middleware
(X-Request-ID, echoed on the response and in every log line), HTTP
metrics middleware, and /metrics (Prometheus)."""
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .routers import auth, search_chat_reports, videos
from .services import detection, metrics, worker
from .services.logging_config import configure_logging, request_id_ctx, set_request_id
from .services.vlm import check_health as vlm_health, provider_name, validate_vlm_base_url

configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
logger = logging.getLogger("visioniq.main")

app = FastAPI(title="VisionIQ", version="1.0.0",
              description="Multimodal Video Intelligence and Agentic Search Platform (independent implementation, inspired by NVIDIA VSS architecture).")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def _route_template(request: Request) -> str:
    """The matched route template (/api/v1/videos/{video_id}) for
    metric labels — never the raw path, which would create one time
    series per video id. Unmatched paths (404) are 'unmatched'."""
    route = request.scope.get("route")
    return getattr(route, "path", "unmatched") if route else "unmatched"


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    # Registered first so it runs innermost (after the request-ID
    # middleware): the timing covers the whole handler, not the
    # request-ID bookkeeping. /metrics is not counted (a scrape would
    # count itself) and /health stays out of the latency histogram
    # only if it is a probe — no, health is cheap and real traffic
    # can hit it; it stays in.
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    metrics.observe_http(request.method, _route_template(request),
                         response.status_code, time.perf_counter() - start)
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Registered last so it runs outermost: the id is set before
    # anything else logs. A client-supplied X-Request-ID is honoured
    # (tracing across services); otherwise a fresh one is minted.
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    token = set_request_id(rid)
    try:
        response = await call_next(request)
    finally:
        # Reset via the token so a reused event-loop task cannot leak
        # this request's id into the next one.
        request_id_ctx.reset(token)
    response.headers["X-Request-ID"] = rid
    return response

def run_migrations() -> None:
    """Apply Alembic migrations to settings.DATABASE_URL (H2: the app
    never creates tables with create_all). Runs at import so
    TestClient use without a lifespan context manager still works,
    and again at startup (a no-op when already migrated).

    Phase 10: alembic's fileConfig (from alembic.ini) replaces the
    root logger's handlers and sets the root level to WARNING — after
    an upgrade, no app INFO log would ever be emitted. Re-apply the
    structured logging config here so the JSON formatter survives."""
    from alembic import command
    from alembic.config import Config

    from .database import normalized_database_url
    from .services.logging_config import configure_logging

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", normalized_database_url())
    command.upgrade(cfg, "head")
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)


@app.on_event("startup")
def startup():
    # Phase 9 (SSRF): a VLM URL pointing at an internal address is a
    # startup error, not a runtime surprise. Only checked for real
    # VLM providers; the fallback/template path needs no URL.
    if settings.VLM_PROVIDER != "fallback" and settings.VLM_BASE_URL:
        validate_vlm_base_url(settings.VLM_BASE_URL)
    # Phase 10: warn once at startup when the storage volume is
    # nearly full (the /metrics disk gauge carries the same number).
    import shutil

    try:
        usage = shutil.disk_usage(settings.STORAGE_DIR)
        free_pct = 100.0 * usage.free / usage.total if usage.total else 0.0
        if free_pct < settings.STORAGE_WARN_FREE_PCT:
            logger.warning("storage disk only %.1f%% free (%d bytes left)",
                           free_pct, usage.free)
    except Exception as e:  # noqa: BLE001 - a failed probe must not block startup
        logger.warning("storage disk probe failed at startup: %s", e)
    run_migrations()
    db: Session = SessionLocal()
    try:
        recovered = worker.recover_stuck_jobs(db)
        if recovered:
            print(f"VisionIQ: recovered {recovered} interrupted job(s)")
        pruned = auth.prune_expired_tokens(db)
        if pruned:
            print(f"VisionIQ: pruned {pruned} expired token(s)")
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "vlm_provider": provider_name(),
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "worker_mode": settings.WORKER_MODE,
            "detection": detection.provider_status()}


@app.get("/health/vlm")
def health_vlm():
    """Live VLM probe (Phase 1): pings the configured model server and
    reports whether the model is actually reachable. No auth: it reveals
    no data, only the provider/model/status."""
    return vlm_health()


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus scrape target (Phase 10). Unauthenticated by design
    — Prometheus needs to reach it without a user token. In production
    restrict it at the reverse proxy / firewall to the monitoring
    network (see docs/OBSERVABILITY.md); METRICS_ENABLED=0 turns it
    off entirely."""
    if not settings.METRICS_ENABLED:
        from fastapi import HTTPException

        raise HTTPException(404, "Metrics disabled")
    from prometheus_client import CONTENT_TYPE_LATEST

    return PlainTextResponse(metrics.generate_metrics(),
                             media_type=CONTENT_TYPE_LATEST)


app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(search_chat_reports.router)

# Run migrations at import too, so TestClient use without a lifespan
# context manager (and plain `uvicorn app.main:app`) still works.
# Startup recovery above still handles interrupted jobs on real runs.
run_migrations()
