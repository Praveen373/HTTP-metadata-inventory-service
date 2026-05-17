"""
Domain models — the canonical shape of data throughout the application.
These are pure Python / Pydantic v2 models with no framework coupling.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class FetchStatus(str, Enum):
    """Lifecycle states of a metadata record."""

    PENDING = "pending"      # queued for background fetch
    COMPLETE = "complete"    # data fetched and stored
    FAILED = "failed"        # fetch attempted but errored


class MetadataRecord(BaseModel):
    """
    The canonical metadata document stored in MongoDB.

    url_hash: SHA-256 hex digest of the normalised URL — used as the
              unique lookup key with a MongoDB unique index.
    """

    url_hash: str
    url: str
    status: FetchStatus = FetchStatus.PENDING
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    page_source: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    fetched_at: Optional[datetime] = None

    model_config = {"use_enum_values": True}
