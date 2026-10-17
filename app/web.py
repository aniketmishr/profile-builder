"""Serves the built React app: the embeddable chat at /chat/<session> and the mock admin panel at /admin.

The chat must be embeddable in a third-party admin panel, so it is allowed to be framed by the origins in
FRAME_ANCESTORS (default "*": tighten it to your panel's origin). Every other page may only be framed by
this site. If the app has not been built (a plain checkout), the routes answer with a hint instead of failing.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def mount_web(app: FastAPI, static_dir: Path, frame_ancestors: str) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        hint = {"detail": "web app not built; run `npm run build:api` in web/ (the Docker image does this)"}

        @app.get("/chat/{session_id}", include_in_schema=False)
        @app.get("/admin", include_in_schema=False)
        def not_built(session_id: str | None = None):
            return JSONResponse(hint, status_code=404)

        return

    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    def page(ancestors: str) -> FileResponse:
        return FileResponse(index, headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"frame-ancestors {ancestors}",
            "X-Content-Type-Options": "nosniff",
        })

    @app.get("/chat/{session_id}", include_in_schema=False)
    def chat_page(session_id: str):
        return page(frame_ancestors)

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    def admin_page():
        return page("'self'")
