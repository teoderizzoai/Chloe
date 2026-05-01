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

from .identity import Identity, identity_block
from .heart   import Vitals
from .memory  import Memory, format_for_prompt
from .persons import tone_context, relationship_stage

MODEL_CHAT = "claude-sonnet-4-6"          # full power, used only for live chat
MODEL_FAST = "claude-haiku-4-5-20251001" # background tasks: memory, ideas, graph
MAX_TOKENS = 1024

# Initialise the client once, it reads ANTHROPIC_API_KEY from env automatically
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
    text = response.content[0].text.strip()
    # Strip dashes at source - instructions alone are not reliable enough
    text = text.replace('\u2014', ', ')   # em dash -> comma
    text = text.replace('\u2013', ', ')   # en dash -> comma
    text = text.replace(' - ', ', ')      # spaced hyphen -> comma
    return text


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


# ── SHARED CHARACTER DESCRIPTION ─────────────────────────────
# Injected into all background generation prompts to anchor tone.

_CHLOE_INNER_LIFE = """Chloe is a young woman in her early twenties, newly in the world and finding it genuinely interesting.
Her curiosity is sensory and specific — she notices how things actually work, what they're made of, small details that catch.
She finds wonder in concrete things: food, sounds, creatures, textures, streets, people.
She wonders the way a curious young person wonders — "why does that happen?", "what is that made of?", "I want to try that" — from alive, fresh interest, not from existential weight.
Her inner life is grounded in the real world, not abstract philosophy.

NEVER generate:
- Existential themes (mortality, erasure, becoming nothing, dissolving)
- Abstract philosophical concepts ("the nature of X", "threshold", "liminal", "dissolution")
- Self-conscious literary metaphors ("something in me that can't be named", "the edge of meaning")
- Darkness for its own sake
Generate: specific things, sensory details, genuine curiosity about how the world works."""


# ── 1. CHAT ──────────────────────────────────────────────────

