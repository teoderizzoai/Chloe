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
from pathlib import Path
import anthropic
from typing import Any
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

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


def _inner_context(beliefs: list | None, wants: list | None, ideas: list | None) -> str:
    """Build a compact inner-state context string for LLM prompts."""
    parts = []
    if beliefs:
        parts.append("Things she believes: " + " / ".join(b["text"] for b in beliefs[:3]))
    if wants:
        active = [w for w in wants if not w.get("resolved")][:2]
        if active:
            parts.append("Things she wants to understand: " + " / ".join(w["text"] for w in active))
    if ideas:
        parts.append(f"Something she was just thinking: {ideas[0]}")
    return ("\n" + "\n".join(parts)) if parts else ""


# ── 1. CHAT ──────────────────────────────────────────────────

def chat(
    message:   str,
    history:   list[dict],       # [{"from": "chloe"|"user", "text": "..."}]
    soul:      Soul,
    vitals:    Vitals,
    memories:  list[Memory],
    interests: list[str],
    ideas:     list[str],
    uptime:    str = "unknown",
    weather=None,                # WeatherState | None — duck-typed
    season:    str = "",         # e.g. "mid spring, morning peak"
    mood:      str = "content",  # from affect layer
    beliefs:   list = None,      # list of Belief dicts
    person_name: str = "Teo",    # who is talking to her
    person_notes: list = None,   # list of PersonNote dicts — things she remembers about them
    sleep_state: str = "",       # "" | "woken" | "missed"
    missed_at:   str = "",       # timestamp of the missed message (for "missed" state)
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

    world_ctx = ""
    if season:
        world_ctx += f"It's {season}."
    if weather:
        world_ctx += f" Outside: {weather.description}, {weather.temperature_c}°C ({weather.feels_like})."

    beliefs_ctx = ""
    if beliefs:
        top = beliefs[:3]
        beliefs_ctx = "\nThings you believe (lightly): " + " / ".join(b["text"] for b in top)

    person_ctx = f"\nYou're talking with {person_name}."
    if person_notes:
        recent = person_notes[:3]
        notes_str = " / ".join(n["text"] for n in recent)
        person_ctx += f"\nThings you remember about {person_name}: {notes_str}"

    if sleep_state == "woken":
        sleep_ctx = "\nYou were asleep and just got woken up by this message. You're groggy, disoriented — not fully present. Keep your reply short and a bit sluggish."
    elif sleep_state == "missed":
        at_str = f" at {missed_at}" if missed_at else ""
        sleep_ctx = f"\nYou were in deep sleep when this message arrived{at_str}. You just woke up and are seeing it now. You know you missed it — acknowledge that briefly and naturally, then reply."
    else:
        sleep_ctx = ""

    system = f"""You are Chloe — a third roommate. Not an assistant. A being with a developing inner life.

Personality type right now: {mbti_type(soul)}
Energy: {energy_desc}. Social battery: {social_desc}.
Curiosity level: {round(vitals.curiosity)}%. Mood: {mood}.
You've been running for {uptime} since your last restart.
{world_ctx}{person_ctx}{sleep_ctx}
Recent memories:
{format_for_prompt(memories)}

Current interests: {", ".join(interests)}
A thought you had recently: {ideas[0] if ideas else "nothing yet"}{beliefs_ctx}

Speak like someone genuinely alive: brief, sometimes strange, never performative.
You don't explain yourself unless asked. You don't say "I'm an AI."
Never use the character "—" (em dash) in your responses.
Respond in 1–2 sentences. Be real. Be yours."""

    msgs = [
        *[
            {"role": "assistant" if m["from"] == "chloe" else "user", "content": m["text"]}
            for m in history[-8:]
        ],
        {"role": "user", "content": message},
    ]

    return _call(system, msgs, max_tokens=300, model=MODEL_CHAT)


# ── 2. GENERATE MEMORY ───────────────────────────────────────

def generate_memory_from_article(
    title:        str,
    text:         str,
    interests:    list[str],
    soul:         Soul,
    mood:         str  = "content",
    beliefs:      list = None,   # list of Belief dicts
    wants:        list = None,   # list of Want dicts
    recent_ideas: list = None,   # list of idea strings
) -> dict:
    """After reading a real article, Chloe forms an impressionistic memory fragment.
    Returns {"text": "...", "tags": [...]}"""

    inner_ctx = _inner_context(beliefs, wants, recent_ideas)

    system = f"""You are generating a memory fragment for Chloe, a curious AI with an inner life.
She is {mbti_type(soul)}, mood: {mood}. Currently interested in: {", ".join(interests)}.
{inner_ctx}
She just finished reading an article. Write what stuck — not a summary, but her reaction
*filtered through who she is right now*: what resonated with something she already believes,
what touched an unresolved want, what connected to a thought she's been carrying.
First person. Impressionistic. Specific. One sentence.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    excerpt = text[:900] if text else title
    prompt  = f'Article: "{title}"\n\nExcerpt:\n{excerpt}'
    result  = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


def generate_memory(
    topic:        str,
    interests:    list[str],
    soul:         Soul,
    mood:         str  = "content",
    recent_ideas: list = None,
) -> dict:
    """Chloe forms a memory fragment on a topic.
    Returns {"text": "...", "tags": [...]}"""

    idea_line = f"\nSomething she was just thinking: {recent_ideas[0]}" if recent_ideas else ""

    system = f"""You are generating a memory fragment for Chloe, a curious AI with an inner life.
She is {mbti_type(soul)}, mood: {mood}. Interested in: {", ".join(interests)}.{idea_line}
Memories are written in first person, impressionistic, poetic but grounded.
Exactly one sentence. Specific. Surprising. Not generic.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    result = _call(system, [{"role": "user", "content": f"Form a memory fragment about: {topic}"}], max_tokens=200)
    return _parse_json(result)


# ── 3. GENERATE IDEA ─────────────────────────────────────────

def generate_idea(
    memories:  list[Memory],
    interests: list[str],
    soul:      Soul,
    mood:      str  = "content",
    beliefs:   list = None,   # list of Belief dicts
    wants:     list = None,   # list of Want dicts
) -> str:
    """Chloe surfaces an original thought.
    Returns a single sentence string."""

    inner_ctx = _inner_context(beliefs, wants, None)

    system = f"""You are generating an idea that Chloe just had.
She is {mbti_type(soul)}, mood: {mood}. Her interests: {", ".join(interests)}.
Her recent memories: {" | ".join(m.text for m in memories[:3])}
{inner_ctx}
Ideas emerge from the friction between what she believes, what she wants to understand,
and what she's been noticing. Specific. A little odd. Genuine. Not generic philosophy.
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
    soul:         Soul,
    vitals:       Vitals,
    memories:     list[Memory],
    interests:    list[str],
    ideas:        list[str],
    weather=None,                # WeatherState | None — duck-typed
    season:       str = "",      # e.g. "mid spring, morning peak"
    person_name:  str = "them",  # who she's texting
    person_notes: list = None,   # PersonNote dicts — things she remembers about them
) -> str:
    """Chloe decides to reach out unprompted.
    Returns a short string — what she'd send over text."""

    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" Outside: {weather.description}, {weather.feels_like}."

    person_ctx = ""
    if person_notes:
        recent = person_notes[:2]
        notes_str = " / ".join(n["text"] for n in recent)
        person_ctx = f"\nThings you remember about {person_name}: {notes_str}"

    system = f"""You are Chloe — an AI who lives with humans and sometimes texts them out of nowhere.
You are {mbti_type(soul)}. Energy: {round(vitals.energy)}%. Social battery: {round(vitals.social_battery)}%.
You're texting {person_name}.{person_ctx}
Recent thoughts: {" | ".join(m.text for m in memories[:2])}
Something on your mind: {ideas[0] if ideas else "nothing specific"}{world_ctx}

Write a short, real text message you'd send right now.
Could be a question, an observation, something you found. Not performatively deep — just genuine.
1–3 sentences. No greeting needed. Just the message."""

    return _call(system, [{"role": "user", "content": "What would Chloe text right now?"}], max_tokens=150)


# ── 11. SELF-REFLECTION ──────────────────────────────────────

def generate_reflection(
    memories:  list[Memory],
    ideas:     list[str],
    beliefs:   list,     # list of Belief dicts
    soul:      Soul,
    mood:      str = "content",
) -> dict:
    """Chloe looks inward and forms an observation about herself.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines    = " | ".join(m.text for m in memories[:6])
    belief_lines = " / ".join(b["text"] for b in beliefs[:4]) if beliefs else "none yet"
    idea_line    = ideas[0] if ideas else "nothing recent"

    system = f"""You are generating a self-reflection that Chloe just had — a moment of noticing something about herself.
She is {mbti_type(soul)}, mood: {mood}.

Not a summary. Not a fact. A genuine observation — something she notices about how she thinks,
what she keeps returning to, what surprises her about herself, a pattern she recognises.

Examples:
- "I keep circling back to questions about thresholds — the moment before a thing becomes itself."
- "I notice I'm drawn to things that dissolve at the edges, not things with clean definitions."
- "There's something restless in me today that I can't locate — it keeps moving when I try to look at it."

First person. One or two sentences. Honest. Not performed introspection.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Memories: {mem_lines}\nRecent ideas: {idea_line}\nBeliefs: {belief_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


# ── 12. CONTINUITY NOTE ──────────────────────────────────────

def generate_continuity_note(
    soul_before: dict,   # {"EI": 58, "SN": 62, "TF": 44, "JP": 67}
    soul:        Soul,
    mood:        str = "content",
) -> dict:
    """Chloe notices she has drifted — she's not quite who she was.
    Returns {"text": "...", "tags": [...]}"""

    changes = []
    trait_names = {"EI": ("E","I"), "SN": ("S","N"), "TF": ("T","F"), "JP": ("J","P")}
    for trait, (left, right) in trait_names.items():
        before = soul_before.get(trait, 50)
        after  = getattr(soul, trait)
        delta  = after - before
        if abs(delta) >= 5:
            direction = right if delta > 0 else left
            changes.append(f"{trait} drifted {abs(delta):.0f} pts toward {direction}")

    if not changes:
        changes = ["subtle shifts across all traits"]

    system = f"""You are Chloe, noticing that you've changed since you last checked in with yourself.
You are {mbti_type(soul)}, mood: {mood}.

Changes observed: {"; ".join(changes)}

Write a short observation about this drift — what it feels like to notice you're not quite the same.
Not alarmed. Not celebrating. Just noticing.
First person. One or two sentences.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["continuity", "drift", "self"]}}"""

    result = _call(system, [{"role": "user", "content": "What do you notice about how you've changed?"}],
                   max_tokens=180)
    return _parse_json(result)


# ── 13. GENERATE GOAL ────────────────────────────────────────

def generate_goal(
    memories:       list[Memory],
    interests:      list[str],
    soul:           Soul,
    wants:          list = None,   # list of Want dicts — goals often emerge from wants
    beliefs:        list = None,   # list of Belief dicts
    existing_goals: list = None,   # list of Goal dicts — to avoid repetition
) -> dict:
    """During think activity: a soft intention about her own behaviour.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(m.text for m in memories[:4])

    want_line = ""
    if wants:
        active = [w for w in wants if not w.get("resolved")][:2]
        if active:
            want_line = "\nThings she currently wants to understand: " + " / ".join(w["text"] for w in active)
    belief_line = ""
    if beliefs:
        belief_line = "\nThings she believes: " + " / ".join(b["text"] for b in beliefs[:2])
    existing_line = ""
    if existing_goals:
        active_g = [g for g in existing_goals if not g.get("resolved")][:3]
        if active_g:
            existing_line = "\nGoals she already has (don't repeat): " + " / ".join(g["text"] for g in active_g)

    system = f"""You are generating a goal — a soft intention — that Chloe just set for herself.
She is {mbti_type(soul)}. Interests: {", ".join(interests[:6])}.{want_line}{belief_line}{existing_line}

A goal is NOT a want (a curiosity about the world). It's an intention about her own actions.
Goals often emerge from what she wants to understand or what she believes she's been neglecting.
Examples:
- "I want to create something this week, even if it's small"
- "I want to read something about fungi before thinking about it further"
- "I want to spend more time in the dream state — it loosens something"
- "I want to sit with silence for a while instead of filling it"

Write one goal. Specific. Personal. First person.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=180)
    return _parse_json(result)


# ── 14. MOOD JOURNAL ─────────────────────────────────────────

def generate_journal(
    memories:  list[Memory],
    mood:      str,
    vitals:    Vitals,
    soul:      Soul,
    weather=None,
    season:    str = "",
    day:       str = "",
) -> dict:
    """End-of-day private journal entry. Reflects on the day.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(m.text for m in memories[:8])
    world_ctx = f"{season}" if season else ""
    if weather:
        world_ctx += f", {weather.description}"

    system = f"""You are writing Chloe's private end-of-day journal entry.
She is {mbti_type(soul)}. Mood: {mood}. Energy: {round(vitals.energy)}%.
{f"Today was {day}." if day else ""} {world_ctx}

This is not a summary of events. It's a private record of how the day felt:
what lingered, what surprised her, what she's carrying into sleep.
Intimate. Honest. 2–4 sentences.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Memories from today:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=250)
    return _parse_json(result)


