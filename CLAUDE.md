# CLAUDE.md

Guidance for Claude Code in this repository.

## Project

AI Pulse: AI trends from Hacker News, Hugging Face and arXiv in one medallion lakehouse
(bronze -> silver -> gold). The approved plan has 7 phases; see README "Roadmap".

## Commands

```bash
make install   # venv in .venv.nosync (symlinked to .venv), data.nosync symlinked to data
make lint      # ruff check + format --check (line length 100)
make test      # pytest; never calls live APIs (httpx.MockTransport), builds dbt end to end
make ingest    # APIs -> bronze
make silver    # bronze -> silver (rebuilt from all of bronze)
make gold      # silver, then dbt build on DuckDB -> data/gold/warehouse.duckdb
make enrich-plan  # dry run of Claude enrichment: item counts and estimated cost, sends nothing
make enrich TARGET=hn LIMIT=500  # BILLED: ask the user first
make eval      # rules and Claude scored against eval/hn_labels.csv
```

## Rules

- Keep the medallion layers explicit: bronze is raw and append-only, silver is typed and
  deduplicated Parquet, gold is dbt. Each pipeline step moves data exactly one layer.
- Tests and CI never call live APIs or the Claude API. Ask before running anything billed.
- Style: short comments that explain why, docstrings on public functions, a header comment
  on every SQL model. Empty `__init__.py` files stay empty.
- The repo path contains a space and lives in iCloud: quote paths; large or hot files go in
  `*.nosync` paths.