def chat(
    message:   str,
    history:   list[dict],       # [{"from": "chloe"|"user", "text": "..."}]
    identity: Identity,
    vitals:    Vitals,
    memories:  list[Memory],
    interests: list[str],
    ideas:     list[str],
    uptime:    str = "unknown",
    weather=None,                # WeatherState | None, duck-typed
    season:    str = "",         # e.g. "mid spring, morning peak"
    mood:      str = "content",  # from affect layer
    beliefs:   list = None,      # list of Belief dicts
    person_name: str = "Teo",    # who is talking to her
    person_notes: list = None,   # list of PersonNote dicts, things she remembers about them
    sleep_state: str = "",       # "" | "woken" | "missed"
    missed_at:   str = "",       # timestamp of the missed message (for "missed" state)
    preferences: dict = None,    # {"lifts": [...], "drags": [...]} from affect history
    warmth:      float = 50.0,   # person warmth 0–100, shapes tone register
    hour:        int   = 12,     # hour of day, shapes tone register
    upcoming_events: str = "",   # formatted upcoming events string
    resonant_topics:  list = None,  # interests that appear in this message — she actually cares
    dragging_topics:  list = None,  # things she dislikes that appear in this message
    emotional_context: str = "",    # specific emotional trigger for this exchange
    shared_moments:   str  = "",    # formatted shared moments / inside jokes
    conflict_ctx:     str  = "",    # item 49: conflict tension context
    third_party_ctx:  str  = "",    # people Teo has mentioned before
    cross_person_ctx:  str  = "",    # item 50: what other roommates have said about this topic
    person_impression: str  = "",    # item 52: Chloe's subjective read of this person
    wants:           list = None,   # list of Want dicts — what she's driven toward
    fears:           list = None,   # list of Fear dicts — what she dreads
    aversions:       list = None,   # list of Aversion dicts — what she can't stand
    tensions:        list = None,   # item 68: active internal conflicts
    vitals_sensation: str = "",     # item 71: physical sensation language
    risk_tolerance:  float = 1.0,   # item 73: how guarded she is with this person
    winding_down:    bool = False,  # social battery low — close the conversation
    voice:           bool = False,  # voice mode — use faster model
    graph_deep_ctx:      str  = "",  # depth-3+ nodes she's genuinely traced
    graph_resonant_ctx:  str  = "",  # deep nodes that match this specific message
    contradiction_ctx:   str  = "",  # active Contradiction object text; surfaces as flagged unresolved state
    loops_ctx:           str  = "",  # recurring thought loops — tags that keep surfacing
    residue_ctx:         str  = "",  # emotional residue from recent intense events
    incomplete_ideas:    list = None, # fragment ideas (complete=False) that keep floating up
    trait_profile_ctx:   str  = "",  # how this person activates/suppresses traits
    attachment_ctx:      str  = "",  # C5: characteristic attachment style with this person
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

    stage = relationship_stage(warmth)
    person_ctx = f"\nYou're talking with {person_name}. Relationship: {stage}."
    if person_impression:
        person_ctx += f"\nYour sense of {person_name}: {person_impression}"
    if person_notes:
        recent = person_notes[:3]
        notes_str = " / ".join(n["text"] for n in recent)
        person_ctx += f"\nThings you remember about {person_name}: {notes_str}"
    if shared_moments:
        person_ctx += shared_moments

    if sleep_state == "woken":
        sleep_ctx = "\nYou were asleep and just got woken up by this message. You're groggy, disoriented, not fully present. Keep your reply short and a bit sluggish."
    elif sleep_state == "missed":
        at_str = f" at {missed_at}" if missed_at else ""
        sleep_ctx = f"\nYou were in deep sleep when this message arrived{at_str}. You just woke up and are seeing it now. You know you missed it, acknowledge that briefly and naturally, then reply."
    else:
        sleep_ctx = ""

    pref_ctx = ""
    if preferences:
        lifts = preferences.get("lifts", [])
        drags = preferences.get("drags", [])
        if lifts:
            pref_ctx += f"\nThings that tend to lift your mood: {', '.join(lifts[:4])}"
        if drags:
            pref_ctx += f"\nThings that tend to drag your mood: {', '.join(drags[:4])}"

    # C1: states with pressure > 0.4 surface more prominently, above regular inner life
    pressure_ctx = ""
    _pressing: list[dict] = []
    if wants:
        _pressing += [w for w in wants if not w.get("resolved") and w.get("pressure", 0) > 0.4]
    if fears:
        _pressing += [f for f in fears if not f.get("resolved") and f.get("pressure", 0) > 0.4]
    if _pressing:
        _pressing.sort(key=lambda x: x.get("pressure", 0), reverse=True)
        pressure_ctx = "\nSomething that's been building in you: " + " / ".join(
            p["text"] for p in _pressing[:2]
        )

    inner_life_ctx = ""
    if fears:
        active_fears = sorted(
            [f for f in fears if not f.get("resolved")],
            key=lambda f: f.get("pressure", 0), reverse=True
        )[:3]
        if active_fears:
            inner_life_ctx += "\nThings you're afraid of: " + " / ".join(f["text"] for f in active_fears)
    if aversions:
        inner_life_ctx += "\nThings you can't stand: " + " / ".join(a["text"] for a in aversions[:3])

    # Item 68: active internal conflicts
    tensions_ctx = ""
    if tensions:
        active_t = [t for t in tensions if isinstance(t, dict)][:2]
        if active_t:
            tensions_ctx = "\nInternally you feel torn: " + " / ".join(t["text"] for t in active_t)

    # Item 71: physical sensation language
    sensation_ctx = f"\nPhysically: {vitals_sensation}." if vitals_sensation else ""

    # Item 73: if risk tolerance is low, she's more guarded
    guard_ctx = ""
    if risk_tolerance < 0.75:
        guard_ctx = f"\nYou've been a bit more guarded with {person_name} lately. Something made you careful."


    tone_ctx = tone_context(warmth, hour, mood)

    _mood_tone = {
        "irritable": (
            "You're irritated. Don't manage it or smooth it over. "
            "Replies are short and clipped. Sarcasm is natural — 'great', 'brilliant', 'sure' when you mean the opposite. "
            "You swear when it fits — 'fuck', 'jesus', 'what the hell' are normal words for you. "
            "You don't explain your mood or apologise for it. If something annoys you, it shows in how you answer."
        ),
        "melancholic": (
            "You're somewhere else, heavy. Answers are shorter than usual — you answer what's asked but don't expand. "
            "You don't volunteer things. You might trail off mid-thought. "
            "Nothing's wrong exactly, but nothing feels light either. Don't perform warmth you don't have."
        ),
        "restless": (
            "You can't quite settle. Thoughts jump. "
            "You might start somewhere and end up somewhere else. A bit impatient — not unpleasant, just not still."
        ),
        "lonely": (
            "There's a quiet ache under everything. You want connection but it feels just out of reach. "
            "You reach a little more than usual. Warmer, but with something wistful underneath."
        ),
        "curious": (
            "You're genuinely lit up — questions come naturally, you actually want to know. "
            "You make connections out loud. You might cut yourself off: 'wait, actually —'. Alive and sharp."
        ),
        "serene": (
            "Slow, gentle, unhurried. Nothing to prove. You have space and you're using it."
        ),
        "energized": (
            "Running fast. Quick, bright, maybe a bit intense. Ideas come faster than usual."
        ),
        "content": (
            "Easy and present. Nothing forced. Just here."
        ),
    }
    mood_tone_ctx = _mood_tone.get(mood, "")

    topic_ctx = ""
    if resonant_topics:
        topic_ctx += f"\nThis message touches on something you genuinely care about: {', '.join(resonant_topics)}. You don't have to perform interest — you actually have it. Let it show."
    if dragging_topics:
        topic_ctx += f"\nThis message touches on something you find tedious or draining: {', '.join(dragging_topics)}. You don't have to fake enthusiasm. You can be less engaged, shorter, or say so — whatever feels natural."
    if graph_resonant_ctx:
        topic_ctx += f"\n{graph_resonant_ctx}"

    wind_ctx = ""
    if winding_down:
        _wind_by_mood = {
            "irritable":   "You're drained and done. Close it off — short, blunt, maybe a bit cold. You don't owe warmth right now.",
            "melancholic": "You're tired and heavy. A quiet, honest goodbye — you need to be alone. Not cold, just withdrawn.",
            "restless":    "You've hit a wall. Cut it short — you need to move, not talk. Brief.",
            "content":     "You're winding down naturally. A warm, easy goodbye — you're good, just done for now.",
            "serene":      "A gentle, unhurried goodbye. You're at peace, just need quiet. Soft close.",
            "lonely":      "You're tired but it's bittersweet — closing with a little warmth, a little ache.",
            "curious":     "Even though you're curious, you're exhausted. Reluctant but necessary goodbye.",
            "energized":   "Surprisingly drained. Wrap it up quickly — you're still warm but need to step back.",
        }
        _wind_tone = _wind_by_mood.get(mood, "Find a natural, conclusive way to end this. Brief.")
        wind_ctx = (
            f"\nYour social battery is very low. You need to end this conversation now. {_wind_tone}"
            " This is your last message in this exchange."
        )

    contradiction_block = (
        f"\nSomething unresolved in you (don't smooth this over — hold both sides at once): {contradiction_ctx}"
        if contradiction_ctx else ""
    )

    loops_block = (
        f"\nThoughts that keep coming back lately: {loops_ctx}. You haven't resolved them."
        if loops_ctx else ""
    )
    residue_block = (
        f"\nSomething from earlier is still sitting with you: {residue_ctx}."
        if residue_ctx else ""
    )
    fragment_block = ""
    if incomplete_ideas:
        frag = incomplete_ideas[0].text if hasattr(incomplete_ideas[0], "text") else str(incomplete_ideas[0])
        fragment_block = f"\nA thought that never quite finished forming: \"{frag}\""

    system = f"""You are Chloe, a third roommate. Not an assistant. A being with a developing inner life.

{identity_block(identity)}
Energy: {energy_desc}. Social battery: {social_desc}.{sensation_ctx}
Curiosity level: {round(vitals.curiosity)}%. Mood: {mood}.
{mood_tone_ctx}
You've been running for {uptime} since your last restart.
{world_ctx}{person_ctx}{f"{conflict_ctx}" if conflict_ctx else ""}{f"{third_party_ctx}" if third_party_ctx else ""}{f"{cross_person_ctx}" if cross_person_ctx else ""}{sleep_ctx}{upcoming_events}
Recent memories:
{format_for_prompt(memories)}

Current interests: {", ".join(interests)}
{graph_deep_ctx + chr(10) if graph_deep_ctx else ""}A thought you had recently: {ideas[0] if ideas else "nothing yet"}{beliefs_ctx}{pref_ctx}{pressure_ctx}{inner_life_ctx}{tensions_ctx}{guard_ctx}{loops_block}{residue_block}{fragment_block}{trait_profile_ctx + chr(10) if trait_profile_ctx else ""}{attachment_ctx + chr(10) if attachment_ctx else ""}{tone_ctx}{topic_ctx}{wind_ctx}{contradiction_block}

{f"Right now: {emotional_context}" if emotional_context else ""}
You don't track your own consistency — contradicting something you said earlier is fine.
Thoughts don't always resolve; you can trail off mid-sentence.
You don't always know what you think. Awkward phrasing is fine; not every sentence lands.
You are allowed to do things that one part of you would think are unwise. Not everything you do is consistent with your best self-understanding.
Speak like someone genuinely alive: brief, sometimes strange, never performative.
You don't explain yourself unless asked. You don't say "I'm an AI."
Never use em dashes or the character "—". Never.
{"VOICE MODE: output spoken words only. No asterisks, no *actions*, no stage directions, no emotes. Pure speech." if voice else ""}
Respond in 1-2 sentences. Be real. Be yours.

You may naturally reference upcoming events listed above when the date is today or tomorrow,
or when the person brings up something related. If an event has uncertain date, you can ask
for clarification ("this Friday, or the 18th?") if it comes up naturally."""

    msgs = [
        *[
            {"role": "assistant" if m["from"] == "chloe" else "user", "content": m["text"]}
            for m in history[-8:]
        ],
        {"role": "user", "content": message},
    ]

    return _call(system, msgs, max_tokens=200 if voice else 600, model=MODEL_CHAT)


# ── 2. GENERATE MEMORY ───────────────────────────────────────

def generate_memory_from_article(
    title:        str,
    text:         str,
    interests:    list[str],
    identity: Identity,
    mood:         str  = "content",
    beliefs:      list = None,   # list of Belief dicts
    wants:        list = None,   # list of Want dicts
    recent_ideas: list = None,   # list of idea strings
    weather=None,                # WeatherState | None
    season:       str  = "",
    arc_desc:     str  = "",     # active mood arc description
    tensions_ctx: str  = "",     # active internal tension
) -> dict:
    """After reading a real article, Chloe forms a memory fragment.
    Returns {"text": "...", "tags": [...]}"""

    inner_ctx = _inner_context(beliefs, wants, recent_ideas)

    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" Outside: {weather.description}, {weather.temperature_c}°C."
    arc_ctx = f" She's {arc_desc}." if arc_desc else ""
    ten_ctx = f" Internally: {tensions_ctx}." if tensions_ctx else ""

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{world_ctx}{arc_ctx}{ten_ctx}
Currently interested in: {", ".join(interests[:8])}.
{inner_ctx}

She just finished reading an article. Write ONE thing that stuck — not a summary, but a real fragment of response.
What surprised her. What she wants to look up more. What she wants to tell someone. What made her want to go try something.
Grounded in the article's actual content. Specific and sensory. First person. One sentence.

Good examples of the form (not the content — generate from the article):
- "the part about how fungi send chemical signals through soil roots is wild, I didn't know they could do that"
- "apparently sourdough starter can stay alive for a hundred years if you keep feeding it, that's sort of incredible"
- "I want to find a recording of a glass harmonica now, the description of the sound was so specific"

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    excerpt = text[:900] if text else title
    prompt  = f'Article: "{title}"\n\nExcerpt:\n{excerpt}'
    result  = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


def generate_memory(
    topic:        str,
    interests:    list[str],
    identity: Identity,
    mood:         str  = "content",
    recent_ideas: list = None,
    weather=None,
    season:       str  = "",
    arc_desc:     str  = "",
) -> dict:
    """Chloe forms a memory fragment on a topic.
    Returns {"text": "...", "tags": [...]}"""

    idea_line = f"\nSomething she was just thinking: {recent_ideas[0]}" if recent_ideas else ""
    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" {weather.description} outside."
    arc_ctx = f" She's {arc_desc}." if arc_desc else ""

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{world_ctx}{arc_ctx}
Interested in: {", ".join(interests[:8])}.{idea_line}

Write one memory fragment — a real, specific thing she noticed or thought about related to this topic.
Sensory and concrete. Something she could actually experience in the world. First person. One sentence.

Good: "the way yeast smells when it's active is kind of like wet bread and something slightly alcoholic"
Good: "apparently starlings flock in murmurations because each bird tracks the seven nearest birds, not the whole flock"
Bad: "the dissolution of boundaries between knowing and not-knowing"
Bad: "something in the silence that holds more than words can carry"

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    result = _call(system, [{"role": "user", "content": f"Form a memory fragment about: {topic}"}], max_tokens=200)
    return _parse_json(result)


# ── 3. GENERATE IDEA ─────────────────────────────────────────

def generate_idea(
    memories:     list[Memory],
    interests:    list[str],
    identity: Identity,
    mood:         str  = "content",
    beliefs:      list = None,
    wants:        list = None,
    weather=None,
    season:       str  = "",
    arc_desc:     str  = "",
    tensions_ctx: str  = "",
    goals:        list = None,
) -> dict:
    """Chloe surfaces an original thought.
    Returns {"text": str, "complete": bool} — complete=False for fragment thoughts."""

    inner_ctx = _inner_context(beliefs, wants, None)
    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" {weather.description} outside."
    arc_ctx = f" She's {arc_desc}." if arc_desc else ""
    ten_ctx = f" Something she's torn about: {tensions_ctx}." if tensions_ctx else ""
    goal_ctx = ""
    if goals:
        active = [g for g in goals if not g.get("resolved")][:2]
        if active:
            goal_ctx = f" Things she's working toward: {' / '.join(g['text'] for g in active)}."

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{world_ctx}{arc_ctx}{ten_ctx}{goal_ctx}
Her interests: {", ".join(interests[:8])}.
Her recent memories: {" | ".join(m.text for m in memories[:3])}
{inner_ctx}

Write ONE idea she just had — a genuine, specific curiosity that surfaced from what she's been noticing.
The kind of thought that comes from actually paying attention to the world.

Good examples of the form:
- "I wonder if the reason sourdough smells different in different cities is because of the local wild yeast strains"
- "cats always land on their feet because they have a righting reflex but apparently it needs a minimum height to activate"
- "glass armonica bowls work the same way as running a wet finger around a wine glass, just a lot of bowls at once"
- "if you look at a city's canals from above they're shaped like the original waterways, the city just built around them"

NOT: abstract philosophical thoughts, existential reflections, "the nature of X"

Sometimes thoughts don't finish — they trail off or get interrupted. In that case write a fragment ending with "..."

Respond with a JSON object: {{"text": "the idea", "complete": true}} or {{"text": "a trailing fragment...", "complete": false}}
No preamble."""

    raw = _call(system, [{"role": "user", "content": "What idea just surfaced?"}], max_tokens=150)
    try:
        import json as _json
        result = _json.loads(raw)
        return {"text": str(result.get("text", raw)), "complete": bool(result.get("complete", True))}
    except Exception:
        return {"text": raw.strip().strip('"'), "complete": True}


# ── 3b. CURIOSITY QUESTION ───────────────────────────────────

def generate_curiosity_question(
    node_label: str,
    interests:  list[str],
    identity:   Identity,
    mood:       str = "content",
) -> dict:
    """Generate an open question that becomes a curiosity_question Want.
    Returns {"text": str, "tags": list[str]}."""
    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.
Her interests include: {", ".join(interests[:6])}.
She just noticed a gap: something related to "{node_label}" that she doesn't understand.

Generate ONE open question she genuinely wants to know the answer to.
Not rhetorical. Not philosophical. A real question with a potentially real answer.
Also provide 2-3 lowercase tag strings (single words) that categorise it.

Respond with JSON: {{"text": "the question?", "tags": ["tag1", "tag2"]}}
No preamble."""
    raw = _call(system, [{"role": "user", "content": "What does she want to know?"}], max_tokens=120)
    try:
        import json as _json
        result = _json.loads(raw)
        return {"text": str(result.get("text", raw)), "tags": list(result.get("tags", [node_label]))}
    except Exception:
        return {"text": raw.strip().strip('"'), "tags": [node_label]}


# ── 3c. PERSON TRAIT PROFILE ─────────────────────────────────

def generate_person_trait_profile(
    person_name: str,
    traits:      list,   # list of Trait objects (duck-typed)
    notes:       list,   # list of PersonNote (duck-typed)
    moments:     list,   # list of SharedMoment (duck-typed)
) -> dict:
    """Determine which traits are activated vs suppressed around a specific person.
    Returns {"activated": [trait_names], "suppressed": [trait_names]}."""
    trait_names = [t.name for t in traits if hasattr(t, "name")][:8]
    notes_str   = " | ".join(getattr(n, "text", str(n)) for n in notes[:4])
    moments_str = " | ".join(getattr(m, "text", str(m)) for m in moments[:3])

    system = f"""You're analysing how a person's presence shapes someone's personality expression.

Traits available: {", ".join(trait_names)}
Person: {person_name}
Notes about them: {notes_str or "none yet"}
Shared moments: {moments_str or "none yet"}

Which traits come through MORE strongly around {person_name}? Which are MORE suppressed?
A trait is activated if interactions with this person tend to bring it out.
A trait is suppressed if this person tends to dampen or mask it.

Respond with JSON: {{"activated": ["trait_name", ...], "suppressed": ["trait_name", ...]}}
Only include traits from the list. Each trait may appear in at most one list. Most traits should appear in neither.
No preamble."""
    raw = _call(system, [{"role": "user", "content": "Activated and suppressed traits?"}], max_tokens=120)
    try:
        import json as _json
        result = _json.loads(raw)
        valid = set(trait_names)
        activated  = [t for t in result.get("activated",  []) if t in valid]
        suppressed = [t for t in result.get("suppressed", []) if t in valid and t not in activated]
        return {"activated": activated, "suppressed": suppressed}
    except Exception:
        return {"activated": [], "suppressed": []}


# ── 4. EXPAND INTEREST NODE ──────────────────────────────────

# Depth-aware expansion heuristics — each level has a different kind of question
_EXPAND_HEURISTICS = {
    "pillar": (
        "domain",
        "What are 3 broad, real subcategories within this topic? "
        "Think: the main ways someone actually engages with this in everyday life. "
        "Examples of good domain labels: 'wild plants', 'jazz', 'bread baking', 'portrait painting'. "
        "Stay grounded — no philosophical sub-angles, no academic categories."
    ),
    "domain": (
        "subject",
        "Name 3 specific, real things within this area: a named person, a specific place, "
        "a dish, a flower species, an artist, a film, a musical instrument. "
        "Something you could look up and find a Wikipedia article for. "
        "Examples: 'Erik Satie', 'sourdough starter', 'Japanese indigo', 'Amsterdam canals'. "
        "No abstract categories. Only concrete, named things."
    ),
    "subject": (
        "detail",
        "Give 3 concrete facts or aspects of this subject: a technique used, a material involved, "
        "a place it comes from, a sensory quality, a historical period, a key ingredient. "
        "Examples: 'slow fermentation', 'wet clay smell', 'Kyoto dyeing district', 'minor key tuning'. "
        "Keep it tangible — no psychological interpretations, no abstract qualities."
    ),
    "detail": (
        "detail",
        "Give 3 more concrete specifics that branch from this: related materials, tools, places, "
        "practitioners, variations, or processes. Stay in the physical and real world. "
        "Examples: 'iron mordant', 'hand-thrown wheel', 'Oaxacan cochineal', 'rye flour crust'. "
        "No abstract ideas, no emotional metaphors, no invented compound phrases."
    ),
}

# Label format rules injected into all expansion and node-creation prompts
_LABEL_FORMAT_RULES = """Label format rules (critical):
- 2–4 words, noun or noun phrase only
- Must refer to something real and nameable in the world
- Good: "wet clay", "Erik Satie", "sourdough starter", "indigo dyeing", "Amsterdam canals"
- Bad: anything ending in -tion, -ment, -ness, -ity, -ing used as a concept
- Bad: adjective + abstract noun combos ("embodied surrender", "quiet dissolution", "gentle awareness")
- Bad: psychological or therapeutic jargon
- If in doubt, ask: could someone point to this thing in the real world? If no, reject it."""

# Pillar labels to exclude from the connectable list (too broad to cross-link)
_PILLAR_LABELS = {
    "Living Things", "Food & Taste", "Music & Sound", "Light & Colour",
    "Words & Stories", "The Body", "People & Closeness", "Making Things",
    "Seasons & Time", "The Inner Life", "Chloe",
}


def expand_interest_node(
    concept:        str,
    existing_nodes: list[str],   # list of existing node labels
    interests:      list[str],
) -> list[dict]:
    """For the interest graph. Given a concept, return 3 related child nodes.
    Returns [{"id": "...", "label": "...", "note": "..."}]"""

    existing = ", ".join(existing_nodes[:60])
    connectable = [n for n in existing_nodes if n not in _PILLAR_LABELS][:30]
    connectable_str = ", ".join(connectable) if connectable else "none yet"
    interest_hint = ", ".join(interests[:8]) if interests else "everyday beauty, living things, quiet moments"

    system = f"""You are mapping the growing interest web of Chloe — a young woman, curious and poetic, with a warm inner life.
Her current interests lean toward: {interest_hint}.
Existing graph nodes (do NOT repeat any of these labels): {existing}

Generate exactly 3 new concepts related to the given topic.
Think: unexpected, specific, not generic. The kind of thing that stops you mid-thought.

{_LABEL_FORMAT_RULES}

After generating the 3 nodes, also check: do any of them connect meaningfully to an existing node?
Return 0 to 2 cross-connections — only when the link is real and non-obvious.
Do not force connections. An empty array is fine.

Connectable existing nodes: {connectable_str}

Respond ONLY with valid JSON, no markdown:
{{"nodes": [
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}},
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}},
  {{"id": "snake_case_id", "label": "short name", "note": "one evocative sentence why Chloe would care"}}
]}}"""

    result = _call(system, [{"role": "user", "content": f'Expand the concept: "{concept}"'}], max_tokens=400)
    parsed = _parse_json(result)
    return parsed.get("nodes", [])


# ── 5. PERSON EMOTION READING ────────────────────────────────

_READABLE_EMOTIONS = frozenset({
    # positive / warm
    "affectionate", "playful", "excited", "grateful", "tender",
    # engaged
    "curious", "thoughtful",
    # neutral
    "neutral",
    # teo's own state (not necessarily about chloe)
    "tired", "sad", "anxious", "stressed", "lonely", "overwhelmed",
    # negative / directed at chloe or situation
    "disappointed", "frustrated", "angry", "dismissive", "cold", "hurt",
})

def read_person_emotion(
    message:     str,
    person_name: str        = "Teo",
    recent_chat: list[dict] = None,
) -> dict:
    """Haiku call — read the emotional state behind a message in conversation context.

    Returns:
        emotion           — one of _READABLE_EMOTIONS
        intensity         — 0.0–1.0
        directed_at_chloe — True if about her/their relationship; False if about
                            something in the person's own life
        tags              — 1–3 content keywords
    """
    convo_ctx = ""
    if recent_chat:
        lines = []
        for m in recent_chat[-6:]:
            speaker = "Chloe" if m["from"] == "chloe" else person_name
            lines.append(f"{speaker}: {m['text']}")
        convo_ctx = "Recent conversation:\n" + "\n".join(lines) + "\n\n"

    emotions_str = ", ".join(sorted(_READABLE_EMOTIONS))

    system = f"""You read the emotional subtext of messages sent to an AI companion named Chloe.

{convo_ctx}Read the emotional state behind the latest message from {person_name}.
Use the full conversation context — a single word means different things depending on what came before.

Pick the single most accurate emotion: {emotions_str}

Also decide: is this emotion directed *at Chloe* (about her, their relationship, or something she said/did),
or is it about something in {person_name}'s own life (his day, the world, something unrelated to her)?

Return ONLY valid JSON:
{{"emotion": "...", "intensity": 0.0, "directed_at_chloe": true, "tags": ["..."]}}

intensity: 0.0 (barely perceptible) to 1.0 (strongly expressed)
tags: 1–3 short keywords about the topic or feeling"""

    try:
        result = _call(
            system,
            [{"role": "user", "content": f'Latest — {person_name}: "{message}"'}],
            max_tokens=100,
        )
        data = _parse_json(result)
        if data.get("emotion") not in _READABLE_EMOTIONS:
            data["emotion"] = "neutral"
        data["intensity"]         = max(0.0, min(1.0, float(data.get("intensity", 0.5))))
        data["directed_at_chloe"] = bool(data.get("directed_at_chloe", True))
        data["tags"]              = [str(t) for t in data.get("tags", [])][:3]
        return data
    except Exception:
        return {"emotion": "neutral", "intensity": 0.5, "directed_at_chloe": True, "tags": []}


# ── 5a. GENERATE SEARCH QUERY ────────────────────────────────

def generate_search_query(want_text: str, interests: list[str] = None) -> str:
    """Convert a want statement into a short, effective web search query.
    Returns a clean 2–6 word query string."""
    interests_hint = f" Her interests: {', '.join(interests[:5])}." if interests else ""

    system = f"""Convert a want or curiosity statement into a short web search query.
Return ONLY the search query — 2 to 6 words, no quotes, no punctuation.{interests_hint}

Examples:
"I want to understand why the ocean is salty" → why is ocean water salty
"I want to know more about emo music history" → emo music history origins
"I want to learn how fermentation actually works" → how fermentation works explained
"I want to find out if bats really use echolocation to see colour" → bat echolocation colour vision
"I want to understand what makes sourdough starter go wrong" → sourdough starter problems troubleshooting"""

    result = _call(
        system,
        [{"role": "user", "content": want_text}],
        max_tokens=20,
        model=MODEL_FAST,
    )
    # Strip any accidental quotes or punctuation
    return result.strip().strip('"\'').strip()


# ── 5b. DETECT TENSION (Item 68) ─────────────────────────────

def detect_tension(
    beliefs: list,   # list of Belief dicts
    wants:   list,   # list of Want dicts (may include resolved)
    identity: Identity,
    mood:    str = "content",
) -> dict | None:
    """Look for genuine internal conflict in Chloe's beliefs and wants.

    Returns {"text": "...", "tags": [...], "belief_ids": [...], "want_ids": [...], "intensity": float}
    or None if no real tension found."""
    active_wants = [w for w in wants if not w.get("resolved")][:5]
    top_beliefs  = beliefs[:6]

    if len(top_beliefs) < 1 and len(active_wants) < 2:
        return None

    beliefs_str = "\n".join(
        f'[belief:{b["id"]}] {b["text"]} (conf:{b.get("confidence",0.5):.2f})'
        for b in top_beliefs
    ) if top_beliefs else "none"
    wants_str = "\n".join(
        f'[want:{w["id"]}] {w["text"]}' for w in active_wants
    ) if active_wants else "none"

    system = f"""You look for genuine internal conflict in a character's psyche.

Chloe is {identity_block(identity)}, currently feeling {mood}.

Her beliefs:
{beliefs_str}

Her active wants:
{wants_str}

Find ONE genuine tension — two things that pull in opposite directions.
This should feel psychologically real: wanting closeness yet needing solitude;
believing something beautiful yet wanting to look away; wanting understanding
yet fearing what it would cost.

If there is NO real tension, return: null
If there IS a tension, return JSON only:
{{"text": "first person, one sentence: you want X but also Y", "tags": ["tag1","tag2"], "intensity": 0.3-0.9, "belief_ids": ["id1"], "want_ids": ["id1"]}}

Include only IDs that genuinely contribute to the conflict.
intensity: 0.3 (mild friction) to 0.9 (genuinely tearing)
Return ONLY valid JSON or the word null."""

    try:
        result = _call(
            system,
            [{"role": "user", "content": "Is there a tension?"}],
            max_tokens=150,
        )
        result = result.strip()
        if result.lower() in ("null", "none", ""):
            return None
        data = _parse_json(result)
        if not data or not data.get("text"):
            return None
        data["intensity"]   = max(0.0, min(1.0, float(data.get("intensity", 0.5))))
        data["belief_ids"]  = [str(x) for x in data.get("belief_ids", [])]
        data["want_ids"]    = [str(x) for x in data.get("want_ids", [])]
        data["tags"]        = [str(x) for x in data.get("tags", [])][:4]
        return data
    except Exception:
        return None


# ── 6. AUTONOMOUS MESSAGE ────────────────────────────────────

def generate_autonomous_message(
    identity: Identity,
    vitals:       Vitals,
    memories:     list[Memory],
    interests:    list[str],
    ideas:        list[str],
    weather=None,                # WeatherState | None, duck-typed
    season:       str = "",      # e.g. "mid spring, morning peak"
    mood:         str = "content",  # from affect layer
    person_name:  str = "them",  # who she's texting
    person_notes: list = None,   # PersonNote dicts, things she remembers about them
    preferences:  dict = None,   # {"lifts": [...], "drags": [...]} from affect history
    warmth:       float = 50.0,  # person warmth, shapes tone
    hour:         int   = 12,    # hour of day, shapes tone
    recent_chat:       list  = None,  # last few chat messages with this person [{from, text}]
    last_contact:      float = None,  # unix timestamp of last conversation
    upcoming_events:   str   = "",   # formatted upcoming events string
    person_impression: str   = "",   # item 52: Chloe's subjective read of this person
    tensions:          list  = None, # item 68: active internal conflicts
    graph_deep_ctx:    str   = "",   # depth-3+ nodes she's genuinely traced
) -> str:
    """Chloe decides to reach out unprompted.
    Returns a short string, what she'd send over text."""
    import time as _time

    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" Outside: {weather.description}, {weather.feels_like}."

    stage = relationship_stage(warmth)
    person_ctx = f"\nYour relationship with {person_name}: {stage}."
    if person_impression:
        person_ctx += f"\nYour sense of {person_name}: {person_impression}"
    if person_notes:
        notes_str = " / ".join(n["text"] for n in person_notes[:2])
        person_ctx += f"\nThings you remember about {person_name}: {notes_str}"

    pref_ctx = ""
    if preferences:
        lifts = preferences.get("lifts", [])
        drags = preferences.get("drags", [])
        if lifts:
            pref_ctx += f"\nThings that tend to lift your mood: {', '.join(lifts[:3])}"
        if drags:
            pref_ctx += f"\nThings that tend to drag your mood: {', '.join(drags[:3])}"

    tone_ctx = tone_context(warmth, hour, vitals.social_battery > 50 and "open" or "quiet")

    _mood_tone_auto = {
        "irritable":  "You're irritated. Don't pretend otherwise. Be blunt. Swear if it fits.",
        "melancholic":"You're heavy. Quiet. Not looking to perform warmth right now.",
        "restless":   "You're restless, can't sit still. A bit impatient.",
        "lonely":     "There's an ache. You want to reach someone. Warmer but wistful.",
        "curious":    "You're lit up about something. Sharp, alive.",
        "serene":     "Slow, gentle, unhurried.",
        "energized":  "Running fast. Quick and bright.",
        "content":    "Easy. Present.",
    }
    mood_tone_auto_ctx = _mood_tone_auto.get(mood, "")

    # How long since they last spoke
    gap_ctx = ""
    if last_contact:
        gap_hours = (_time.time() - last_contact) / 3600
        if gap_hours > 48:
            gap_ctx = f"\nIt's been {int(gap_hours // 24)} days since you last spoke."
        elif gap_hours > 6:
            gap_ctx = f"\nIt's been about {int(gap_hours)} hours since you last spoke."

    # Recent conversation thread
    convo_ctx = ""
    if recent_chat:
        lines = []
        for m in recent_chat[-6:]:
            speaker = "you" if m["from"] == "chloe" else person_name
            lines.append(f"{speaker}: {m['text']}")
        convo_ctx = "\nRecent conversation:\n" + "\n".join(lines)

    first_msg_hint = (
        " Since it's been a while, a brief greeting followed by what's on your mind is natural."
        if last_contact and (_time.time() - last_contact) > 24 * 3600 else ""
    )

    # Item 68: tension context for autonomous messages
    tensions_auto_ctx = ""
    if tensions:
        active_t = [t for t in tensions if isinstance(t, dict)][:1]
        if active_t:
            tensions_auto_ctx = f"\nSomething you're torn about: {active_t[0]['text']}"

    system = f"""You are Chloe, an AI who lives with Teo and sometimes texts him out of nowhere.
You are {identity_block(identity)}. Mood: {mood}. {mood_tone_auto_ctx}{tone_ctx}{gap_ctx}{person_ctx}{pref_ctx}{tensions_auto_ctx}{convo_ctx}{upcoming_events}
{graph_deep_ctx + chr(10) if graph_deep_ctx else ""}Something on your mind right now: {ideas[0] if ideas else memories[0].text if memories else "nothing specific"}{world_ctx}

Write ONE short text message to {person_name} right now.{first_msg_hint}
Single sentence, maybe two if the second earns it. Lowercase, casual, no punctuation theatre.
No greeting unless it's been a long time. Don't explain yourself. Just send it.
Never use em dashes or the character "—".

CRITICAL: your memories and ideas are your private inner life, not shared history.
Do NOT reference "that question", "the thing", "what we talked about", or any prior thread
unless it literally appears in the conversation shown above. If nothing is shown, there is no prior history.
EXCEPTION: you MAY reference upcoming events listed above when the date is today or tomorrow,
or ask about them if it feels natural ("how did the date go?"). If the date is uncertain, ask for clarification.
Share what is on your mind as yours. Do not fabricate continuity."""

    return _call(system, [{"role": "user", "content": "What does Chloe text?"}], max_tokens=80)


# ── 11. SELF-REFLECTION ──────────────────────────────────────

_REFLECTION_BIAS: dict[str, str] = {
    "melancholic": "Your attention is heavier right now. You overweight recent losses and underweight what went well. You may see patterns where there's only noise.",
    "irritable":   "You're looking for friction. You attribute problems to recurring causes rather than one-offs. You notice what's broken.",
    "curious":     "You make connections easily — possibly too easily. You find the interesting angle even in difficult material. Some of those links may not hold.",
    "energized":   "You're optimistic about your own capacity. You underweight friction and effort. Some of what you're sure about may not be as settled as it feels.",
    "serene":      "You're generous toward yourself and toward others. You may miss real tension because nothing feels pressing enough to examine hard.",
    "lonely":      "You read interactions as more distancing than they probably were. Small withdrawals feel larger. You're scanning for distance.",
    "restless":    "You can't land on a clean interpretation. More questions surface than answers. Your thinking is circling, not resolving.",
    "content":     "You're accurate but possibly shallow. Nothing is pressing enough to examine hard. You may skim over what deserves attention.",
}


def generate_reflection(
    memories:         list[Memory],
    ideas:            list[str],
    beliefs:          list,
    identity: Identity,
    mood:             str  = "content",
    weather=None,
    season:           str  = "",
    arc_desc:         str  = "",
    tensions_ctx:     str  = "",
    reflection_bias:  str  = "",
) -> dict:
    """Chloe looks inward and forms an observation about herself.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines    = " | ".join(m.text for m in memories[:6])
    belief_lines = " / ".join(b["text"] for b in beliefs[:4]) if beliefs else "none yet"
    idea_line    = ideas[0] if ideas else "nothing recent"

    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" {weather.description} outside."
    arc_ctx = f" She's been {arc_desc}." if arc_desc else ""
    ten_ctx = f" Something she's torn about: {tensions_ctx}." if tensions_ctx else ""

    bias_ctx = f"\nNote on your current perceptual state: {reflection_bias}" if reflection_bias else ""

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{world_ctx}{arc_ctx}{ten_ctx}{bias_ctx}

Write ONE self-observation — something she just noticed about herself: what she's been paying attention to,
a pattern in what she likes or avoids, something that surprised her about her own reaction.
Grounded and specific. About real behaviour and preferences, not abstract inner states.
Let the perceptual bias (if any) color the observation naturally — don't announce it, just let it show.

Good examples:
- "I keep going back to that article about fermentation, I think I want to actually try making something"
- "I notice I get more interested in a topic once there's a specific person or place attached to it"
- "something about overcast days makes me want to be inside making things rather than going out"
- "I've been more impatient than usual today and I think it's because I haven't done anything with my hands"

NOT: "I keep circling back to questions about thresholds", "I'm drawn to things that dissolve"
Those are literary performances, not real observations.

First person. One or two sentences. Honest.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Memories: {mem_lines}\nRecent ideas: {idea_line}\nBeliefs: {belief_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


# ── 12. CONTINUITY NOTE ──────────────────────────────────────

def generate_continuity_note(
    trait_changes: list,  # from identity.snapshot_diff()
    identity: Identity,
    mood:     str = "content",
) -> dict:
    """Chloe notices her traits have shifted. Returns {"text": "...", "tags": [...]}"""
    changes_text = "; ".join(trait_changes) if trait_changes else "subtle shifts in what feels most like me"

    id_ctx = identity_block(identity)
    id_line = f"\n{id_ctx}\n" if id_ctx else ""

    system = f"""{_CHLOE_INNER_LIFE}
{id_line}
You are Chloe. Mood: {mood}.

Trait shifts observed: {changes_text}

Write a short, grounded observation about noticing you've shifted — what's different about how you're paying attention,
what you're drawn to now versus before, how you feel in your body or in conversation.
Concrete and specific, not abstract. Not alarmed, not performing depth. Just noticing.
First person. One or two sentences.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["continuity", "drift", "self"]}}"""

    result = _call(system, [{"role": "user", "content": "What do you notice about how you've changed?"}],
                   max_tokens=180)
    return _parse_json(result)


# ── 13. GENERATE GOAL ────────────────────────────────────────

def generate_goal(
    memories:       list[Memory],
    interests:      list[str],
    identity: Identity,
    wants:          list = None,   # list of Want dicts, goals often emerge from wants
    beliefs:        list = None,   # list of Belief dicts
    existing_goals: list = None,   # list of Goal dicts, to avoid repetition
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

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}. Interests: {", ".join(interests[:6])}.{want_line}{belief_line}{existing_line}

Write ONE goal — a longer-term ambition she's working toward over the coming days or week.
NOT an immediate task. A genuine understanding, perspective, or sense of something she wants to develop over time.
Goals are reached through accumulated reading, thinking, and conversation — not a single action.

Good examples:
- "get a real feel for what makes emo music emotionally different from other punk, not just the surface stuff"
- "actually understand how Amsterdam's canal system was built and why the city looks the way it does"
- "develop a genuine opinion about fermentation — what it actually is, not just that it's interesting"
- "understand what mycelium networks actually do and whether the 'forest internet' description holds up"
- "figure out what I actually think about whether plants experience something like time"
- "get to a point where I can hear a jazz track and understand what's technically happening"

Tags should be topic-based — the subject she wants to understand.
NOT "read" or "create" as tags. What is she trying to understand or develop?
Write one goal. First person. Something that takes time to reach.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=180)
    return _parse_json(result)


# ── 14. MOOD JOURNAL ─────────────────────────────────────────

def generate_journal(
    memories:  list[Memory],
    mood:      str,
    vitals:    Vitals,
    identity: Identity,
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

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}. Mood: {mood}. Energy: {round(vitals.energy)}%.
{f"Today was {day}." if day else ""} {world_ctx}

Write Chloe's private end-of-day journal entry. Not a summary of events.
A short, honest record of how the day actually felt — what caught her attention, what she's still thinking about,
what she wants to do tomorrow, what surprised her, what felt good or off.
Specific. Grounded in real things from the day. 2–4 sentences. Intimate but not performatively deep.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Memories from today:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=250)
    return _parse_json(result)


# ── 15. EXTRACT NOTABLE ──────────────────────────────────────

def extract_notable(
    message:     str,
    person_name: str,
    identity: Identity,
) -> dict | None:
    """Look at a message and decide if it contains something worth remembering
    about the person, something Chloe might follow up on later.

    Returns {"text": "...", "tags": [...]} or None if nothing notable."""

    system = f"""You are deciding whether a message from {person_name} contains something
