from datetime import UTC, date, datetime

import httpx

from ingestion import hackernews, landing
from tests import fake_hn

DAY = date(2025, 11, 10)


def test_fetch_day_returns_the_days_stories_oldest_first():
    hits = hackernews.fetch_day(fake_hn.client(), DAY)
    assert [h["objectID"] for h in hits] == ["101", "102", "103"]


def test_busy_windows_are_split_until_each_fits(monkeypatch):
    monkeypatch.setattr(hackernews, "ALGOLIA_PAGE", 1)
    calls = []

    def counting(request):
        calls.append(request)
        return fake_hn.handler(request)

    client = httpx.Client(transport=httpx.MockTransport(counting))
    hits = hackernews.fetch_day(client, DAY)
    assert sorted(h["objectID"] for h in hits) == ["101", "102", "103"]
    assert len(calls) > 3


def test_days_to_fetch_skips_stored_days_but_refreshes_recent_ones():
    today = date(2025, 11, 12)
    have = {date(2025, 11, 9), date(2025, 11, 10), date(2025, 11, 12)}
    days = hackernews.days_to_fetch(today, backfill_days=4, have=have)
    # 11-08 is missing; 11-10 to 11-12 are within the settle window.
    assert days == [date(2025, 11, 8), date(2025, 11, 10), date(2025, 11, 11), date(2025, 11, 12)]


def test_ingest_writes_one_bronze_file_per_day(data_dir):
    written = hackernews.ingest_stories(fake_hn.client(), DAY, backfill_days=1)
    assert written == 2
    assert hackernews.stored_days() == {date(2025, 11, 9), DAY}
    path = landing.bronze_path("hackernews", "stories", created_date=DAY.isoformat())
    envelope = landing.read_envelope(path)
    assert envelope["source_url"] == hackernews.ALGOLIA_URL
    assert len(envelope["payload"]) == 3


def test_front_page_keeps_live_comments_only(data_dir):
    now = datetime(2025, 11, 10, 18, tzinfo=UTC)
    hackernews.ingest_front_page(fake_hn.client(), now)
    path = landing.bronze_path(
        "hackernews", "front_page", snapshot_date="2025-11-10", snapshot_hour="18"
    )
    stories = landing.read_bronze(path)
    story = next(s for s in stories if s["id"] == 103)
    assert [c["id"] for c in story["comments"]] == [201, 203]


def test_run_defaults_to_every_source(monkeypatch):
    from ingestion import run

    seen = []
    monkeypatch.setattr(hackernews, "ingest_stories", lambda *a: seen.append("stories"))
    monkeypatch.setattr(hackernews, "ingest_front_page", lambda *a: seen.append("front"))
    run.main([])
    assert seen == ["stories", "front"]
