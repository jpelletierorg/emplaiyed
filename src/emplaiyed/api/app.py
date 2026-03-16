"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from emplaiyed.api.deps import close_db, get_assets_dir

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

# ---------------------------------------------------------------------------
# Jinja2 — shared instance
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: ensure assets directory exists
    get_assets_dir().mkdir(parents=True, exist_ok=True)
    yield
    # Shutdown
    close_db()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="emplaiyed",
        description="AI-powered job seeking toolkit — web interface",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ---- static files ----
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Mount generated assets if the directory exists
    assets_dir = get_assets_dir()
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # ---- routes ----
    from emplaiyed.api.routes.pages import router as pages_router
    from emplaiyed.api.routes.health import router as health_router
    from emplaiyed.api.routes.profile import router as profile_router
    from emplaiyed.api.routes.sources import router as sources_router
    from emplaiyed.api.routes.applications import router as applications_router
    from emplaiyed.api.routes.work_items import router as work_items_router
    from emplaiyed.api.routes.chat import router as chat_router
    from emplaiyed.api.routes.contacts import router as contacts_router

    app.include_router(health_router)
    app.include_router(pages_router)
    app.include_router(profile_router)
    app.include_router(sources_router)
    app.include_router(applications_router)
    app.include_router(work_items_router)
    app.include_router(chat_router)
    app.include_router(contacts_router)

    return app
