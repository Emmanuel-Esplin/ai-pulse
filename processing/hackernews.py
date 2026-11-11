"""Hacker News bronze to silver rows: stories and top-level comments.

A story can appear in many bronze files (a day refetched, several front-page snapshots);
the latest observation wins, because points and comment counts only settle over time.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import pyarrow as pa

from ingestion.hackernews import SOURCE
from processing.silver import bronze_files, latest

Row = dict[str, Any]

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


def build() -> dict[str, list[Row]]:
    stories: list[Row] = []
    comments: list[Row] = []
    for _, observed_at, hits in bronze_files(SOURCE, "stories"):
        stories += [algolia_story(h, observed_at) for h in hits if h.get("title")]
    for _, observed_at, items in bronze_files(SOURCE, "front_page"):
        for item in items:
            if item.get("type") == "story" and item.get("title"):
                stories.append(firebase_story(item, observed_at))
                comments += [c for c in firebase_comments(item, observed_at) if c["text"]]
    return {"stories": latest(stories, "story_id"), "comments": latest(comments, "comment_id")}
