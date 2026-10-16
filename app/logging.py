import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

# Set by the auth dependency / services; every log line carries them.
tenant_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
session_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "msg": record.getMessage(),
            "tenant_id": tenant_ctx.get(),
            "session_id": session_ctx.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def log(msg: str, **fields) -> None:
    logging.getLogger("app").info(msg, extra={"extra_fields": fields})