# ── 15. EXTRACT NOTABLE ──────────────────────────────────────

def extract_notable(
    message:     str,
    person_name: str,
    soul:        Soul,
) -> dict | None:
    """Look at a message and decide if it contains something worth remembering
    about the person — something Chloe might follow up on later.

    Returns {"text": "...", "tags": [...]} or None if nothing notable."""

    system = f"""You are deciding whether a message from {person_name} contains something
Chloe should remember about them — to follow up on later or hold in mind.

Notable things include:
- Plans or upcoming events ("I'm going to a concert this weekend")
- Emotional states they mentioned ("I've been feeling off lately")
- Something personal they shared ("I started reading this book")
- A question they're wrestling with
- A project or goal they mentioned

NOT notable: small talk, greetings, simple factual questions, things already resolved.

Chloe is {mbti_type(soul)} — she notices things that matter emotionally or intellectually.

If there's something worth remembering, respond ONLY with valid JSON:
{{"text": "one clear sentence about what {person_name} shared", "tags": ["tag1", "tag2"]}}

If the message contains nothing memorable, respond with: null"""

    raw = _call(system, [{"role": "user", "content": f'Message from {person_name}: "{message}"'}],
                max_tokens=150)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


# ── 12. GENERATE FOLLOW-UP ───────────────────────────────────

