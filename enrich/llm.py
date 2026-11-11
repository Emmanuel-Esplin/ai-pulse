"""LLM enrichment, treated as one more source in the medallion.

Inputs come from silver; Claude's raw responses land in bronze (bronze/llm/<task>/...),
append-only like every other API's; processing/llm.py parses them into silver tables.
Bronze doubles as the cache: an item whose (task version, document, text) already has a
successful response is never sent again, so re-runs and rebuilds cost nothing.

`LLMClient` is the seam for providers: `AnthropicBatchClient` today, Bedrock later.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ingestion import landing

SOURCE = "llm"
DEFAULT_MODEL = "claude-opus-5-5"
# Batches cut the price in half and suit work nobody waits on. Chunks bound what one failed
# batch can lose; the API allows 100,000 requests per batch.
BATCH_CHUNK = 5000

# USD per million tokens at standard rates: (input, output, cache read). Batches are half.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
BATCH_DISCOUNT = 0.5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Task:
    """One kind of enrichment: a fixed prompt and the JSON schema its answers must follow.

    Bump `version` whenever the prompt or schema changes: cached answers to the old version
    are then ignored, so every item is asked again.
    """

    name: str
    version: str
    system: str
    schema: dict[str, Any]
    max_tokens: int = 8000
    effort: str = "low"
    # Rough output size per item, thinking included; only used for the cost estimate.
    expected_output_tokens: int = 400


@dataclass(frozen=True)
class Item:
    """One document to enrich. The key changes when either the id or the text does."""

    doc_id: str
    text: str

    def key(self, task: Task) -> str:
        digest = hashlib.sha256(f"{task.name}\0{task.version}\0{self.doc_id}\0{self.text}".encode())
        return digest.hexdigest()[:40]  # custom_id allows 64 characters


@dataclass
class Response:
    """One item's outcome, as written to bronze."""

    key: str
    doc_id: str
    status: str  # succeeded | refused | truncated | invalid_json | errored | expired | canceled
    output: dict[str, Any] | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    error: str | None = None


class LLMClient(Protocol):
    model: str

    def submit(self, task: Task, items: list[Item]) -> str:
        """Send items for processing; returns a batch id."""

    def collect(self, batch_id: str) -> list[Response] | None:
        """The batch's responses, or None while it is still running."""


