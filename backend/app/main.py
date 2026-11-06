"""VisionIQ API entrypoint. Startup: run Alembic migrations (the only
schema path — H2), recover jobs left running by a crash, prune expired
auth tokens, validate the VLM URL against the SSRF allow-list (Phase 9).
Auth rate limiting is Redis-backed in the auth router (M5); there is no
in-memory login middleware any more (removed in v0.11.0 — it only
covered /login and reset on every restart)."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .routers import auth, search_chat_reports, videos
from .services import detection, worker
from .services.vlm import check_health as vlm_health, provider_name, validate_vlm_base_url

app = FastAPI(title="VisionIQ", version="0.11.0",
              description="Multimodal Video Intelligence and Agentic Search Platform (independent implementation, inspired by NVIDIA VSS architecture).")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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


@app.on_event("startup")
def startup():
    # Phase 9 (SSRF): a VLM URL pointing at an internal address is a
    # startup error, not a runtime surprise. Only checked for real
    # VLM providers; the fallback/template path needs no URL.
    if settings.VLM_PROVIDER != "fallback" and settings.VLM_BASE_URL:
        validate_vlm_base_url(settings.VLM_BASE_URL)
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
    return {"status": "ok", "version": "0.11.0", "vlm_provider": provider_name(),
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
