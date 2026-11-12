"""Claude's bronze responses to silver: HN technology mentions, arXiv digests, and usage.

A document can have several answers (a newer prompt version, a story whose comments
changed). The latest successful answer wins, so a prompt change rolls out as documents
are re-asked, without mixing two answers for one document.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pyarrow as pa

from enrich import llm as enrich_llm
from enrich.llm import iter_responses
from processing.silver import latest

Row = dict[str, Any]

SOURCE = enrich_llm.SOURCE

INT, STRING, BOOL, TS = pa.int64(), pa.string(), pa.bool_(), pa.timestamp("s", tz="UTC")
ANSWER = [("model", STRING), ("task_version", STRING), ("observed_at", TS)]

SCHEMAS: dict[str, pa.Schema] = {
    "responses": pa.schema(
        [
            ("task", STRING),
            ("task_version", STRING),
            ("doc_id", STRING),
            ("key", STRING),
            ("status", STRING),
            ("model", STRING),
            ("input_tokens", INT),
            ("output_tokens", INT),
            ("cache_read_tokens", INT),
            ("cache_write_tokens", INT),
            ("error", STRING),
            ("observed_at", TS),
        ]
    ),
    "hn_mentions": pa.schema(
        [
            ("story_id", INT),
            ("technology_id", STRING),
            ("name", STRING),
            ("sentiment", STRING),
            ("is_main_subject", BOOL),
            *ANSWER,
        ]
    ),
    "arxiv_digest": pa.schema(
        [
            ("arxiv_id", STRING),
            ("summary", STRING),
            ("contribution_type", STRING),
            ("technologies", pa.list_(STRING)),
            ("new_terms", pa.list_(STRING)),
            ("is_llm_related", BOOL),
            *ANSWER,
        ]
    ),
}


def _responses(task: str) -> list[Row]:
    return [
        {**r, "task": task, "task_version": version, "observed_at": fetched}
        for version, fetched, r in iter_responses(task)
    ]


def _answers(rows: list[Row]) -> list[Row]:
    """The latest successful answer per document."""
    ok = [r for r in rows if r["status"] == "succeeded" and r["output"] is not None]
    return latest(ok, "doc_id")


def _meta(r: Row) -> Row:
    return {"model": r["model"], "task_version": r["task_version"], "observed_at": r["observed_at"]}


def hn_mentions(answers: list[Row]) -> list[Row]:
    rows = []
    for r in answers:
        # One row per (story, technology); "other" keeps one row per distinct name.
        seen: set[tuple[str, str]] = set()
        for m in r["output"]["mentions"]:
            name_key = m["name"].strip().lower() if m["technology_id"] == "other" else ""
            if (m["technology_id"], name_key) in seen:
                continue
            seen.add((m["technology_id"], name_key))
            rows.append(
                {
                    "story_id": int(r["doc_id"]),
                    "technology_id": m["technology_id"],
                    "name": m["name"].strip(),
                    "sentiment": m["sentiment"],
                    "is_main_subject": m["is_main_subject"],
                    **_meta(r),
                }
            )
    return rows


def arxiv_digest(answers: list[Row]) -> list[Row]:
    return [
        {
            "arxiv_id": r["doc_id"],
            "summary": r["output"]["summary"].strip(),
            "contribution_type": r["output"]["contribution_type"],
            "technologies": sorted(set(r["output"]["technologies"])),
            "new_terms": [t.strip() for t in r["output"]["new_terms"] if t.strip()],
            "is_llm_related": r["output"]["is_llm_related"],
            **_meta(r),
        }
        for r in answers
    ]


def build() -> dict[str, list[Row]]:
    hn = _responses("hn_technologies")
    arxiv = _responses("arxiv_digest")
    usage = [{k: r.get(k) for k in SCHEMAS["responses"].names} for r in hn + arxiv]
    usage.sort(key=lambda r: (r["task"], r["observed_at"] or datetime.min, r["key"]))
    return {
        "responses": usage,
        "hn_mentions": hn_mentions(_answers(hn)),
        "arxiv_digest": arxiv_digest(_answers(arxiv)),
    }
