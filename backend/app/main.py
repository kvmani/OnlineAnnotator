from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_config
from .db import get_engine, init_db, session_scope
from .routers import (
    annotations_router,
    auth_router,
    datasets_router,
    export_router,
    images_router,
    ledger_router,
    tools_router,
    ws_router,
)
from .services.seed_data import seed_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("online_annotator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Init database tables and seed sample data
    logger.info("Starting OnlineAnnotator backend...")
    init_db()
    with session_scope() as db:
        seed_database(db)
    logger.info("OnlineAnnotator backend ready.")
    yield
    # Shutdown
    logger.info("Shutting down OnlineAnnotator backend...")


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(
        title="OnlineAnnotator - Microstructure Semantic Segmentation",
        version="1.0.0",
        description="Intranet web application for annotating microstructures, hydride segmentation ground truth data preparation, and active learning.",
        root_path=config.server.base_path,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(auth_router)
    app.include_router(datasets_router)
    app.include_router(images_router)
    app.include_router(annotations_router)
    app.include_router(tools_router)
    app.include_router(export_router)
    app.include_router(ledger_router)
    app.include_router(ws_router)

    # Health Check
    @app.get("/health")
    @app.get("/api/v1/health")
    def health_check():
        return {
            "status": "ok",
            "service": "OnlineAnnotator",
            "version": "1.0.0",
            "target": "HydrideSegmentation",
        }

    # Mount static assets and serve frontend
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    static_dir = frontend_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve index.html for SPA
    index_file = frontend_dir / "index.html"

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Don't intercept API or WebSocket calls
        if full_path.startswith("api/") or full_path.startswith("static/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)

        if index_file.exists():
            return FileResponse(str(index_file), media_type="text/html")
        return JSONResponse({"message": "OnlineAnnotator Frontend Index Not Found"}, status_code=200)

    return app


app = create_app()
