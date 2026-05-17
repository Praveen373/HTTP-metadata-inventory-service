"""
Dependency injection — FastAPI dependencies that wire infrastructure
to services on each request.

All heavy objects (Motor client, httpx client) are created once at
startup (stored on app.state) and retrieved here. This avoids
creating new connections per request.
"""

from typing import Annotated

import httpx
from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorClient

from app.infrastructure.http_fetcher import HTTPFetcher
from app.infrastructure.mongo_repository import MongoRepository
from app.services.metadata_service import MetadataService
from app.workers.background_worker import BackgroundWorker


def get_mongo_client(request: Request) -> AsyncIOMotorClient:
    return request.app.state.mongo_client


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_repository(
    mongo_client: Annotated[AsyncIOMotorClient, Depends(get_mongo_client)],
) -> MongoRepository:
    return MongoRepository(mongo_client)


def get_fetcher(
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> HTTPFetcher:
    return HTTPFetcher(http_client)


def get_worker(
    fetcher: Annotated[HTTPFetcher, Depends(get_fetcher)],
    repository: Annotated[MongoRepository, Depends(get_repository)],
) -> BackgroundWorker:
    return BackgroundWorker(fetcher, repository)


def get_metadata_service(
    fetcher: Annotated[HTTPFetcher, Depends(get_fetcher)],
    repository: Annotated[MongoRepository, Depends(get_repository)],
    worker: Annotated[BackgroundWorker, Depends(get_worker)],
) -> MetadataService:
    return MetadataService(fetcher, repository, worker)
