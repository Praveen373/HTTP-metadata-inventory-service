"""
Unit tests for BackgroundWorker.

Verifies:
  - dispatch() creates an asyncio.Task (no blocking)
  - _fetch_and_store() upserts on success
  - _fetch_and_store() calls mark_failed on exception
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.domain import FetchStatus
from app.workers.background_worker import BackgroundWorker


class TestBackgroundWorkerDispatch:

    @pytest.mark.asyncio
    async def test_dispatch_returns_task(self, mock_fetcher, mock_repository):
        worker = BackgroundWorker(mock_fetcher, mock_repository)
        task = worker.dispatch("abc123hash", "https://example.com")

        assert isinstance(task, asyncio.Task)
        # Allow the task to complete
        await asyncio.sleep(0)
        await task

    @pytest.mark.asyncio
    async def test_dispatch_does_not_block(self, mock_fetcher, mock_repository):
        """dispatch() must return immediately — not await the fetch."""
        fetch_started = asyncio.Event()
        fetch_allowed = asyncio.Event()

        async def slow_fetch(url):
            fetch_started.set()
            await fetch_allowed.wait()
            return MagicMock(headers={}, cookies={}, page_source="", final_url=url)

        mock_fetcher.fetch = AsyncMock(side_effect=slow_fetch)
        worker = BackgroundWorker(mock_fetcher, mock_repository)

        # dispatch must return before the fetch even starts
        task = worker.dispatch("abc", "https://example.com")
        assert not fetch_started.is_set(), "dispatch() should not await the fetch"

        # Now let it complete
        fetch_allowed.set()
        await task


class TestFetchAndStore:

    @pytest.mark.asyncio
    async def test_success_upserts_complete_record(
        self, mock_fetcher, mock_repository, sample_fetch_result
    ):
        mock_fetcher.fetch = AsyncMock(return_value=sample_fetch_result)
        worker = BackgroundWorker(mock_fetcher, mock_repository)

        await worker._fetch_and_store("deadbeef", "https://example.com")

        mock_repository.upsert.assert_awaited_once()
        upserted: object = mock_repository.upsert.call_args[0][0]
        assert upserted.status == FetchStatus.COMPLETE
        assert upserted.headers == sample_fetch_result.headers
        assert upserted.cookies == sample_fetch_result.cookies
        assert upserted.page_source == sample_fetch_result.page_source

    @pytest.mark.asyncio
    async def test_failure_marks_failed(self, mock_fetcher, mock_repository):
        mock_fetcher.fetch = AsyncMock(side_effect=Exception("timeout"))
        worker = BackgroundWorker(mock_fetcher, mock_repository)

        await worker._fetch_and_store("deadbeef", "https://example.com")

        mock_repository.mark_failed.assert_awaited_once_with("deadbeef", "timeout")
        mock_repository.upsert.assert_not_awaited()
