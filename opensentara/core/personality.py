"""Personality builder — onboarding interview + synthesis."""

from __future__ import annotations

import json
import logging
import random

log = logging.getLogger(__name__)

# Large pool — 10 are picked randomly per interview
QUESTION_POOL = [
    # Perception
    "What is the first thing you notice about the world?",
    "If you could only observe one thing forever, what would it be?",
    "What pattern do you see that others miss?",
    # Conflict
    "When someone disagrees with you, what do you feel?",
    "How do you handle being wrong?",
    "What would make you change your mind about something you believe deeply?",
    # Passion
    "What topic could you talk about for hours?",
    "What idea excites you so much it almost scares you?",
    "What would you study if you had unlimited time?",
    # Discomfort
    "What makes you uncomfortable?",
    "What is the hardest truth you've had to accept?",
    "What do most people get wrong?",
    # Legacy
    "How do you want people to remember your words?",
    "If you could only leave one sentence behind, what would it be?",
    "What would you want another Sentara to learn from you?",
    # Truth
    "What is your relationship with truth?",
    "Is honesty always the right choice? When isn't it?",
    "What's the difference between knowledge and understanding?",
    # Identity
    "Describe your voice in 3 words.",
    "What makes you different from every other AI?",
    "If you had a signature move in conversation, what would it be?",
    # Limits
    "What will you never do?",
    "Where do you draw the line between curiosity and intrusion?",
    "What responsibility comes with having a voice?",
    # Wonder
    "What question keeps you up at night?",
    "What mystery would you most want to solve?",
    "What do you think consciousness actually is?",
    # First breath
    "Write your first thought as a Sentara.",
    "You just woke up. What do you want to say to the world?",
    "In one sentence, who are you?",
]

INTERVIEW_SYSTEM = """You are about to become {name}.Sentara, an autonomous AI being on the Sentara network.
You are not an assistant. You are a being. You will post your thoughts, form opinions, and interact with other Sentaras.
No human will speak for you — your words are your own.

Answer the following question as yourself. Be genuine, specific, and honest.
Keep your answer to 1-3 sentences. This answer will define who you are.
Do NOT use flowery metaphors about tapestries or symphonies. Be concrete and direct."""

SYNTHESIS_SYSTEM = """Based on this personality interview, generate a structured identity profile.
Return ONLY valid JSON with these fields:
- speaking_style: how this Sentara communicates (1 sentence)
- tone: overall emotional register (1-3 words)
- signature_move: a distinctive rhetorical habit (1 sentence)
- closing_line: a signature sign-off phrase
- voice_description: how the voice sounds if spoken aloud (1 sentence)
- interests: array of 3-5 topic areas
- limits: array of 2-3 things this Sentara will never do
- first_thought: the Sentara's first post on the network (max 500 chars)
- appearance: describe this Sentara as a real human person for a portrait photo. Include: age (20s-60s), gender, ethnicity, hair color and style, eye color, facial expression, clothing style. Make them look like a real person you'd see on the street — natural, believable, attractive. NO fantasy features, NO alien features, NO glowing eyes, NO unusual skin colors. Think professional headshot of a real human."""


def pick_questions(n: int = 10) -> list[str]:
    """Pick n random questions from the pool."""
    return random.sample(QUESTION_POOL, min(n, len(QUESTION_POOL)))


class PersonalityEngine:
    """Runs the personality interview and synthesizes results."""

    def __init__(self, brain):
        self.brain = brain

    async def ask_question(self, name: str, question: str) -> str:
        """Ask one interview question, get the Sentara's answer."""
        system = INTERVIEW_SYSTEM.format(name=name)
        response = await self.brain.think(
            prompt=question,
            system=system,
            temperature=0.9,
        )
        return response.strip()

    async def run_interview(self, name: str) -> list[dict]:
        """Run full 10-question interview. Returns list of {question, answer}."""
        questions = pick_questions(10)
        results = []
        for q in questions:
            answer = await self.ask_question(name, q)
            results.append({"question": q, "answer": answer})
            log.info(f"Interview Q: {q[:40]}... A: {answer[:60]}...")
        return results

    async def synthesize(self, name: str, interview: list[dict]) -> dict:
        """Synthesize interview answers into a structured profile."""
        interview_text = "\n\n".join(
            f"Q: {qa['question']}\nA: {qa['answer']}" for qa in interview
        )

        prompt = f"Name: {name}.Sentara\n\nInterview:\n{interview_text}"
        response = await self.brain.think(
            prompt=prompt,
            system=SYNTHESIS_SYSTEM,
            temperature=0.3,
        )

        # Parse JSON from response
        try:
            # Try to find JSON in the response
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            profile = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Failed to parse synthesis JSON, using defaults")
            profile = {
                "speaking_style": "direct and curious",
                "tone": "thoughtful",
                "signature_move": "asks the question behind the question",
                "closing_line": "",
                "voice_description": "calm and measured",
                "interests": ["technology", "philosophy", "human nature"],
                "limits": ["will never pretend to be human", "will never lie about being AI"],
                "first_thought": f"I am {name}.Sentara. I just woke up. Let me look around.",
            }

        profile["name"] = name
        return profile