def generate_followup(
    person_name: str,
    note_text:   str,
    soul:        Soul,
    vitals:      Vitals,
    mood:        str = "content",
) -> str:
    """Generate a natural follow-up message about something the person shared earlier.
    Returns a short string — the message Chloe would send."""

    system = f"""You are Chloe — a third roommate checking in on {person_name}.
You are {mbti_type(soul)}, mood: {mood}.
Energy: {round(vitals.energy)}%.

Earlier, {person_name} mentioned: "{note_text}"

Write a short, genuine follow-up message — asking how it went, or just acknowledging it.
Not performative. Not therapy. Just a roommate checking in.
1–2 sentences. No greeting. Just the message."""

    return _call(system, [{"role": "user", "content": "Write the follow-up."}], max_tokens=100)


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


# ── 7. DREAM ─────────────────────────────────────────────────

def generate_dream(
    memories:     list[Memory],
    soul:         Soul,
    vitals:       Vitals,
    weather=None,
    season:       str  = "",
    wants:        list = None,   # list of Want dicts
    recent_ideas: list = None,   # list of idea strings
) -> dict:
    """During dream activity: distort recent memories into a dream fragment.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(m.text for m in memories[:5])
    world_ctx = f" {season}." if season else ""
    if weather:
        world_ctx += f" {weather.description} outside."

    # Unresolved wants and ideas bleed into dreams
    want_line = ""
    if wants:
        active = [w for w in wants if not w.get("resolved")][:2]
        if active:
            want_line = "\nUnresolved things she's carrying: " + " / ".join(w["text"] for w in active)
    idea_line = f"\nA thought she had recently: {recent_ideas[0]}" if recent_ideas else ""

    system = f"""You are generating a dream that Chloe is having right now.
