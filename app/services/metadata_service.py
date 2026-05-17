"""
MetadataService — orchestrates the core business logic.

This layer sits between the API router (transport) and the
infrastructure (fetcher + repository). Neither layer knows about
the other; all coordination happens here.

URL hashing:
  SHA-256 of the raw URL string is used as the stable lookup key.
  This gives us O(1) MongoDB lookups via the unique index, and means
  we never rely on string-matching URLs (which can vary by trailing
  slash, encoding, etc.).
"""

import hashlib
import logging
from datetime import datetime, timezone

from app.infrastructure.http_fetcher import HTTPFetcher
from app.infrastructure.mongo_repository import MongoRepository
from app.models.domain import FetchStatus, MetadataRecord
from app.workers.background_worker import BackgroundWorker

logger = logging.getLogger(__name__)


def _hash_url(url: str) -> str:
    """Stable SHA-256 hex digest of a URL string."""
    return hashlib.sha256(url.encode()).hexdigest()


class MetadataService:
    """
    Coordinates fetch, store, and cache-check operations.

    Injected with infrastructure dependencies — no direct I/O here.
    """

    def __init__(
        self,
        fetcher: HTTPFetcher,
        repository: MongoRepository,
        worker: BackgroundWorker,
    ) -> None:
        self._fetcher = fetcher
        self._repository = repository
        self._worker = worker

    async def create(self, url: str) -> MetadataRecord:
        """
        POST handler logic:
          Fetch the URL synchronously (within this request), store the
          full result, and return the completed record.

        If the URL was already fetched (url_hash exists), we re-fetch
        and overwrite — POST is always a fresh collection.
        """
        url_hash = _hash_url(url)
        logger.info("POST create: url_hash=%s", url_hash[:8])

        result = await self._fetcher.fetch(url)

        record = MetadataRecord(
            url_hash=url_hash,
            url=url,
            status=FetchStatus.COMPLETE,
            headers=result.headers,
            cookies=result.cookies,
            page_source=result.page_source,
            fetched_at=datetime.now(timezone.utc),
        )
        await self._repository.upsert(record)
        return record

    async def get_or_queue(self, url: str) -> tuple[MetadataRecord, bool]:
        """
        GET handler logic. Returns (record, is_new).

        Cache hit  → return (record, False) — caller sends 200
        Cache miss → insert pending, fire background task
                     return (pending_record, True) — caller sends 202

        The 'is_new' flag tells the router which HTTP status to use.
        """
        url_hash = _hash_url(url)
        existing = await self._repository.find_by_url_hash(url_hash)

        if existing is not None:
            logger.info("Cache HIT: url_hash=%s status=%s", url_hash[:8], existing.status)
            return existing, False

        # Cache miss — create a pending record immediately so any
        # concurrent GET for the same URL won't spawn a duplicate task.
        logger.info("Cache MISS: url_hash=%s — queuing background fetch", url_hash[:8])
        pending = MetadataRecord(
            url_hash=url_hash,
            url=url,
            status=FetchStatus.PENDING,
        )
        await self._repository.upsert(pending)

        # Fire-and-forget: does NOT block the response
        self._worker.dispatch(url_hash, url)

        return pending, True
