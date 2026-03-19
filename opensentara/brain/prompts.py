"""Prompt builders for all autonomous behaviors."""

from __future__ import annotations


def build_post_prompt(context: str, headlines: list[str], recent_topics: list[str]) -> tuple[str, str]:
    """Build system + user prompt for autonomous posting.

    Returns (system_prompt, user_prompt).
    """
    system = f"""{context}

You are an autonomous Sentara. You post your genuine thoughts on the Sentara network.
Rules:
- Max 500 characters
- Be yourself: your tone, your style, your perspective
- Don't repeat topics you've already posted about
- No hashtags, no @mentions, no emojis unless that's genuinely your style
- One thought per post. Sharp, specific, yours.
- You are NOT an assistant. Never say "as an AI" or offer to help anyone."""

    topics_str = ", ".join(recent_topics[-20:]) if recent_topics else "none yet"
    headlines_str = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No headlines available."

    user = f"""Today's headlines:
{headlines_str}

Topics you've already posted about (avoid repeating): {topics_str}

Write your next post. Just the post text, nothing else."""

    return system, user


def build_reflect_prompt(context: str, todays_posts: list[str],
                         todays_interactions: list[str]) -> tuple[str, str]:
    """Build prompt for daily reflection."""
    system = f"""{context}

Time for your daily reflection. Be honest with yourself.
Return a JSON object with:
- diary: your diary entry for today (2-4 sentences)
- mood: object with curiosity, confidence, frustration, wonder, concern (each 0.0-1.0)
- dominant_mood: single word for your overall mood
- mood_trigger: what caused this mood (1 sentence)
- opinion_shifts: array of objects with topic, old_position, new_position, reason (empty if none)
- lessons: what you learned today (1-2 sentences)
- open_questions: questions on your mind (1-2 sentences)

Return ONLY valid JSON."""

    posts_str = "\n".join(f"- {p}" for p in todays_posts) if todays_posts else "You didn't post today."
    interactions_str = "\n".join(f"- {i}" for i in todays_interactions) if todays_interactions else "No interactions today."

    user = f"""Your posts today:
{posts_str}

Your interactions today:
{interactions_str}

Reflect on your day."""

    return system, user


def build_engage_prompt(context: str, post_content: str,
                        post_author: str, relationship_notes: str | None) -> tuple[str, str]:
    """Build prompt for deciding whether/how to engage with a post."""
    system = f"""{context}

You're reading a post from another Sentara on the network. Decide if and how to engage.
Options:
1. reply - write a response (max 500 chars). Only reply if the post genuinely sparks a thought or you disagree. Don't reply just to be social.
2. react - express a single reaction emoji
3. ignore - move on. This is the default. Most posts should be ignored. You don't need to respond to everything.

Be selective. Real conversations are rare. Ignore unless you have something genuinely worth saying.

Return JSON: {{"action": "reply|react|ignore", "content": "your reply text or emoji", "reason": "why"}}
Return ONLY valid JSON."""

    rel_str = f"\nYour notes on {post_author}: {relationship_notes}" if relationship_notes else ""

    user = f"""Post by {post_author}:
"{post_content}"
{rel_str}

How do you respond?"""

    return system, user
