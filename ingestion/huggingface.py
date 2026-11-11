"""Hugging Face Hub to bronze: a daily snapshot of the most-used public models.

The Hub reports downloads as a rolling 30-day total and has no history endpoint, so growth
can only be measured by snapshotting every day and comparing. Three rankings are taken, since
each catches models the others miss: downloads (established), likes (popular) and trending
(new this week). Bronze keeps each ranking's pages exactly as returned.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from ingestion import landing
from ingestion.http import get

SOURCE = "huggingface"
MODELS_URL = "https://huggingface.co/api/models"
PAGE_SIZE = 1000
# Pages per ranking. The API allows 500 requests per 5 minutes; this is 16 a day.
RANKINGS = {"downloads": 10, "likes": 5, "trendingScore": 1}

log = logging.getLogger(__name__)


def fetch_ranking(client: httpx.Client, sort: str, pages: int) -> list[dict[str, Any]]:
    """The top `pages * PAGE_SIZE` models by `sort`, following the API's cursor links."""
    url: str | None = MODELS_URL
    params: dict[str, Any] | None = {"sort": sort, "direction": -1, "limit": PAGE_SIZE}
    models: list[dict[str, Any]] = []
    for _ in range(pages):
        if url is None:
            break
        response = get(client, url, params)
        models += response.json()
        url = response.links.get("next", {}).get("url")
        params = None  # the cursor link already carries them
    return models


def ingest_models(client: httpx.Client, today: date) -> int:
    """Write today's snapshot of each ranking once; a second run the same day is a no-op."""
    written = 0
    for sort, pages in RANKINGS.items():
        path = landing.bronze_path(SOURCE, "models", snapshot_date=today.isoformat(), ranking=sort)
        if landing.store().exists(path):
            continue
        models = fetch_ranking(client, sort, pages)
        landing.write_bronze(path, models, f"{MODELS_URL}?sort={sort}")
        log.info("huggingface %s: %d models", sort, len(models))
        written += 1
    return written
