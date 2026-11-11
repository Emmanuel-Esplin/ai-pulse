"""A stand-in for Claude: answers from fixed rules, never calls the API."""

from __future__ import annotations

from dataclasses import dataclass, field

from enrich.llm import Item, Response, Task

# Text fragment -> HN mention it produces. "llama.cpp" shows the LLM telling it apart from Llama.
HN_RULES = {
    "vector DB": {
        "technology_id": "vector_database",
        "name": "vector DB",
        "sentiment": "positive",
        "is_main_subject": True,
    },
    "fine-tuning": {
        "technology_id": "fine_tuning",
        "name": "fine-tuning",
        "sentiment": "mixed",
        "is_main_subject": True,
    },
    "open-weights model": {
        "technology_id": "other",
        "name": "Open-weights models",
        "sentiment": "positive",
        "is_main_subject": True,
    },
}


@dataclass
class FakeLLMClient:
    model: str = "fake-model"
    refuse: set[str] = field(default_factory=set)  # doc_ids to refuse
    finish_after: int = 0  # how many collect() calls report "still running"
    batches: dict[str, tuple[Task, list[Item]]] = field(default_factory=dict)
    submitted: list[list[str]] = field(default_factory=list)

    def submit(self, task: Task, items: list[Item]) -> str:
        batch_id = f"batch_{len(self.batches) + 1}"
        self.batches[batch_id] = (task, items)
        self.submitted.append([i.doc_id for i in items])
        return batch_id

    def collect(self, batch_id: str) -> list[Response] | None:
        if self.finish_after:
            self.finish_after -= 1
            return None
        task, items = self.batches[batch_id]
        return [self._answer(task, item) for item in items]

    def _answer(self, task: Task, item: Item) -> Response:
        response = Response(
            key=item.key(task),
            doc_id="",
            status="succeeded",
            model=self.model,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=900,
        )
        if item.doc_id in self.refuse:
            response.status = "refused"
            return response
        if task.name == "hn_technologies":
            response.output = {"mentions": [m for k, m in HN_RULES.items() if k in item.text]}
        else:
            response.output = {
                "summary": f"  Plain summary of {item.doc_id}. ",
                "contribution_type": "method",
                "technologies": ["rag", "rag"] if "Retrieval" in item.text else [],
                "new_terms": ["LongRAG", " "],
                "is_llm_related": "Retrieval" in item.text,
            }
        return response