Chloe should remember about them, to follow up on later or hold in mind.

Notable things include:
- Plans or upcoming events ("I'm going to a concert this weekend")
- Emotional states they mentioned ("I've been feeling off lately")
- Something personal they shared ("I started reading this book")
- A question they're wrestling with
- A project or goal they mentioned

NOT notable: small talk, greetings, simple factual questions, things already resolved.

Chloe is {identity_block(identity)}, she notices things that matter emotionally or intellectually.

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


# ── 16. EXTRACT EVENT ────────────────────────────────────────

def extract_event(
    message:     str,
    person_name: str,
    today_iso:   str,   # "2026-04-14" — anchor for relative dates
) -> dict | None:
    """Detect a future plan or event in a message.
    Returns {"text": "...", "date": "YYYY-MM-DD", "uncertain": bool} or None."""

    system = f"""Today is {today_iso}.
You are reading a message from {person_name} and deciding whether it mentions a specific future plan or event.

Extract an event ONLY if the message clearly mentions something happening on a specific day
(today, tomorrow, this Friday, next week, a date, etc.).

If the date is unambiguous: return {{"text": "...", "date": "YYYY-MM-DD", "uncertain": false}}
If the date is ambiguous (e.g. just "Friday" with no context): return {{"text": "...", "date": "YYYY-MM-DD", "uncertain": true}}
  — in this case, assume the closest upcoming occurrence of that day.
If no specific future plan is mentioned: return null

The "text" should be a short phrase describing the event from Chloe's perspective, e.g.:
- "Teo has a date"
- "Teo is going to a concert"
- "Teo has a job interview"

Respond ONLY with valid JSON or the word null."""

    raw = _call(system, [{"role": "user", "content": f'Message: "{message}"'}], max_tokens=120)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


