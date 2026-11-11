"""Bronze to silver: typed, deduplicated Parquet, one file per table.

Silver is rebuilt from all of bronze each run, so a parser fix reaches every past day.
A story can appear in many bronze files (a day refetched, several front-page snapshots);
the latest observation wins, because points and comment counts only settle over time.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion import hackernews, landing

Row = dict[str, Any]

log = logging.getLogger(__name__)

INT, STRING, TS = pa.int64(), pa.string(), pa.timestamp("s", tz="UTC")

SCHEMAS: dict[str, pa.Schema] = {
    "stories": pa.schema(
        [
            ("story_id", INT),
            ("title", STRING),
            ("url", STRING),
            ("domain", STRING),
            ("author", STRING),
            ("points", INT),
            ("num_comments", INT),
            ("story_text", STRING),
            ("created_at", TS),
            ("observed_at", TS),
            ("observed_via", STRING),
        ]
    ),
    "comments": pa.schema(
        [
            ("comment_id", INT),
            ("story_id", INT),
            ("position", INT),
            ("author", STRING),
            ("text", STRING),
            ("created_at", TS),
            ("observed_at", TS),
        ]
    ),
}
KEYS = {"stories": "story_id", "comments": "comment_id"}


def clean_text(raw: str | None) -> str | None:
    """HN's HTML (paragraph tags, links, entities) as plain text."""
    if not raw:
        return None
    text = re.sub(r"<p>", "\n\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip() or None


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.") or None


def _ts(seconds: int | None) -> datetime | None:
    return datetime.fromtimestamp(seconds, UTC) if seconds is not None else None


def algolia_story(hit: Row, observed_at: datetime) -> Row:
    return {
        "story_id": int(hit["objectID"]),
        "title": hit.get("title"),
        "url": hit.get("url"),
        "domain": domain_of(hit.get("url")),
        "author": hit.get("author"),
        "points": hit.get("points"),
        "num_comments": hit.get("num_comments"),
        "story_text": clean_text(hit.get("story_text")),
        "created_at": _ts(hit["created_at_i"]),
        "observed_at": observed_at,
        "observed_via": "algolia",
    }


def firebase_story(item: Row, observed_at: datetime) -> Row:
    return {
        "story_id": item["id"],
        "title": item.get("title"),
        "url": item.get("url"),
        "domain": domain_of(item.get("url")),
        "author": item.get("by"),
        "points": item.get("score"),
        "num_comments": item.get("descendants"),
        "story_text": clean_text(item.get("text")),
        "created_at": _ts(item.get("time")),
        "observed_at": observed_at,
        "observed_via": "firebase",
    }


def firebase_comments(item: Row, observed_at: datetime) -> Iterator[Row]:
    for position, comment in enumerate(item.get("comments", []), start=1):
        yield {
            "comment_id": comment["id"],
            "story_id": item["id"],
            "position": position,
            "author": comment.get("by"),
            "text": clean_text(comment.get("text")),
            "created_at": _ts(comment.get("time")),
            "observed_at": observed_at,
        }


def _bronze_files(endpoint: str) -> Iterator[tuple[datetime, Any]]:
    store = landing.store()
    for path in store.list_files(store.path("bronze", hackernews.SOURCE, endpoint), ".json"):
        envelope = landing.read_envelope(path)
        yield datetime.fromisoformat(envelope["fetched_at"]), envelope["payload"]


def latest(rows: Iterable[Row], key: str) -> list[Row]:
    """One row per key: the latest observation, ties broken by the order seen."""
    best: dict[Any, Row] = {}
    for row in rows:
        current = best.get(row[key])
        if current is None or row["observed_at"] >= current["observed_at"]:
            best[row[key]] = row
    return sorted(best.values(), key=lambda r: r[key])


def build_hackernews() -> dict[str, list[Row]]:
    stories: list[Row] = []
    comments: list[Row] = []
    for observed_at, hits in _bronze_files("stories"):
        stories += [algolia_story(h, observed_at) for h in hits if h.get("title")]
    for observed_at, items in _bronze_files("front_page"):
        for item in items:
            if item.get("type") == "story" and item.get("title"):
                stories.append(firebase_story(item, observed_at))
                comments += [c for c in firebase_comments(item, observed_at) if c["text"]]
    return {"stories": latest(stories, "story_id"), "comments": latest(comments, "comment_id")}


def write_table(source: str, table: str, rows: list[Row]) -> None:
    store = landing.store()
    path = landing.silver_path(source, table)
    store.make_parent(path)
    data = pa.Table.from_pylist(rows, schema=SCHEMAS[table])
    tmp = path + ".tmp"
    pq.write_table(data, tmp, filesystem=store.fs)
    store.fs.move(tmp, path)
    log.info("silver %s/%s: %d rows", source, table, data.num_rows)


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for table, rows in build_hackernews().items():
        write_table(hackernews.SOURCE, table, rows)


if __name__ == "__main__":
    main()
