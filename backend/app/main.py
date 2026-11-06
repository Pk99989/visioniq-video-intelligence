"""VisionIQ API entrypoint. Startup: run Alembic migrations (the only
schema path — H2), recover jobs left running by a crash, prune expired
auth tokens. A simple per-IP login rate limit (30/min) guards
brute-force attempts without adding a Redis dependency in laptop mode."""
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .routers import auth, search_chat_reports, videos
from .services import detection, worker
from .services.vlm import check_health as vlm_health, provider_name

app = FastAPI(title="VisionIQ", version="0.9.0",
              description="Multimodal Video Intelligence and Agentic Search Platform (independent implementation, inspired by NVIDIA VSS architecture).")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_login_hits: dict[str, list[float]] = defaultdict(list)


def run_migrations() -> None:
    """Apply Alembic migrations to settings.DATABASE_URL (H2: the app
    never creates tables with create_all). Runs at import so
    TestClient use without a lifespan context manager still works,
    and again at startup (a no-op when already migrated)."""
    from alembic import command
    from alembic.config import Config

    from .database import normalized_database_url

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", normalized_database_url())
    command.upgrade(cfg, "head")


@app.middleware("http")
async def login_rate_limit(request: Request, call_next):
    if request.url.path.endswith("/auth/login"):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        _login_hits[ip] = [t for t in _login_hits[ip] if now - t < 60]
        if len(_login_hits[ip]) >= 30:
            return JSONResponse({"detail": "Too many login attempts, try again later"}, status_code=429)
        _login_hits[ip].append(now)
    return await call_next(request)


@app.on_event("startup")
def startup():
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
    return {"status": "ok", "version": "0.9.0", "vlm_provider": provider_name(),
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "worker_mode": settings.WORKER_MODE,
            "detection": detection.provider_status()}


@app.get("/health/vlm")
def health_vlm():
    """Live VLM probe (Phase 1): pings the configured model server and
    reports whether the model is actually reachable. No auth: it reveals
    no data, only the provider/model/status."""
    return vlm_health()


app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(search_chat_reports.router)

# Run migrations at import too, so TestClient use without a lifespan
# context manager (and plain `uvicorn app.main:app`) still works.
# Startup recovery above still handles interrupted jobs on real runs.
run_migrations()
