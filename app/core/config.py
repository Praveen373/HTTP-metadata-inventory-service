"""
Application configuration.
All settings are loaded from environment variables (or .env file).
pydantic-settings validates and type-coerces every value at startup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object — injected as a dependency where needed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # MongoDB
    mongo_uri: str = "mongodb://mongo:27017"
    mongo_db_name: str = "metadata_inventory"
    mongo_collection_name: str = "metadata"

    # HTTP fetcher
    http_timeout_seconds: float = 15.0
    http_max_retries: int = 2

    # App
    app_env: str = "development"
    log_level: str = "INFO"


# Module-level singleton — imported everywhere
settings = Settings()
