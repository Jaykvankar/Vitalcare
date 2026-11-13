"""FastAPI application: API + the built React app on one origin."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth_routes, devices, ingest_routes, patients
from .config import PROJECT_DIR, get_settings
from .db import create_schema, init_engine
from .ml.infer import load_model
from .security import audit, server_keys

log = logging.getLogger("rpm")
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Device endpoints authenticate with signatures / HMAC proofs, not cookies, so CSRF checks do not apply.
DEVICE_PATHS = ("/api/ingest", "/api/devices/pair")


def init_backend() -> None:
    settings = get_settings()          # fails fast if RPM_MASTER_KEY is missing
    init_engine(settings.database_url)
    create_schema()
    server_keys.load_or_create()
    load_model()                       # fails fast if the model file does not match its pinned hash


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    init_backend()
    audit.append("server_start")
    yield
    from .simulator import runner

    runner.stop()
    audit.append("server_stop")
    audit.checkpoint_now()


def create_app(*, with_lifespan: bool = True) -> FastAPI:
    app = FastAPI(title="Secure Remote Patient Monitoring", lifespan=lifespan if with_lifespan else None,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # noqa: ANN001, ANN202
        path = request.url.path
        # CSRF defence for cookie-authenticated calls. Device ingest is authenticated by signatures instead.
        if request.method in UNSAFE and path.startswith("/api/") and not path.startswith(DEVICE_PATHS):
            origin = request.headers.get("origin")
            if origin is not None and origin not in get_settings().allowed_origins:
                return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
            if request.headers.get("x-rpm-request") != "1":
                return JSONResponse({"detail": "Missing X-RPM-Request header"}, status_code=403)
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Strict-Transport-Security"] = "max-age=31536000"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if path.startswith("/api/docs"):
            h["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"
            )
        else:
            h["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        if path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        return response

    app.include_router(auth_routes.router)
    app.include_router(patients.router)
    app.include_router(admin.router)
    app.include_router(ingest_routes.router)
    app.include_router(devices.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):  # noqa: ANN202
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            candidate = (FRONTEND_DIST / full_path).resolve()
            if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
