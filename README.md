# AI Pulse

One lakehouse for AI trends from three public sources: **Hacker News** (what engineers talk
about), **Hugging Face** (which open models people download) and **arXiv** (what researchers
publish). They share one data model, so a technology like "Llama" or "vLLM" can be followed
across all three, week by week.

> Status: phase 3 of 7. All three sources run from bronze to gold; Claude adds technology
> mentions with sentiment for Hacker News and plain-English digests for arXiv papers.

## Medallion architecture

```
 Hacker News (Algolia + Firebase)    Hugging Face Hub    arXiv API
              │                             │                │
              ▼                             ▼                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ BRONZE  data/bronze/<source>/…/*.json                            │
 │         raw API responses, append-only, with fetched_at + URL    │
 └──────────────────────────────────────────────────────────────────┘
              │  processing/silver.py: typed, deduplicated, latest observation wins
              ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ SILVER  data/silver/<source>/<table>.parquet                     │
 │         + llm/: Claude's mentions, sentiment and paper digests   │
 │           (parsed from bronze/llm, Claude's raw responses)       │
 └──────────────────────────────────────────────────────────────────┘
              │  dbt (transform/)
              ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ GOLD    data/gold/warehouse.duckdb                               │
 │         staging views, dimensions, facts, trend marts            │
 └──────────────────────────────────────────────────────────────────┘
              │
              ▼
        dashboard + weekly digest  [phase 6]
```

Each Make target is one hop: `make ingest` (sources to bronze), `make silver`, `make gold`.
Bronze is never edited, so silver and gold can always be rebuilt from it.

## Claude enrichment

Claude is treated as one more source. Items come from silver; the Message Batches API
(half price) answers them with structured outputs that must follow a JSON schema; the raw
responses land in `bronze/llm/` like any other API's, and silver parses them.

- **Hacker News** (`hn_technologies`): every AI technology a post refers to, the sentiment
  towards each, and whether it is the main subject. Names outside the taxonomy come back as
  `other` and feed `mart_emerging_terms`.
- **arXiv** (`arxiv_digest`): a two-to-three sentence plain-English summary, the paper's
  contribution type, its technologies, and new terms it introduces.

Bronze doubles as the cache: an item with a successful answer for the current prompt
version is never sent again. `make enrich-plan` shows what would be sent and its estimated
cost without sending anything; `mart_llm_usage` reports actual spend from the API's token
counts. Rules and Claude are scored against hand labels in [docs/eval.md](docs/eval.md).

## Quick start

```bash
make install   # venv and data folders (kept out of iCloud via .nosync)
make test      # no network: tests use an invented Hacker News
make ingest    # first run backfills 90 days: HN ~4 min (~90k stories), arXiv ~10 min
make gold      # silver, then dbt build on DuckDB
make enrich-plan               # what Claude enrichment would send and cost (free)
make enrich TARGET=hn LIMIT=500   # billed; needs ANTHROPIC_API_KEY
```

## Sources

| Source | API | Notes |
|---|---|---|
| Hacker News | [HN Search (Algolia)](https://hn.algolia.com/api), [Firebase API](https://github.com/HackerNews/API) | Every story by day; front-page snapshot with top comments |
| Hugging Face | [Hub API](https://huggingface.co/docs/hub/api) | Daily snapshot of the top 10k models by downloads, 5k by likes, 1k trending. The Hub has no history, so growth builds up from the first snapshot |
| arXiv | [arXiv API](https://info.arxiv.org/help/api/index.html) | Every paper in cs.AI, cs.LG, cs.CL, cs.CV, stat.ML by submission day; 3 s between requests per arXiv's terms |

## One data model across sources

`transform/seeds/technologies.csv` lists 68 technologies (model families, labs, frameworks,
techniques, products, hardware) and `technology_aliases.csv` the words that count as a mention.
Every source resolves to the same `technology_id`:

- Hacker News stories and arXiv papers: an alias appears as a whole word in the title or text.
- Hugging Face models: the model id or its base model names a model family, so a community
  quantization such as `someone/Qwen3-4B-GGUF` counts towards Qwen.
- Hugging Face models also cite arXiv papers in their tags (`stg_hf_model_papers`), which
  links models to the research behind them directly.

These rules are the baseline; phase 3 adds LLM extraction with sentiment and measures both.

Raw data stays out of the repo (`data/` is git-ignored).

## Roadmap

1. Scaffold and Hacker News, bronze to gold ✅
2. Hugging Face and arXiv ingestion; technology taxonomy and rule-based matching ✅
3. LLM enrichment: tech mentions and sentiment, paper digests (Claude API, batched and cached) ✅
4. Embeddings and semantic search over papers (MiniLM + DuckDB vss)
5. Gold trend marts: rising and falling technologies across sources
6. Dashboard and weekly "what's hot in open AI" digest
7. Scheduling, then AWS (Lambda, Step Functions, Athena)

## License

MIT
