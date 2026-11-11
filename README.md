# AI Pulse

One lakehouse for AI trends from three public sources: **Hacker News** (what engineers talk
about), **Hugging Face** (which open models people download) and **arXiv** (what researchers
publish). They share one data model, so a technology like "Llama" or "vLLM" can be followed
across all three, week by week.

> Status: phase 2 of 7. All three sources run from bronze to gold, with rule-based
> technology matching. LLM enrichment comes next.

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
 │         + enrichment: tech mentions, sentiment, summaries,       │
 │           embeddings (Claude API, local MiniLM)  [phases 3-4]    │
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

## Quick start

```bash
make install   # venv and data folders (kept out of iCloud via .nosync)
make test      # no network: tests use an invented Hacker News
make ingest    # first run backfills 90 days: HN ~4 min (~90k stories), arXiv ~10 min
make gold      # silver, then dbt build on DuckDB
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
3. LLM enrichment: tech mentions and sentiment, paper summaries (Claude API, batched and cached)
4. Embeddings and semantic search over papers (MiniLM + DuckDB vss)
5. Gold trend marts: rising and falling technologies across sources
6. Dashboard and weekly "what's hot in open AI" digest
7. Scheduling, then AWS (Lambda, Step Functions, Athena)

## License

MIT
