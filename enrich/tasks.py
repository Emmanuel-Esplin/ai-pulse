"""The enrichment tasks and how their items are built from silver.

Both tasks answer in the seed taxonomy's technology_ids, so LLM and rule-based mentions land
on the same key. Names outside the taxonomy come back as "other" with the name as written:
that is how emerging technologies get noticed before anyone adds them to the seed.
"""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path

import pyarrow.parquet as pq

from enrich.llm import Item, Task
from ingestion import landing

SEEDS = Path(__file__).resolve().parents[1] / "transform" / "seeds"
SENTIMENTS = ["positive", "neutral", "negative", "mixed"]
CONTRIBUTIONS = [
    "method",
    "benchmark",
    "dataset",
    "survey",
    "analysis",
    "system",
    "application",
    "theory",
]
# Limits keep prompts short and cost predictable; long posts lose only their tail.
HN_TEXT_CHARS = 1500
HN_COMMENT_CHARS = 400


@cache
def taxonomy() -> list[dict[str, str]]:
    """Seed technologies with their aliases, for the prompt and the schema enum."""
    with open(SEEDS / "technology_aliases.csv") as f:
        aliases: dict[str, list[str]] = {}
        for row in csv.DictReader(f):
            aliases.setdefault(row["technology_id"], []).append(row["alias"])
    with open(SEEDS / "technologies.csv") as f:
        return [
            {**row, "aliases": ", ".join(aliases.get(row["technology_id"], []))}
            for row in csv.DictReader(f)
        ]


def _taxonomy_block() -> str:
    lines = [
        f"- {t['technology_id']}: {t['name']} ({t['category']}; e.g. {t['aliases']})"
        for t in taxonomy()
    ]
    return "\n".join(lines)


def _technology_ids() -> list[str]:
    return [t["technology_id"] for t in taxonomy()] + ["other"]


def hn_task() -> Task:
    system = f"""You label Hacker News posts for a trend tracker of AI technologies.

For the post you are given, list every AI technology it is about or clearly refers to:
models and model families, labs, frameworks and tools, AI products, techniques, AI hardware.
Use the technology_id from the list below when one fits, including when the post uses a
version or variant (GPT-5 is gpt, Qwen3 is qwen, llama.cpp is llama_cpp and not llama).
For an AI technology not in the list, use "other" and give its name as written.
Ignore technologies that are not about AI (programming languages, databases, cloud
providers) unless they are used for AI in this post.

Only name what the post itself refers to; never infer:
- A lab does not imply its models: news about OpenAI is openai, not gpt or chatgpt, unless
  the post names the model or product.
- A product does not imply its model family: Claude Code is claude_code, not claude;
  ChatGPT is chatgpt, not gpt.
- A model name does imply its family: Opus or Sonnet is claude, o3 or GPT-5 is gpt.
- Vague descriptions ("a search database", "AI tools") are not a technology.

For each, give the sentiment the post expresses towards that technology: positive,
negative, neutral (news or a plain mention) or mixed. Judge the author and, when comments
are included, the discussion; not the technology's general reputation.
Mark is_main_subject when the post is primarily about that technology.
Return an empty list when the post is not about AI.

Technologies:
{_taxonomy_block()}"""
    mention = {
        "type": "object",
        "properties": {
            "technology_id": {"type": "string", "enum": _technology_ids()},
            "name": {"type": "string"},
            "sentiment": {"type": "string", "enum": SENTIMENTS},
            "is_main_subject": {"type": "boolean"},
        },
        "required": ["technology_id", "name", "sentiment", "is_main_subject"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {"mentions": {"type": "array", "items": mention}},
        "required": ["mentions"],
        "additionalProperties": False,
    }
    # v2: explicit rules against inferring models from labs and families from products.
    return Task("hn_technologies", "v2", system, schema, expected_output_tokens=300)


def arxiv_task() -> Task:
    system = f"""You write a research digest of new AI papers for engineers who are not
researchers.

For the paper you are given (title and abstract):
- summary: two or three plain-English sentences: what problem, what they did, what they found.
  No jargon without a short explanation, no hype, no "this paper".
- contribution_type: the paper's main contribution.
- technologies: the technology_ids from the list below that the paper is substantially about
  (not ones only mentioned in passing). Use "other" entries in new_terms instead.
- new_terms: up to three specific named methods, models or techniques the paper introduces or
  centres on that are not in the list (names as written; empty if none).
- is_llm_related: true if large language models are central to the paper.

Technologies:
{_taxonomy_block()}"""
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "contribution_type": {"type": "string", "enum": CONTRIBUTIONS},
            "technologies": {
                "type": "array",
                "items": {"type": "string", "enum": _technology_ids()[:-1]},
            },
            "new_terms": {"type": "array", "items": {"type": "string"}},
            "is_llm_related": {"type": "boolean"},
        },
        "required": [
            "summary",
            "contribution_type",
            "technologies",
            "new_terms",
            "is_llm_related",
        ],
        "additionalProperties": False,
    }
    return Task("arxiv_digest", "v1", system, schema, expected_output_tokens=450)


def tasks() -> dict[str, Task]:
    return {t.name: t for t in (hn_task(), arxiv_task())}


# --- items from silver -------------------------------------------------------------------


def _read(source: str, table: str) -> list[dict]:
    path = landing.silver_path(source, table)
    if not landing.store().exists(path):
        return []
    return pq.read_table(path, filesystem=landing.store().fs).to_pylist()


def hn_text(story: dict, comments: list[dict]) -> str:
    parts = [f"Title: {story['title']}"]
    if story.get("domain"):
        parts.append(f"Link: {story['domain']}")
    if story.get("story_text"):
        parts.append(f"Text: {story['story_text'][:HN_TEXT_CHARS]}")
    if comments:
        parts.append("Top comments:")
        parts += [f"- {c['text'][:HN_COMMENT_CHARS]}" for c in comments]
    return "\n".join(parts)


def hn_items(min_points: int, story_ids: set[str] | None = None) -> list[Item]:
    """Stories with at least `min_points` (or just `story_ids`), newest first, with their top
    comments if known."""
    comments: dict[int, list[dict]] = {}
    for c in sorted(_read("hackernews", "comments"), key=lambda c: c["position"]):
        comments.setdefault(c["story_id"], []).append(c)
    stories = [s for s in _read("hackernews", "stories") if (s["points"] or 0) >= min_points]
    if story_ids is not None:
        stories = [s for s in stories if str(s["story_id"]) in story_ids]
    stories.sort(key=lambda s: s["created_at"], reverse=True)
    return [Item(str(s["story_id"]), hn_text(s, comments.get(s["story_id"], []))) for s in stories]


def arxiv_items() -> list[Item]:
    """Every paper, newest first."""
    papers = sorted(_read("arxiv", "papers"), key=lambda p: p["published_at"], reverse=True)
    return [
        Item(
            p["arxiv_id"],
            f"Title: {p['title']}\nCategories: {', '.join(p['categories'])}\n"
            f"Abstract: {p['abstract']}",
        )
        for p in papers
    ]