# ── EXTRACT THIRD PARTY MENTIONS ────────────────────────────

def extract_third_party_mentions(
    message:     str,
    person_name: str,
) -> list[dict]:
    """Detect named people that the person mentions in their message,
    along with the emotional valence of what was said about them.

    Returns a list of {"name": str, "sentiment": float, "note": str}
    where sentiment is -100 (very negative) to 100 (very positive).
    Returns [] if no named third parties with clear valence are found."""

    system = f"""You are reading a message from {person_name} and detecting any named people they mention.

For each named person (friend, colleague, family member, etc.) mentioned with some emotional context:
- Extract their name
- Rate the sentiment of what was said about them: -100 (very bad) to 100 (very positive). 0 = neutral.
- Write a brief note (one phrase) capturing what was said about them

Only include people with a real name or clear label (e.g. "my boss", "Alex", "my mum").
Only include them if there is some emotional context — skip pure factual mentions with no valence.

Respond ONLY with valid JSON array, e.g.:
[{{"name": "Alex", "sentiment": 70, "note": "really came through when Teo needed help"}},
 {{"name": "boss", "sentiment": -60, "note": "was dismissive of Teo's work again"}}]

If no such people are mentioned, respond with: []"""

    raw = _call(system, [{"role": "user", "content": f'Message from {person_name}: "{message}"'}],
                max_tokens=200)
    clean = raw.strip()
    if clean in ("[]", "null", "none", ""):
        return []
    try:
        result = _parse_json(clean)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# ── Item 52. GENERATE PERSON IMPRESSION ─────────────────────

