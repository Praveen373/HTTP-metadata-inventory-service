"""
API-layer schemas — what the HTTP client sends and receives.
Kept separate from domain models so the API contract can evolve
independently of internal data structures.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator

from app.models.domain import FetchStatus


class MetadataCreateRequest(BaseModel):
    """Body for POST /metadata."""

    url: str

    @field_validator("url")
    @classmethod
    def url_must_have_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.strip()


class MetadataResponse(BaseModel):
    """
    Unified response for both POST (200) and GET (200/202).
    Optional fields are null when status == 'pending'.
    """

    url: str
    status: FetchStatus
    headers: Optional[dict[str, str]] = None
    cookies: Optional[dict[str, str]] = None
    page_source: Optional[str] = None
    fetched_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"use_enum_values": True}


class AcknowledgementResponse(BaseModel):
    """Returned as 202 when a GET triggers a background fetch."""

    message: str
    url: str
    status: FetchStatus = FetchStatus.PENDING

    model_config = {"use_enum_values": True}
