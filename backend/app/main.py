"""FastAPI entrypoint: mounts /api/v1 and serves the built SPA at / (§1, §11)."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routers import admin, auth, health, polls, results, votes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

settings = get_settings()

# Max accepted request body. Our largest legitimate payload (20 questions × 10
# options) is a few KiB; 64 KiB is a comfortable ceiling that still blocks
# unbounded-input abuse.
MAX_BODY_BYTES = 64 * 1024


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class MaxBodySizeMiddleware:
    """Reject oversized request bodies before they reach route handlers.

    Fast path trusts a declared Content-Length; without one we buffer up to the
    cap and reject if exceeded (guards chunked/streamed bodies).
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in (
            "GET",
            "HEAD",
            "DELETE",
            "OPTIONS",
        ):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                return await self._reject(send)
            if declared > self.max_bytes:
                return await self._reject(send)
            return await self.app(scope, receive, send)

        # No Content-Length: buffer with a hard cap, then replay to the app.
        buffered: list[dict] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    return await self._reject(send)
                buffered.append(message)
                more = message.get("more_body", False)
            else:  # http.disconnect
                buffered.append(message)
                more = False

        iterator = iter(buffered)

        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        return await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"detail":"Request too large."}'}
        )


app = FastAPI(title="vote.sjolie.net", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(MaxBodySizeMiddleware, max_bytes=MAX_BODY_BYTES)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


api = FastAPI(title="vote API")
api.include_router(health.router, tags=["health"])
api.include_router(auth.router, tags=["auth"])
api.include_router(polls.router, tags=["polls"])
api.include_router(votes.router, tags=["votes"])
api.include_router(results.router, tags=["results"])
api.include_router(admin.router, tags=["admin"])

# Mount the versioned API. Everything else falls through to the SPA.
app.mount("/api/v1", api)


@app.get("/api/v1")
async def api_root() -> dict:
    return {"service": "vote.sjolie.net", "version": "v1"}


# ---------------------------------------------------------------------------
# Static SPA serving with history-fallback to index.html (§1).
# ---------------------------------------------------------------------------
def resolve_static_file(static_root: str, full_path: str) -> str | None:
    """Map a request path to a real file *inside* static_root, or None.

    Prevents path traversal: the resolved realpath must stay within the
    (realpath of the) static root. `..`, absolute paths, and symlink escapes all
    resolve to None.
    """
    if not full_path:
        return None
    root = os.path.realpath(static_root)
    candidate = os.path.realpath(os.path.join(root, full_path))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
    except ValueError:
        # Different drives / mixed absolute paths.
        return None
    if os.path.isfile(candidate):
        return candidate
    return None


def add_spa_fallback(target: FastAPI, static_root: str) -> None:
    """Register the SPA history-fallback route on `target` for `static_root`."""
    index_path = os.path.join(static_root, "index.html")
    assets_dir = os.path.join(static_root, "assets")
    if os.path.isdir(assets_dir):
        target.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @target.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Never let /api paths hit the SPA fallback.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        safe = resolve_static_file(static_root, full_path)
        if safe is not None:
            return FileResponse(safe)
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)


if os.path.isdir(settings.static_dir):
    add_spa_fallback(app, settings.static_dir)
else:  # pragma: no cover - dev without built frontend
    @app.get("/")
    async def no_frontend() -> dict:
        return {"detail": "Frontend not built; API is at /api/v1"}
