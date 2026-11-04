"""VisionIQ configuration. All secrets come from the environment, never code.

This module is deliberately dependency-light: it reads env vars so the same
code runs on SQLite (laptop dev) and PostgreSQL (docker-compose / prod).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


class Settings:
    DATABASE_URL: str = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'visioniq.db'}")
    STORAGE_DIR: Path = Path(_env("STORAGE_DIR", str(BASE_DIR / "storage")))
    JWT_SECRET: str = _env("JWT_SECRET", "dev-only-change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = _env_int("JWT_EXPIRE_MINUTES", 60 * 24)
    MAX_UPLOAD_MB: int = _env_int("MAX_UPLOAD_MB", 500)
    ALLOWED_EXTENSIONS: set[str] = {
        e.strip().lower()
        for e in _env("ALLOWED_EXTENSIONS", "mp4,mov,webm,mkv,avi").split(",")
        if e.strip()
    }
    FRAME_FPS: float = _env_float("FRAME_FPS", 1.0)
    MAX_FRAMES: int = _env_int("MAX_FRAMES", 120)
    SCENE_THRESHOLD: float = _env_float("SCENE_THRESHOLD", 30.0)
    EMBEDDING_DIM: int = _env_int("EMBEDDING_DIM", 384)
    # vlm: fallback | openai_compatible | ollama | nvidia_nim
    VLM_PROVIDER: str = _env("VLM_PROVIDER", "fallback")
    VLM_MODEL: str = _env("VLM_MODEL", "")
    VLM_BASE_URL: str = _env("VLM_BASE_URL", "")
    VLM_API_KEY: str = _env("VLM_API_KEY", "")
    QDRANT_URL: str = _env("QDRANT_URL", "")
    QDRANT_COLLECTION: str = _env("QDRANT_COLLECTION", "visioniq_frames")
    SYNC_PROCESSING: bool = _env("SYNC_PROCESSING", "0") == "1"
    WORKER_CONCURRENCY: int = _env_int("WORKER_CONCURRENCY", 1)


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
