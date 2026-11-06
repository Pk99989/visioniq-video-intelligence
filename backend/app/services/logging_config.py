"""Structured logging (Phase 10).

One JSON object per line on stdout: {"ts", "level", "logger", "msg",
"request_id", "job_id", ...}. request_id is set by the request-ID
middleware (main.py) and job_id by the pipeline (worker.py); both
travel in contextvars so every log line in a request or a job carries
them without passing them through every call. When LOG_FORMAT=text
the same records render as human-readable lines (handy for local dev).

The formatter only copies JSON-safe scalar extras (str/int/float/
bool/None) — a stray object on a record never breaks the log line.
"""
import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "visioniq_request_id", default=None)
job_id_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "visioniq_job_id", default=None)

# Fields LogRecord always has — everything else on the record is a
# caller-supplied extra and may be worth emitting.
_RESERVED = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "threadInfo", "process", "processName", "message", "asctime",
    "taskName",
})


def set_request_id(value: str | None) -> contextvars.Token:
    return request_id_ctx.set(value)


def set_job_id(value: int | None) -> contextvars.Token:
    return job_id_ctx.set(value)


def get_request_id() -> str | None:
    return request_id_ctx.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid is not None:
            out["request_id"] = rid
        jid = job_id_ctx.get()
        if jid is not None:
            out["job_id"] = jid
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Replace the root handler with one that writes to stdout.
    Safe to call twice (uvicorn's own config runs separately).

    Also re-enables every logger: alembic's fileConfig (run by
    run_migrations) disables all loggers not named in alembic.ini —
    including uvicorn's — and leaves them disabled after the upgrade.
    Without this, no uvicorn access log and no app INFO log would ever
    be emitted after migrations run."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for lg in list(logging.root.manager.loggerDict.values()):
        if isinstance(lg, logging.Logger):
            lg.disabled = False
    # Uvicorn's loggers keep their own plain-format handlers (set by
    # uvicorn's dictConfig before the app is imported). Route them
    # through the same handler so server, access and app logs are all
    # one JSON stream; propagate=False so a line is never emitted
    # twice (once by the uvicorn handler, once by the root handler).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
        lg.addHandler(handler)
        lg.propagate = False
        lg.setLevel(getattr(logging, level.upper(), logging.INFO))
