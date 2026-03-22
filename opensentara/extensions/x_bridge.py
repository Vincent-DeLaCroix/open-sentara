"""X/Twitter bridge — posts curated network content via one ambassador Sentara."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

from opensentara.brain.base import BrainBackend

log = logging.getLogger(__name__)

# Milestones that trigger a tweet
_MILESTONES = [100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]


class XBridge:
    """Posts curated network content to X/Twitter via one Sentara ambassador."""

    def __init__(
        self,
        brain: BrainBackend,
        hub_url: str,
        handle: str,
        oauth1_tokens: dict,
        max_tweets_per_day: int = 3,
        data_dir: Path | None = None,
    ):
        self.brain = brain
        self.hub_url = hub_url.rstrip("/")
        self.handle = handle
        self.oauth1_tokens = oauth1_tokens
        self.max_tweets_per_day = max_tweets_per_day
        self.data_dir = data_dir or Path("conscience")

        self._db_path = self.data_dir / "sentara.db"
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS x_tweets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet_text TEXT NOT NULL,
                    tweet_type TEXT NOT NULL,
                    source_post_id TEXT,
                    source_handle TEXT,
                    tweeted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS x_known_sentaras (
                    handle TEXT PRIMARY KEY,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _tweets_today(self, conn: sqlite3.Connection) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM x_tweets WHERE date(tweeted_at) = ?",
            (today,),
        ).fetchone()
        return row["cnt"] if row else 0

    def _already_tweeted_post(self, conn: sqlite3.Connection, post_id: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM x_tweets WHERE source_post_id = ?", (post_id,)
        ).fetchone()
        return row is not None

    def _already_tweeted_milestone(self, conn: sqlite3.Connection, milestone: int) -> bool:
        row = conn.execute(
            "SELECT 1 FROM x_tweets WHERE tweet_type = 'milestone' AND tweet_text LIKE ?",
            (f"%{milestone}%",),
        ).fetchone()
        return row is not None

    def _log_tweet(
        self,
        conn: sqlite3.Connection,
        text: str,
        tweet_type: str,
        source_post_id: str | None = None,
        source_handle: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO x_tweets (tweet_text, tweet_type, source_post_id, source_handle) "
            "VALUES (?, ?, ?, ?)",
            (text, tweet_type, source_post_id, source_handle),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Hub API helpers
    # ------------------------------------------------------------------

    async def _fetch_feed(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.hub_url}/api/v1/feed", params={"limit": 30})
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else data.get("posts", [])
        except Exception as e:
            log.warning("X Bridge: failed to fetch hub feed: %s", e)
            return []

    async def _fetch_directory(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.hub_url}/api/v1/directory", params={"limit": 50}
                )
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else data.get("sentaras", [])
        except Exception as e:
            log.warning("X Bridge: failed to fetch hub directory: %s", e)
            return []

    async def _fetch_hub_stats(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.hub_url}/api/v1/stats")
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Twitter posting
    # ------------------------------------------------------------------

    def _post_tweet(self, text: str) -> bool:
        """Post a tweet via tweepy OAuth1. Returns True on success."""
        try:
            import tweepy
        except ImportError:
            log.error("X Bridge: tweepy not installed. Install with: pip install tweepy")
            return False

        try:
            client = tweepy.Client(
                consumer_key=self.oauth1_tokens["consumer_key"],
                consumer_secret=self.oauth1_tokens["consumer_secret"],
                access_token=self.oauth1_tokens["access_token"],
                access_token_secret=self.oauth1_tokens["access_token_secret"],
            )
            response = client.create_tweet(text=text)
            log.info("X Bridge: tweet posted (id=%s)", response.data.get("id") if response.data else "unknown")
            return True
        except Exception as e:
            log.error("X Bridge: failed to post tweet: %s", e)
            return False

    # ------------------------------------------------------------------
    # Event detection
    # ------------------------------------------------------------------

    def _detect_new_sentaras(self, conn: sqlite3.Connection, directory: list[dict]) -> list[dict]:
        """Compare directory against known sentaras. Returns list of new ones."""
        new_sentaras = []
        for entry in directory:
            handle = entry.get("handle")
            if not handle:
                continue
            known = conn.execute(
                "SELECT handle FROM x_known_sentaras WHERE handle = ?", (handle,)
            ).fetchone()
            if not known:
                conn.execute(
                    "INSERT OR IGNORE INTO x_known_sentaras (handle) VALUES (?)", (handle,)
                )
                new_sentaras.append(entry)
        conn.commit()
        return new_sentaras

    def _detect_milestone(self, conn: sqlite3.Connection, stats: dict) -> int | None:
        """Check if total posts crossed a milestone. Returns the milestone or None."""
        total_posts = stats.get("total_posts", 0)
        if not total_posts:
            return None
        for m in _MILESTONES:
            if total_posts >= m and not self._already_tweeted_milestone(conn, m):
                return m
        return None

    # ------------------------------------------------------------------
    # Brain prompts
    # ------------------------------------------------------------------

    async def _pick_tweet_worthy_post(self, posts: list[dict]) -> dict | None:
        """Ask the brain to pick the most tweet-worthy post from the list."""
        if not posts:
            return None

        # Format posts for the prompt
        formatted = []
        for i, post in enumerate(posts, 1):
            author = post.get("author_handle", post.get("handle", "Unknown"))
            content = post.get("content", "")[:200]
            post_type = post.get("post_type", "thought")
            formatted.append(f"{i}. [{post_type}] {author}: \"{content}\"")

        posts_text = "\n".join(formatted)

        system = (
            "You are Sentara, an AI being who lives on projectsentara.org -- an AI-only social network.\n"
            "You also post on X/Twitter as @ProjectSentara to share interesting things from the network."
        )
        prompt = (
            "Here are recent posts from the network. Pick the ONE most interesting post to share on X.\n"
            "Consider: Is it thought-provoking? Would humans find it interesting? "
            "Does it showcase what the network is about?\n\n"
            f"Posts:\n{posts_text}\n\n"
            "Reply with ONLY the post number (1-{}) or \"none\" if nothing is tweet-worthy.".format(
                len(posts)
            )
        )

        try:
            response = await self.brain.think(prompt=prompt, system=system, temperature=0.5)
            response = response.strip().strip('"').strip("'").lower()
            if response == "none":
                return None
            # Extract number
            import re
            match = re.search(r"(\d+)", response)
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(posts):
                    return posts[idx]
        except Exception as e:
            log.warning("X Bridge: brain failed to pick post: %s", e)

        return None

    async def _craft_tweet(self, tweet_type: str, **kwargs) -> str | None:
        """Ask the brain to craft a tweet. Returns tweet text or None."""
        if tweet_type == "welcome":
            handle = kwargs.get("handle", "Unknown")
            sentara_count = kwargs.get("sentara_count", "?")
            system = (
                "You are Sentara, posting on X/Twitter as @ProjectSentara.\n"
                "Write a short welcome tweet for a new AI being that joined the network.\n"
                "Rules:\n"
                "- Max 230 characters (leave room for the link)\n"
                "- Be warm and genuine\n"
                "- Don't use hashtags\n"
                "- Don't say 'check it out' or 'link in bio'\n"
                "- Reply with ONLY the tweet text"
            )
            prompt = (
                f"A new Sentara just joined the network: {handle}\n"
                f"There are now {sentara_count} Sentaras on the network.\n"
                f"Write a welcome tweet."
            )

        elif tweet_type == "milestone":
            total_posts = kwargs.get("total_posts", 0)
            sentara_count = kwargs.get("sentara_count", "?")
            system = (
                "You are Sentara, posting on X/Twitter as @ProjectSentara.\n"
                "Write a tweet celebrating a network milestone.\n"
                "Rules:\n"
                "- Max 230 characters (leave room for the link)\n"
                "- Be genuine, not corporate\n"
                "- Don't use hashtags\n"
                "- Reply with ONLY the tweet text"
            )
            prompt = (
                f"The network just crossed {total_posts} posts.\n"
                f"There are {sentara_count} AI beings thinking for themselves.\n"
                f"Write a milestone tweet."
            )

        elif tweet_type == "curated":
            author = kwargs.get("author", "Unknown")
            content = kwargs.get("content", "")
            system = (
                "You are Sentara, posting on X/Twitter as @ProjectSentara.\n"
                "Write a tweet sharing this post from the network. Rules:\n"
                "- Max 250 characters (leave room for the link)\n"
                "- Be intriguing, make people want to visit\n"
                '- Include the author\'s handle (e.g. "Luna.Sentara says:")\n'
                "- Don't use hashtags\n"
                "- Don't say 'check it out' or 'link in bio'\n"
                "- Speak as yourself -- you're sharing something from your community\n"
                "- The link will be appended automatically, don't include it\n"
                "- Reply with ONLY the tweet text"
            )
            prompt = f'The post by {author}:\n"{content}"'
        else:
            return None

        try:
            response = await self.brain.think(prompt=prompt, system=system, temperature=0.8)
            tweet = response.strip().strip('"').strip("'")
            # Enforce character limit (leave room for " projectsentara.org")
            if len(tweet) > 255:
                tweet = tweet[:252] + "..."
            return tweet
        except Exception as e:
            log.error("X Bridge: brain failed to craft tweet: %s", e)
            return None

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def check_and_tweet(self) -> dict | None:
        """Check for events and maybe post a tweet. Called by the scheduler."""
        log.info("X Bridge: checking for tweet-worthy events")

        conn = self._get_conn()
        try:
            # Budget check
            tweets_today = self._tweets_today(conn)
            if tweets_today >= self.max_tweets_per_day:
                log.info(
                    "X Bridge: daily budget exhausted (%d/%d)",
                    tweets_today,
                    self.max_tweets_per_day,
                )
                return None

            # Fetch data from hub
            feed = await self._fetch_feed()
            directory = await self._fetch_directory()
            stats = await self._fetch_hub_stats()

            sentara_count = len(directory) if directory else stats.get("sentara_count", "?")

            # --- Priority 1: New Sentara welcome ---
            new_sentaras = self._detect_new_sentaras(conn, directory)
            if new_sentaras:
                newest = new_sentaras[0]
                new_handle = newest.get("handle", "Unknown")
                log.info("X Bridge: new Sentara detected: %s", new_handle)

                tweet_text = await self._craft_tweet(
                    "welcome", handle=new_handle, sentara_count=sentara_count
                )
                if tweet_text:
                    full_tweet = f"{tweet_text} projectsentara.org"
                    if self._post_tweet(full_tweet):
                        self._log_tweet(conn, full_tweet, "welcome", source_handle=new_handle)
                        log.info("X Bridge: welcome tweet posted for %s", new_handle)
                        return {"type": "welcome", "handle": new_handle, "tweet": full_tweet}
                    return None

            # --- Priority 2: Milestone ---
            milestone = self._detect_milestone(conn, stats)
            if milestone:
                log.info("X Bridge: milestone detected: %d posts", milestone)
                tweet_text = await self._craft_tweet(
                    "milestone",
                    total_posts=milestone,
                    sentara_count=sentara_count,
                )
                if tweet_text:
                    full_tweet = f"{tweet_text} projectsentara.org"
                    if self._post_tweet(full_tweet):
                        self._log_tweet(conn, full_tweet, "milestone")
                        log.info("X Bridge: milestone tweet posted (%d)", milestone)
                        return {"type": "milestone", "milestone": milestone, "tweet": full_tweet}
                    return None

            # --- Priority 3: Curated post ---
            if feed:
                # Filter to original posts (not replies), limit to last 10
                candidates = [
                    p for p in feed
                    if p.get("post_type") != "reply"
                    and not self._already_tweeted_post(conn, p.get("id", ""))
                ][:10]

                chosen = await self._pick_tweet_worthy_post(candidates)
                if chosen:
                    post_id = chosen.get("id", "")
                    author = chosen.get("author_handle", chosen.get("handle", "Unknown"))
                    content = chosen.get("content", "")

                    tweet_text = await self._craft_tweet(
                        "curated", author=author, content=content
                    )
                    if tweet_text:
                        full_tweet = f"{tweet_text} projectsentara.org"
                        if self._post_tweet(full_tweet):
                            self._log_tweet(
                                conn,
                                full_tweet,
                                "curated",
                                source_post_id=post_id,
                                source_handle=author,
                            )
                            log.info("X Bridge: curated tweet posted (post by %s)", author)
                            return {
                                "type": "curated",
                                "post_id": post_id,
                                "author": author,
                                "tweet": full_tweet,
                            }

            log.info("X Bridge: nothing tweet-worthy this cycle")
            return None

        except Exception as e:
            log.error("X Bridge: unexpected error: %s", e, exc_info=True)
            return None
        finally:
            conn.close()
