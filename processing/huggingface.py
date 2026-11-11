"""Hugging Face bronze to silver rows: one row per model per daily snapshot.

A model often appears in several rankings on the same day; those are merged into one row
that records which rankings it was in. Only the trending ranking carries trendingScore.
The Hub's tags are parsed into the fields trends need: license, the base model it was built
on (and how: finetune, quantized, adapter, merge) and the arXiv papers it cites.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pyarrow as pa

from ingestion.huggingface import SOURCE
from processing.silver import bronze_files

Row = dict[str, Any]

INT, STRING, TS = pa.int64(), pa.string(), pa.timestamp("s", tz="UTC")

SCHEMAS: dict[str, pa.Schema] = {
    "model_snapshots": pa.schema(
        [
            ("snapshot_date", pa.date32()),
            ("model_id", STRING),
            ("author", STRING),
            ("model_name", STRING),
            ("downloads_30d", INT),
            ("likes", INT),
            ("trending_score", INT),
            ("pipeline_tag", STRING),
            ("library_name", STRING),
            ("license", STRING),
            ("base_model", STRING),
            ("base_relation", STRING),
            ("arxiv_ids", pa.list_(STRING)),
            ("rankings", pa.list_(STRING)),
            ("created_at", TS),
            ("observed_at", TS),
        ]
    ),
}

BASE_RELATIONS = ("finetune", "quantized", "adapter", "merge")


def parse_tags(tags: list[str]) -> Row:
    """License, base model and relation, and cited arXiv ids from a model's Hub tags."""
    license_ = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
    arxiv_ids = sorted({t.split(":", 1)[1] for t in tags if t.startswith("arxiv:")})
    base_model, relation = None, None
    for tag in tags:
        parts = tag.split(":", 2)
        if parts[0] != "base_model":
            continue
        if len(parts) == 3 and parts[1] in BASE_RELATIONS:
            base_model, relation = parts[2], parts[1]
            break  # a relation tag is the most specific; take the first
        if base_model is None:
            base_model = parts[1]
    return {
        "license": license_,
        "base_model": base_model,
        "base_relation": relation,
        "arxiv_ids": arxiv_ids,
    }


def model_row(model: Row, snapshot_date: date, ranking: str, observed_at: datetime) -> Row:
    author, _, name = model["id"].rpartition("/")
    created = model.get("createdAt")
    return {
        "snapshot_date": snapshot_date,
        "model_id": model["id"],
        "author": author or None,
        "model_name": name,
        "downloads_30d": model.get("downloads"),
        "likes": model.get("likes"),
        "trending_score": model.get("trendingScore"),
        "pipeline_tag": model.get("pipeline_tag"),
        "library_name": model.get("library_name"),
        **parse_tags(model.get("tags", [])),
        "rankings": [ranking],
        "created_at": datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
        "observed_at": observed_at,
    }


def merge(rows: list[Row]) -> list[Row]:
    """One row per (snapshot_date, model_id), keeping every ranking and any trending score."""
    merged: dict[tuple[date, str], Row] = {}
    for row in rows:
        key = (row["snapshot_date"], row["model_id"])
        if key not in merged:
            merged[key] = row
            continue
        kept = merged[key]
        kept["rankings"] = sorted(set(kept["rankings"]) | set(row["rankings"]))
        if kept["trending_score"] is None:
            kept["trending_score"] = row["trending_score"]
    return [merged[k] for k in sorted(merged)]


def build() -> dict[str, list[Row]]:
    rows: list[Row] = []
    for path, observed_at, models in bronze_files(SOURCE, "models"):
        snapshot = re.search(r"snapshot_date=(\d{4}-\d{2}-\d{2})", path)
        ranking = re.search(r"ranking=(\w+)\.json$", path)
        if not (snapshot and ranking):
            continue
        day = date.fromisoformat(snapshot.group(1))
        rows += [model_row(m, day, ranking.group(1), observed_at) for m in models]
    return {"model_snapshots": merge(rows)}
