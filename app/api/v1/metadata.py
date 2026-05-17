"""
API Router — v1 metadata endpoints.

Transport layer only: validate input, call the service, shape the response.
No business logic lives here.

Endpoints:
  POST /api/v1/metadata  — collect and store metadata for a URL (sync)
  GET  /api/v1/metadata  — retrieve metadata; triggers async fetch on miss
"""

import logging
from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core.dependencies import get_metadata_service
from app.models.domain import FetchStatus
from app.models.schemas import (
    AcknowledgementResponse,
    MetadataCreateRequest,
    MetadataResponse,
)
from app.services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.post(
    "",
    response_model=MetadataResponse,
    status_code=status.HTTP_200_OK,
    summary="Collect and store URL metadata",
    description=(
        "Fetches headers, cookies, and page source for the given URL "
        "synchronously, stores the result in MongoDB, and returns the "
        "full metadata record."
    ),
)
async def create_metadata(
    body: MetadataCreateRequest,
    service: Annotated[MetadataService, Depends(get_metadata_service)],
) -> MetadataResponse:
    """
    POST /api/v1/metadata

    Always performs a fresh fetch — existing records are overwritten.
    Returns 200 with the full metadata on success.
    Returns 422 if the URL is malformed.
    Returns 502 if the target URL is unreachable.
    """
    try:
        record = await service.create(body.url)
    except Exception as exc:
        logger.error("POST create failed for url=%s: %s", body.url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch URL: {exc}",
        )

    return MetadataResponse(
        url=record.url,
        status=record.status,
        headers=record.headers,
        cookies=record.cookies,
        page_source=record.page_source,
        fetched_at=record.fetched_at,
        created_at=record.created_at,
    )


@router.get(
    "",
    summary="Retrieve URL metadata",
    description=(
        "Returns stored metadata for a URL if available (200). "
        "If the URL has not been fetched yet, queues a background fetch "
        "and returns 202 Accepted immediately."
    ),
)
async def get_metadata(
    url: Annotated[str, Query(description="The URL to retrieve metadata for")],
    service: Annotated[MetadataService, Depends(get_metadata_service)],
) -> JSONResponse:
    """
    GET /api/v1/metadata?url=https://example.com

    200 — record found (status: complete or failed)
    202 — cache miss; background fetch has been queued
    422 — url query parameter missing or blank
    """
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url must be a valid http:// or https:// URL",
        )

    record, is_new = await service.get_or_queue(url)

    if is_new:
        # 202 Accepted — background worker has been dispatched
        body = AcknowledgementResponse(
            message=(
                "Metadata not yet available. A background fetch has been "
                "queued. Retry this request in a few seconds."
            ),
            url=record.url,
            status=FetchStatus.PENDING,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=body.model_dump(),
        )

    # 200 OK — return whatever we have (complete, pending re-check, or failed)
    body = MetadataResponse(
        url=record.url,
        status=record.status,
        headers=record.headers if record.headers else None,
        cookies=record.cookies if record.cookies else None,
        page_source=record.page_source,
        fetched_at=record.fetched_at,
        created_at=record.created_at,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body.model_dump(mode="json"),
    )