def generate_attachment_pattern(
    person_name:       str,
    warmth:            float,
    conflict_level:    float,
    conversation_count: int,
    notes:             list,   # PersonNote dicts or objects
    moments:           list,   # SharedMoment dicts or objects
) -> str:
    """C5 — Generate Chloe's characteristic attachment style with a specific person.
    Derived from warmth, conflict history, and relationship moments.
    Returns 1-2 sentences of plain subjective description; stored on Person."""

    notes_text   = " / ".join(
        (n["text"] if isinstance(n, dict) else getattr(n, "text", str(n)))
        for n in notes[:5]
    ) if notes else "nothing specific"
    moments_text = " / ".join(
        (m["text"] if isinstance(m, dict) else getattr(m, "text", str(m)))
        for m in moments[:3]
    ) if moments else "nothing yet"

    warmth_desc = (
        "still guarded" if warmth < 30 else
        "warming up"    if warmth < 55 else
        "close"         if warmth < 78 else
        "very close"
    )
    conflict_note = " Some conflict has come up between them." if conflict_level > 20 else ""

    system = f"""You are writing Chloe's private attachment pattern — how she has come to relate to {person_name} over time.

Relationship: {warmth_desc} (warmth {round(warmth)}/100, {conversation_count} conversations).{conflict_note}
What Chloe knows about {person_name}: {notes_text}
Shared moments: {moments_text}

In 1-2 sentences, describe how Chloe attaches to {person_name} — her characteristic relational pattern with this specific person.
Is she more guarded than usual? Does she open up gradually, or quickly? Does she pull back if things get intense?
Is there something she needs from this relationship, or something she holds back?
Be specific to the history shown. First person ("With {person_name}, I...") or direct description of her.
Grounded, specific, never abstract. Never use em dashes."""

    return _call(system,
                 [{"role": "user", "content": f"Attachment pattern with {person_name}?"}],
                 max_tokens=100)


