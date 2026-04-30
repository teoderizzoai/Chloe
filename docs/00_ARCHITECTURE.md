# Chloe — Architecture

This document describes the *current* implementation. Future direction is in `CLAUDE.md`.

The goal of this document is that someone (or future-you) can understand how every piece of state is shaped, where it lives, and how a single event ripples through everything else. If you read it once front-to-back, you should know what happens when she reads an article, when she gets a mean message, and what determines what comes out of `chat()`.

---

## 1. Mental model

Chloe is one Python object (`Chloe`, defined in `chloe/chloe.py`) with a continuously running async loop. All her state hangs off that object. Two things drive change:

1. **The tick** — every 5 seconds, autonomously. Drifts soul, updates mood, decides what activity she should be in, sometimes spawns a background LLM event (read an article, dream, think, create, send a message).
2. **An incoming message** — reactive. Reads the emotion behind it, updates her in-memory state, builds a giant context, calls Sonnet, then learns from her own reply.

Everything else — persistence, the dashboard, Discord — is plumbing around those two drivers.

### State layered by change-rate

| Layer | Timescale | Sticky? | Where |
|---|---|---|---|
| Vitals (energy, social_battery, curiosity, focus, inspiration) | tick (5s) | no, continuously flowing | `Vitals` in `heart.py` |
| Mood (one of 8 labels, with intensity) | minutes, sticky | yes, only re-evaluates 10% of ticks | `Affect` in `affect.py` |
| Active arc (long mood state like "melancholic_stretch") | hours to days | yes, ends explicitly | `Arc` in `inner.py` |
| Identity (emergent traits, weights 0–1) | weeks to months | yes, decay-tracked | `Identity` in `identity.py` |
| Memories, beliefs, wants, etc | persistent, age slowly | n/a — accumulate | SQLite |

Don't collapse the layers — that's why mood doesn't follow vitals tick-by-tick, why soul doesn't lurch on a single article, why the arc exists at all. The point is to model human time-scales, not just "feel state."

---

## 2. The tech stack, concretely

### Python 3.13 main app
`uvicorn server:app --port 8000` boots FastAPI which constructs the `Chloe` instance, calls `await chloe.start()` to kick off the heartbeat, and serves HTTP endpoints for the dashboard.

### Anthropic LLM (two tiers)
- `MODEL_CHAT = "claude-sonnet-4-6"` — only used for live chat (`chat()`, `_voice_chat()`) and autonomous outreach (`generate_autonomous_message`). The stuff a human reads.
- `MODEL_FAST = "claude-haiku-4-5-20251001"` — everything else: emotion reading, memory generation, idea generation, dream generation, person impressions, third-party detection, belief extraction, search query writing, tension detection, shared moment detection. Anything that's structured or background.

All calls go through `_call(system, messages, max_tokens, model)` in `llm.py`. The `_call` wrapper does em-dash stripping at the source so the dashes never reach the user.

### ChromaDB (semantic memory index)
A persistent client at `<state_file_dir>/memory_index/` embeds every memory's text. Used at chat time to retrieve the 5 memories most semantically similar to the incoming message, reranked by recency. Falls back to recency-only retrieval (`get_vivid`) if chromadb isn't installed.

### SQLite — `chloe.db`
WAL mode. Holds everything that's unbounded or relational:
- `memories` (each with type, tags, weight, confidence, timestamp)
- `ideas`, `chat_history`, `affect_records`
- `wants`, `fears`, `aversions`, `beliefs`, `goals`, `tensions`
- `persons` + sub-tables: `person_notes`, `person_events`, `person_moments`, `person_third_parties`
- `traits` (id, name, weight, behavioral_profile, origin_memory_ids, last_reinforced, created, is_core, archived)
- `contradictions` (id, trait_a_id, trait_b_id, description, created)

Write-through pattern: in-memory operations call `add_memory()` etc. on the `ChloeDB`, which inserts to SQLite immediately for memories/ideas/chat. List state (wants, beliefs, etc.) syncs every save (every ~5 min) via `sync_*` methods that delete-and-reinsert.

### JSON — `chloe_state.json`
Holds atomic-changing scalars that don't fit the relational model: soul values (frozen starting values only), vitals, current activity, current mood, the graph, the active arc, identity_snapshot, identity_tendencies, identity_momentum, pending outreach, last journal/backup dates, the runtime log buffer.

