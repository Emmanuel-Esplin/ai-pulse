from datetime import UTC, date, datetime

from enrich import llm, run, tasks
from enrich.bedrock import TOOL_NAME, BedrockConverseClient
from ingestion import hackernews
from processing import silver
from tests import fake_hn


class FakeRuntime:
    """Answers like Bedrock's Converse API; story 102 gets an answer that breaks the schema."""

    def __init__(self):
        self.requests = []

    def converse(self, **request):
        self.requests.append(request)
        text = request["messages"][0]["content"][0]["text"]
        mentions = (
            [
                {
                    "technology_id": "fine_tuning",
                    "name": "fine-tuning",
                    "sentiment": "mixed",
                    "is_main_subject": True,
                }
            ]
            if "fine-tuning" in text
            else []
        )
        answer = {"mentions": mentions}
        if "fine-tuning" in text:
            answer = {"mentions": [{**mentions[0], "sentiment": "angry"}]}
        return {
            "output": {"message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": answer}}]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 120, "outputTokens": 30},
        }


def _client(runtime):
    return BedrockConverseClient("qwen.qwen3-32b-v1:0", runtime=runtime, chunk_size=2, workers=2)


def test_request_forces_the_schema_tool():
    client = _client(FakeRuntime())
    task = tasks.hn_task()
    request = client.request(task, llm.Item("1", "Title: x"))
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert request["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"] == task.schema
    # Open-weights models get no cache checkpoint; Nova does.
    assert len(request["system"]) == 1
    nova = BedrockConverseClient("eu.amazon.nova-2-lite-v1:0", runtime=FakeRuntime())
    assert nova.request(task, llm.Item("1", "x"))["system"][1] == {
        "cachePoint": {"type": "default"}
    }


def test_bedrock_run_writes_each_chunk_and_rejects_schema_breaks(data_dir):
    hackernews.ingest_stories(fake_hn.client(), date(2025, 11, 10), backfill_days=0)
    hackernews.ingest_front_page(fake_hn.client(), datetime(2025, 11, 11, 6, tzinfo=UTC))
    silver.main([])
    runtime = FakeRuntime()
    run.main(["hn", "--min-points", "0", "--yes"], client=_client(runtime))
    assert len(runtime.requests) == 3
    responses = {r["doc_id"]: r for _, _, r in llm.iter_responses("hn_technologies")}
    assert responses["101"]["status"] == "succeeded"
    assert responses["102"]["status"] == "invalid_json"  # "angry" is not a sentiment
    assert responses["101"]["input_tokens"] == 120
    # Nothing left pending: chunks were written as they finished.
    assert llm.pending_keys(tasks.hn_task()) == set()
    # Only the rejected story is asked again.
    run.main(["hn", "--min-points", "0", "--yes"], client=_client(runtime))
    assert len(runtime.requests) == 4


def test_a_bedrock_run_leaves_claude_batches_alone(data_dir):
    from tests import fake_llm

    hackernews.ingest_stories(fake_hn.client(), date(2025, 11, 10), backfill_days=0)
    silver.main([])
    claude = fake_llm.FakeLLMClient(finish_after=5)
    run.main(["hn", "--min-points", "0", "--yes"], client=claude)
    assert llm.collect(_client(FakeRuntime()), tasks.tasks()) == 0
    assert len(llm.pending_keys(tasks.hn_task())) == 3


def test_eval_set_selects_labelled_stories(data_dir, monkeypatch):
    from enrich import evaluate

    hackernews.ingest_stories(fake_hn.client(), date(2025, 11, 10), backfill_days=0)
    silver.main([])
    monkeypatch.setattr(evaluate, "load_labels", lambda: {"102": set(), "999": set()})
    runtime = FakeRuntime()
    run.main(["hn", "--eval-set", "--yes"], client=_client(runtime))
    assert len(runtime.requests) == 1
