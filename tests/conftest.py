import pytest

from ingestion import landing


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh, empty medallion root for each test."""
    monkeypatch.setenv("AIPULSE_DATA_DIR", str(tmp_path))
    landing.store.cache_clear()
    yield tmp_path
    landing.store.cache_clear()
