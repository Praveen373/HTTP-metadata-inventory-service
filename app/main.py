"""
Application factory — creates and configures the FastAPI app.

Lifespan context manager handles startup and shutdown:
  Startup:  create Motor client, httpx client, ensure DB indexes
  Shutdown: close both clients gracefully

Using lifespan (not @app.on_event) is the current FastAPI best practice.
Both clients are stored on app.state and retrieved via DI dependencies.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from app.api.v1.metadata import router as metadata_router
from app.core.config import settings
from app.infrastructure.mongo_repository import MongoRepository

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manage application-level resources.

    Motor and httpx clients are created once at startup and shared
    across all requests via app.state. This avoids per-request
    connection overhead and respects connection pool limits.
    """
    logger.info("Starting HTTP Metadata Inventory Service...")

    # Motor client — async MongoDB driver (never use PyMongo in async code)
    mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
    )

    # httpx shared async client — one connection pool for all fetches
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        follow_redirects=True,
        headers={"User-Agent": "MetadataInventoryService/1.0"},
    )

    # Ensure MongoDB indexes exist (idempotent)
    try:
        repo = MongoRepository(mongo_client)
        await repo.create_indexes()
        logger.info("MongoDB connection established and indexes ensured.")
    except ServerSelectionTimeoutError as exc:
        logger.warning(
            "MongoDB not reachable at startup — will retry on first request. (%s)", exc
        )

    # Store on app.state for dependency injection
    app.state.mongo_client = mongo_client
    app.state.http_client = http_client

    yield  # Application runs here

    # Graceful shutdown
    logger.info("Shutting down — closing clients...")
    await http_client.aclose()
    mongo_client.close()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Application factory — returns a configured FastAPI instance."""

    app = FastAPI(
        title="HTTP Metadata Inventory Service",
        description=(
            "Collects and stores HTTP headers, cookies, and page source "
            "for any given URL. Supports synchronous collection (POST) and "
            "asynchronous background collection with immediate acknowledgement (GET)."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS — permissive for development; tighten for production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(metadata_router, prefix="/api/v1")

    # Global exception handler — never expose raw tracebacks
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected error occurred."},
        )

    @app.get("/health", tags=["ops"], summary="Health check")
    async def health() -> dict:
        return {"status": "ok", "service": "metadata-inventory"}

    return app


app = create_app()
