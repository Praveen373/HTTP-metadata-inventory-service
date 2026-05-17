"""
MongoDB repository — the only layer that speaks directly to the database.

Uses Motor (async MongoDB driver) so every operation is non-blocking
and safe inside FastAPI's async event loop.

Key design decisions:
- url_hash (SHA-256) carries a unique index → O(1) lookups, no duplicates
- upsert=True on writes → naturally idempotent; safe to call multiple times
- All methods accept/return domain models, not raw dicts
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import ASCENDING, IndexModel

from app.core.config import settings
from app.models.domain import FetchStatus, MetadataRecord

logger = logging.getLogger(__name__)


class MongoRepository:
    """Async repository for MetadataRecord persistence."""

    def __init__(self, client: AsyncIOMotorClient) -> None:
        db = client[settings.mongo_db_name]
        self._col: AsyncIOMotorCollection = db[settings.mongo_collection_name]

    async def create_indexes(self) -> None:
        """
        Idempotent index creation — called once at application startup.
        url_hash unique index ensures no duplicate records and
        powers fast lookups without a full collection scan.
        """
        indexes = [
            IndexModel([("url_hash", ASCENDING)], unique=True, name="url_hash_unique"),
            IndexModel([("status", ASCENDING)], name="status_idx"),
        ]
        await self._col.create_indexes(indexes)
        logger.info("MongoDB indexes ensured.")

    async def find_by_url_hash(self, url_hash: str) -> Optional[MetadataRecord]:
        """Return a MetadataRecord or None if not found."""
        doc = await self._col.find_one({"url_hash": url_hash})
        if doc is None:
            return None
        doc.pop("_id", None)
        return MetadataRecord(**doc)

    async def upsert(self, record: MetadataRecord) -> None:
        """
        Insert or update a record keyed on url_hash.
        Using upsert=True makes this idempotent — safe to call from
        both the POST handler and the background worker.
        """
        payload = record.model_dump(exclude_none=False)
        payload.pop("_id", None)
        await self._col.update_one(
            {"url_hash": record.url_hash},
            {"$set": payload},
            upsert=True,
        )

    async def mark_failed(self, url_hash: str, error: str) -> None:
        """Update record status to failed with an error message."""
        await self._col.update_one(
            {"url_hash": url_hash},
            {
                "$set": {
                    "status": FetchStatus.FAILED,
                    "error_message": error,
                    "fetched_at": datetime.now(timezone.utc),
                }
            },
        )
