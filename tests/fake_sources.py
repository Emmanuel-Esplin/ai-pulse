"""Invented Hugging Face and arXiv APIs behind httpx.MockTransport, shaped like the real ones."""

from __future__ import annotations

import httpx

HF_MODELS = {
    "downloads": [
        {
            "id": "meta-llama/Llama-3.1-8B-Instruct",
            "downloads": 9_000_000,
            "likes": 5000,
            "pipeline_tag": "text-generation",
            "library_name": "transformers",
            "createdAt": "2024-07-18T08:56:00.000Z",
            "tags": [
                "transformers",
                "license:llama3.1",
                "arxiv:2407.21783",
                "base_model:meta-llama/Llama-3.1-8B",
                "base_model:finetune:meta-llama/Llama-3.1-8B",
            ],
        },
        {
            "id": "Qwen/Qwen3-4B",
            "downloads": 4_000_000,
            "likes": 900,
            "pipeline_tag": "text-generation",
            "library_name": "transformers",
            "createdAt": "2025-04-27T03:40:08.000Z",
            "tags": ["license:apache-2.0"],
        },
        {
            "id": "sentence-transformers/all-MiniLM-L6-v2",
            "downloads": 3_000_000,
            "likes": 6000,
            "pipeline_tag": "sentence-similarity",
            "library_name": "sentence-transformers",
            "createdAt": "2022-03-02T23:29:05.000Z",
            "tags": ["arxiv:1904.06472"],
        },
    ],
    "likes": [
        {
            "id": "sentence-transformers/all-MiniLM-L6-v2",
            "downloads": 3_000_000,
            "likes": 6000,
            "pipeline_tag": "sentence-similarity",
            "library_name": "sentence-transformers",
            "createdAt": "2022-03-02T23:29:05.000Z",
            "tags": ["arxiv:1904.06472"],
        },
    ],
    "trendingScore": [
        {
            "id": "someone/Qwen3-4B-GGUF",
            "downloads": 20_000,
            "likes": 300,
            "trendingScore": 250,
            "pipeline_tag": "text-generation",
            "library_name": "gguf",
            "createdAt": "2026-11-01T10:00:00.000Z",
            "tags": ["base_model:Qwen/Qwen3-4B", "base_model:quantized:Qwen/Qwen3-4B"],
        },
        {
            "id": "Qwen/Qwen3-4B",
            "downloads": 4_000_000,
            "likes": 900,
            "trendingScore": 40,
            "pipeline_tag": "text-generation",
            "library_name": "transformers",
            "createdAt": "2025-04-27T03:40:08.000Z",
            "tags": ["license:apache-2.0"],
        },
    ],
}


def hf_handler(request: httpx.Request) -> httpx.Response:
    """Serves each ranking in pages of 2, linking pages with a cursor like the Hub does."""
    sort = request.url.params.get("sort")
    cursor = int(request.url.params.get("cursor", 0))
    models = HF_MODELS[sort][cursor : cursor + 2]
    headers = {}
    if cursor + 2 < len(HF_MODELS[sort]):
        nxt = f"https://huggingface.co/api/models?sort={sort}&cursor={cursor + 2}"
        headers["Link"] = f'<{nxt}>; rel="next"'
    return httpx.Response(200, json=models, headers=headers)


def _entry(arxiv_id: str, version: int, title: str, abstract: str, cats: list[str]) -> str:
    categories = "".join(
        f'<category term="{c}" scheme="http://arxiv.org/schemas/atom"/>' for c in cats
    )
    return f"""<entry>
    <id>http://arxiv.org/abs/{arxiv_id}v{version}</id>
    <title>{title}</title>
    <updated>2025-11-10T09:00:00Z</updated>
    <summary>{abstract}</summary>
    {categories}
    <published>2025-11-10T08:00:00Z</published>
    <arxiv:primary_category term="{cats[0]}"/>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
  </entry>"""


ARXIV_ENTRIES = [
    _entry(
        "2511.00001",
        1,
        "Retrieval-Augmented Generation\n  for Long Contexts",
        "We extend RAG with vLLM serving and evaluate Llama 3.",
        ["cs.CL", "cs.AI"],
    ),
    _entry(
        "2511.00002",
        2,
        "Sparse Mixture of Experts at Scale",
        "A mixture-of-experts model trained with JAX.",
        ["cs.LG"],
    ),
    _entry(
        "2511.00003",
        1,
        "Phi in Fluid Flux Equations",
        "The flux phi of a vector field.",
        ["stat.ML"],
    ),
]


def arxiv_handler(request: httpx.Request) -> httpx.Response:
    """Serves the three papers in pages of `max_results`."""
    start = int(request.url.params["start"])
    size = int(request.url.params["max_results"])
    page = ARXIV_ENTRIES[start : start + size]
    xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>{len(ARXIV_ENTRIES)}</opensearch:totalResults>
  {"".join(page)}
</feed>"""
    return httpx.Response(200, text=xml)


def hf_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(hf_handler))


def arxiv_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(arxiv_handler))
