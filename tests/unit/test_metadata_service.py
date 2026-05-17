"""
Unit tests for MetadataService.

All I/O is mocked — these tests run without MongoDB or network access.
They verify the service's orchestration logic: what it calls, when,
and what it returns.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, call

import pytest
import pytest_asyncio

from app.models.domain import FetchStatus, MetadataRecord
from app.services.metadata_service import MetadataService, _hash_url


class TestHashUrl:
    """URL hashing must be deterministic and stable."""

    def test_produces_sha256_hex(self):
        url = "https://example.com"
        result = _hash_url(url)
        expected = hashlib.sha256(url.encode()).hexdigest()
        assert result == expected

    def test_same_url_same_hash(self):
        url = "https://example.com/path?q=1"
        assert _hash_url(url) == _hash_url(url)

    def test_different_urls_different_hashes(self):
        assert _hash_url("https://example.com") != _hash_url("https://other.com")

    def test_hash_is_64_chars(self):
        # SHA-256 hex digest is always 64 characters
        assert len(_hash_url("https://example.com")) == 64


class TestMetadataServiceCreate:
    """POST path: fetch synchronously and store."""

    @pytest.mark.asyncio
    async def test_create_fetches_and_stores(
        self, mock_fetcher, mock_repository, mock_worker, sample_url, sample_fetch_result
    ):
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)
        record = await service.create(sample_url)

        mock_fetcher.fetch.assert_awaited_once_with(sample_url)
        mock_repository.upsert.assert_awaited_once()
        assert record.status == FetchStatus.COMPLETE
        assert record.url == sample_url
        assert record.headers == sample_fetch_result.headers
        assert record.cookies == sample_fetch_result.cookies
        assert record.page_source == sample_fetch_result.page_source

    @pytest.mark.asyncio
    async def test_create_does_not_dispatch_worker(
        self, mock_fetcher, mock_repository, mock_worker, sample_url
    ):
        """POST should NEVER touch the background worker."""
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)
        await service.create(sample_url)
        mock_worker.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_propagates_fetch_error(
        self, mock_fetcher, mock_repository, mock_worker, sample_url
    ):
        mock_fetcher.fetch = AsyncMock(side_effect=Exception("connection refused"))
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)

        with pytest.raises(Exception, match="connection refused"):
            await service.create(sample_url)

        mock_repository.upsert.assert_not_awaited()


class TestMetadataServiceGetOrQueue:
    """GET path: cache hit returns record; miss queues background task."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_record_and_false(
        self, mock_fetcher, mock_repository, mock_worker, sample_url, complete_record
    ):
        mock_repository.find_by_url_hash = AsyncMock(return_value=complete_record)
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)

        record, is_new = await service.get_or_queue(sample_url)

        assert is_new is False
        assert record.status == FetchStatus.COMPLETE
        mock_worker.dispatch.assert_not_called()
        mock_fetcher.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_miss_creates_pending_and_dispatches(
        self, mock_fetcher, mock_repository, mock_worker, sample_url
    ):
        mock_repository.find_by_url_hash = AsyncMock(return_value=None)
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)

        record, is_new = await service.get_or_queue(sample_url)

        assert is_new is True
        assert record.status == FetchStatus.PENDING
        mock_repository.upsert.assert_awaited_once()
        mock_worker.dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_dispatches_correct_args(
        self, mock_fetcher, mock_repository, mock_worker, sample_url, sample_url_hash
    ):
        mock_repository.find_by_url_hash = AsyncMock(return_value=None)
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)

        await service.get_or_queue(sample_url)

        args = mock_worker.dispatch.call_args
        assert args[0][0] == sample_url_hash  # url_hash
        assert args[0][1] == sample_url       # url

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_fetch(
        self, mock_fetcher, mock_repository, mock_worker, sample_url, complete_record
    ):
        """On a cache hit we must NOT make an outbound HTTP request."""
        mock_repository.find_by_url_hash = AsyncMock(return_value=complete_record)
        service = MetadataService(mock_fetcher, mock_repository, mock_worker)

        await service.get_or_queue(sample_url)

        mock_fetcher.fetch.assert_not_awaited()
