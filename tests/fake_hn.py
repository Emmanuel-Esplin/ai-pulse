"""An invented Hacker News behind httpx.MockTransport; tests never call the real APIs."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

import httpx

DAY_START = 1_762_732_800  # 2025-11-10 00:00 UTC

STORIES = [
    {
        "objectID": "101",
        "title": "Show HN: A tiny vector DB in Rust",
        "url": "https://www.example.com/a",
        "author": "ana",
        "points": 120,
        "num_comments": 30,
        "created_at_i": DAY_START + 3_600,
    },
    {
        "objectID": "102",
        "title": "Ask HN: Is fine-tuning still worth it?",
        "url": None,
        "author": "ben",
        "points": 45,
        "num_comments": 60,
        "created_at_i": DAY_START + 7_200,
        "story_text": "<p>Curious &amp; honest answers&#x2F;please",
    },
    {
        "objectID": "103",
        "title": "New open-weights model tops leaderboard",
        "url": "https://lab.example.org/x",
        "author": "cy",
        "points": 300,
        "num_comments": 150,
        "created_at_i": DAY_START + 50_000,
    },
]

ITEMS = {
    103: {
        "id": 103,
        "type": "story",
        "by": "cy",
        "time": DAY_START + 50_000,
        "score": 410,
        "descendants": 170,
        "title": "New open-weights model tops leaderboard",
        "url": "https://lab.example.org/x",
        "kids": [201, 202, 203],
    },
    104: {
        "id": 104,
        "type": "job",
        "by": "hr",
        "time": DAY_START + 60_000,
        "title": "We're hiring",
    },
    201: {
        "id": 201,
        "type": "comment",
        "by": "dee",
        "time": DAY_START + 51_000,
        "parent": 103,
        "text": "Benchmarks look <i>great</i>, but the license is restrictive.",
    },
    202: {"id": 202, "type": "comment", "deleted": True, "time": DAY_START + 51_500, "parent": 103},
    203: {
        "id": 203,
        "type": "comment",
        "by": "eve",
        "time": DAY_START + 52_000,
        "parent": 103,
        "text": "Runs fine on a single GPU.",
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "hn.algolia.com":
        nf = parse_qs(request.url.query.decode())["numericFilters"][0]
        lo, hi = map(int, re.findall(r"\d+", nf))
        hits = [s for s in STORIES if lo <= s["created_at_i"] < hi]
        return httpx.Response(200, json={"nbHits": len(hits), "hits": hits})
    path = request.url.path
    if path.endswith("/topstories.json"):
        return httpx.Response(200, json=[103, 104])
    item_id = int(path.rsplit("/", 1)[1].removesuffix(".json"))
    return httpx.Response(200, content=json.dumps(ITEMS.get(item_id)))


def client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))
