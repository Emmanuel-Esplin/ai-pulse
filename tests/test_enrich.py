from datetime import UTC, date, datetime

import pyarrow.parquet as pq

from enrich import llm, run, tasks
from ingestion import arxiv, hackernews, landing
from processing import silver
from tests import fake_hn, fake_llm, fake_sources


def _silver_with_data():
    hackernews.ingest_stories(fake_hn.client(), date(2025, 11, 10), backfill_days=0)
    hackernews.ingest_front_page(fake_hn.client(), datetime(2025, 11, 11, 6, tzinfo=UTC))
    arxiv.ingest_papers(fake_sources.arxiv_client(), date(2025, 11, 10), backfill_days=0, pause=0)
    silver.main([])


def _silver_table(table):
    return pq.read_table(landing.silver_path("llm", table)).to_pylist()


def test_tasks_use_the_seed_taxonomy():
    hn = tasks.hn_task()
    ids = hn.schema["properties"]["mentions"]["items"]["properties"]["technology_id"]["enum"]
    assert "llama_cpp" in ids and ids[-1] == "other"
    assert "- rag: Retrieval-augmented generation" in hn.system
    arxiv_ids = tasks.arxiv_task().schema["properties"]["technologies"]["items"]["enum"]
    assert "other" not in arxiv_ids


def test_hn_items_respect_points_and_include_comments(data_dir):
    _silver_with_data()
    items = {i.doc_id: i.text for i in tasks.hn_items(min_points=50)}
    assert sorted(items) == ["101", "103"]  # 102 has 45 points
    assert "Top comments:\n- Benchmarks look great" in items["103"]


def test_item_key_changes_with_text_and_task_version():
    task = tasks.hn_task()
    item = llm.Item("1", "Title: a")
    assert item.key(task, "m") != llm.Item("1", "Title: b").key(task, "m")
    assert item.key(task, "m") != item.key(task, "other-model")
    newer = llm.Task(task.name, task.version + "-next", task.system, task.schema)
    assert item.key(task, "m") != item.key(newer, "m")
    assert len(item.key(task, "m")) <= 64


def test_dry_run_sends_nothing(data_dir, capsys):
    _silver_with_data()
    client = fake_llm.FakeLLMClient()
    run.main(["hn", "--min-points", "0"], client=client)
    out = capsys.readouterr().out
    assert "3 items, 3 not yet answered, sending 3" in out and "Dry run" in out
    assert client.submitted == []


def test_submit_collect_and_cache(data_dir):
    _silver_with_data()
    client = fake_llm.FakeLLMClient(finish_after=1, refuse={"102"})
    run.main(["hn", "--min-points", "0", "--yes"], client=client)
    # Submitted but not finished: the batch is pending and its items are not sent again.
    assert llm.collect(client, tasks.tasks()) == 1
    run.main(["hn", "--min-points", "0", "--yes"], client=client)
    assert len(client.submitted) == 1
    # Finished: responses land in bronze and the pending record is gone.
    assert llm.collect(client, tasks.tasks()) == 0
    statuses = sorted(
        (r["doc_id"], r["status"]) for _, _, r in llm.iter_responses("hn_technologies")
    )
    assert statuses == [("101", "succeeded"), ("102", "refused"), ("103", "succeeded")]
    # Only the refused story is asked again.
    run.main(["hn", "--min-points", "0", "--yes"], client=client)
    assert client.submitted[-1] == ["102"]


def test_responses_become_silver(data_dir):
    _silver_with_data()
    client = fake_llm.FakeLLMClient()
    run.main(["hn", "--min-points", "0", "--yes", "--wait"], client=client)
    run.main(["arxiv", "--yes", "--wait"], client=client)
    silver.main([])
    mentions = sorted(
        (m["story_id"], m["technology_id"], m["sentiment"]) for m in _silver_table("hn_mentions")
    )
    assert mentions == [
        (101, "vector_database", "positive"),
        (102, "fine_tuning", "mixed"),
        (103, "other", "positive"),
    ]
    digest = {d["arxiv_id"]: d for d in _silver_table("arxiv_digest")}
    assert digest["2511.00001"]["summary"] == "Plain summary of 2511.00001."
    assert digest["2511.00001"]["technologies"] == ["rag"]
    assert digest["2511.00001"]["new_terms"] == ["LongRAG"]
    usage = _silver_table("responses")
    assert len(usage) == 6 and {u["cache_read_tokens"] for u in usage} == {900}


def test_cost_estimate_uses_batch_prices():
    task = llm.Task("t", "v1", "x" * 3500, {}, expected_output_tokens=1000)
    items = [llm.Item(str(n), "y" * 3500) for n in range(1000)]
    cost = llm.estimate_cost(task, items, "claude-opus-5-5")
    # 1M input at $4, 1M cached at $0.20, 1M output at $20; batch halves it.
    assert cost["usd"] == 12.10


def test_gold_compares_rules_with_llm(data_dir):
    from tests import dbt_runner

    _silver_with_data()
    client = fake_llm.FakeLLMClient()
    run.main(["hn", "--min-points", "0", "--yes", "--wait"], client=client)
    run.main(["arxiv", "--yes", "--wait"], client=client)
    silver.main([])
    dbt_runner.build(data_dir)
    comparison = dbt_runner.query(
        data_dir,
        "select technology_id, found_by_both, rules_only, llm_only "
        "from main.mart_extraction_comparison "
        "order by technology_id",
    )
    assert comparison == [("fine_tuning", 1, 0, 0), ("vector_database", 1, 0, 0)]
    terms = dbt_runner.query(
        data_dir,
        "select term, hn_mentions, arxiv_mentions from main.mart_emerging_terms order by term",
    )
    assert terms == [("longrag", 0, 3), ("open-weights models", 1, 0)]
    usage = dbt_runner.query(
        data_dir, "select task, responses, cost_usd from main.mart_llm_usage order by task"
    )
    # The fake model has no price, so its cost is unknown rather than zero.
    assert usage == [("arxiv_digest", 3, None), ("hn_technologies", 3, None)]


def test_score_counts_pairs():
    from enrich import evaluate

    expected = {"1": {"a", "b"}, "2": set()}
    predicted = {"1": {"a", "c"}, "2": {"d"}}
    s = evaluate.score(predicted, expected)
    assert (s["tp"], s["fp"], s["fn"]) == (1, 2, 1)
    assert round(s["precision"], 2) == 0.33 and s["recall"] == 0.5


def test_labels_use_known_technologies():
    from enrich import evaluate

    labels = evaluate.load_labels()
    known = {t["technology_id"] for t in tasks.taxonomy()}
    assert len(labels) == 50
    assert set().union(*labels.values()) <= known
