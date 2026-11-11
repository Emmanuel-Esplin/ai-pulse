# Medallion pipeline, one target per hop:
#   make ingest  (APIs -> bronze)   make silver  (bronze -> silver)   make gold  (silver -> gold)
# Also: make install | make lint | make format | make test | make all
PYTHON ?= .venv/bin/python
BOOTSTRAP_PYTHON ?= /opt/anaconda3/bin/python
# macOS can hide the editable-install .pth under iCloud-synced Desktop, so set this explicitly.
export PYTHONPATH := $(CURDIR)

.PHONY: install lint format test ingest silver gold pipeline all

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

# Bronze. The first run backfills 90 days of Hacker News (about 2 minutes); later runs
# fetch only new days and the last two, whose scores may still change.
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

all: lint test
