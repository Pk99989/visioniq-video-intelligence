"""VisionIQ API entrypoint. Startup: create tables, recover jobs left
running by a crash. A simple per-IP login rate limit (30/min) guards
brute-force attempts without adding a Redis dependency in laptop mode."""
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, init_db
from .routers import auth, search_chat_reports, videos
from .services import detection, worker
from .services.vlm import provider_name

app = FastAPI(title="VisionIQ", version="0.1.0",
              description="Multimodal Video Intelligence and Agentic Search Platform (independent implementation, inspired by NVIDIA VSS architecture).")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_login_hits: dict[str, list[float]] = defaultdict(list)


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
    init_db()
    db: Session = SessionLocal()
    try:
        recovered = worker.recover_stuck_jobs(db)
        if recovered:
            print(f"VisionIQ: recovered {recovered} interrupted job(s)")
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0", "vlm_provider": provider_name(),
            "detection": detection.provider_status()}


app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(search_chat_reports.router)

# Create tables at import too, so TestClient use without a lifespan
# context manager (and plain `uvicorn app.main:app`) still works.
# Startup recovery above still handles interrupted jobs on real runs.
init_db()
