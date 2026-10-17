from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.db import get_db
from app.logging import tenant_ctx
from app.repo import ScopedRepo, find_tenant_for_key
from app.security import verify_session_token

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Tenant API key")
session_token_header = APIKeyHeader(
    name="X-Session-Token", auto_error=False, scheme_name="SessionToken",
    description="Signed token from a session's chat_url. Only valid for that session's debrief endpoints.",
)


async def _repo_from_api_key(request: Request, db: Session, api_key: str | None) -> ScopedRepo:
    if not api_key:
        raise HTTPException(401, "Missing X-API-Key header")
    tenant_id = await run_in_threadpool(find_tenant_for_key, db, api_key)
    if tenant_id is None:
        raise HTTPException(401, "Invalid or revoked API key")
    request.state.tenant_id = tenant_id
    tenant_ctx.set(tenant_id)
    return ScopedRepo(db, tenant_id)


async def get_repo(
    request: Request,
    db: Session = Depends(get_db),
    api_key: str | None = Depends(api_key_header),
) -> ScopedRepo:
    """Resolve the tenant from the API key and hand back a repo locked to that tenant."""
    return await _repo_from_api_key(request, db, api_key)


async def get_debrief_repo(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: str | None = Depends(api_key_header),
    token: str | None = Depends(session_token_header),
) -> ScopedRepo:
    """Debrief endpoints accept the tenant API key (admin panel) OR a session token (embedded chat).

    A token is bound to one session: it can only reach that session's debrief endpoints, because only these
    routes use this dependency. Its tenant comes from the signed claims, never from the client.
    """
    if token:
        claims = verify_session_token(token)
        if claims is None:
            raise HTTPException(401, "Invalid or expired session token")
        if claims["sid"] != session_id:
            raise HTTPException(404, "session not found")  # don't reveal that other sessions exist
        request.state.tenant_id = claims["tid"]
        tenant_ctx.set(claims["tid"])
        return ScopedRepo(db, claims["tid"])
    return await _repo_from_api_key(request, db, api_key)
