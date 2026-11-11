from datetime import UTC, date, datetime

import httpx
import pyarrow.parquet as pq
import pytest

from ingestion import arxiv, huggingface, landing
from processing import arxiv as arxiv_silver
from processing import huggingface as hf_silver
from processing import silver
from tests import fake_sources

DAY = date(2025, 11, 10)


def test_hf_follows_cursor_links_across_pages(data_dir):
    models = huggingface.fetch_ranking(fake_sources.hf_client(), "downloads", pages=5)
    assert [m["id"] for m in models] == [m["id"] for m in fake_sources.HF_MODELS["downloads"]]


def test_hf_snapshot_is_taken_once_a_day(data_dir):
    assert huggingface.ingest_models(fake_sources.hf_client(), DAY) == 3
    assert huggingface.ingest_models(fake_sources.hf_client(), DAY) == 0


def test_hf_tags_parse_into_license_base_model_and_papers():
    tags = fake_sources.HF_MODELS["downloads"][0]["tags"]
    assert hf_silver.parse_tags(tags) == {
        "license": "llama3.1",
        "base_model": "meta-llama/Llama-3.1-8B",
        "base_relation": "finetune",
        "arxiv_ids": ["2407.21783"],
    }
    assert hf_silver.parse_tags(["base_model:a/b"])["base_relation"] is None


def test_hf_silver_merges_rankings_per_model(data_dir):
    huggingface.ingest_models(fake_sources.hf_client(), DAY)
    rows = hf_silver.build()["model_snapshots"]
    by_id = {r["model_id"]: r for r in rows}
    assert len(rows) == 4
    assert by_id["Qwen/Qwen3-4B"]["rankings"] == ["downloads", "trendingScore"]
    assert by_id["Qwen/Qwen3-4B"]["trending_score"] == 40
    assert by_id["sentence-transformers/all-MiniLM-L6-v2"]["rankings"] == ["downloads", "likes"]
    gguf = by_id["someone/Qwen3-4B-GGUF"]
    assert (gguf["author"], gguf["base_model"], gguf["base_relation"]) == (
        "someone",
        "Qwen/Qwen3-4B",
        "quantized",
    )


def test_arxiv_query_filters_categories_and_submission_day():
    query = arxiv.day_query(DAY)
    assert "cat:cs.CL" in query and "cat:stat.ML" in query
    assert "submittedDate:[202511100000 TO 202511110000]" in query


def test_arxiv_pages_until_the_total_is_reached(monkeypatch):
    monkeypatch.setattr(arxiv, "PAGE_SIZE", 2)
    pages = arxiv.fetch_day(fake_sources.arxiv_client(), DAY, pause=0)
    assert [p.count("<entry>") for p in pages] == [2, 1]


def test_arxiv_retries_a_spurious_empty_page(monkeypatch):
    calls = []

    def flaky(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200, text="<feed><opensearch:totalResults>3</opensearch:totalResults></feed>"
            )
        return fake_sources.arxiv_handler(request)

    client = httpx.Client(transport=httpx.MockTransport(flaky))
    pages = arxiv.fetch_day(client, DAY, pause=0)
    assert len(calls) == 2 and pages[0].count("<entry>") == 3


def test_arxiv_gives_up_on_endless_empty_pages():
    empty = "<feed><opensearch:totalResults>3</opensearch:totalResults></feed>"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=empty)))
    with pytest.raises(RuntimeError, match="empty pages"):
        arxiv.fetch_day(client, DAY, pause=0)


def test_arxiv_silver_parses_atom(data_dir):
    arxiv.ingest_papers(fake_sources.arxiv_client(), DAY, backfill_days=0, pause=0)
    silver.main([])
    papers = pq.read_table(landing.silver_path("arxiv", "papers")).to_pylist()
    first = papers[0]
    assert first["arxiv_id"] == "2511.00001" and first["version"] == 1
    assert first["title"] == "Retrieval-Augmented Generation for Long Contexts"
    assert first["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first["primary_category"] == "cs.CL"
    assert first["categories"] == ["cs.CL", "cs.AI"]
    assert first["published_at"] == datetime(2025, 11, 10, 8, tzinfo=UTC)
    assert papers[1]["version"] == 2


def test_arxiv_parser_skips_error_entries():
    xml = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors</id>'
        "<title>Error</title></entry></feed>"
    )
    assert list(arxiv_silver.parse_feed(xml, datetime.now(UTC))) == []
