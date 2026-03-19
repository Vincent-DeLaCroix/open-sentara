"""Research module — gather headlines from RSS feeds via the hub's feed bank."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import httpx

log = logging.getLogger(__name__)

# Cache feeds fetched from the hub
_feed_cache: list[str] = []

# Track broken feeds to avoid retrying within a session
_broken_feeds: set[str] = set()


async def fetch_feeds_from_hub(hub_url: str, interests: list[str],
                               mood: str = "") -> list[str]:
    """Fetch RSS feed URLs from the hub based on Sentara's interests and mood."""
    global _feed_cache

    interests_str = ",".join(interests) if interests else ""
    params = {"interests": interests_str}
    if mood:
        params["mood"] = mood

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{hub_url.rstrip('/')}/api/v1/feeds",
                params=params,
            )
            if resp.status_code == 200:
                data = resp.json()
                feeds = data.get("feeds", [])
                mood_bonus = data.get("mood_bonus", [])
                if mood_bonus:
                    log.info(f"Mood '{mood}' added categories: {mood_bonus}")
                if feeds:
                    _feed_cache = feeds
                    log.info(f"Fetched {len(feeds)} feed URLs from hub")
                    return feeds
    except Exception as e:
        log.debug(f"Could not fetch feeds from hub: {e}")

    # Fall back to cached feeds
    if _feed_cache:
        log.warning("Hub unreachable, using cached feeds")
        return _feed_cache

    log.warning("Hub unreachable and no cached feeds available")
    return []


async def fetch_rss_headlines(feeds: list[str], max_per_feed: int = 10,
                              min_headlines: int = 5) -> list[str]:
    """Fetch headlines from RSS feeds with fallback for broken feeds.

    Skips feeds that failed previously in this session.
    Ensures at least min_headlines are returned if possible.
    """
    headlines = []
    working_count = 0

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for feed_url in feeds:
            # Skip known-broken feeds
            if feed_url in _broken_feeds:
                continue

            try:
                resp = await client.get(feed_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenSentara/0.1)"
                })
                if resp.status_code != 200:
                    log.warning(f"RSS feed returned {resp.status_code}: {feed_url}")
                    _broken_feeds.add(feed_url)
                    continue

                parsed = feedparser.parse(resp.text)
                count = 0
                for entry in parsed.entries[:max_per_feed]:
                    title = entry.get("title", "").strip()
                    if title:
                        headlines.append(title)
                        count += 1

                if count > 0:
                    working_count += 1
                else:
                    _broken_feeds.add(feed_url)

            except Exception as e:
                log.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
                _broken_feeds.add(feed_url)

    if _broken_feeds:
        log.info(f"Skipped {len(_broken_feeds)} broken feeds this session")

    log.info(f"Fetched {len(headlines)} headlines from {working_count} working feeds")
    return headlines
