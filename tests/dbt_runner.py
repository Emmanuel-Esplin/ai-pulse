"""Run the dbt project against a test data directory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def build(data_dir: Path) -> None:
    (data_dir / "gold").mkdir(exist_ok=True)
    dbt = Path(sys.executable).with_name("dbt")
    result = subprocess.run(
        [str(dbt), "build", "--profiles-dir", "."],
        cwd=ROOT / "transform",
        env={
            "AIPULSE_DATA_DIR": str(data_dir),
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:]


def query(data_dir: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(data_dir / "gold" / "warehouse.duckdb"), read_only=True) as con:
        return con.execute(sql).fetchall()
