import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ingestion import hackernews, landing
from processing import silver
from tests import fake_hn

ROOT = Path(__file__).resolve().parents[1]


def test_clean_text_turns_hn_html_into_plain_text():
    assert silver.clean_text("<p>Curious &amp; honest answers&#x2F;please") == (
        "Curious & honest answers/please"
    )
    assert silver.clean_text("a<p>b <i>c</i>") == "a\n\nb c"
    assert silver.clean_text("") is None


def test_domain_drops_www():
    assert silver.domain_of("https://www.example.com/a?b=1") == "example.com"
    assert silver.domain_of(None) is None


def test_latest_observation_wins():
    early = datetime(2025, 11, 10, tzinfo=UTC)
    late = datetime(2025, 11, 11, tzinfo=UTC)
    rows = [
        {"story_id": 1, "points": 5, "observed_at": late},
        {"story_id": 1, "points": 2, "observed_at": early},
    ]
    assert silver.latest(rows, "story_id") == [rows[0]]


def _fill_bronze():
    client = fake_hn.client()
    hackernews.ingest_stories(client, date(2025, 11, 10), backfill_days=0)
    hackernews.ingest_front_page(client, datetime(2025, 11, 11, 6, tzinfo=UTC))


def test_bronze_to_silver(data_dir):
    _fill_bronze()
    silver.main([])
    stories = pq.read_table(landing.silver_path("hackernews", "stories")).to_pylist()
    by_id = {s["story_id"]: s for s in stories}
    assert sorted(by_id) == [101, 102, 103]  # the job posting is not a story
    # The front-page snapshot is newer than the day file, so its score wins.
    assert by_id[103]["points"] == 410 and by_id[103]["observed_via"] == "firebase"
    assert by_id[101]["domain"] == "example.com"
    comments = pq.read_table(landing.silver_path("hackernews", "comments")).to_pylist()
    assert [(c["comment_id"], c["position"]) for c in comments] == [(201, 1), (203, 2)]


def test_gold_builds_and_passes_dbt_tests(data_dir):
    _fill_bronze()
    silver.main([])
    (data_dir / "gold").mkdir()
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
    with duckdb.connect(str(data_dir / "gold" / "warehouse.duckdb"), read_only=True) as con:
        row = con.execute(
            "select stories, show_hn, ask_hn, stories_100_plus from main.mart_hn_daily"
        ).fetchall()
    assert row == [(3, 1, 1, 2)]
