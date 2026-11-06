"""SQLAlchemy engine/session. SQLite is the laptop default; PostgreSQL is
selected purely by setting DATABASE_URL, no code change needed.

Phase 7 (M1): Postgres gets a bounded connection pool (pool_size /
max_overflow / timeout / recycle from settings). SQLite keeps the
single-connection default (check_same_thread=False) because its
pool is a SingletonThreadPool by design.

Schema is managed by Alembic only (H2): nothing here calls
create_all on the app path. The app runs `alembic upgrade head` at
startup (see app/main.py run_migrations); tests do the same through
the app import.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

# SQLAlchemy 2.x maps the bare "postgresql://" scheme to the psycopg
# (v3) driver, which VisionIQ does not install — requirements pin
# psycopg2-binary. Rewrite the bare scheme to psycopg2 so the plain
# URL in .env.example and docker-compose.yml just works.
def normalized_database_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


_DB_URL = normalized_database_url()

if _DB_URL.startswith("sqlite"):
    engine = create_engine(_DB_URL,
                           connect_args={"check_same_thread": False}, future=True)
else:
    engine = create_engine(
        _DB_URL, future=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_POOL_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Legacy helper kept for scripts that build a scratch DB outside
    the app path. The app itself uses Alembic migrations (H2) — do
    not call this from app code."""
    from . import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(bind=engine)
