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
    # Environment: development | production. Production refuses the
    # dev-only password-reset token return (see H1 in TECHNICAL_DEBT.md).
    ENV: str = _env("ENV", "development")
    # H1 fix (v0.4.1): the reset token must NOT be returned in the API
    # response — anyone could reset anyone's password with no email
    # access. It is returned only when this dev flag is explicitly on
    # AND ENV is not production, so local tests can still exercise the
    # reset flow. In production, wire an email sender instead: the
    # token is created and stored hashed, and this endpoint only says
    # "if that email is registered, a reset token was created".
    DEV_RETURN_RESET_TOKEN: bool = _env("DEV_RETURN_RESET_TOKEN", "0") == "1"
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
    # Phase 2 (v0.4.0): adaptive sampling + dedupe. Short videos get up
    # to ADAPTIVE_FPS_MAX fps; long videos drop towards ADAPTIVE_FPS_MIN
    # so total frames stay near MAX_FRAMES. Dedupe drops near-identical
    # frames (histogram correlation >= DEDUPE_SIMILARITY) but always
    # keeps one frame per DEDUPE_MAX_GAP_SECONDS so a static shot still
    # yields frames. SCENE_MERGE_SIMILARITY merges adjacent scenes
    # whose representative frames look the same (flicker splits).
    ADAPTIVE_SAMPLING: bool = _env("ADAPTIVE_SAMPLING", "1") == "1"
    ADAPTIVE_FPS_MIN: float = _env_float("ADAPTIVE_FPS_MIN", 0.2)
    ADAPTIVE_FPS_MAX: float = _env_float("ADAPTIVE_FPS_MAX", 2.0)
    DEDUPE_SIMILARITY: float = _env_float("DEDUPE_SIMILARITY", 0.995)
    DEDUPE_MAX_GAP_SECONDS: float = _env_float("DEDUPE_MAX_GAP_SECONDS", 2.0)
    SCENE_MERGE_SIMILARITY: float = _env_float("SCENE_MERGE_SIMILARITY", 0.99)
    EMBEDDING_DIM: int = _env_int("EMBEDDING_DIM", 384)
    # vlm: fallback | openai_compatible | ollama | nvidia_nim
    VLM_PROVIDER: str = _env("VLM_PROVIDER", "fallback")
    VLM_MODEL: str = _env("VLM_MODEL", "")
    VLM_BASE_URL: str = _env("VLM_BASE_URL", "")
    VLM_API_KEY: str = _env("VLM_API_KEY", "")
    # Phase 1 (v0.4.0): VLM reliability. Timeout per attempt, retries
    # with exponential backoff, short timeout for the health probe.
    VLM_TIMEOUT_SECONDS: int = _env_int("VLM_TIMEOUT_SECONDS", 120)
    VLM_MAX_RETRIES: int = _env_int("VLM_MAX_RETRIES", 2)
    VLM_RETRY_BACKOFF_SECONDS: float = _env_float("VLM_RETRY_BACKOFF_SECONDS", 2.0)
    VLM_HEALTH_TIMEOUT_SECONDS: int = _env_int("VLM_HEALTH_TIMEOUT_SECONDS", 10)
    QDRANT_URL: str = _env("QDRANT_URL", "")
    QDRANT_COLLECTION: str = _env("QDRANT_COLLECTION", "visioniq_frames")
    SYNC_PROCESSING: bool = _env("SYNC_PROCESSING", "0") == "1"
    WORKER_CONCURRENCY: int = _env_int("WORKER_CONCURRENCY", 1)
    # Phase 2: embeddings: hash | fastembed | sentence_transformers
    EMBEDDING_PROVIDER: str = _env("EMBEDDING_PROVIDER", "hash")
    FASTEMBED_MODEL: str = _env("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")
    # Phase 2: detection weights. ONNX (yolov8n.onnx) is preferred on the
    # laptop: it runs on onnxruntime without torch. The .pt file is used
    # only when ultralytics is installed.
    YOLO_MODEL_PATH: str = _env("YOLO_MODEL_PATH", "")
    # Phase 2: worker mode: in_process | celery. Celery needs Redis.
    WORKER_MODE: str = _env("WORKER_MODE", "in_process")
    CELERY_BROKER_URL: str = _env("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = _env("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
