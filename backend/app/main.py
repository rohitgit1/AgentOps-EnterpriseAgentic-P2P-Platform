"""P2P AgentOps — application entry point.

Run locally:  python -m app.main   (or: uvicorn app.main:app --reload)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .config import settings
from .database import SessionLocal, drop_all, init_db
from .services.events import bus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
logger = logging.getLogger("p2p")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind_loop(asyncio.get_running_loop())

    if settings.reset_database_on_startup:
        logger.info("Resetting database (P2P_RESET_DATABASE_ON_STARTUP=1)")
        drop_all()
    init_db()

    if settings.seed_on_startup:
        from .seed import seed_all

        db = SessionLocal()
        try:
            result = seed_all(db)
            if result.get("seeded"):
                logger.info(
                    "Demo dataset ready: %s invoices, %s suppliers",
                    result.get("invoices"), result.get("suppliers"),
                )
            else:
                logger.info("Existing data found — seed skipped.")
        finally:
            db.close()

    logger.info(
        "P2P AgentOps %s ready · HITL enforcement=%s · reasoning=%s",
        settings.version,
        settings.enforce_human_in_the_loop,
        settings.llm_provider,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Enterprise Agentic Procure-to-Pay operations platform. Ten specialised agents "
        "propose; qualified humans decide; every decision is audited."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/api/health", tags=["governance"])
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "hitl_enforced": settings.enforce_human_in_the_loop,
        "agents_paused": settings.agents_paused,
    }


# --------------------------------------------------------------------------
# Serve the built frontend when it exists, so `python -m app.main` alone
# gives the client a complete, single-port demo.
# --------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "app": settings.app_name,
            "version": settings.version,
            "note": "Frontend build not found. Run the UI dev server, or build it into frontend/dist.",
            "api_docs": "/api/docs",
        }


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=bool(int(__import__("os").environ.get("P2P_RELOAD", "0"))),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
