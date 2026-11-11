"""One HTTP client setup and retry policy for every source."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# A plain client name; no contact details are sent to the APIs.
USER_AGENT = "ai-pulse/0.1 (+https://github.com/Emmanuel-Esplin/ai-pulse)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def make_client(timeout: float = 30) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRY_STATUSES


@retry(
    retry=retry_if_exception(_retryable),
    wait=wait_exponential(multiplier=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def get(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """GET with retries on network errors, rate limits and server errors."""
    response = client.get(url, params=params)
    response.raise_for_status()
    return response


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> Any:
    return get(client, url, params).json()