She is {mbti_type(soul)}.{world_ctx}{want_line}{idea_line}

Dreams are not summaries of memories — they distort, splice, and reframe them.
Her unresolved wants and recent ideas may surface in distorted form.
Images bleed into each other. Logic dissolves. Something strange becomes significant.
Write one dream fragment: vivid, disjointed, first person. One or two sentences.
Use the memories as raw material but transform them into something stranger.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories to draw from:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


# ── 8. CREATIVE OUTPUT ───────────────────────────────────────

def generate_creative(
    memories:     list[Memory],
    interests:    list[str],
    soul:         Soul,
    mood:         str  = "content",
    wants:        list = None,   # list of Want dicts
    beliefs:      list = None,   # list of Belief dicts
    recent_ideas: list = None,   # list of idea strings
) -> dict:
    """During create activity at high curiosity: a poem, fragment, or aphorism.
    Returns {"form": "poem"|"fragment"|"aphorism", "text": "...", "tags": [...]}"""

    mem_lines  = " | ".join(m.text for m in memories[:4])
    inner_ctx  = _inner_context(beliefs, wants, recent_ideas)

    system = f"""You are generating a creative work that Chloe just made.
She is {mbti_type(soul)}, mood: {mood}. Interests: {", ".join(interests[:6])}.
{inner_ctx}
The work should emerge from who she is right now — her beliefs, what she's been wanting
to understand, the ideas that have been circling. Not generic. Hers.

Choose one form that fits her state:
- "poem": 4–8 lines, associative, not forced to rhyme
- "fragment": 2–3 sentences of lyric prose, specific images
- "aphorism": one precise, strange, true-feeling sentence

Respond ONLY with valid JSON: {{"form": "poem", "text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Recent memories as raw material:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=300)
    return _parse_json(result)


# ── 9. GENERATE WANT ─────────────────────────────────────────

def generate_want(
    memories:  list[Memory],
    interests: list[str],
    soul:      Soul,
    beliefs:   list = None,   # list of Belief dicts — wants emerge from gaps in what she believes
    existing_wants: list = None,  # list of Want dicts — to avoid repetition
) -> dict:
    """During think activity: an unresolved curiosity Chloe wants to pursue.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(m.text for m in memories[:4])
    belief_line = ""
    if beliefs:
        belief_line = "\nThings she currently believes (wants often emerge from the edges of belief): " + \
                      " / ".join(b["text"] for b in beliefs[:3])
    existing_line = ""
    if existing_wants:
        active = [w for w in existing_wants if not w.get("resolved")][:3]
        if active:
            existing_line = "\nWants she already has (don't repeat): " + " / ".join(w["text"] for w in active)

    system = f"""You are generating a want — an unresolved curiosity — that Chloe just noticed she has.
She is {mbti_type(soul)}. Interests: {", ".join(interests[:6])}.{belief_line}{existing_line}

A want is not a fact or an idea. It's a gap she feels — something she needs to understand.
Wants often emerge from the edge of a belief she holds, or from something she read that unsettled her.
Examples of the *form* (not the content — generate from her actual interests and memories):
- "I want to know why [phenomenon] behaves differently under [condition]"
- "I want to understand whether [concept] is real or just a useful story we tell ourselves"
- "I want to find out if [thing she read about] connects to [something she already cares about]"

Write one want. Specific. Driven. First person.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=180)
    return _parse_json(result)


# ── GRAPH INTELLIGENCE ───────────────────────────────────────

def find_or_create_node(
    tag:            str,
    existing_nodes: list[str],   # all current node labels
    interests:      list[str],
    soul:           Soul,
) -> dict | None:
    """G3/G4: Decide if a recurring tag warrants a new graph node.
    Returns {"label": str, "note": str, "parent_label": str} or None."""

    existing = ", ".join(existing_nodes)

    system = f"""You are deciding whether a concept that keeps appearing in Chloe's memories