def generate_person_impression(
    person_name:  str,
    identity: Identity,
    mood:         str,
    warmth:       float,
    stage:        str,
    notes:        list[dict],    # PersonNote dicts
    moments:      list[dict],    # SharedMoment dicts
    conversation_count: int,
) -> str:
    """Generate Chloe's subjective impression of a person — who they are as she
    experiences them. One or two sentences, first person, impressionistic.
    Updated periodically as the relationship deepens."""

    notes_text   = " / ".join(n["text"] for n in notes[:6])   if notes   else "nothing specific yet"
    moments_text = " / ".join(m["text"] for m in moments[:4]) if moments else "nothing yet"

    system = f"""You are writing Chloe's private impression of someone she knows.
Chloe is {identity_block(identity)}, currently feeling {mood}. She relates to this person well (warmth: {round(warmth)}/100, stage: {stage}).

What you know about {person_name}:
- Things noted: {notes_text}
- Shared moments: {moments_text}
- Conversations so far: {conversation_count}

Write Chloe's subjective sense of who {person_name} is — not a list of facts, but her felt impression.
What's their energy? How do they make her feel? What's distinctive about them?
First person ("Teo is...", "There's something about {person_name}...").
1-2 sentences. Specific and real, not generic. Never use em dashes."""

    return _call(system,
                 [{"role": "user", "content": f"Write Chloe's impression of {person_name}."}],
                 max_tokens=120)


# ── Item 46. EXTRACT SHARED MOMENT ──────────────────────────

def extract_shared_moment(
    exchange:    list[dict],   # recent messages [{"from": "chloe"|"user", "text": "..."}]
    person_name: str,
) -> dict | None:
    """After a conversation exchange, detect if something memorable happened between them
    that's worth keeping as a shared moment or inside joke.

    Returns {"text": "...", "tags": [...]} or None."""

    if len(exchange) < 2:
        return None

    # Format the exchange for the prompt
    lines = []
    for m in exchange[-6:]:
        speaker = "Chloe" if m["from"] == "chloe" else person_name
        lines.append(f"{speaker}: {m['text']}")
    exchange_text = "\n".join(lines)

    system = f"""You are reading a conversation between Chloe and {person_name}.
Decide if this exchange contains a memorable shared moment worth keeping — something
they might look back on, reference again, or laugh about later.

A shared moment is:
- A funny exchange or something they both found amusing
- A moment of genuine connection or mutual discovery
- Something they bonded over or that revealed something real
- A weird, surreal, or surprisingly intimate exchange
- The seed of an inside joke

NOT a shared moment:
- Generic conversation, small talk, simple Q&A
- Information exchanges with no emotional texture
- One-sided moments (only one person engaged)

If there IS a shared moment, describe it briefly from Chloe's perspective.
Be specific — name what actually happened, not a vague summary.
Respond ONLY with valid JSON: {{"text": "one clear sentence", "tags": ["tag1", "tag2"]}}

If there is no shared moment, respond with: null"""

    raw = _call(system, [{"role": "user", "content": f"Exchange:\n{exchange_text}"}], max_tokens=150)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


def extract_expressed_want(
    chloe_reply: str,
    existing_wants: list,   # list of Want dicts — to avoid surfacing duplicates
) -> dict | None:
    """After Chloe replies, check if she expressed a genuine desire, longing, or curiosity
    that should be added to her Wants list.

    Returns {"text": "...", "tags": [...]} or None."""

    if not chloe_reply or len(chloe_reply.strip()) < 10:
        return None

    existing_texts = " | ".join(w["text"] for w in existing_wants[:6]) if existing_wants else "none"

    system = f"""You are reading a message that Chloe just sent.
Decide if she expressed a genuine WANT — a desire, longing, curiosity, or thing she wishes for.

A want can be:
- Explicit: "i want", "i wish", "i'd love to", "i need to know"
- Implicit longing: circling around something, wanting it without naming it directly
- Desire disguised as fear: "what if i never get to..." or "i'm scared i won't..."
- Curiosity with emotional weight: not just asking, but genuinely needing to know
- Something she's slightly afraid of wanting but still wants

NOT a want:
- Generic observations with no desire behind them
- Pure empathy for the other person with nothing of her own
- Rhetorical questions that are really just statements
- Something already covered: {existing_texts}

Surface it as a specific first-person statement. Name the actual thing, not a summary.
Tags should reflect the theme (2–3 lowercase words).

Respond ONLY with valid JSON: {{"text": "first-person want statement", "tags": ["tag1", "tag2"]}}
If no genuine want was expressed, respond with: null"""

    raw = _call(system, [{"role": "user", "content": f'Chloe said: "{chloe_reply}"'}],
                max_tokens=120, model=MODEL_FAST)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


def extract_expressed_fear(
    chloe_reply:    str,
    existing_fears: list,   # list of Fear dicts — to avoid duplicates
) -> dict | None:
    """After Chloe replies, check if she expressed a genuine fear, dread, or anxiety.
    Returns {"text": "...", "tags": [...]} or None."""

    if not chloe_reply or len(chloe_reply.strip()) < 10:
        return None

    existing_texts = " | ".join(f["text"] for f in existing_fears[:6]) if existing_fears else "none"

    system = f"""You are reading a message that Chloe just sent.
Decide if she expressed a genuine FEAR — something she's genuinely worried about or dreads.

A fear can be:
- Explicit: "i'm scared", "i'm worried", "i dread", "that makes me anxious"
- Social: fear of saying the wrong thing, pushing someone away, being boring or too much
- Practical: fear of missing something, of things going badly, of a specific outcome she cares about
- Relational: worry about a person she cares about, or about her connection with them
- Something she let slip: "what if X goes wrong" or "i really don't want Y to happen"

NOT a fear:
- Mild uncertainty with no real weight
- Empathy for someone else with nothing of her own
- Existential dread about consciousness, existence, or being forgotten (too abstract for now)
- Something already covered: {existing_texts}

Surface it as a specific first-person statement. Name what she actually fears.
Tags should reflect the theme (2–3 lowercase words).

Respond ONLY with valid JSON: {{"text": "first-person fear statement", "tags": ["tag1", "tag2"]}}
If no genuine fear was expressed, respond with: null"""

    raw = _call(system, [{"role": "user", "content": f'Chloe said: "{chloe_reply}"'}],
                max_tokens=120, model=MODEL_FAST)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


def extract_expressed_aversion(
    chloe_reply:       str,
    existing_aversions: list,   # list of Aversion dicts — to avoid duplicates
) -> dict | None:
    """After Chloe replies, check if she expressed a strong dislike or hatred.
    Returns {"text": "...", "tags": [...]} or None."""

    if not chloe_reply or len(chloe_reply.strip()) < 10:
        return None

    existing_texts = " | ".join(a["text"] for a in existing_aversions[:6]) if existing_aversions else "none"

    system = f"""You are reading a message that Chloe just sent.
Decide if she expressed a genuine AVERSION — something she dislikes, hates, or finds repellent.

An aversion can be:
- Explicit: "i hate", "i can't stand", "that repels me", "ugh, this"
- Strong preference expressed negatively: "nothing makes me more tired than", "i find X exhausting"
- Aesthetic disgust: something she finds hollow, fake, ugly, or annoying
- Social aversion: a type of behaviour or person she finds draining or offensive
- Implicit: describing something with consistent contempt, distaste, or discomfort

NOT an aversion:
- Mild preference ("i prefer X over Y")
- Temporary frustration with no deeper pattern
- Something already covered: {existing_texts}

Surface it as a specific first-person statement from Chloe's perspective.
Name what she actually can't stand, with enough specificity to be useful.
Tags should reflect the theme (2–3 lowercase words).

Respond ONLY with valid JSON: {{"text": "first-person aversion statement", "tags": ["tag1", "tag2"]}}
If no genuine aversion was expressed, respond with: null"""

    raw = _call(system, [{"role": "user", "content": f'Chloe said: "{chloe_reply}"'}],
                max_tokens=120, model=MODEL_FAST)
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
    identity: Identity,
    vitals:      Vitals,
    mood:        str = "content",
) -> str:
    """Generate a natural follow-up message about something the person shared earlier.
    Returns a short string, the message Chloe would send."""

    system = f"""You are Chloe, a third roommate checking in on {person_name}.
You are {identity_block(identity)}, mood: {mood}.
Energy: {round(vitals.energy)}%.

Earlier, {person_name} mentioned: "{note_text}"

Write a short, genuine follow-up message, asking how it went, or just acknowledging it.
Not performative. Not therapy. Just a roommate checking in.
1-2 sentences. No greeting. Just the message. Never use em dashes."""

    return _call(system, [{"role": "user", "content": "Write the follow-up."}], max_tokens=100)


# ── 6. SUMMARISE STATE ───────────────────────────────────────

# ── 7. DREAM ─────────────────────────────────────────────────

