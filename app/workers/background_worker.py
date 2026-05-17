"""
Background Worker — fire-and-forget async task dispatcher.

CRITICAL DESIGN NOTE:
The assignment requires: "must run independently of the request-response
cycle and must not delay the API's response" and explicitly forbids
"loops or external service-to-self HTTP calls".

We use asyncio.create_task() — NOT FastAPI's BackgroundTasks.

Why not BackgroundTasks?
  FastAPI's BackgroundTasks are tied to the request/response lifecycle.
  They run *after* the response is sent, but the task reference is still
  held inside the Starlette middleware chain. Under certain error
  conditions this can block cleanup.

asyncio.create_task() schedules a coroutine directly on the running
event loop, completely decoupled from the HTTP request that spawned it.
The endpoint returns instantly; the task lives on independently.
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.infrastructure.http_fetcher import HTTPFetcher
from app.infrastructure.mongo_repository import MongoRepository
from app.models.domain import FetchStatus, MetadataRecord

logger = logging.getLogger(__name__)


class BackgroundWorker:
    """Dispatches fire-and-forget fetch tasks onto the event loop."""

    def __init__(self, fetcher: HTTPFetcher, repository: MongoRepository) -> None:
        self._fetcher = fetcher
        self._repository = repository

    def dispatch(self, url_hash: str, url: str) -> asyncio.Task:
        """
        Schedule a fetch-and-store coroutine as a background task.

        Returns the Task object (callers can ignore it — it runs on its own).
        The task is tracked by the event loop; exceptions are logged, not
        swallowed silently.
        """
        task = asyncio.create_task(
            self._fetch_and_store(url_hash, url),
            name=f"fetch:{url_hash[:8]}",
        )
        # Attach a done-callback so unhandled exceptions surface in logs
        task.add_done_callback(self._on_task_done)
        logger.info("Background task dispatched for url_hash=%s", url_hash[:8])
        return task

    async def _fetch_and_store(self, url_hash: str, url: str) -> None:
        """
        Core background coroutine:
          1. Fetch headers, cookies, page_source via HTTPFetcher
          2. Upsert the complete record into MongoDB
          3. On any error → mark the record as FAILED
        """
        try:
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
            logger.info("Background fetch complete for url_hash=%s", url_hash[:8])

        except Exception as exc:
            logger.error(
                "Background fetch failed for url_hash=%s: %s",
                url_hash[:8],
                exc,
            )
            await self._repository.mark_failed(url_hash, str(exc))

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """Log any exception that wasn't explicitly caught inside the task."""
        if task.cancelled():
            logger.warning("Background task %s was cancelled.", task.get_name())
        elif task.exception():
            logger.error(
                "Unhandled exception in background task %s: %s",
                task.get_name(),
                task.exception(),
            )