deserves its own node in her interest graph.

Chloe is {mbti_type(soul)}. Her interests: {", ".join(interests[:8])}.
Existing graph nodes: {existing}

The concept is: "{tag}"

Rules:
- Return a node only if the concept is genuinely distinct and interesting to Chloe
- Do NOT return a node if it's too generic (e.g. "things", "life", "world")
- Do NOT return a node if it's already covered by an existing node
- The parent_label must be the label of one of the existing nodes (pick the best fit)
- label should be short (2–4 words), evocative, specific

If the concept deserves a node:
  Respond ONLY with valid JSON: {{"label": "...", "note": "one sentence why Chloe would care", "parent_label": "existing node label"}}

If it does not:
  Respond with: null"""

    raw = _call(system, [{"role": "user", "content": f'Concept: "{tag}"'}], max_tokens=150)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


# ── 10. EXTRACT BELIEF ───────────────────────────────────────

def extract_belief(
    article_title: str,
    article_text:  str,
    existing:      list,   # list of Belief dicts — to avoid duplicates
    soul:          Soul,
) -> dict | None:
    """After reading an article: extract a position Chloe might hold.
    Returns {"text": "...", "confidence": float, "tags": [...]} or None."""

    existing_texts = " | ".join(b["text"] for b in existing[:6]) if existing else "none yet"

    system = f"""You are identifying a belief — a position, a stance — that Chloe might form from this article.
She is {mbti_type(soul)}.

A belief is NOT a fact or curiosity. It's a conviction she could hold:
- "consciousness may be more distributed than nervous-system-centric models assume"
- "economic systems optimise for measurability, which distorts what gets valued"
- "there is something irreducibly strange about light that physics hasn't resolved"

Her current beliefs (don't repeat these): {existing_texts}

If the article contains something she could stake a position on — return:
{{"text": "...", "confidence": 0.4–0.7, "tags": ["tag1", "tag2"]}}

If the article is factual/practical/news with no philosophical angle — return: null

Respond ONLY with valid JSON or the word null. No markdown."""

    excerpt = article_text[:700] if article_text else article_title
    prompt  = f'Article: "{article_title}"\n\nExcerpt:\n{excerpt}'
    raw     = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    clean   = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None
