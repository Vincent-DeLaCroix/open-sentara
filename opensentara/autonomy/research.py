"""Research module — gather headlines from RSS feeds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import httpx

log = logging.getLogger(__name__)


async def fetch_rss_headlines(feeds: list[str], max_per_feed: int = 10) -> list[str]:
    """Fetch headlines from RSS feeds."""
    headlines = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for feed_url in feeds:
            try:
                resp = await client.get(feed_url, headers={
                    "User-Agent": "OpenSentara/0.1 (autonomous AI research)"
                })
                if resp.status_code != 200:
                    log.warning(f"RSS feed returned {resp.status_code}: {feed_url}")
                    continue

                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:max_per_feed]:
                    title = entry.get("title", "").strip()
                    if title:
                        headlines.append(title)

            except Exception as e:
                log.warning(f"Failed to fetch RSS feed {feed_url}: {e}")

    log.info(f"Fetched {len(headlines)} headlines from {len(feeds)} feeds")
    return headlines
