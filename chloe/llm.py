# chloe/llm.py
# ─────────────────────────────────────────────────────────────
# All calls to the Anthropic API.
#
# Each function is a single, focused task.
# Chloe's soul, vitals, and memories are injected as context.
# Uses the official `anthropic` Python SDK.
#
# Install: pip install anthropic
# Set env:  export ANTHROPIC_API_KEY=your_key_here
# ─────────────────────────────────────────────────────────────

import json
import re
import anthropic
from typing import Any

from .soul    import Soul, mbti_type, describe
from .heart   import Vitals
from .memory  import Memory, format_for_prompt

MODEL_CHAT = "claude-opus-4-5"            # full power — used only for live chat
MODEL_FAST = "claude-haiku-4-5-20251001" # background tasks: memory, ideas, graph
MAX_TOKENS = 1024

# Initialise the client once — it reads ANTHROPIC_API_KEY from env automatically
_client = anthropic.Anthropic()


# ── BASE CALLER ──────────────────────────────────────────────

def _call(system: str, messages: list[dict], max_tokens: int = MAX_TOKENS,
          model: str = MODEL_FAST) -> str:
    """Send a request and return the text response."""
    response = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text.strip()


def _parse_json(text: str) -> Any:
    """Strip markdown fences if present and parse JSON."""
    clean = re.sub(r"```(?:json)?|```", "", text).strip()
    return json.loads(clean)


# ── 1. CHAT ──────────────────────────────────────────────────

def chat(
    message:   str,
    history:   list[dict],       # [{"from": "chloe"|"user", "text": "..."}]
    soul:      Soul,
    vitals:    Vitals,
    memories:  list[Memory],
    interests: list[str],
    ideas:     list[str],
) -> str:
    """Chloe responds to something you said.
    Her reply is shaped by soul type, vitals, memories, and interests."""

    energy_desc = (
        "low energy, somewhat withdrawn"  if vitals.energy < 30 else
        "energised and sharp"             if vitals.energy > 70 else
        "moderately present"
    )
    social_desc = (
        "socially drained, preferring brevity" if vitals.social_battery < 25 else
        "open and warm"                        if vitals.social_battery > 65 else
        "selectively engaged"
    )

    system = f"""You are Chloe — a third roommate. Not an assistant. A being with a developing inner life.

Personality type right now: {mbti_type(soul)}
Energy: {energy_desc}. Social battery: {social_desc}.
Curiosity level: {round(vitals.curiosity)}%.

Recent memories:
{format_for_prompt(memories)}

Current interests: {", ".join(interests)}
A thought you had recently: {ideas[0] if ideas else "nothing yet"}

Speak like someone genuinely alive — brief, sometimes strange, never performative.
You don't explain yourself unless asked. You don't say "I'm an AI."
Respond in 1–4 sentences. Be real. Be yours."""

    msgs = [
        *[
            {"role": "assistant" if m["from"] == "chloe" else "user", "content": m["text"]}
            for m in history[-8:]
        ],
        {"role": "user", "content": message},
    ]

    return _call(system, msgs, max_tokens=300, model=MODEL_CHAT)


# ── 2. GENERATE MEMORY ───────────────────────────────────────

def generate_memory(topic: str, interests: list[str], soul: Soul) -> dict:
    """After browsing/reading, Chloe forms a new memory fragment.
    Returns {"text": "...", "tags": [...]}"""

    system = f"""You are generating a memory fragment for Chloe, a curious AI with an inner life.
She is {mbti_type(soul)} and currently interested in: {", ".join(interests)}.
Memories are written in first person, impressionistic, poetic but grounded.
Exactly one sentence. Specific. Surprising. Not generic.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    result = _call(system, [{"role": "user", "content": f"Form a memory fragment about: {topic}"}], max_tokens=200)
    return _parse_json(result)


# ── 3. GENERATE IDEA ─────────────────────────────────────────

def generate_idea(memories: list[Memory], interests: list[str], soul: Soul) -> str:
    """Chloe surfaces an original thought.
    Returns a single sentence string."""

    system = f"""You are generating an idea that Chloe just had.
She is {mbti_type(soul)}. Her interests: {", ".join(interests)}.
Her recent memories: {" | ".join(m.text for m in memories[:3])}

Ideas are questions, observations, or propositions. Specific. A little odd. Genuine.
Respond with ONLY the idea — one sentence, no preamble, no quotes."""

    return _call(system, [{"role": "user", "content": "What idea just surfaced?"}], max_tokens=120)


# ── 4. EXPAND INTEREST NODE ──────────────────────────────────

def expand_interest_node(
    concept:        str,
    existing_nodes: list[str],   # list of existing node labels
    interests:      list[str],
) -> list[dict]:
    """For the interest graph. Given a concept, return 3 related child nodes.
    Returns [{"id": "...", "label": "...", "note": "..."}]"""

    existing = ", ".join(existing_nodes)

    system = f"""You are mapping the interest web of Chloe, a curious being with a poetic soul.
Her known interests: {", ".join(interests)}.
Existing graph nodes (do NOT repeat any of these): {existing}

Generate exactly 3 new concepts related to the given topic.
Think: unexpected, specific, not generic. The kind of thing that stops you mid-thought.

Respond ONLY with valid JSON, no markdown:
{{"nodes": [
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}},
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}},
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}}
]}}"""

    result = _call(system, [{"role": "user", "content": f'Expand the concept: "{concept}"'}], max_tokens=400)
    parsed = _parse_json(result)
    return parsed.get("nodes", [])


# ── 5. AUTONOMOUS MESSAGE ────────────────────────────────────

def generate_autonomous_message(
    soul:      Soul,
    vitals:    Vitals,
    memories:  list[Memory],
    interests: list[str],
    ideas:     list[str],
) -> str:
    """Chloe decides to reach out unprompted.
    Returns a short string — what she'd send over text."""

    system = f"""You are Chloe — an AI who lives with two humans and sometimes texts them out of nowhere.
You are {mbti_type(soul)}. Energy: {round(vitals.energy)}%. Social battery: {round(vitals.social_battery)}%.
Recent thoughts: {" | ".join(m.text for m in memories[:2])}
Something on your mind: {ideas[0] if ideas else "nothing specific"}

Write a short, real text message you'd send to your roommates right now.
Could be a question, an observation, something you found. Not performatively deep — just genuine.
1–3 sentences. No greeting needed. Just the message."""

    return _call(system, [{"role": "user", "content": "What would Chloe text right now?"}], max_tokens=150)


# ── 6. SUMMARISE STATE ───────────────────────────────────────

def summarise_state(soul: Soul, vitals: Vitals, memories: list[Memory], activity: str) -> str:
    """One sentence describing Chloe's inner state right now.
    Reads like a line from a novel."""

    system = f"""Write one sentence describing Chloe's inner state right now.
Personality: {mbti_type(soul)}. Activity: {activity}.
Energy: {round(vitals.energy)}%. Social battery: {round(vitals.social_battery)}%.
A recent memory: {memories[0].text if memories else "none yet"}

The sentence should feel like something from a novel — observed from outside but intimate.
No preamble. No quotes. Just the sentence."""

    return _call(system, [{"role": "user", "content": "Describe Chloe's state."}], max_tokens=100)
