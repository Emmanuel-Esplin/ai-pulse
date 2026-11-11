"""arXiv to bronze: every new AI paper, one file per submission day, Atom XML kept as returned.

The query covers cs.AI, cs.LG, cs.CL, cs.CV and stat.ML, cross-lists included, filtered by
the v1 submission time. arXiv's terms ask for one request every 3 seconds.
Papers appear in the API when announced, a day or more after submission (longer over a
weekend), so the last few days are refetched until they settle.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import httpx

from ingestion import landing
from ingestion.http import get

SOURCE = "arxiv"
API_URL = "https://export.arxiv.org/api/query"
CATEGORIES = ("cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML")
PAGE_SIZE = 1000
PAUSE_SECONDS = 3.0
SETTLE_DAYS = 4
# The API now and then returns an empty page for a query that has results; retry those.
EMPTY_PAGE_RETRIES = 3

log = logging.getLogger(__name__)


def day_query(day: date) -> str:
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    start, end = day.strftime("%Y%m%d0000"), (day + timedelta(days=1)).strftime("%Y%m%d0000")
    return f"({cats}) AND submittedDate:[{start} TO {end}]"


def _total(xml: str) -> int:
    match = re.search(r"<opensearch:totalResults>(\d+)<", xml)
    return int(match.group(1)) if match else 0


def _entries(xml: str) -> int:
    return xml.count("<entry>")


def fetch_day(client: httpx.Client, day: date, pause: float = PAUSE_SECONDS) -> list[str]:
    """Every Atom page for papers first submitted on `day` (UTC)."""
    pages: list[str] = []
    start, total = 0, None
    while total is None or start < total:
        params = {
            "search_query": day_query(day),
            "start": start,
            "max_results": PAGE_SIZE,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        for attempt in range(EMPTY_PAGE_RETRIES):
            time.sleep(pause if pages or attempt else 0)
            xml = get(client, API_URL, params).text
            total = _total(xml)
            if _entries(xml) or start >= total:
                break
            log.warning("arxiv %s: empty page at %d of %d, retrying", day, start, total)
        else:
            raise RuntimeError(f"arXiv kept returning empty pages for {day} at {start}")
        pages.append(xml)
        start += _entries(xml)
    return pages


def ingest_papers(
    client: httpx.Client, today: date, backfill_days: int, pause: float = PAUSE_SECONDS
) -> int:
    """Write one bronze file per submission day; returns how many days were written."""
    days = landing.days_to_fetch(
        today, backfill_days, landing.stored_days(SOURCE, "papers", "submitted_date"), SETTLE_DAYS
    )
    for n, day in enumerate(days):
        if n:
            time.sleep(pause)
        pages = fetch_day(client, day, pause)
        path = landing.bronze_path(SOURCE, "papers", submitted_date=day.isoformat())
        landing.write_bronze(path, pages, API_URL)
        log.info("arxiv %s: %d papers", day, sum(_entries(p) for p in pages))
    return len(days)
