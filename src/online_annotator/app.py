"""Application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ._version import TOOL_NAME, __version__
from .api import auth as auth_api
from .api import images as images_api
from .api import meta as meta_api
from .api import projects as projects_api
from .api.deps import CLIENT_HEADER, CLIENT_HEADER_VALUE
from .config import Settings, load_settings
from .db import init_schema, make_engine, make_session_factory
from .services.auth import LoginRateLimiter
from .services.demo import bootstrap_admin, seed_demo

logger = logging.getLogger("online_annotator")
WEB_DIR = Path(__file__).resolve().parent / "web"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Only this endpoint accepts navigator.sendBeacon, which cannot set headers; it can
# only release the caller's own lock, so it is harmless as a cross-site target.
BEACON_PATHS = ("/lock/release",)

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
       "frame-ancestors 'self'; base-uri 'self'; form-action 'self'")


def create_app(settings: Settings | None = None, *, admin_email: str | None = None,
               admin_password: str | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.prepare_storage()
    engine = make_engine(settings.resolved_database_url)
    init_schema(engine)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with session_factory() as db:
            result = bootstrap_admin(db, settings, admin_email, admin_password)
            if result.created and result.password:
                logger.warning(
                    "\n%s\n  First administrator created\n    e-mail:   %s\n    password: %s\n"
                    "  (also written to %s; change it at first sign-in)\n%s",
                    "=" * 64, result.email, result.password,
                    settings.data_dir / "initial_admin_password.txt", "=" * 64)
            if settings.demo:
                seed_demo(db, settings)
                logger.warning("DEMO MODE: sample accounts with published passwords are active. "
                               "Never use demo mode on a production server.")
        yield
        engine.dispose()

    app = FastAPI(title=TOOL_NAME, version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.login_limiter = LoginRateLimiter(settings.login_attempts_per_15min)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if (request.method in MUTATING and path.startswith("/api/")
                and request.headers.get(CLIENT_HEADER) != CLIENT_HEADER_VALUE
                and not path.endswith(BEACON_PATHS)):
            return JSONResponse({"detail": "Request blocked: missing client header (possible cross-site "
                                           "request). Reload the page and try again."}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if path.startswith("/api/") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
            problems.append(f"{where}: {err.get('msg')}" if where else err.get("msg"))
        return JSONResponse({"detail": "Please check the form: " + "; ".join(problems)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):  # pragma: no cover - safety net
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse({"detail": "Something went wrong on the server. Your last change may not be "
                                       "saved; try again, and tell an administrator if it repeats."},
                            status_code=500)

    app.include_router(meta_api.router)
    app.include_router(auth_api.router)
    app.include_router(projects_api.router)
    app.include_router(images_api.router)

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", __version__)

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        return Response(index_html, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/help", include_in_schema=False)
    def help_redirect() -> RedirectResponse:
        return RedirectResponse("./#/help")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(WEB_DIR / "static" / "img" / "favicon.svg", media_type="image/svg+xml")

    return app
