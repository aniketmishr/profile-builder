import time

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from app.api import debug_router, router
from app.config import get_settings
from app.db import get_engine
from app.logging import log, setup_logging

settings = get_settings()
setup_logging(settings.log_level)

app = FastAPI(
    title="Profile Builder API",
    version="0.1.0",
    description="Per-user profile store for support-agent debriefs. Authenticate with the `X-API-Key` header.",
)
app.include_router(router)
if settings.enable_debug_endpoints:
    app.include_router(debug_router)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/health":
        log(
            "request", method=request.method, path=request.url.path, status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
            tenant_id=getattr(request.state, "tenant_id", None),
        )
    return response


@app.get("/health", tags=["ops"])
def health():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ok", "db": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return {"service": "profile-builder", "docs": "/docs", "health": "/health"}
