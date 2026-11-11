"""Hacker News to bronze: every story by day (Algolia), plus a front-page snapshot (Firebase).

Two official read-only APIs, no key needed:
- Algolia's HN Search covers every story since 2006 and filters by time, so it drives the
  daily history and the backfill. One bronze file per UTC day holds all that day's stories.
- The Firebase API is what the site itself serves: the current front page with live scores
  and comment trees. Each run saves one snapshot with the top-level comments of each story,
  which the LLM later reads for sentiment.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

import httpx

from ingestion import landing
from ingestion.http import get_json

SOURCE = "hackernews"
ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
FIREBASE_URL = "https://hacker-news.firebaseio.com/v0"

# Algolia returns at most 1,000 hits per query, so busy windows are split until they fit.
ALGOLIA_PAGE = 1000
# Scores and comment counts settle within about two days; older days are not refetched.
SETTLE_DAYS = 2
FRONT_PAGE_STORIES = 30
COMMENTS_PER_STORY = 5

log = logging.getLogger(__name__)


# --- Algolia: stories by day -------------------------------------------------------------


def fetch_window(client: httpx.Client, start: int, end: int) -> list[dict[str, Any]]:
    """Every story created in [start, end) as Unix seconds, splitting the window if needed."""
    params = {
        "tags": "story",
        "numericFilters": f"created_at_i>={start},created_at_i<{end}",
        "hitsPerPage": ALGOLIA_PAGE,
    }
    body = get_json(client, ALGOLIA_URL, params)
    if body["nbHits"] <= ALGOLIA_PAGE or end - start <= 60:
        if body["nbHits"] > ALGOLIA_PAGE:
            log.warning(
                "over %d stories in one minute at %d; some are missing", ALGOLIA_PAGE, start
            )
        return body["hits"]
    middle = (start + end) // 2
    return fetch_window(client, start, middle) + fetch_window(client, middle, end)


def fetch_day(client: httpx.Client, day: date) -> list[dict[str, Any]]:
    """All stories created on one UTC day, oldest first."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    hits = fetch_window(client, start, start + 86_400)
    return sorted(hits, key=lambda h: (h["created_at_i"], h["objectID"]))


def ingest_stories(client: httpx.Client, today: date, backfill_days: int) -> int:
    """Write one bronze file per day; returns how many days were written."""
    days = landing.days_to_fetch(
        today, backfill_days, landing.stored_days(SOURCE, "stories", "created_date"), SETTLE_DAYS
    )
    for day in days:
        hits = fetch_day(client, day)
        path = landing.bronze_path(SOURCE, "stories", created_date=day.isoformat())
        landing.write_bronze(path, hits, ALGOLIA_URL)
        log.info("hackernews stories %s: %d", day, len(hits))
    return len(days)


# --- Firebase: front-page snapshot with comments -----------------------------------------


def fetch_item(client: httpx.Client, item_id: int) -> dict[str, Any] | None:
    return get_json(client, f"{FIREBASE_URL}/item/{item_id}.json")


def fetch_front_page(client: httpx.Client) -> list[dict[str, Any]]:
    """Top stories, each with its first few live top-level comments under `comments`."""
    ids = get_json(client, f"{FIREBASE_URL}/topstories.json")[:FRONT_PAGE_STORIES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        stories = [s for s in pool.map(lambda i: fetch_item(client, i), ids) if s]
        for story in stories:
            kid_ids = story.get("kids", [])[: COMMENTS_PER_STORY * 2]
            kids = [k for k in pool.map(lambda i: fetch_item(client, i), kid_ids) if k]
            live = [k for k in kids if not k.get("dead") and not k.get("deleted")]
            story["comments"] = live[:COMMENTS_PER_STORY]
    return stories


def ingest_front_page(client: httpx.Client, now: datetime) -> int:
    stories = fetch_front_page(client)
    path = landing.bronze_path(
        SOURCE,
        "front_page",
        snapshot_date=now.date().isoformat(),
        snapshot_hour=f"{now.hour:02d}",
    )
    landing.write_bronze(path, stories, FIREBASE_URL)
    log.info("hackernews front page: %d stories", len(stories))
    return len(stories)