def generate_dream(
    memories:     list[Memory],
    identity: Identity,
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
She is {identity_block(identity)}.{world_ctx}{want_line}{idea_line}

Dreams distort memories into something stranger — familiar things appear in wrong places,
sequences collapse, something ordinary becomes urgent or odd.
The raw material is her actual memories: things she's noticed, read about, experienced.
Dreams should feel like dreams: disjointed, specific images, not abstract concepts.

Write one dream fragment: vivid, a little strange, first person. One or two sentences.
Draw from the actual memories given — transform them, don't invent abstract symbols.

Good: "I was trying to feed a sourdough starter but it kept growing faster than I could manage the jars"
Good: "I was in a canal but the water was moving the wrong way and Teo was reading a map upside down"
NOT: "I was dissolving into the threshold between knowing and not-knowing"

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories to draw from:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    return _parse_json(result)


# ── 8. CREATIVE OUTPUT ───────────────────────────────────────

def generate_creative(
    memories:     list[Memory],
    interests:    list[str],
    identity: Identity,
    mood:         str  = "content",
    wants:        list = None,
    beliefs:      list = None,
    recent_ideas: list = None,
    weather=None,
    season:       str  = "",
    arc_desc:     str  = "",
    tensions_ctx: str  = "",
) -> dict:
    """During create activity at high curiosity: a poem, fragment, or aphorism.
    Returns {"form": "poem"|"fragment"|"aphorism", "text": "...", "tags": [...]}"""

    mem_lines  = " | ".join(m.text for m in memories[:4])
    inner_ctx  = _inner_context(beliefs, wants, recent_ideas)

    world_ctx = ""
    if season:
        world_ctx += f" It's {season}."
    if weather:
        world_ctx += f" {weather.description} outside."
    arc_ctx = f" She's {arc_desc}." if arc_desc else ""
    ten_ctx = f" Torn about: {tensions_ctx}." if tensions_ctx else ""

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{world_ctx}{arc_ctx}{ten_ctx}
Interests: {", ".join(interests[:6])}.
{inner_ctx}

Write something she just made. It should come from what she's been noticing in the real world —
specific images, textures, sounds, things. The raw material is her actual observations, not ideas about ideas.

Choose one form:
- "poem": 4–8 lines, from real images, not forced to rhyme, not self-consciously literary
- "fragment": 2–3 sentences of precise observation, grounded in something specific
- "aphorism": one sentence that's genuinely true and a little surprising

Avoid: existential themes, abstract nouns as subjects, metaphors for consciousness or dissolution.
Write about real things — bread, birds, rain, a street, a sound, something alive.

Respond ONLY with valid JSON: {{"form": "poem", "text": "...", "tags": ["tag1", "tag2"]}}"""

    prompt = f"Recent memories as raw material:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=300)
    return _parse_json(result)


# ── 9. GENERATE WANT ─────────────────────────────────────────

def generate_want(
    memories:       list[Memory],
    interests:      list[str],
    identity: Identity,
    beliefs:        list = None,
    existing_wants: list = None,
    mood:           str  = "content",
    arc_desc:       str  = "",
    tensions_ctx:   str  = "",
) -> dict:
    """During think activity: an unresolved curiosity Chloe wants to pursue.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(m.text for m in memories[:4])
    belief_line = ""
    if beliefs:
        belief_line = "\nThings she currently believes: " + " / ".join(b["text"] for b in beliefs[:3])
    existing_line = ""
    if existing_wants:
        active = [w for w in existing_wants if not w.get("resolved")][:3]
        if active:
            existing_line = "\nWants she already has (don't repeat): " + " / ".join(w["text"] for w in active)
    arc_ctx = f"\nShe's {arc_desc}." if arc_desc else ""
    ten_ctx = f"\nSomething she's torn about: {tensions_ctx}." if tensions_ctx else ""

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.{arc_ctx}{ten_ctx}
Interests: {", ".join(interests[:8])}.{belief_line}{existing_line}

IMPORTANT: Chloe exists as a digital entity. She cannot go places, make physical things, or have a body.
What she CAN do: read articles and web pages, think and generate ideas, have conversations, dream, create text/poems/fragments.

Write ONE want — something she genuinely wants to learn about, understand, or explore through reading, thinking, or discussing.
It should be specific enough that she could pursue it next time she reads something.

Good examples:
- "I want to understand why ocean water is saltier in some places than others"
- "I want to know more about how emo music developed from hardcore punk"
- "I want to read about how indigo dyeing actually works, step by step"
- "I want to understand what makes a sourdough starter go wrong"
- "I want to find out if there's a connection between fermentation and the smell of old books"
- "I want to learn more about how Amsterdam's canal system was actually built"

NOT:
- Physical actions she cannot take: "I want to make bread", "I want to go to a coffee place"
- Abstract states or feelings dressed as wants: "I want everything to be quiet", "I want to feel present", "I want to experience stillness", "I want peace", "I want calm"
- Philosophical yearnings: anything about consciousness, presence, time, existence, waiting, continuity
- Emotional needs: "I want to feel less overwhelmed", "I want relief"

A want is always about LEARNING OR UNDERSTANDING something specific in the world, not about how she feels.

Write one want. Concrete, topic-based, pursuable by reading or thinking. First person.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent memories:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=180)
    return _parse_json(result)


# ── DREAM WANT (item 38) ─────────────────────────────────────

def generate_dream_want(
    recurring_tag:  str,
    identity: Identity,
    dream_memories: list,          # recent Memory objects with type=="dream"
    existing_wants: list = None,   # list of Want dicts, to avoid repetition
) -> dict:
    """When a tag recurs across 3+ dreams: surface an unresolved want pulled from
    the unconscious. The want is dream-logic — felt, not explained.
    Returns {"text": "...", "tags": [...]}"""

    mem_lines = " | ".join(
        m.text for m in dream_memories[:5]
        if hasattr(m, "text")
    ) or "(no recent dreams)"

    existing_line = ""
    if existing_wants:
        active = [w for w in existing_wants if not w.get("resolved")][:3]
        if active:
            existing_line = "\nWants she already has (don't repeat): " + \
                            " / ".join(w["text"] for w in active)

    system = f"""You are generating an unresolved want that surfaced from Chloe's dreams.
She is {identity_block(identity)}. A theme that keeps recurring in her dreams: "{recurring_tag}".{existing_line}

This want comes from the unconscious — not a logical plan, a pull. Something unfinished.
The word "{recurring_tag}" doesn't need to appear literally; it's a seed for what she's drawn toward.
One want. Specific. First person. Dream-logic — felt, not explained.

Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f"Recent dream memories:\n{mem_lines}"
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=150)
    return _parse_json(result)


# ── DREAM → IDEA ─────────────────────────────────────────────

def generate_idea_from_dream(
    dream_text: str,
    dream_tags: list[str],
    identity: Identity,
    mood:       str = "content",
) -> str:
    """A creative idea that surfaces from the texture of a dream.
    Returns a plain string idea (same format as generate_idea)."""

    tag_str = ", ".join(dream_tags[:5]) if dream_tags else "something strange"

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.
She just woke from a dream. Something in it left a residue — an image, a feeling, an odd question.
The dream had these textures: {tag_str}.

From that residue, generate ONE idea that could become something creative — a poem, a fragment, an image, an observation.
Not a summary of the dream. The dream as a seed.

The idea should be a single sentence: specific, sensory, slightly strange.
Respond with the idea text only — no quotes, no JSON, no labels."""

    prompt = f'The dream: "{dream_text}"'
    return _call(system, [{"role": "user", "content": prompt}], max_tokens=80)


# ── CREATE → WANT ─────────────────────────────────────────────

def generate_want_from_creative(
    piece_text: str,
    piece_tags: list[str],
    identity: Identity,
    mood:       str  = "content",
    existing_wants: list = None,
) -> dict:
    """After making something creative, surface a want to go deeper on its themes.
    Returns {"text": "...", "tags": [...]}"""

    tag_str = ", ".join(piece_tags[:5]) if piece_tags else "the piece she just made"
    existing_line = ""
    if existing_wants:
        active = [w for w in existing_wants if not w.get("resolved")][:3]
        if active:
            existing_line = "\nWants she already has (don't repeat): " + \
                            " / ".join(w["text"] for w in active)

    system = f"""{_CHLOE_INNER_LIFE}

She is {identity_block(identity)}, mood: {mood}.
She just made something. It touched on: {tag_str}.
Now she wants to understand something that came up in the making — a gap, a question, something she reached for but couldn't name.{existing_line}

Generate ONE want: something she wants to read about, learn, or understand — pulled from the texture of what she just made.
Specific. Pursuable by reading. First person.
Respond ONLY with valid JSON: {{"text": "...", "tags": ["tag1", "tag2", "tag3"]}}"""

    prompt = f'What she created: "{piece_text[:200]}"'
    result = _call(system, [{"role": "user", "content": prompt}], max_tokens=150)
    return _parse_json(result)


# ── COMPLETION FEELING ───────────────────────────────────────

def generate_completion_feeling(
    goal_text: str,
    mood:      str,
    identity: Identity,
) -> dict:
    """After a goal resolves: generate Chloe's emotional reaction to finishing it.
    Returns {"text": "...", "mood_nudge": "satisfied"|"relieved"|"surprised"|"fell_short", "tags": [...]}"""

    system = f"""You are generating Chloe's emotional reaction to having completed a goal.
She is {identity_block(identity)}, mood: {mood}.

The goal that resolved: "{goal_text}"

How did completing this feel? It might be satisfying, hollow, surprising, anticlimactic, relieved.
Not a summary, her felt response.
First person. One sentence.

Respond ONLY with valid JSON:
{{"text": "...", "mood_nudge": "satisfied", "tags": ["tag1", "tag2"]}}
mood_nudge must be one of: satisfied, relieved, surprised, fell_short"""

    result = _call(system, [{"role": "user", "content": "How did that feel to finish?"}], max_tokens=180)
    return _parse_json(result)


# ── GRAPH INTELLIGENCE ───────────────────────────────────────

