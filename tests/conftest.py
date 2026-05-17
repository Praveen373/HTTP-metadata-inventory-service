"""
Shared pytest fixtures.

Strategy:
  - Unit tests mock all I/O (no real HTTP, no real Mongo)
  - Integration tests use a real MongoDB via docker-compose
  - httpx.AsyncClient is mocked with httpx.MockTransport for unit tests
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response

from app.infrastructure.http_fetcher import FetchResult, HTTPFetcher
from app.infrastructure.mongo_repository import MongoRepository
from app.models.domain import FetchStatus, MetadataRecord
from app.workers.background_worker import BackgroundWorker


# ── Sample data ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_url() -> str:
    return "https://example.com"


@pytest.fixture
def sample_url_hash() -> str:
    import hashlib
    return hashlib.sha256(b"https://example.com").hexdigest()


@pytest.fixture
def sample_fetch_result() -> FetchResult:
    return FetchResult(
        headers={"content-type": "text/html", "server": "nginx"},
        cookies={"session": "abc123"},
        page_source="<html><body>Hello World</body></html>",
        final_url="https://example.com",
    )


@pytest.fixture
def complete_record(sample_url, sample_url_hash) -> MetadataRecord:
    from datetime import datetime, timezone
    return MetadataRecord(
        url_hash=sample_url_hash,
        url=sample_url,
        status=FetchStatus.COMPLETE,
        headers={"content-type": "text/html"},
        cookies={"session": "abc123"},
        page_source="<html></html>",
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pending_record(sample_url, sample_url_hash) -> MetadataRecord:
    return MetadataRecord(
        url_hash=sample_url_hash,
        url=sample_url,
        status=FetchStatus.PENDING,
    )


# ── Mocked infrastructure ──────────────────────────────────────────────────────

@pytest.fixture
def mock_fetcher(sample_fetch_result) -> HTTPFetcher:
    fetcher = MagicMock(spec=HTTPFetcher)
    fetcher.fetch = AsyncMock(return_value=sample_fetch_result)
    return fetcher


@pytest.fixture
def mock_repository() -> MongoRepository:
    repo = MagicMock(spec=MongoRepository)
    repo.find_by_url_hash = AsyncMock(return_value=None)
    repo.upsert = AsyncMock(return_value=None)
    repo.mark_failed = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_worker() -> BackgroundWorker:
    worker = MagicMock(spec=BackgroundWorker)
    worker.dispatch = MagicMock(return_value=MagicMock())  # returns a Task-like
    return worker
