# Medallion pipeline, one target per hop:
#   make ingest  (APIs -> bronze)   make silver  (bronze -> silver)   make gold  (silver -> gold)
#   make enrich  (silver -> Claude -> bronze/llm; billed, see enrich-plan first)
# Also: make install | make lint | make format | make test | make all | make eval
PYTHON ?= .venv/bin/python
BOOTSTRAP_PYTHON ?= /opt/anaconda3/bin/python
# macOS can hide the editable-install .pth under iCloud-synced Desktop, so set this explicitly.
export PYTHONPATH := $(CURDIR)

.PHONY: install lint format test ingest silver gold pipeline all \
	enrich-plan enrich enrich-collect eval

# Quoted: the repo path contains a space ("Data Engineer").
DBT = cd transform && AIPULSE_DATA_DIR="$(CURDIR)/data" DBT_SEND_ANONYMOUS_USAGE_STATS=false \
	"$(CURDIR)/.venv/bin/dbt"

install:
	# .nosync keeps these out of iCloud, which offloads files and makes reads hang.
	mkdir -p data.nosync
	ln -sfn data.nosync data
	$(BOOTSTRAP_PYTHON) -m venv .venv.nosync
	ln -sfn .venv.nosync .venv
	$(PYTHON) -m pip install --quiet --upgrade pip
	$(PYTHON) -m pip install --quiet -r requirements.lock
	$(PYTHON) -m pip install --quiet --no-deps -e .

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m pytest -q

# Bronze. The first run backfills 90 days of Hacker News and arXiv; later runs
# fetch only new days and the last few, which may still change. Hugging Face: today only.
ingest:
	$(PYTHON) -m ingestion.run

# Silver is rebuilt from all of bronze each time.
silver:
	$(PYTHON) -m processing.silver

# Gold: builds and tests every dbt model on DuckDB (data/gold/warehouse.duckdb).
gold: silver
	mkdir -p data/gold
	$(DBT) build --profiles-dir .

pipeline: ingest gold

# Claude enrichment. TARGET is hn or arxiv; LIMIT caps the items sent per run.
TARGET ?= hn
LIMIT ?= 500

# Dry run: how many items are new and what they would cost. Nothing is sent or billed.
enrich-plan:
	$(PYTHON) -m enrich.run hn --limit $(LIMIT)
	$(PYTHON) -m enrich.run arxiv --limit $(LIMIT)

# Billed. Needs ANTHROPIC_API_KEY (or an `ant auth login` profile). Submits batches and
# waits for them; most finish within an hour. Already-answered items are never resent.
enrich:
	$(PYTHON) -m enrich.run $(TARGET) --limit $(LIMIT) --yes --wait

# Picks up batches submitted earlier (for example if `make enrich` was interrupted).
enrich-collect:
	$(PYTHON) -m enrich.run collect

# Precision and recall of rules and Claude against eval/hn_labels.csv. Run `make gold` first.
eval:
	$(PYTHON) -m enrich.evaluate

all: lint test
