"""Bronze to silver for every source: typed, deduplicated Parquet, one file per table.

Silver is rebuilt from all of bronze each run, so a parser fix reaches every past day.
Each source module turns its bronze into rows (`build()`) under fixed schemas (`SCHEMAS`);
this module does the reading, deduplication and writing they share.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ingestion import landing

Row = dict[str, Any]

log = logging.getLogger(__name__)


def bronze_files(source: str, endpoint: str) -> Iterator[tuple[str, datetime, Any]]:
    """(path, fetched_at, payload) for every bronze file of one endpoint, in path order."""
    store = landing.store()
    for path in store.list_files(store.path("bronze", source, endpoint), ".json"):
        envelope = landing.read_envelope(path)
        yield path, datetime.fromisoformat(envelope["fetched_at"]), envelope["payload"]


def latest(rows: Iterable[Row], key: str | tuple[str, ...]) -> list[Row]:
    """One row per key: the latest `observed_at`, ties going to the row seen last."""
    keys = (key,) if isinstance(key, str) else key
    best: dict[tuple, Row] = {}
    for row in rows:
        k = tuple(row[c] for c in keys)
        current = best.get(k)
        if current is None or row["observed_at"] >= current["observed_at"]:
            best[k] = row
    return [best[k] for k in sorted(best)]


def write_table(source: str, table: str, rows: list[Row], schema: pa.Schema) -> None:
    """Replace one silver table; written to a temp file first so readers never see half."""
    store = landing.store()
    path = landing.silver_path(source, table)
    store.make_parent(path)
    data = pa.Table.from_pylist(rows, schema=schema)
    tmp = path + ".tmp"
    pq.write_table(data, tmp, filesystem=store.fs)
    store.fs.move(tmp, path)
    log.info("silver %s/%s: %d rows", source, table, data.num_rows)


def main(argv: list[str] | None = None) -> None:
    # Imported here: the source modules import this one for the shared helpers.
    from processing import arxiv, hackernews, huggingface

    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for module in (hackernews, huggingface, arxiv):
        for table, rows in module.build().items():
            write_table(module.SOURCE, table, rows, module.SCHEMAS[table])


if __name__ == "__main__":
    main()