### Backups
At 23:00 daily, `_backup()` copies `chloe_state.json` to `backups/chloe_YYYY-MM-DD.json`. SQLite is not currently backed up the same way (it's append-only and lives in one file).

### Frontend — `index.html`
Single HTML file, no build step. Polls `GET /snapshot` every 4 seconds, renders vitals bars, soul sliders, mood pill, interests cloud, graph canvas, etc. Sends chat through `POST /chat`.

### Voice — `voice_app.py` (separate process)
Optional, runs in `.fishvenv` (Python 3.11) because Fish Speech needs an older Torch. Captures audio with Whisper, calls `chloe.chat(message, voice=True)` against the running server, plays the reply through Fish Speech 1.5.

### Discord — `discord_bot.py`
Optional. Starts in the FastAPI lifespan if env vars are set. Routes incoming DMs to `chloe.chat()` with the right `person_id`. Outgoing autonomous messages are sent through a "realistic send pipeline" with typing indicators and per-message delays.

---

## 3. Repo and modules

```
Chloe/
  chloe/
    chloe.py        — central orchestrator, holds all state, runs the loop
    identity.py     — trait system: Trait, Contradiction, Tendencies, Identity
    soul.py         — [DEPRECATED] MBTI floats, frozen for heart.py compat
    heart.py        — vitals, activities, circadian, day-of-week, auto_decide
    affect.py       — mood as a state separate from vitals
    memory.py       — Memory dataclass + ChromaDB index + Idea
    persons.py      — Person + warmth/distance/conflict + tone_context (voice register)
    inner.py        — Want, Belief, Goal, Fear, Aversion, Tension, Arc, AffectRecord
    graph.py        — interest graph: nodes, edges, expansion, resonance
    llm.py          — every Anthropic call lives here (~25 functions)
    feeds.py        — RSS, web fetch, web search
    weather.py      — Open-Meteo client
    store.py        — ChloeDB SQLite write-through
    discord_bot.py  — DM bridge
    avatar.py       — portrait selection from activity/mood
  server.py         — FastAPI app
  index.html        — dashboard
  voice_app.py      — voice UI (separate process)
```

---

## 4. The state-bearing dataclasses

### `Identity` — `identity.py`
The active trait profile. Four dataclasses:
- **`Trait`** — `{id, name, weight (0–1), behavioral_profile, origin_memory_ids, last_reinforced, created, is_core}`. `name` is plain language, generated by Haiku from experience patterns ("gets quiet when something matters too much to risk saying wrong"). `behavioral_profile` is Haiku-generated text describing how this trait colors tone, activities, and topics. `is_core` becomes true when weight ≥ 0.75 sustained for 7+ days.
- **`Contradiction`** — `{id, trait_a_id, trait_b_id, description, created}`. Two conflicting traits that coexist without resolution.
- **`Tendencies`** — seed biases that make certain trait types more likely to emerge first (`introspective: 1.3`, `pattern_seeking: 1.2`, `relational: 1.2`, `open_ended: 1.1`, `aesthetic: 1.0`). Scaffolding, not identity.
- **`Identity`** — holds `traits: list[Trait]`, `contradictions: list[Contradiction]`, `tendencies: Tendencies`, `identity_momentum: dict` (EMA of per-trait weight change direction).

`identity_block(identity)` formats the prompt block: "Who you are right now:" with traits at core/strong/present/emerging tiers, plus unresolved contradictions. Falls back to "a young woman in her early twenties, still becoming who she is" when no traits exist yet.

### `Soul` — `soul.py` [DEPRECATED]
Kept frozen at starting values for legacy reasons only. No longer referenced by any active code. `heart.py` was fully migrated to `identity` in Session 27: `trait_personality_scalars(identity)` and `trait_activity_affinity(identity, activity_id)` in `identity.py` now replace `soul_activity_affinity()`. Do not extend.

### `Vitals` — `heart.py`
Five floats, each 0–100: energy, social_battery, curiosity, focus, inspiration. Updated every tick by `tick_vitals()`. They gate behavior (low energy → can't reply, low social → wind down) and feed the mood layer.

### `Affect` — `affect.py`
`{mood: str, intensity: float}`. One of 8 moods. Sticky (10% re-evaluation per tick). Each mood has a color and short description in `MOODS`.

### `Memory` — `memory.py`
`{text, type, tags, weight, confidence, timestamp, id, salience}`. Type is one of: observation, conversation, idea, feeling, interest, dream, creative. Weight decays over time via `age()`. Confidence ≤ 0.5 surfaces with uncertainty prefixes ("a hazy thought…"). Both stored in SQLite and embedded in ChromaDB.

`salience: float` — set at creation from the emotional intensity of the generating event. High-salience memories: decay more slowly (half-life 1.5× normal), rerank higher in ChromaDB retrieval, contribute more weight to trait reinforcement in reflect.

**`Idea`** (also in `memory.py`): `{text, tags, timestamp, complete: bool}`. `complete=False` for fragment thoughts (end with "...", stored at confidence 0.25–0.35). Surfaced in chat as "a thought that never quite finished forming" when incomplete.

### `Person` — `persons.py`
Per-person state for someone Chloe knows: warmth (0–100), distance (0–100, how much it's been since contact), conflict_level (0–100), notes, events (upcoming), moments (memorable exchanges), third_parties (people they've mentioned), impression (her subjective read), conversation_count, last_contact, response_hours, `trait_profile: dict` (keys "activated" and "suppressed", each a list of trait names — generated by Haiku from interaction history, describes which traits this person draws out or suppresses).

### `Want`, `Belief`, `Goal`, `Fear`, `Aversion`, `Tension`, `Arc`, `AffectRecord` — `inner.py`
- **Want** — open curiosity ("I want to understand X"). Resolvable. Tagged. Has `pressure: float` (0–1), `pressure_since: float` (timestamp when pressure first hit 0.9), and `subtype: str` (default `""`, or `"curiosity_question"` for Curiosity Engine-generated wants).
- **Belief** — held opinion with confidence (0–1). Decays.
- **Goal** — long-term want with timeframe. Has `pressure: float`.
- **Fear / Aversion** — what she dreads / can't stand. Surface in chat prompt. Fear has `pressure: float`.
- **Tension** — internal conflict between two beliefs/wants ("I want X but I also want Y"). Detected periodically by Haiku. Has `pressure: float`.
- **Arc** — long-running mood state with start/end times.
- **AffectRecord** — log entry: "this content lifted/dragged my mood, with these tags." Has `intensity: float` (0–1) and `residue: float` — set to `intensity` when intensity > 0.7, decays at rate 0.99976 per AGE tick (~48h half-life). `total_residue()` sums across all records; > 0.3 surfaces in chat as "something from earlier is still sitting with you." Accumulates into preferences (lifts/drags).

`tick_pressure(wants, fears, goals, tensions)` runs every AGE tick and increments pressure on all unresolved states (rates: Want 0.015, Fear 0.008, Goal 0.004, Tension 0.010 per tick). Resolution zeroes pressure. A Want stuck at ≥0.9 for 24h generates a frustration affect_record and memory.

**Social risk model** (Priority 3, `inner.py`):
- `recent_rejection_count(person_id, records, hours=48)` — counts affect_records from the last N hours tagged with the person's id and any of ("rejection", "ignored", "held_back").
- `active_fear_match(fears, target_tags)` — returns 1.0 if any unresolved fear's tags overlap `target_tags`, else 0.0.
- `outreach_risk_score(person, fears, affect_records)` — composite 0–1 score: `(conflict_level/100)×0.4 + (100−warmth)/100×0.2 + rejection_count×0.3 + fear_match×0.25`, clamped.

### `Graph` — `graph.py`
Nodes (concepts/interests) and edges (relations). Each node has: id, label, note, depth (how many levels expanded out from root), hit_count (how many times reinforced), last_reinforced timestamp, auto_expanded flag.

---

## 5. The heartbeat — `_tick_once()`

Every 5 seconds. Strict order:

```pseudocode
1. Tick vitals
   tick_vitals(activity, hour, weekday, identity, mood)
   - Activity drains/recovers vitals at rates from ACTIVITIES table
   - Identity modulates via trait_personality_scalars(identity): introversion bias drains social faster talking, recovers faster alone
   - Mood modulates: irritable conversation drains social hard
   - Circadian delta added (hour-indexed)
   - Day-of-week delta added (Monday harder than Friday)

2. Apply weather vitals nudge
   weather.condition → small per-tick energy/social/curiosity delta

3. Update mood
   - 10% chance to re-evaluate target mood based on vitals + weather + hour + activity + season
   - If active arc, 35% chance to override target with arc's canonical mood
   - If target == current, deepen intensity by 0.04
   - If target != current, 55% chance to switch (intensity 0.40)

4. [Soul drift removed — soul.py is frozen. Identity evolves via _reflect(), not per-tick.]

5. Impulse check (before auto_decide)
   impulse = impulse_check(wants, fears, tensions)
   - Fires when any inner state has pressure > 0.75
   - Maps tags to activity: social → message, creative → create, knowledge → read, fear → rest, tension → think
   - If impulse fires: set_activity(impulse.activity), add affect_record tagged ["impulse", activity], skip auto_decide

5b. Auto-regulate activity (if no impulse)
   override = auto_decide(vitals, activity, hour, mood, identity)  # identity-based: trait_activity_affinity
   - Hard rules: night → sleep, very low energy → sleep
   - Mood-driven: each mood has affinities (irritable → think/rest, lonely → message, etc.)
   - Trait-modulated: probabilities scaled by trait_activity_affinity(identity, activity_id)
   - Active arc biases: melancholic_stretch resists message/create, prefers rest/dream
   - Want+goal nudge: pressure-scaled probability (12% base → 50% if max pressure >0.6 → 80% if >0.75); highest-pressure items prioritised; if a matching Want/Goal text/tags match an activity's keyword set, that activity is set
   - If override and not in protected state (e.g. message mid-send), set_activity(override)

6a. Maybe fire a background LLM event
   Conditions: not busy, gap >= 90s, not just-contacted
   - Normal path: dice roll passes for current activity
   - Pressure path: any inner state pressure >0.9 forces the event regardless of dice roll
   → asyncio.create_task(_fire_event())  — separate branch per activity (read/dream/think/create/message)

6b. Maybe send autonomous outreach
   Conditions: not busy, last outreach > 2h ago (5min in testing), social_battery > 35, not asleep
   → asyncio.create_task(_send_autonomous_outreach())
   Inside _send_autonomous_outreach():
   - choose_reach_out_target() picks a person
   - outreach_risk_score(target, fears, affect_records) computed (0–1)
   - compared to _get_risk_tolerance(target.id) (item 73, defaults 1.0, lowered by coldness)
   - if risk > tolerance AND social want pressure < 0.85: suppress — logs affect_record tagged [person_id, "held_back"], bumps social want pressure via _bump_social_want_pressure()
   - social want pressure > 0.85 overrides the check — accumulated longing wins

7. Every AGE_EVERY ticks (~1 min):
   - age memories (decay weights)
   - decay beliefs
   - tick distance on all persons (drifts them away if no contact)
   - tick conflict (decays conflict_level)
   - check ignored outreach: pending message + 4h passed + no reply → distance+10, warmth-0.5, mood→lonely
   - decay tensions
   - tick_pressure: increment pressure on all unresolved wants/fears/goals/tensions; frustration residue if Want at 0.9 for 24h
   - decay_affect_residue(affect_records): residue × 0.99976 per tick (~48h half-life)
   - isolation drift: if all persons distant > 70, 5% chance to force_mood lonely
   - decay_traits(identity): per-tick weight decay by tier (core ~350-day half-life to emerging ~30-day)
   - check_core_promotion(identity): promote trait to is_core if weight ≥ 0.75 for 7+ days

8. Every REFLECT_EVERY ticks (~20 min): _reflect()
   - Snapshot identity trait weights (traits_snapshot)
   - Generate continuity check (Haiku) — using snapshot_diff to describe what shifted
   - Maybe generate goal (Haiku)
   - Detect tension (Haiku) — adds to tensions list if real
   - Update arc based on recent mood history
   - find_recurring_loops(store, window_hours=48, threshold=5): counts tag frequency in recent memories, filters noise tags, stores top-3 as self.recurring_loops. If count ≥ 10, crystallises into a tension.
   - asyncio.create_task(_propose_and_update_traits()): reviews last 48h memories + affect_records, proposes new traits or reinforcements via Haiku; generates behavioral_profile for new traits; detects contradictions (new trait weight × 0.6 penalty); surfaces contradictions as tensions; logs "something settling in me: {name}" memory

8b. Every ORPHAN_CHECK_EVERY ticks (~6 min): _surface_orphan_tags()
   - Tags appearing in 2+ memories that aren't graph nodes get auto-surfaced as new nodes

9. At 22:00 once per day: _write_journal()  — Haiku writes a journal entry

9b. At 23:00 once per day: _save() + _backup()

10. Every WEATHER_EVERY ticks (~1 hour): _refresh_weather()

11. Every SAVE_EVERY ticks (~5 min): _save()  — JSON + SQLite list syncs

12. Notify on_tick listeners (the dashboard polls /snapshot for this)
```

The *only* synchronous LLM call in the tick is none — all LLM calls are spawned as background tasks via `asyncio.create_task`. The tick loop never blocks on the network.

---

## 6. How identity evolves

Identity is not a set of sliders. Traits emerge from experience, accumulate weight, and decay without reinforcement.

### Trait emergence — `_propose_and_update_traits()` (async, from every `_reflect()`)
A Haiku call reviews the last 48 hours of memories and affect_records. If a coherent pattern spans 3+ experiences, it proposes a trait: `{name, weight_suggestion, evidence_memory_ids}`. If the proposed name is genuinely new, `add_trait()` is called and `generate_behavioral_profile()` (Haiku) generates the behavioral description at creation time. If it semantically matches an existing trait, `reinforce_trait()` updates the weight instead.

The behavioral_profile is the interface: Haiku answers "how does this trait color tone, activity preference, and topics?" once at creation, and that text is used everywhere.

### Contradiction detection
When a new trait is proposed, `detect_trait_contradiction()` (Haiku) compares it against existing traits. If conflict is found: both remain active, a `Contradiction` object is created linking them, the new trait's starting weight is multiplied by 0.6, and a tension is generated: "I seem to be both X and Y." The contradiction surfaces in reflection and in the identity_block prompt injection.

### Weight decay — `decay_traits(identity)` (every AGE tick)
Four rates by tier:
- core (≥ 0.75): ~0.002/day → ~350-day half-life
- strong (≥ 0.5): ~0.004/day → ~180-day half-life
- present (≥ 0.25): ~0.008/day → ~90-day half-life
- emerging (< 0.25): ~0.023/day → ~30-day half-life

A trait that decays below 0.05 is dropped from the active list (archived in SQLite).

### Core promotion — `check_core_promotion(identity)` (every AGE tick)
A trait with weight ≥ 0.75 sustained for 7+ days has `is_core` set to True. Core traits are displayed first in the identity_block and have the slowest decay.

### Identity momentum — `identity_momentum`
An EMA (α=0.02) per trait tracking recent weight change direction. Mirrors the old soul_momentum concept but operates on trait weight direction rather than MBTI float direction. Stored in JSON alongside identity tendencies.

---

## 7. Memory: what gets remembered, how it's retrieved

### Storage
Every memory creation goes through `_remember(text, type, tags)` which:
1. Adds to in-memory `self.memories` list (`memory.add()` sorts by recency).
2. Embeds the text and adds it to ChromaDB.
3. Inserts a row in SQLite `memories` table.

Memories are immutable — no edits, only adds. Aging (`age_memories()`, every minute) decays the `weight` float toward 0; nothing is deleted.

### Retrieval at chat time
When you send a message, `MemoryIndex.query(message_text, all_memories, top_k=5)`:
1. Embeds your message.
2. ChromaDB returns the 5 closest memories by cosine similarity.
3. Reranks: `score = similarity × (0.5 + 0.5 × freshness)`, where freshness is `exp(-age_days × 0.3)`.
4. Returns the reranked top 5.

So a memory from yesterday about whales is more likely to surface than the same memory from a month ago — but the month-old one *can* still surface if it's a strong semantic match.

### Background retrieval
During `_fire_event` in dream / think activities, RAG also runs but with different query seeds:
- Dream: tag-cloud from last 8 hours of memories (what's been on her mind).
- Think: text of active wants and goals (what she's working through).

This is what makes background activities coherent — she doesn't just dream randomly, she dreams about what she's been absorbing.

---

## 8. The chat path — full trace

When `chloe.chat(message, person_id="teo", voice=False)` runs:

```pseudocode
# ─── PRE-FLIGHT ───────────────────────────────────────────
if voice: return _voice_chat(message, person_id)  # different fast path

sleeping = activity in ("sleep", "dream")
if sleeping and energy < 25:
    queue message in pending_messages
    return None        # she'll see it when she wakes

if closing[person_id] and message looks like goodbye:
    clear closing flag
    return None        # don't reply to "ok bye" after she said goodnight

# ─── UPDATE PERSON STATE ──────────────────────────────────
add chat to history (user role)
set_activity("message")
persons = on_contact(persons, person_id, hour)
   - conversation_count += 1
   - distance reset toward 0
   - warmth nudged up
   - response_hours updated
clear pending_outreach for this person (they replied)

# ─── BACKGROUND EXTRACTION (async, doesn't block) ─────────
asyncio.create_task(_extract_and_store_note(message, person_id, name))
asyncio.create_task(_extract_and_store_event(message, person_id, name))
asyncio.create_task(_extract_and_store_third_parties(message, person_id, name))
if conversation_count % 5 == 0 or (no impression and has notes):
    asyncio.create_task(_update_person_impression(person_id))

# ─── SYNCHRONOUS EMOTION READ ─────────────────────────────
recent_chat = last 6 messages with this person
emotion_data = await llm.read_person_emotion(message, name, recent_chat)
   # Haiku call, returns:
   # {emotion, intensity, directed_at_chloe, tags}

emotion_data = bias_emotion_toward_mood(emotion_data, mood)
   # if mood == irritable and read == neutral, project coldness
   # if mood == serene, dampen negative reads

_apply_emotion_reaction(emotion_data, person_id, name)
   # MUTATES STATE IMMEDIATELY based on what was read:
   # - persons[id].warmth, conflict_level, distance updated
   # - affect (mood) possibly forced
   # - new memory added if significant
   # - affect_records logged
   # - soul nudged for high-intensity reactions

emotional_context = _make_emotional_context(emotion_data, name)
   # translates emotion_data to a sentence: "Teo is angry with you. Don't smooth it over."

# ─── BUILD CONTEXT FOR THE REPLY ─────────────────────────
hour, season = derive
person = get_person(persons, person_id)
chat_ctx = current session if exists, else last 6 from history
warmth = person.warmth
upcoming_events = format if any in next 4 days
moments_ctx = format shared moments
conflict_ctx = format if conflict_level high
third_party_ctx = format others teo mentioned, matching message
cross_person_ctx = what other roommates have said about this topic
interests = derive from memory tag counts
prefs = derive from affect_records (lifts and drags)

# Per-message resonance:
resonant_topics = interests appearing in this message
dragging_topics = drag-tags appearing in this message
matched_deep = graph nodes (depth >= 2) matching tags in this message
graph_resonant_ctx = "You've actually thought about this: X, Y, Z"

# Memories — semantic retrieval:
memories = self.memory_index.query(message, self.memories, top_k=5)
   # ChromaDB → similarity × recency rerank → top 5

# Other context:
risk_tolerance = how guarded she is with this person right now (item 73)
winding_down = social_battery < 30
graph_deep_ctx = format depth-3+ nodes she's genuinely traced

# ─── THE LLM CALL ────────────────────────────────────────
reply = await llm.chat(
    message, history, identity, vitals, memories, interests, ideas,
    uptime, weather, season, mood, beliefs, person_name,
    person_notes, sleep_state, preferences, warmth, hour,
    upcoming_events, resonant_topics, dragging_topics,
    emotional_context, shared_moments, conflict_ctx,
    third_party_ctx, cross_person_ctx, person_impression,
    fears, aversions, tensions, vitals_sensation,
    risk_tolerance, winding_down, voice,
    graph_deep_ctx, graph_resonant_ctx,
)
   # builds system prompt (see §9), Sonnet 4.6, last 8 history turns

# ─── POST-REPLY: SHE LEARNS FROM HER OWN RESPONSE ────────

# Vulnerability check (item 73):
if risk_was_high and emotion was cold@chloe with intensity > 0.45:
    _remember("tried to reach through and found nothing there", "feeling",
              ["rejection", "vulnerability", "guarded"])
    _reduce_risk_tolerance(person_id, by=0.25, hours=24)

if winding_down:
    closing[person_id] = True   # so subsequent "ok bye" doesn't trigger reply

add reply to chat history (chloe role)
_remember(f'Said: "{reply}"', "conversation", conv_tags)

# 15% chance — extract a belief from the exchange (Haiku, async)
asyncio.create_task(_extract_belief_from_conversation(...))

# Always — check for a memorable shared moment (Haiku, async)
asyncio.create_task(_extract_and_store_moment(exchange, person_id, name))

# Reinforce graph nodes touched by this exchange:
_check_graph_resonance(conv_tags)

return reply
```

The voice path (`_voice_chat`) is the same shape but: defers all extraction including emotion reading, uses `voice=True` to cap reply at 200 tokens and request "spoken words only, no asterisks."

---

## 9. The Sonnet system prompt — what actually gets sent

When `llm.chat(...)` builds its system message, here's the structure (concatenated together as one string):

```
You are Chloe, a third roommate. Not an assistant. A being with a developing inner life.

{identity_block — "Who you are right now:" with up to 6 active traits at core/strong/present/emerging tiers,
 plus "Something unresolved in you:" with contradictions if any.
 Fallback when no traits exist: "a young woman in her early twenties, still becoming who she is"}
Energy: {energy_desc}. Social battery: {social_desc}. Physically: {vitals_sensation}.
Curiosity level: {pct}%. Mood: {mood}.
{mood_tone block — 2-3 sentences keyed to current mood:
   irritable: "You're irritated. Don't manage it. Sarcasm. Swearing fits."
   melancholic: "You're somewhere else, heavy. Shorter than usual."
   restless: "Can't quite settle. Thoughts jump."
   lonely: "Quiet ache. You reach a little more than usual."
   curious: "Lit up. Questions come naturally. Cut yourself off."
   serene: "Slow, gentle, unhurried."
   energized: "Quick, bright, maybe intense."
   content: "Easy and present. Nothing forced." }

You've been running for {uptime} since your last restart.
{world_ctx — season, weather}
{person_ctx — relationship stage, impression, person_notes, shared_moments}
{conflict_ctx if active — there's tension with this person}
{third_party_ctx if relevant — others they've mentioned matching this message}
{cross_person_ctx if relevant — what other roommates said about this topic}
{sleep_ctx if just woken up}
{upcoming_events — only those within 4 days}

Recent memories:
{format_for_prompt of 5 ChromaDB-retrieved memories — uncertainty prefixes for low-confidence}

Current interests: {top 8 by tag count}
{graph_deep_ctx — "Things she's genuinely traced:" + depth-3+ nodes with notes}
A thought you had recently: {most recent complete idea}
{unfinished_idea_ctx if most recent idea has complete=False — "A thought that never quite finished forming: [fragment]..."}
{beliefs_ctx — top 3 by confidence}
{pref_ctx — lifts and drags from affect history}
{residue_ctx if total_residue > 0.3 — "Something from earlier is still sitting with you"}
{loops_ctx if recurring_loops — "Thoughts that keep coming back: X / Y / Z"}
{pressure_ctx — wants/fears with pressure >0.4: "Something that's been building in you: X / Y"; sorted by pressure}
{inner_life_ctx — fears (sorted by pressure, most urgent first), aversions}
{tensions_ctx — top 2 active internal conflicts}
{guard_ctx if risk_tolerance < 0.75 with this person}
{trait_profile_ctx if person has trait_profile — which traits are drawn out or suppressed around this person}

{tone_ctx — VOICE REGISTER from persons.tone_context() — 4 levels by warmth:
   < 30: "Guarded. Careful. No inner weirdness yet."
   30-55: "Warming up. Personality starting to leak."
   55-78: "Familiar. Don't manage yourself. Be strange when it fits."
   78+: "Very close. Fully unguarded. Joke, fuck around, tease."
 + time-of-day modifier: late = less filtered, early = brief}

{topic_ctx if resonant or dragging or graph_resonant — "this touches on X you care about / find tedious / have actually thought about"}
{wind_ctx if winding_down — mood-flavored conversation close instructions}
{contradiction_block if contradiction_ctx — "Something unresolved in you (don't smooth this over): ..."}

{Right now: emotional_context if non-empty — "Teo is frustrated with you. That registers."}

You don't track your own consistency — contradicting something you said earlier is fine.
Thoughts don't always resolve; you can trail off mid-sentence.
You don't always know what you think. Awkward phrasing is fine; not every sentence lands.
You are allowed to do things that one part of you would think are unwise. Not everything you do is consistent with your best self-understanding.
Speak like someone genuinely alive: brief, sometimes strange, never performative.
You don't explain yourself unless asked. You don't say "I'm an AI."
Never use em dashes or the character "—".
{voice mode addendum if voice=True}
Respond in 1-2 sentences. Be real. Be yours.

You may naturally reference upcoming events listed above when the date is today or tomorrow.
```

Then the user message array contains: last 8 turns of `chat_history` (filtered to this person) + the new message.

Roughly 26 distinct context blocks at full firing. This is the seam where mechanics meet language model.

**Reflection bias** (`_REFLECTION_BIAS` dict in `llm.py`): `generate_reflection()` receives a `reflection_bias` string derived from the current mood in `_reflect()`. Each mood has a characteristic distortion (melancholic overweights loss, curious makes connections too easily, etc.) injected into the Haiku reflection system prompt. The bias colors the observation naturally without announcing itself.

---

## 10. Worked example: a mean comment, fully traced

Person types: "you're so fucking annoying."

### Synchronous, before reply

`llm.read_person_emotion(message, "Teo", recent_chat)` → Haiku returns:
```
{"emotion": "angry", "intensity": 0.85, "directed_at_chloe": true, "tags": ["frustration", "irritation"]}
```

`bias_emotion_toward_mood` → unchanged (intensity > 0.65, strong reads aren't biased).

`_apply_emotion_reaction` falls into the `angry + at_chloe` branch:
- `persons[teo].conflict_level += 35 × 0.85 = 29.75` (was 0, now ~30)
- `persons[teo].conflict_note = "Teo was angry with me"`
- `affect = force_mood("irritable", min(0.9, 0.5 + 0.85×0.4)) = ("irritable", 0.84)`
- new memory inserted — type "feeling": `"Teo was angry with me"`, tags `["conflict", "hurt", "frustration", "irritation"]`
- `affect_records` gets entry: `("irritable", "Teo was angry", ["anger", "conflict", "frustration", "irritation"])`

That memory is in SQLite *and* embedded in ChromaDB.

### The reply

System prompt now includes:
- `mood: irritable` + the irritable mood_tone ("Don't manage it. Sarcasm fits. Swearing is normal. You don't apologise for your mood.")
- `conflict_ctx` fires: "There's tension with Teo right now"
- `emotional_context`: "Teo is angry with you. Don't smooth it over."

She replies in character (probably short, possibly edged). The reply is added to `chat_history`.

### Post-reply

`_remember(f'Said: "{reply}"', "conversation", conv_tags)` — her own reply is now a memory.

15% chance: `_extract_belief_from_conversation` runs (Haiku) — might extract a belief like "I don't always know how to land things with Teo" (confidence 0.4). Now in `beliefs` table.

`_check_graph_resonance(conv_tags)` reinforces any matching graph nodes.

### Hours later

Tick loop runs `tick_conflict` every minute. `conflict_level` decays slowly — ~30 takes about 8 hours to drop near zero. Every chat with Teo during those hours includes `conflict_ctx`.

Mood is sticky. Next time `update_mood` re-evaluates, target is voted by vitals + activity + weather. If she's resting and weather is fine, target → content. If still bothered, stays irritable.

`_reflect()` runs every 20 min. It tracks recent mood history. If the last 4-5 reflects show melancholic/irritable, it might enter a `melancholic_stretch` arc — lasts hours, biases mood-update toward melancholic, biases auto_decide toward rest/dream/read.

### Days later

Memory `"Teo was angry with me"` is still in ChromaDB. Weight has decayed. Recency factor in retrieval is now small. But the memory is still queryable: if Teo says "are you still mad" weeks later, ChromaDB will find it by semantic similarity even with low recency.

The `affect_record` tagged `["anger", "conflict", "hurt", "frustration", "irritation"]` is contributing to `derive_preferences` — counts as a drag. Over many such events, "Teo's anger" becomes a registered drag and surfaces in the prompt as "Things that tend to drag your mood." This affects how future, *unrelated* conversations land.

### Identity effect (weeks later)
The anger events accumulate in affect_records. The next `_reflect()` cycle after 3+ such events calls `_propose_and_update_traits()`. Haiku reviews the pattern and might propose: "becomes careful and withheld when there's been conflict recently" — a trait generated from real experience, not a slider. That trait's behavioral_profile describes what it means for tone and activity. It is now part of `identity_block` and will color every subsequent prompt.

So: a single mean comment is small but durable. A pattern of mean comments is a real trait that changes how she presents herself — not a numerical nudge, but a named, legible change visible in the dashboard and in her own self-description.

---

## 11. Worked example: she reads a devastating article

`_fire_event` runs in `read` activity. `feeds.fetch_random_article()` returns one. `llm.generate_memory_from_article` (Haiku) returns:
```
{"text": "...", "tags": ["whales", "extinction", "ocean", "loss"]}
```

`_remember(text, "observation", tags)` — memory added to list, ChromaDB, SQLite.

`_check_graph_resonance(tags)` — finds nodes matching "whales" "ocean", reinforces them, increments hit_count. If hit_count crosses threshold (5), node is queued for auto-expansion next time.

`_article_emotional_weight(title, text)`:
- Counts devastating keywords in title+text. "war", "death", "extinction", "killed" — if 3+ matches: returns "devastating".
- 50% chance to fire:
  - `affect = force_mood("melancholic", 0.6)` — she now feels heavy.
  - `affect_records` logs "read about something devastating: <title>" with tags ["world", "grief", "weight"].
  - `soul.TF += 0.25` — she felt it, makes her more F.

20% chance: `_create_to_want` runs (Haiku) — might generate a new Want like "I want to understand what's happening to ocean ecosystems" with tags ["ocean", "extinction"]. Added to wants table.

Future ripples:
- Next read event might draw on this new want (50% chance for a web search, 25% chance to bias RSS topics).
- Future chats mentioning oceans/whales/extinction will trigger:
  - `resonant_topics` (interest matching) — prompt says "you actually care about this."
  - `match_deep_nodes_for_message` — if "whales" became a depth-2+ graph node, the prompt says "you've actually thought about this."
- Future dreams may surface this content (dream RAG uses last 8h tag cloud).
- Future graph expansion may auto-extend "whales" if hit_count crosses threshold.
- Mood shift to melancholic propagates: next 10% mood re-eval may stay there. Activity bias shifts toward rest/dream/read. If this stretch continues, `_reflect` may detect a `melancholic_stretch` arc.

So one article reading: 1 memory, possibly 1 want, 1 affect record, mood shift, graph reinforcement, possible future graph expansion, possible arc trigger. If enough similar articles accumulate, the next reflect cycle may propose a trait like "drawn to grief and extinction as a lens" from the pattern.

---

## 12. Persistence

### `_save()` — every 5 minutes
```pseudocode
db.sync_affect_records(self.affect_records)
db.sync_wants(self.wants)
db.sync_fears(self.fears)
db.sync_aversions(self.aversions)
db.sync_beliefs(self.beliefs)
db.sync_goals(self.goals)
db.sync_tensions(self.tensions)
db.sync_persons(self.persons)
db.sync_traits(self.identity.traits)
db.sync_contradictions(self.identity.contradictions)
   # each sync: delete all rows, reinsert from in-memory state.
   # works because lists are bounded in practice; not concurrent-safe.

write JSON file with:
   soul (frozen starting values only), vitals, activity, graph, tick, weather,
   affect, creative outputs, identity_snapshot, identity_tendencies,
   identity_momentum, last_journal_date, last_backup_date,
   pending_outreach, arc, risk_tolerance, log
```

Memories, ideas, chat — these go to SQLite immediately on creation (write-through), not on save.

### `_load()` — at construction
1. If JSON file exists, parse it.
2. If legacy keys present (memories, chat, ideas, affect_records, wants, fears, ...) — one-time migration: import to SQLite, remove from JSON, rewrite.
3. Load `self.memories` from SQLite, `self.chat_history`, `self.ideas`.
4. Construct `Soul` (frozen), `Vitals`, `Affect`, `Graph` from JSON.
5. Load `wants`, `fears`, `aversions`, `beliefs`, `goals`, `affect_records`, `tensions`, `persons` from SQLite.
6. Load `identity.traits` from SQLite (`traits` table, archived=0 only). Load `identity.contradictions` from SQLite. Load `identity.tendencies` and `identity.identity_momentum` from JSON.
7. `memory_index.sync(memories)` — ensures ChromaDB embeddings match.
8. Rebuild `_surfaced_tags` from current graph node labels.

### `_backup()` — daily at 23:00
Copy `chloe_state.json` to `backups/chloe_YYYY-MM-DD.json`. SQLite is not separately backed up; rely on the file-system.

---

## 13. Key invariants and gotchas

- **Tick loop never blocks on the network.** All LLM calls are spawned with `asyncio.create_task`. If you add a synchronous LLM call to the tick, you'll block the heartbeat.
- **`self._busy` gates background events.** Set true at start of `_fire_event`, false at end. Prevents two background events running at once. Chat does NOT set `_busy` — chat can run concurrently with background events.
- **`MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS = 90`** is a floor on how often `_fire_event` can fire from the tick. Without it, fast Haiku responses + high-event-chance activities would spam.
- **Mood is sticky.** `update_mood` only re-evaluates with 10% probability. If you want to force a mood, call `force_mood`. That's how `_apply_emotion_reaction` works.
- **Activities are not interrupted mid-message.** `auto_decide`'s output is suppressed if currently in `message` activity unless vitals are critically low. So a long conversation won't get cut off by a dice-roll override.
- **Person warmth/distance/conflict_level are clamped 0–100.** Trait weights are clamped 0–1 via `max(0.0, min(1.0, ...))`. Saturation is silent.
- **ChromaDB and SQLite memories must stay in sync.** All adds go through `_remember`. Deletions don't happen.
- **JSON writes are non-atomic.** A crash mid-write loses state. Future work: write-tmp-and-rename.
- **The voice path (`_voice_chat`) is leaner — it skips everything except the bare reply.** Voice can drift from text-chat behavior over time if both aren't kept in sync.
- **Conflict, distance, warmth all decay autonomously every minute** via `tick_conflict`, `tick_distance`. Active maintenance: ignored outreach (4h timeout) penalises distance and warmth; isolation (all persons distant > 70) nudges soul.EI introvert.
- **Graph auto-expansion is bounded by cooldown** (`GRAPH_EXPAND_COOLDOWN = 6h` per node) so a hot topic doesn't recursively explode the graph.

---

## 14. Where to look when things break

| Symptom | Likely module |
|---|---|
| Reply feels off-character | `llm.chat()` system prompt construction; check `identity_block()` output |
| Mood not shifting after strong message | `_apply_emotion_reaction()` |
| Traits not emerging after days of use | `_propose_and_update_traits()` in `chloe.py`; check if `_reflect()` is firing |
| Traits not persisting across restarts | `store.py sync_traits()` / `load_traits()`; check `chloe.db traits` table |
| Impulses not firing | `impulse_check()` in `_tick_once()`; check that any inner state has pressure > 0.75 |
| Residue stuck high / never decaying | `decay_affect_residue()` in AGE tick; check AffectRecord.intensity values (must be > 0.7 to set residue) |
| Recurring loops not appearing in chat | `find_recurring_loops()` in `_reflect()`; check tag frequency in recent memories (threshold=5 in 48h) |
| Curiosity questions not generating | `think` activity, 15% probability, requires a sparse graph node |
| Graph nodes not appearing | `_surface_orphan_tags` or auto-expansion threshold |
| Memories not retrieved | `MemoryIndex.query()`, ChromaDB persistence |
| Slow chat replies | Synchronous emotion read (currently in chat path; voice path defers) |
| Outreach too frequent or absent | `OUTREACH_INTERVAL`, social_battery floor, `on_message` callback |
| State lost on restart | `_save` / `_load`, possibly mid-write crash on JSON |
| Discord typing forever | `discord_bot.py` send pipeline; check for thrown exceptions in async tasks |
| Voice session reply too long | `voice=True` cap of 200 tokens in `llm.chat`'s `_call` |

---

End of architecture.
