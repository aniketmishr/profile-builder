from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.db import get_db
from app.logging import tenant_ctx
from app.repo import ScopedRepo, find_tenant_for_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Tenant API key")


async def get_repo(
    request: Request,
    db: Session = Depends(get_db),
    api_key: str | None = Depends(api_key_header),
) -> ScopedRepo:
    """Resolve the tenant from the API key and hand back a repo locked to that tenant."""
    if not api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    tenant_id = await run_in_threadpool(find_tenant_for_key, db, api_key)
    if tenant_id is None:
        raise HTTPException(401, "Invalid or revoked API key")
    request.state.tenant_id = tenant_id
    tenant_ctx.set(tenant_id)
    return ScopedRepo(db, tenant_id)
