"""arXiv bronze to silver rows: one row per paper, from the Atom XML kept in bronze.

Ids are stored without the version suffix ("2611.10022", not "2611.10022v1") so that a paper
is one row whatever version was seen, and so Hugging Face's `arxiv:` tags join to it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pyarrow as pa
from defusedxml.ElementTree import fromstring

from ingestion.arxiv import SOURCE
from processing.silver import bronze_files, latest

Row = dict[str, Any]

STRING, TS = pa.string(), pa.timestamp("s", tz="UTC")

SCHEMAS: dict[str, pa.Schema] = {
    "papers": pa.schema(
        [
            ("arxiv_id", STRING),
            ("version", pa.int64()),
            ("title", STRING),
            ("abstract", STRING),
            ("authors", pa.list_(STRING)),
            ("primary_category", STRING),
            ("categories", pa.list_(STRING)),
            ("comment", STRING),
            ("published_at", TS),
            ("updated_at", TS),
            ("observed_at", TS),
        ]
    ),
}

NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ID_PATTERN = re.compile(r"abs/(.+?)v(\d+)$")


def _text(entry: ET.Element, path: str) -> str | None:
    node = entry.find(path, NS)
    if node is None or node.text is None:
        return None
    # Titles and abstracts arrive hard-wrapped; fold the line breaks into spaces.
    return " ".join(node.text.split()) or None


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse_feed(xml: str, observed_at: datetime) -> Iterator[Row]:
    """Every paper in one Atom page."""
    for entry in fromstring(xml).findall("a:entry", NS):
        match = ID_PATTERN.search(_text(entry, "a:id") or "")
        if not match:
            continue  # an error entry, not a paper
        primary = entry.find("arxiv:primary_category", NS)
        yield {
            "arxiv_id": match.group(1),
            "version": int(match.group(2)),
            "title": _text(entry, "a:title"),
            "abstract": _text(entry, "a:summary"),
            "authors": [_text(a, "a:name") for a in entry.findall("a:author", NS)],
            "primary_category": primary.get("term") if primary is not None else None,
            "categories": [c.get("term") for c in entry.findall("a:category", NS)],
            "comment": _text(entry, "arxiv:comment"),
            "published_at": _ts(_text(entry, "a:published")),
            "updated_at": _ts(_text(entry, "a:updated")),
            "observed_at": observed_at,
        }


def build() -> dict[str, list[Row]]:
    rows: list[Row] = []
    for _, observed_at, pages in bronze_files(SOURCE, "papers"):
        for xml in pages:
            rows += parse_feed(xml, observed_at)
    return {"papers": latest(rows, "arxiv_id")}
