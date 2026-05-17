"""
Integration tests for POST and GET API endpoints.

Uses FastAPI's TestClient (via httpx) with mocked infrastructure.
No real MongoDB or HTTP calls — infrastructure is overridden via
FastAPI's dependency_overrides mechanism.

This tests the full request→response cycle including:
  - Request validation
  - HTTP status codes
  - Response body shape
  - Correct service method called
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.domain import FetchStatus, MetadataRecord
from app.models.schemas import MetadataResponse
from app.services.metadata_service import MetadataService


@pytest.fixture
def mock_service(complete_record, pending_record):
    """A fully mocked MetadataService."""
    svc = MagicMock(spec=MetadataService)
    svc.create = AsyncMock(return_value=complete_record)
    svc.get_or_queue = AsyncMock(return_value=(complete_record, False))
    return svc


@pytest.fixture
def client(mock_service):
    """
    TestClient with MetadataService dependency overridden.
    This is the correct FastAPI way to inject test doubles.
    """
    from app.core.dependencies import get_metadata_service

    app = create_app()
    app.dependency_overrides[get_metadata_service] = lambda: mock_service

    # Provide dummy app.state so lifespan deps don't fail
    app.state.mongo_client = MagicMock()
    app.state.http_client = MagicMock()

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── POST /api/v1/metadata ──────────────────────────────────────────────────────

class TestPostMetadata:

    def test_post_valid_url_returns_200(self, client, mock_service, complete_record):
        response = client.post("/api/v1/metadata", json={"url": "https://example.com"})
        assert response.status_code == 200

    def test_post_response_has_required_fields(self, client, complete_record):
        response = client.post("/api/v1/metadata", json={"url": "https://example.com"})
        data = response.json()
        assert "url" in data
        assert "status" in data
        assert "headers" in data
        assert "cookies" in data
        assert "page_source" in data
        assert "created_at" in data

    def test_post_status_is_complete(self, client):
        response = client.post("/api/v1/metadata", json={"url": "https://example.com"})
        assert response.json()["status"] == FetchStatus.COMPLETE

    def test_post_invalid_url_returns_422(self, client):
        response = client.post("/api/v1/metadata", json={"url": "not-a-url"})
        assert response.status_code == 422

    def test_post_missing_url_returns_422(self, client):
        response = client.post("/api/v1/metadata", json={})
        assert response.status_code == 422

    def test_post_calls_service_create(self, client, mock_service):
        client.post("/api/v1/metadata", json={"url": "https://example.com"})
        mock_service.create.assert_awaited_once_with("https://example.com")

    def test_post_fetch_error_returns_502(self, client, mock_service):
        mock_service.create = AsyncMock(side_effect=Exception("connection refused"))
        response = client.post("/api/v1/metadata", json={"url": "https://example.com"})
        assert response.status_code == 502


# ── GET /api/v1/metadata ───────────────────────────────────────────────────────

class TestGetMetadata:

    def test_get_cache_hit_returns_200(self, client, mock_service, complete_record):
        mock_service.get_or_queue = AsyncMock(return_value=(complete_record, False))
        response = client.get("/api/v1/metadata", params={"url": "https://example.com"})
        assert response.status_code == 200

    def test_get_cache_miss_returns_202(self, client, mock_service, pending_record):
        mock_service.get_or_queue = AsyncMock(return_value=(pending_record, True))
        response = client.get("/api/v1/metadata", params={"url": "https://example.com"})
        assert response.status_code == 202

    def test_get_202_contains_message(self, client, mock_service, pending_record):
        mock_service.get_or_queue = AsyncMock(return_value=(pending_record, True))
        response = client.get("/api/v1/metadata", params={"url": "https://example.com"})
        data = response.json()
        assert "message" in data
        assert data["status"] == FetchStatus.PENDING

    def test_get_missing_url_param_returns_422(self, client):
        response = client.get("/api/v1/metadata")
        assert response.status_code == 422

    def test_get_invalid_url_returns_422(self, client):
        response = client.get("/api/v1/metadata", params={"url": "ftp://bad-scheme"})
        assert response.status_code == 422

    def test_get_calls_service_get_or_queue(self, client, mock_service, complete_record):
        mock_service.get_or_queue = AsyncMock(return_value=(complete_record, False))
        client.get("/api/v1/metadata", params={"url": "https://example.com"})
        mock_service.get_or_queue.assert_awaited_once_with("https://example.com")

    def test_get_200_response_has_data_fields(self, client, mock_service, complete_record):
        mock_service.get_or_queue = AsyncMock(return_value=(complete_record, False))
        response = client.get("/api/v1/metadata", params={"url": "https://example.com"})
        data = response.json()
        assert "headers" in data
        assert "cookies" in data
        assert "page_source" in data


# ── Health check ───────────────────────────────────────────────────────────────

class TestHealthCheck:

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
