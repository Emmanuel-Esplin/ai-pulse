"""Ingest sources into bronze: `python -m ingestion.run [hn] [hf] [arxiv] [--backfill-days N]`.

Each source writes only to its own bronze folder, so one failing API never blocks the others'
data already written. With no sources named, all of them run.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from ingestion import arxiv, hackernews, http, huggingface

SOURCES = ("hn", "hf", "arxiv")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", choices=SOURCES, help="default: all")
    # Days already in bronze are skipped, so a long window only costs time on the first run.
    # Hugging Face has no history, so it always snapshots today only.
    parser.add_argument("--backfill-days", type=int, default=90)
    args = parser.parse_args(argv)
    args.sources = args.sources or list(SOURCES)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # One line per request drowns the summary; failures still surface as exceptions.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    now = datetime.now(UTC)
    with http.make_client(timeout=60) as client:
        if "hn" in args.sources:
            hackernews.ingest_stories(client, now.date(), args.backfill_days)
            hackernews.ingest_front_page(client, now)
        if "hf" in args.sources:
            huggingface.ingest_models(client, now.date())
        if "arxiv" in args.sources:
            arxiv.ingest_papers(client, now.date(), args.backfill_days)


if __name__ == "__main__":
    main()
