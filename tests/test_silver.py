import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ingestion import arxiv, hackernews, huggingface, landing
from processing import hackernews as hn_silver
from processing import silver
from tests import fake_hn, fake_sources

ROOT = Path(__file__).resolve().parents[1]


def test_clean_text_turns_hn_html_into_plain_text():
    assert hn_silver.clean_text("<p>Curious &amp; honest answers&#x2F;please") == (
        "Curious & honest answers/please"
    )
    assert hn_silver.clean_text("a<p>b <i>c</i>") == "a\n\nb c"
    assert hn_silver.clean_text("") is None


def test_domain_drops_www():
    assert hn_silver.domain_of("https://www.example.com/a?b=1") == "example.com"
    assert hn_silver.domain_of(None) is None


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
    huggingface.ingest_models(fake_sources.hf_client(), date(2025, 11, 10))
    arxiv.ingest_papers(fake_sources.arxiv_client(), date(2025, 11, 10), backfill_days=0, pause=0)


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

        def mentions(model):
            rows = con.execute(f"select document_id, technology_id from main.{model}").fetchall()
            return sorted((str(d), t) for d, t in rows)

        daily = con.execute(
            "select stories, show_hn, ask_hn, stories_100_plus from main.mart_hn_daily"
        ).fetchall()
        hn = mentions("int_hn_story_technologies")
        papers = mentions("int_arxiv_paper_technologies")
        hf = mentions("int_hf_model_technologies")
        linked = con.execute("select count(*) from main.stg_hf_model_papers").fetchone()[0]
    assert daily == [(3, 1, 1, 2)]
    assert hn == [("101", "vector_database"), ("102", "fine_tuning")]
    # The third paper ("Phi in Fluid Flux Equations") is physics, and must match nothing.
    assert papers == [
        ("2511.00001", "llama"),
        ("2511.00001", "rag"),
        ("2511.00001", "vllm"),
        ("2511.00002", "jax"),
        ("2511.00002", "moe"),
    ]
    assert hf == [
        ("Qwen/Qwen3-4B", "qwen"),
        ("meta-llama/Llama-3.1-8B-Instruct", "llama"),
        ("someone/Qwen3-4B-GGUF", "gguf"),
        ("someone/Qwen3-4B-GGUF", "qwen"),
    ]
    assert linked == 2
