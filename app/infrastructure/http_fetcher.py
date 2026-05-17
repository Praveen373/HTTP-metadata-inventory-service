"""
HTTP Fetcher — responsible for collecting headers, cookies, and page source.

Uses httpx.AsyncClient (non-blocking) with a shared session created at
startup and injected as a dependency. Never creates a client per-request
— that would exhaust connection pools under load.

Scope: static HTML only. JavaScript execution is explicitly out of scope
per the assignment brief.
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Value object returned from a successful HTTP fetch."""

    headers: dict[str, str]
    cookies: dict[str, str]
    page_source: str
    final_url: str  # URL after any redirects


class HTTPFetcher:
    """
    Thin wrapper around httpx.AsyncClient.

    The client is shared across all requests (injected at startup).
    follow_redirects=True handles 301/302 transparently and records
    the final URL after any redirect chain.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, url: str) -> FetchResult:
        """
        Fetch headers, cookies, and page source for a given URL.

        Raises:
            httpx.TimeoutException: if the request exceeds the configured timeout
            httpx.RequestError: on network-level failures
            httpx.HTTPStatusError: on 4xx/5xx responses
        """
        logger.info("Fetching URL: %s", url)

        response = await self._client.get(
            url,
            follow_redirects=True,
        )
        response.raise_for_status()

        # Normalise headers and cookies to plain dicts of strings.
        # httpx.Headers and Cookies are multi-value-capable; we flatten
        # them here so they serialise cleanly to MongoDB documents.
        headers: dict[str, str] = dict(response.headers)
        cookies: dict[str, str] = {k: v for k, v in response.cookies.items()}

        return FetchResult(
            headers=headers,
            cookies=cookies,
            page_source=response.text,
            final_url=str(response.url),
        )
