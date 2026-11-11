"""Ingest every source into bronze: `python -m ingestion.run [hn] [--backfill-days N]`.

Hugging Face and arXiv join in phase 2; each source writes only to its own bronze folder.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from ingestion import hackernews

SOURCES = ("hn",)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", choices=SOURCES, help="default: all")
    # Days already in bronze are skipped, so a long window only costs time on the first run.
    parser.add_argument("--backfill-days", type=int, default=90)
    args = parser.parse_args(argv)
    args.sources = args.sources or list(SOURCES)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    # One line per request drowns the summary; failures still surface as exceptions.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    now = datetime.now(UTC)
    if "hn" in args.sources:
        with hackernews.make_client() as client:
            hackernews.ingest_stories(client, now.date(), args.backfill_days)
            hackernews.ingest_front_page(client, now)


if __name__ == "__main__":
    main()
