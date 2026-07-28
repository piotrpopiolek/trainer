from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware
from app.api.routers import (
    account,
    auth,
    catalog,
    health,
    legal,
    measurements,
    onboarding,
    progress,
    satellites,
    sessions,
    sync,
    today,
)
from app.core.config import settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(
    title="Trainer API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(BodySizeLimitMiddleware)
register_exception_handlers(app)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(measurements.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(legal.router, prefix="/api")
app.include_router(today.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(satellites.router, prefix="/api")
app.include_router(sync.router, prefix="/api")


@app.get("/api")
async def api_root() -> dict[str, str]:
    return {
        "service": "trainer-api",
        "version": __version__,
        "env": settings.app_env,
    }
