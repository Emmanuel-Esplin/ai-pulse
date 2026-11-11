"""Storage for the medallion layers: a local folder or an s3:// prefix, with one code path.

Bronze is raw API responses, append-only; silver is typed, deduplicated Parquet; gold is
the dbt warehouse. AIPULSE_DATA_DIR picks the root: `data` locally, `s3://<bucket>` in Lambda.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import pyarrow.fs as pafs


class Storage:
    """A root folder on the local disk or in S3. Paths are '/'-joined strings under it."""

    def __init__(self, root: str) -> None:
        if root.startswith("s3://"):
            self.fs, self.base = pafs.FileSystem.from_uri(root)
            self.local = False
        else:
            self.fs, self.base = pafs.LocalFileSystem(), str(Path(root).resolve())
            self.local = True
        self.base = self.base.rstrip("/")

    def path(self, *parts: str) -> str:
        return "/".join([self.base, *parts])

    def exists(self, path: str) -> bool:
        return self.fs.get_file_info(path).type == pafs.FileType.File

    def read_bytes(self, path: str) -> bytes:
        with self.fs.open_input_stream(path) as stream:
            return stream.read()

    def make_parent(self, path: str) -> None:
        """Create the folder for `path`. S3 has no folders, and pyarrow's version of this
        checks the bucket exists, which needs more permissions than the pipeline has."""
        if self.local:
            self.fs.create_dir(path.rsplit("/", 1)[0], recursive=True)

    def write_bytes(self, path: str, data: bytes) -> None:
        """S3 puts are atomic; locally write a temp file and rename, so readers never see half."""
        if not self.local:
            with self.fs.open_output_stream(path) as stream:
                stream.write(data)
            return
        self.make_parent(path)
        tmp = path + ".tmp"
        with self.fs.open_output_stream(tmp) as stream:
            stream.write(data)
        self.fs.move(tmp, path)

    def list_files(self, directory: str, suffix: str) -> list[str]:
        """Every file under `directory` ending in `suffix`, sorted. Empty if it doesn't exist."""
        selector = pafs.FileSelector(directory, recursive=True, allow_not_found=True)
        infos = self.fs.get_file_info(selector)
        return sorted(
            i.path for i in infos if i.type == pafs.FileType.File and i.path.endswith(suffix)
        )

    def delete_dir(self, directory: str) -> None:
        """Delete everything under `directory`. On S3 this deletes object by object, which
        needs only List and Delete on the prefix, not the bucket-level checks pyarrow makes."""
        if self.local:
            if self.fs.get_file_info(directory).type != pafs.FileType.NotFound:
                self.fs.delete_dir(directory)
            return
        for path in self.list_files(directory, ""):
            self.fs.delete_file(path)


@cache
def store() -> Storage:
    """The storage root for this process, from AIPULSE_DATA_DIR."""
    return Storage(os.environ.get("AIPULSE_DATA_DIR", "data"))


def bronze_path(source: str, endpoint: str, **partitions: object) -> str:
    """Hive-style path, e.g. bronze/hackernews/stories/created_date=2026-11-10.json."""
    parts = [f"{key}={value}" for key, value in partitions.items()]
    parts[-1] += ".json"
    return store().path("bronze", source, endpoint, *parts)


def write_bronze(path: str, payload: Any, source_url: str) -> None:
    """Write one raw source document with when and where it came from."""
    envelope = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_url": source_url,
        "payload": payload,
    }
    store().write_bytes(path, json.dumps(envelope, ensure_ascii=False).encode())


def read_envelope(path: str) -> dict[str, Any]:
    """A bronze file whole: fetched_at, source_url and payload."""
    return json.loads(store().read_bytes(path))


def read_bronze(path: str) -> Any:
    """Return the payload of a bronze file."""
    return read_envelope(path)["payload"]


def silver_path(source: str, table: str) -> str:
    """One Parquet file per silver table, e.g. silver/hackernews/stories.parquet."""
    return store().path("silver", source, f"{table}.parquet")