@dataclass
class AnthropicBatchClient:
    """Claude through the Message Batches API, with structured outputs and prompt caching."""

    model: str = DEFAULT_MODEL
    sdk: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.sdk is None:
            import anthropic  # imported here so tests and dry runs need no credentials

            self.sdk = anthropic.Anthropic()

    def request_params(self, task: Task, item: Item) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": task.max_tokens,
            # The system prompt is identical for every item, so it is cached; the item last.
            "system": [
                {"type": "text", "text": task.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": item.text}],
            "output_config": {
                "effort": task.effort,
                "format": {"type": "json_schema", "schema": task.schema},
            },
        }

    def submit(self, task: Task, items: list[Item]) -> str:
        from anthropic.types.messages.batch_create_params import Request

        requests = [
            Request(custom_id=item.key(task), params=self.request_params(task, item))
            for item in items
        ]
        batch = self.sdk.messages.batches.create(requests=requests)
        return batch.id

    def collect(self, batch_id: str) -> list[Response] | None:
        batch = self.sdk.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None
        return [self._response(r) for r in self.sdk.messages.batches.results(batch_id)]

    @staticmethod
    def _response(result: Any) -> Response:
        outcome = result.result
        response = Response(key=result.custom_id, doc_id="", status=outcome.type)
        if outcome.type == "errored":
            response.error = f"{outcome.error.type}"
        if outcome.type != "succeeded":
            return response
        message = outcome.message
        usage = message.usage
        response.model = message.model
        response.input_tokens = usage.input_tokens
        response.output_tokens = usage.output_tokens
        response.cache_read_tokens = usage.cache_read_input_tokens or 0
        response.cache_write_tokens = usage.cache_creation_input_tokens or 0
        # Check why it stopped before reading the content: a refusal or a cut-off answer
        # is not valid JSON for the schema.
        if message.stop_reason == "refusal":
            response.status = "refused"
            return response
        if message.stop_reason == "max_tokens":
            response.status = "truncated"
            return response
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            response.output = json.loads(text)
        except json.JSONDecodeError:
            response.status = "invalid_json"
        return response


# --- bronze: pending batches and responses -------------------------------------------------


def _pending_path(batch_id: str) -> str:
    return landing.store().path("bronze", SOURCE, "_pending", f"{batch_id}.json")


def responses_path(task: Task, batch_id: str) -> str:
    return landing.bronze_path(SOURCE, task.name, version=task.version, batch_id=batch_id)


def iter_responses(task_name: str) -> Iterator[tuple[str, datetime, dict[str, Any]]]:
    """(task version, fetched_at, response) for every response of a task in bronze."""
    store = landing.store()
    for path in store.list_files(store.path("bronze", SOURCE, task_name), ".json"):
        version = re.search(r"version=([^/]+)/", path)
        envelope = landing.read_envelope(path)
        fetched = datetime.fromisoformat(envelope["fetched_at"])
        for response in envelope["payload"]:
            yield (version.group(1) if version else ""), fetched, response


def answered_keys(task: Task) -> set[str]:
    """Keys of items that already have a successful answer for this task version."""
    return {
        r["key"]
        for version, _, r in iter_responses(task.name)
        if version == task.version and r["status"] == "succeeded"
    }


def pending_keys(task: Task) -> set[str]:
    keys: set[str] = set()
    for pending in _pending():
        if pending["task"] == task.name and pending["version"] == task.version:
            keys |= set(pending["doc_ids"])
    return keys


def _pending() -> list[dict[str, Any]]:
    store = landing.store()
    folder = store.path("bronze", SOURCE, "_pending")
    return [json.loads(store.read_bytes(p)) for p in store.list_files(folder, ".json")]


def to_send(task: Task, items: list[Item]) -> list[Item]:
    """Items with no successful answer yet and not already in a running batch."""
    skip = answered_keys(task) | pending_keys(task)
    return [i for i in items if i.key(task) not in skip]


def submit(client: LLMClient, task: Task, items: list[Item]) -> list[str]:
    """Submit items in chunks, recording each batch as pending before anything else can fail."""
    batch_ids = []
    for start in range(0, len(items), BATCH_CHUNK):
        chunk = items[start : start + BATCH_CHUNK]
        batch_id = client.submit(task, chunk)
        record = {
            "batch_id": batch_id,
            "task": task.name,
            "version": task.version,
            "model": client.model,
            "submitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "doc_ids": {item.key(task): item.doc_id for item in chunk},
        }
        landing.store().write_bytes(_pending_path(batch_id), json.dumps(record).encode())
        log.info("submitted %s batch %s: %d items", task.name, batch_id, len(chunk))
        batch_ids.append(batch_id)
    return batch_ids


def collect(client: LLMClient, tasks: dict[str, Task]) -> int:
    """Write every finished pending batch to bronze; returns how many are still running."""
    running = 0
    for pending in _pending():
        task = tasks.get(pending["task"])
        if task is None or task.version != pending["version"]:
            log.warning("pending batch %s is for an unknown task version", pending["batch_id"])
            continue
        responses = client.collect(pending["batch_id"])
        if responses is None:
            running += 1
            continue
        for response in responses:
            response.doc_id = pending["doc_ids"].get(response.key, "")
        payload = [asdict(r) for r in responses]
        landing.write_bronze(
            responses_path(task, pending["batch_id"]), payload, "anthropic:batches"
        )
        landing.store().fs.delete_file(_pending_path(pending["batch_id"]))
        counts: dict[str, int] = {}
        for r in responses:
            counts[r.status] = counts.get(r.status, 0) + 1
        log.info("collected %s batch %s: %s", task.name, pending["batch_id"], counts)
    return running


def wait(client: LLMClient, tasks: dict[str, Task], poll_seconds: float = 60) -> None:
    """Collect until no batch is running. Most finish within an hour, all within 24."""
    while collect(client, tasks):
        time.sleep(poll_seconds)


# --- cost estimate -----------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """About 3.5 characters per token for English prose; good enough to size a bill."""
    return max(1, round(len(text) / 3.5))


def estimate_cost(task: Task, items: list[Item], model: str) -> dict[str, float]:
    """Expected batch cost in USD, assuming the system prompt is read from cache."""
    price_in, price_out, price_cache = PRICES.get(model, PRICES[DEFAULT_MODEL])
    input_tokens = sum(estimate_tokens(i.text) for i in items)
    cached_tokens = estimate_tokens(task.system) * len(items)
    output_tokens = task.expected_output_tokens * len(items)
    usd = (
        (input_tokens * price_in + cached_tokens * price_cache + output_tokens * price_out)
        * BATCH_DISCOUNT
        / 1e6
    )
    return {
        "items": len(items),
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "usd": round(usd, 2),
    }
