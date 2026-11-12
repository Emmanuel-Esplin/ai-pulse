"""Amazon Bedrock as an LLMClient, through the Converse API, which speaks to every model alike.

Bedrock has no Message Batches API, so `submit` answers its items on the spot, several in
parallel within the account's per-minute limits, and `collect` hands back the results.
`synchronous = True` tells enrich.llm to collect each chunk at once, so a crash loses at
most one chunk of paid work.

Structured output is enforced the portable way: the model must call a single tool whose
input schema is the task's JSON schema, and the answer is validated against that schema
before it counts. Anything else is recorded as invalid_json and asked again next run.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from enrich.llm import Item, Response, Task

TOOL_NAME = "record_answer"
log = logging.getLogger(__name__)


@dataclass
class BedrockConverseClient:
    model: str
    region: str = "eu-west-1"
    workers: int = 8
    chunk_size: int = 200
    synchronous: bool = True
    provider: str = "bedrock"
    runtime: Any = field(default=None, repr=False)
    _results: dict[str, list[Response]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.runtime is None:
            import boto3  # only needed for live runs
            from botocore.config import Config

            # Adaptive retries slow down on throttling instead of failing the item.
            config = Config(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)
            self.runtime = boto3.client("bedrock-runtime", region_name=self.region, config=config)

    def request(self, task: Task, item: Item) -> dict[str, Any]:
        system: list[dict[str, Any]] = [{"text": task.system}]
        # Amazon's own models accept a prompt-cache checkpoint; open-weights models may not.
        if "amazon.nova" in self.model:
            system.append({"cachePoint": {"type": "default"}})
        return {
            "modelId": self.model,
            "system": system,
            "messages": [{"role": "user", "content": [{"text": item.text}]}],
            "inferenceConfig": {"maxTokens": 2000},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": TOOL_NAME,
                            "description": "Record the answer for this item.",
                            "inputSchema": {"json": task.schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            },
        }

    def answer(self, task: Task, item: Item) -> Response:
        response = Response(key=item.key(task, self.model), doc_id=item.doc_id, status="succeeded")
        response.model = self.model
        try:
            result = self.runtime.converse(**self.request(task, item))
        except Exception as exc:  # throttling is retried by botocore; what is left is an error
            response.status, response.error = "errored", type(exc).__name__
            return response
        usage = result.get("usage", {})
        response.input_tokens = usage.get("inputTokens", 0)
        response.output_tokens = usage.get("outputTokens", 0)
        response.cache_read_tokens = usage.get("cacheReadInputTokens", 0)
        response.cache_write_tokens = usage.get("cacheWriteInputTokens", 0)
        if result.get("stopReason") == "max_tokens":
            response.status = "truncated"
            return response
        blocks = result["output"]["message"]["content"]
        answer = _answer_from(blocks)
        try:
            if answer is None:
                raise jsonschema.ValidationError("no tool call or JSON answer")
            jsonschema.validate(answer, task.schema)
            response.output = answer
        except jsonschema.ValidationError as exc:
            response.status, response.error = "invalid_json", exc.message[:200]
        return response

    def submit(self, task: Task, items: list[Item]) -> str:
        batch_id = f"bedrock-{uuid.uuid4().hex[:12]}"
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            self._results[batch_id] = list(pool.map(lambda i: self.answer(task, i), items))
        return batch_id

    def collect(self, batch_id: str) -> list[Response] | None:
        return self._results.pop(batch_id, None)


def _answer_from(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The tool call's input or, from models that ignore a forced tool choice and write the
    answer as text, the last JSON object in that text. The schema check comes after either way."""
    call = next((b["toolUse"] for b in blocks if "toolUse" in b), None)
    if call is not None:
        return call["input"]
    text = "".join(b.get("text", "") for b in blocks)
    for match in reversed(list(re.finditer(r"\{.*\}", text, re.DOTALL))):
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None