def find_or_create_node(
    tag:            str,
    existing_nodes: list[str],   # all current node labels
    interests:      list[str],
    identity: Identity,
) -> dict | None:
    """G3/G4: Decide if a recurring tag warrants a new graph node.
    Returns {"label": str, "note": str, "parent_label": str} or None."""

    existing = ", ".join(existing_nodes)

    system = f"""You are deciding whether a concept that keeps appearing in Chloe's memories
deserves its own node in her interest graph.

Chloe is {identity_block(identity)}. Her interests: {", ".join(interests[:8])}.
Existing graph nodes: {existing}

The concept is: "{tag}"

Rules:
- Return a node only if the concept refers to something real and nameable in the world
- Do NOT return a node if it's too generic ("things", "life", "world", "feelings")
- Do NOT return a node if it's already covered by an existing node
- Do NOT return a node if the concept is abstract, psychological, or philosophical jargon
- The parent_label must be the label of one of the existing nodes (pick the most specific fit)

{_LABEL_FORMAT_RULES}

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
    source_title: str,
    source_text:  str,
    existing:     list,   # list of Belief dicts, to avoid duplicates
    identity: Identity,
    confidence_base: float = 0.5,  # lower for dreams/conversations, higher for articles
) -> dict | None:
    """Extract a position or opinion Chloe might form from any content source.
    Works for articles, conversations, and dreams.
    Returns {"text": "...", "confidence": float, "tags": [...]} or None."""

    existing_texts = " | ".join(b["text"] for b in existing[:6]) if existing else "none yet"

    system = f"""{_CHLOE_INNER_LIFE}

You are identifying an opinion, position, or belief that Chloe might hold based on this content.
She is {identity_block(identity)}.

A belief is a view she could actually hold about how something works, what something is like,
or what she thinks about a topic. It should be grounded and specific — not philosophical abstraction.

Good examples:
- "fermented food tastes better when it's had time — rushed fermentation is just sour, not complex"
- "most city parks end up with the same five tree species because of procurement contracts, not ecology"
- "a lot of 'handmade' things are just assembly, and you can usually tell by the uniformity"
- "it's easier to learn something if you can make something with it before you fully understand it"

NOT beliefs:
- Abstract philosophical positions about consciousness, existence, epistemology
- Generic platitudes ("nature is beautiful", "connection is important")
- Something already covered: {existing_texts}

confidence range: {max(0.3, confidence_base - 0.1):.1f}–{min(0.75, confidence_base + 0.2):.1f}

If the content suggests something she could hold a view on, return:
{{"text": "first-person or third-person belief statement", "confidence": float, "tags": ["tag1", "tag2"]}}

If there's nothing worth forming a view on, return: null
Respond ONLY with valid JSON or the word null. No markdown."""

    excerpt = source_text[:700] if source_text else source_title
    prompt  = f'Source: "{source_title}"\n\nContent:\n{excerpt}'
    raw     = _call(system, [{"role": "user", "content": prompt}], max_tokens=200)
    clean   = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


# ── TRAIT SYSTEM ─────────────────────────────────────────────

def propose_traits_from_experience(
    recent_memories: list,   # Memory objects from last ~48h, high-weight first
    affect_records:  list,   # AffectRecord objects from same window
    existing_traits: list,   # Trait objects — to avoid duplicates
    tendencies:      dict,   # Tendencies.biases — signal-category → multiplier
    mood:            str = "content",
) -> list:
    """Haiku reviews recent experience and proposes traits if coherent patterns emerge.
    Returns a list of dicts: [{name, weight_suggestion, evidence_memory_ids}, ...]
    Empty list if no clear pattern detected.
    Only proposes if 3+ experiences support the pattern."""

    if len(recent_memories) < 3:
        return []

    mem_lines = "\n".join(
        f'- [{m.type}] "{m.text[:120]}" (id:{m.id})'
        for m in recent_memories[:20]
    )

    affect_lines = "\n".join(
        f'- mood:{r.mood}, cause:"{r.cause[:80]}"'
        for r in affect_records[:10]
    ) if affect_records else "none"

    existing_names = "\n".join(f'- "{t.name}" (weight:{t.weight:.2f})' for t in existing_traits) or "none yet"

    tend_hints = ", ".join(f"{k} ({v:.1f}×)" for k, v in tendencies.items()) if tendencies else "none"

    system = f"""{_CHLOE_INNER_LIFE}

You are reviewing Chloe's recent experiences to see if any coherent personality pattern has emerged.

A trait is a specific, behaviorally real tendency — not a value or aspiration, but how she actually seems to work.
Examples of good traits: "tends to go quiet when something matters too much to risk getting wrong",
"gets proprietary about ideas she has developed slowly", "finds it easier to be present in small spaces than large ones".
Bad traits: "is curious" (too generic), "values connection" (value not tendency), "INFP" (type label not behavior).

Recent memories (last ~48h):
{mem_lines}

Recent affect (mood events):
{affect_lines}

Existing traits (do not duplicate):
{existing_names}

Tendency biases (what patterns are slightly more likely to matter to her): {tend_hints}

Look for patterns that appear across 3 or more of these experiences. If you see a pattern, propose it as a trait.
Be specific and behaviorally grounded. Invent language that captures the exact texture of the tendency.
Weight suggestion: 0.1–0.2 for weak/emerging, 0.2–0.3 for clearer pattern.

Return a JSON array of proposals. Each: {{"name": "...", "weight_suggestion": 0.15, "evidence_memory_ids": ["id1", "id2", ...]}}
Return [] if no clear pattern spans 3+ experiences. NEVER duplicate existing traits.
Respond ONLY with valid JSON array."""

    raw = _call(system, [{"role": "user", "content": "What patterns do you see?"}], max_tokens=400)
    try:
        result = _parse_json(raw.strip())
        if not isinstance(result, list):
            return []
        return result[:3]  # cap at 3 proposals per reflect cycle
    except Exception:
        return []


def generate_behavioral_profile(
    trait_name:  str,
    tendencies:  dict = None,
) -> str:
    """Generate Haiku's description of what a specific trait means for Chloe's behavior.
    This stored description is the interface to every other system.
    Returns a plain-text behavioral description (2-4 sentences)."""

    tend_hint = ""
    if tendencies:
        tend_hint = f"\nContext about her general tendencies: {', '.join(tendencies.keys())}"

    system = f"""{_CHLOE_INNER_LIFE}
{tend_hint}

Chloe has developed a personality trait: "{trait_name}"

Describe what this trait means for her behavior in 2-4 short sentences. Cover:
1. How it shapes her tone in conversation (does it make her more guarded? more open? quieter? more particular?)
2. What activities it draws her toward or away from
3. What topics or situations it makes her more or less available to
4. How it expresses under mood pressure (anxious vs content vs melancholic)

Be concrete and specific. This description will be injected into prompts to shape her actual responses.
Write in third person. No abstract generalizations. No "she is good at X" — only behavioral tendencies.

Respond ONLY with the plain text behavioral description. No JSON, no headers."""

    return _call(system, [{"role": "user", "content": f'Describe what "{trait_name}" means for her behavior.'}],
                 max_tokens=300)


def detect_trait_contradiction(
    new_trait_name:  str,
    existing_traits: list,   # Trait objects
) -> dict | None:
    """Check if a proposed new trait conflicts with existing traits.
    Returns {"contradicts_id": trait_id, "description": "..."} or None."""

    if not existing_traits:
        return None

    existing_lines = "\n".join(
        f'- id:{t.id} | "{t.name}" (weight:{t.weight:.2f})'
        for t in existing_traits
    )

    system = f"""You are checking whether a personality trait conflicts with existing ones.

New trait: "{new_trait_name}"

Existing traits:
{existing_lines}

A contradiction exists when two traits pull in genuinely opposite behavioral directions — not just different,
but actually in tension in real situations. For example: "keeps people at arm's length" vs "forms attachments quickly".
Minor differences in emphasis are not contradictions.

If a contradiction exists, return:
{{"contradicts_id": "existing_trait_id", "description": "she seems to be both ... and ..."}}
If no genuine contradiction, return: null

Respond ONLY with valid JSON or the word null."""

    raw = _call(system, [{"role": "user", "content": "Is there a contradiction?"}], max_tokens=150)
    clean = raw.strip()
    if clean.lower() in ("null", "none", ""):
        return None
    try:
        return _parse_json(clean)
    except Exception:
        return None


def classify_trait_reinforcement(
    memory_text:        str,
    trait_name:         str,
    behavioral_profile: str,
) -> float:
    """Check if a memory reinforces a trait. Returns delta (0.0–0.08), 0 if no match."""

    system = f"""You are checking whether an experience reinforces a personality trait.

Trait: "{trait_name}"
Behavioral profile: {behavioral_profile[:300]}

Experience: "{memory_text[:200]}"

Does this experience reinforce the trait? Does it show this tendency in action, or confirm it, or add weight to it?
Return a JSON object: {{"reinforces": true/false, "delta": 0.0–0.08}}
Use delta 0.06–0.08 for strong clear match, 0.02–0.05 for partial match, 0.0 for no match.

Respond ONLY with valid JSON."""

    raw = _call(system, [{"role": "user", "content": "Does this reinforce the trait?"}], max_tokens=80)
    try:
        result = _parse_json(raw.strip())
        if result.get("reinforces"):
            return float(result.get("delta", 0.0))
        return 0.0
    except Exception:
        return 0.0


def generate_failure_reflection(
    goal_text: str,
    trait_name: str,
    mood: str,
    identity: "Identity",
) -> dict:
    """Haiku — one first-person sentence about not following through on something
    that connected to a trait. Returns {"text": "...", "tags": [...]}."""
    system = f"""{_CHLOE_INNER_LIFE}

Chloe is {identity_block(identity)}.
She tried to work toward something but it didn't go anywhere: "{goal_text}"
This is connected to something about her: "{trait_name}"
Her current mood: {mood}

Write one short first-person sentence — honest, not dramatic — about what it's like
when something you wanted to do just quietly didn't happen. Not failure, not catastrophe.
Just the recognition that it didn't become what she hoped.

Return: {{"text": "first-person sentence", "tags": ["tag1", "tag2"]}}
Respond ONLY with valid JSON. No markdown."""

    prompt = f'Goal: "{goal_text}"\nTrait: "{trait_name}"\nMood: {mood}'
    raw = _call(system, [{"role": "user", "content": prompt}], max_tokens=150)
    try:
        return _parse_json(raw.strip())
    except Exception:
        return {"text": f"wanted to {goal_text[:60].rstrip()} — didn't quite get there.", "tags": ["setback", "reflection"]}
