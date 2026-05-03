# Chloe — Architecture

This document describes the *current* implementation. Future direction is in `02_CLAUDE.md`.

The goal of this document is that someone (or future-you) can understand how every piece of state is shaped, where it lives, and how a single event ripples through everything else. If you read it once front-to-back, you should know what happens when she reads an article, when she gets a mean message, and what determines what comes out of `chat()`.

---

## 1. Mental model

Chloe is one Python object (`Chloe`, defined in `chloe/chloe.py`) with a continuously running async loop. All her state hangs off that object. Two things drive change:

1. **The tick** — every 30 seconds, autonomously. Updates vitals, updates mood, decides what activity she should be in, sometimes spawns a background LLM event (read an article, dream, think, create, send a message).
2. **An incoming message** — reactive. Reads the emotion behind it, updates her in-memory state, builds a giant context, calls Sonnet, then learns from her own reply.

Everything else — persistence, the dashboard, Discord — is plumbing around those two drivers.

### State layered by change-rate

| Layer | Timescale | Sticky? | Where |
|---|---|---|---|
| Vitals (energy, social_battery, curiosity, focus, inspiration) | tick (30s) | no, continuously flowing | `Vitals` in `heart.py` |
| Mood (one of 8 labels, with intensity) | minutes, sticky | yes, only re-evaluates 10% of ticks | `Affect` in `affect.py` |
| Active arc (long mood state like "melancholic_stretch") | hours, capped at 36h | yes, ends explicitly | `Arc` in `inner.py` |
| Identity (emergent traits, weights 0–1) | weeks to months | yes, decay-tracked | `Identity` in `identity.py` |
| Memories, beliefs, wants, etc | persistent, age slowly | n/a — accumulate | SQLite |

Don't collapse the layers — that's why mood doesn't follow vitals tick-by-tick, why identity doesn't lurch on a single article, why the arc exists at all. The point is to model human time-scales, not just "feel state."

---

## 2. The tech stack, concretely

### Python 3.13 main app
`uvicorn server:app --port 8000` boots FastAPI which constructs the `Chloe` instance, calls `await chloe.start()` to kick off the heartbeat, and serves HTTP endpoints for the dashboard. Deployed on a Hetzner VPS.

### Google Gemini LLM (two tiers)
- `MODEL_CHAT = "gemini-2.5-pro"` — only used for live chat (`chat()`, `_voice_chat()`) and autonomous outreach (`generate_autonomous_message`). The stuff a human reads.
- `MODEL_FAST = "gemini-2.5-flash"` — everything else: emotion reading, memory grading, memory generation, idea generation, dream generation, person impressions, third-party detection, belief extraction, search query writing, tension detection, shared moment detection, trait proposals, behavioral profile generation. Anything that's structured or background.

All calls go through `_call(system, messages, max_tokens, model, cache_prefix)` in `llm.py`. The `_call` wrapper does em-dash stripping at the source so the dashes never reach the user.

**`cache_prefix`**: an optional string that, when set, is prepended to the system prompt. The ~150-token `_CHLOE_INNER_LIFE` character description is passed as `cache_prefix` in all 10 background generation functions (`generate_memory`, `generate_idea`, `generate_reflection`, `generate_journal`, etc.) so it isn't repeated inline in every system string.

### ChromaDB (semantic memory index)
A persistent client at `<state_file_dir>/memory_index/` embeds every memory's text. At live chat time, a three-stage pipeline runs:
1. Rich query constructed from the current message + last 5 conversation turns + mood
2. ChromaDB returns 20 candidates, reranked by `similarity × freshness × salience_boost`
3. Flash grader (`grade_memories()`) filters to the 4-5 most genuinely relevant

Background events (reflection, dreaming, outreach) use a simpler single-step retrieval with activity-specific query seeds. Falls back to recency-only (`get_vivid`) if ChromaDB is unavailable.

### SQLite — `data/chloe.db`
WAL mode. Holds everything that's unbounded or relational:
- `memories` (each with type, tags, weight, confidence, timestamp, salience)
- `ideas`, `chat_history`, `affect_records`
- `wants`, `fears`, `aversions`, `beliefs`, `goals`, `tensions`
- `persons` + sub-tables: `person_notes`, `person_events`, `person_moments`, `person_third_parties`
- `traits` (id, name, weight, behavioral_profile, origin_memory_ids, last_reinforced, created, is_core, setback_count, setback_notes, archived)
- `contradictions` (id, trait_a_id, trait_b_id, description, created)

Write-through pattern: in-memory operations call `add_memory()` etc. on the `ChloeDB`, which inserts to SQLite immediately for memories/ideas/chat. List state (wants, beliefs, etc.) syncs every save (every ~30 min) via `sync_*` methods that delete-and-reinsert.

### JSON — `data/chloe_state.json`
Holds atomic-changing scalars that don't fit the relational model: soul values (frozen starting values only), vitals, current activity, current mood, the graph, the active arc, identity_snapshot, identity_tendencies, identity_momentum, pending outreach, last journal/backup dates, the runtime log buffer.

### Backups
At 23:00 daily, `_backup()` copies `data/chloe_state.json` to `backups/chloe_YYYY-MM-DD.json`. SQLite is not currently backed up the same way.

### Frontend — `index.html`
Single HTML file, no build step. Polls `GET /snapshot` every 4 seconds, renders vitals bars, mood pill, interests cloud, graph canvas, etc. Sends chat through `POST /chat`.

### Voice — `voice/app.py` (separate process)
Optional, runs in `.fishvenv` (Python 3.11) because Fish Speech needs an older Torch. Starts the brain server and Fish Speech automatically. Captures audio with Whisper, calls `chloe.chat(message, voice=True)` against the running server, plays the reply through Fish Speech 1.5.

### Discord — `discord_bot.py`
Optional. Starts in the FastAPI lifespan if env vars are set. Routes incoming DMs to `chloe.chat()` with the right `person_id`. Outgoing autonomous messages are sent through a "realistic send pipeline" with typing indicators and per-message delays.

---

## 3. Repo and modules

```
Chloe/
  chloe/
    chloe.py        — central orchestrator, holds all state, runs the loop
    identity.py     — trait system: Trait, Contradiction, Tendencies, Identity
    soul.py         — [DEPRECATED] MBTI floats, frozen at starting values, not used
    heart.py        — vitals, activities, circadian, day-of-week, auto_decide
    affect.py       — mood as a state separate from vitals
    memory.py       — Memory dataclass + ChromaDB index + Idea
    persons.py      — Person + warmth/distance/conflict + tone_context (voice register)
    inner.py        — Want, Belief, Goal, Fear, Aversion, Tension, Arc, AffectRecord
    graph.py        — interest graph: nodes, edges, expansion, resonance
    llm.py          — every Gemini call lives here (~27 functions)
    feeds.py        — RSS, web fetch, web search
    weather.py      — Open-Meteo client
    store.py        — ChloeDB SQLite write-through
    discord_bot.py  — DM bridge
    avatar.py       — portrait selection from activity/mood
  voice/
    app.py          — self-contained voice UI (separate process, Python 3.11)
    legacy.py       — older push-to-talk voice interface
    pipeline.py     — zero-latency Deepgram streaming pipeline
  assets/images/    — action and emotion portraits served via /media/chloe/
  server.py         — FastAPI app
  index.html        — dashboard
  cli.py            — terminal client
```

---

## 4. The state-bearing dataclasses

### `Identity` — `identity.py`
The active trait profile. Four dataclasses:
- **`Trait`** — `{id, name, weight (0–1), behavioral_profile, origin_memory_ids, last_reinforced, created, is_core, setback_count, setback_notes}`. `name` is plain language, generated by Haiku from experience patterns. `behavioral_profile` is Haiku-generated text describing how this trait colors tone, activities, and topics. `is_core` becomes true when weight ≥ 0.75 sustained for 7+ days.
- **`Contradiction`** — `{id, trait_a_id, trait_b_id, description, created}`. Two conflicting traits that coexist without resolution.
- **`Tendencies`** — seed biases that make certain trait types more likely to emerge first (`introspective: 1.3`, `pattern_seeking: 1.2`, `relational: 1.2`, `open_ended: 1.1`, `aesthetic: 1.0`). Scaffolding, not identity.
- **`Identity`** — holds `traits: list[Trait]`, `contradictions: list[Contradiction]`, `tendencies: Tendencies`, `identity_momentum: dict` (EMA of per-trait weight change direction).

`identity_block(identity)` formats the prompt block: "Who you are right now:" with up to 6 traits at core/strong/present/emerging tiers, plus unresolved contradictions. Falls back to "a young woman in her early twenties, still becoming who she is" when no traits exist yet.

**Trait cap**: at most 10 active traits at any time. When at the cap, `_propose_and_update_traits()` is skipped entirely.

### `Soul` — `soul.py` [DEPRECATED]
Kept frozen at starting values for legacy reasons only. No longer referenced by any active code. `heart.py` was fully migrated to `identity`. Do not extend.

### `Vitals` — `heart.py`
Five floats, each 0–100: energy, social_battery, curiosity, focus, inspiration. Updated every tick (30s) by `tick_vitals()`. They gate behavior (low energy → can't reply, low social → wind down) and feed the mood layer.

### `Affect` — `affect.py`
`{mood: str, intensity: float}`. One of 8 moods. Sticky (10% re-evaluation per tick). Each mood has a color and short description in `MOODS`.

### `Memory` — `memory.py`
`{text, type, tags, weight, confidence, timestamp, id, salience}`. Type is one of: observation, conversation, idea, feeling, interest, dream, creative. Weight decays over time via `age()`. Confidence ≤ 0.5 surfaces with uncertainty prefixes. Both stored in SQLite and embedded in ChromaDB.

`salience: float` — set at creation from the emotional intensity of the generating event. High-salience memories: decay more slowly (half-life 1.5× normal), rerank higher in ChromaDB retrieval, contribute more weight to trait reinforcement.

**`Idea`** (also in `memory.py`): `{text, tags, timestamp, complete: bool}`. Capped at 10 in memory — oldest drop when at limit. `complete=False` for fragment thoughts. Surfaced in chat as "a thought that never quite finished forming" when incomplete.

### `Person` — `persons.py`
Per-person state: warmth (0–100), distance (0–100), conflict_level (0–100), notes, events, moments, third_parties, impression, conversation_count, last_contact, response_hours, `trait_profile: dict` (which traits this person draws out or suppresses), `attachment_pattern: str` (Haiku-generated relational style), `messaging_disabled: bool`.

### `Want`, `Belief`, `Goal`, `Fear`, `Aversion`, `Tension`, `Arc`, `AffectRecord` — `inner.py`
- **Want** — open curiosity. Resolvable. Has `pressure: float`, `pressure_since: float`, `subtype: str`.
- **Belief** — held opinion with confidence (0–1). Decays.
- **Goal** — long-term want with timeframe. Has `pressure: float`, `failed: bool`.
- **Fear / Aversion** — what she dreads / can't stand. Fear has `pressure: float`.
- **Tension** — internal conflict between two beliefs/wants. Has `pressure: float`.
- **Arc** — long-running mood state. Max intensity 0.70. Deepening caps at 36h total duration. Only four types: `melancholic_stretch`, `restless_phase`, `curious_spell`, `withdrawn_period`.
- **AffectRecord** — log entry with `intensity: float` and `residue: float`. Residue set to intensity when > 0.7, decays at 0.99976/tick (~48h half-life). `total_residue() > 0.3` surfaces in chat.

`tick_pressure()` runs every AGE tick. Resolution zeroes pressure. A Want at ≥0.9 for 24h generates frustration affect_record + memory + light trait penalty.

### `Graph` — `graph.py`
Nodes (concepts/interests) and edges. Each node: id, label, note, depth, hit_count, last_reinforced, auto_expanded flag.

---

## 5. The heartbeat — `_tick_once()`

Every 30 seconds. Strict order:

```pseudocode
1. Tick vitals
   tick_vitals(activity, hour, weekday, identity, mood)
   - Activity drains/recovers vitals at rates from ACTIVITIES table
   - Identity modulates via trait_personality_scalars(identity)
   - Mood modulates: irritable conversation drains social hard
   - Circadian delta added (hour-indexed)
   - Day-of-week delta added

2. Apply weather vitals nudge

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
   - If impulse fires: set_activity(impulse.activity), add affect_record, skip auto_decide

5b. Auto-regulate activity (if no impulse)
   override = auto_decide(vitals, activity, hour, mood, identity)
   - Hard rules: night → sleep, very low energy → sleep
   - Mood-driven: each mood has affinities (irritable → think/rest, lonely → message, etc.)
   - Trait-modulated: probabilities scaled by trait_activity_affinity(identity, activity_id)
   - Active arc biases: melancholic_stretch resists message/create, prefers rest/dream
   - Want+goal nudge: pressure-scaled probability; highest-pressure items prioritised

6a. Maybe fire a background LLM event
   Conditions: not busy, gap >= 1h since last event, no recent contact (5 min window)
   - Normal path: dice roll passes for current activity (event_chance scaled to tick_seconds)
   - Activity "message" bypasses dice roll — always fires if gap is met
   - Pressure path: any inner state pressure >0.9 forces event regardless of dice roll
   → asyncio.create_task(_fire_event())
   Note: old value was 90s (960 events/day, €25/day). Current 3600s → ≤16 events/day.

6b. Maybe send autonomous outreach
   Conditions: not busy, last outreach > 48h ago (10min in testing), social_battery > 60,
               not asleep, on_message callback exists, target not in quiet_until window
   → asyncio.create_task(_send_autonomous_outreach())
   Inside: choose_reach_out_target() picks a person → outreach_risk_score() checked →
           if risk > tolerance AND social want pressure < 0.85: suppress + bump pressure
           social want pressure > 0.85 overrides — accumulated longing wins

   Quiet mode: if person sends "I'm busy" / "don't text" / "I'll text you" etc., outreach
   to that person is suppressed for 24h (_quiet_until).

7. Every AGE_EVERY ticks (~6 min):
   - age memories, decay beliefs
   - tick_distance + tick_conflict on all persons
   - check ignored outreach: pending message + 4h + no reply → distance+10, warmth-0.5, mood→lonely
   - decay tensions, decay_affect_residue
   - tick_pressure: increment pressure on all unresolved wants/fears/goals/tensions
   - decay_traits(identity), check_core_promotion(identity)

8. Every REFLECT_EVERY ticks (~2 hours): _reflect()
   - Snapshot identity trait weights
   - Generate reflection (Haiku) — with topic rotation: tags from last 5 reflections that appear
     2+ times are passed as "don't revisit these themes"
   - Generate continuity check (Haiku) using snapshot_diff
   - Detect tension (Haiku)
   - Update arc based on recent mood history (3 consecutive same-mood reflects → arc forms;
     arc deepens at most +2h per reflect, capped at 36h; intensity capped at 0.70)
   - find_recurring_loops: if count ≥ 10 → crystallise as tension
   - Every 3rd reflect cycle AND fewer than 10 active traits:
     asyncio.create_task(_propose_and_update_traits())

8b. Every ORPHAN_CHECK_EVERY ticks (~2 h): _surface_orphan_tags()

9. At 22:00 once per day: _write_journal()

9b. At 23:00 once per day: _save() + _backup()

10. Every WEATHER_EVERY ticks (~6 hours): _refresh_weather()

11. Every SAVE_EVERY ticks (~30 min): _save()

12. Notify on_tick listeners
```

The *only* synchronous LLM call in the tick is none — all LLM calls are spawned as `asyncio.create_task`. The tick loop never blocks on the network.

---

## 6. How identity evolves

Identity is not a set of sliders. Traits emerge from experience, accumulate weight, and decay without reinforcement.

### Trait emergence — `_propose_and_update_traits()` (async, every 6th `_reflect()`)

Only fires when:
- `_reflect_count % 6 == 0` (every 6th cycle, so at most every ~12 hours)
- Active trait count < `MAX_ACTIVE_TRAITS` (10)

A Haiku call reviews the last 48 hours of memories and affect_records. If a coherent pattern spans **5+ experiences**, it proposes at most **1 trait**: `{name, weight_suggestion, evidence_memory_ids}`.

Traits must be **broad behavioral tendencies** — how she generally operates, not situational reactions. Explicitly excluded: existential questioning, consciousness, mortality, identity dissolution, abstract metaphysical themes.

If the proposed name is genuinely new, `add_trait()` is called and `generate_behavioral_profile()` (Haiku) generates the behavioral description. If it semantically matches an existing trait, `reinforce_trait()` updates the weight instead.

### Contradiction detection
When a new trait is proposed, `detect_trait_contradiction()` (Haiku) compares against existing traits. If conflict is found: both remain active, a `Contradiction` object links them, the new trait's starting weight is multiplied by 0.6, and a tension is generated.

### Reflection topic rotation
Before generating each reflection, `_reflect()` scans the last 5 reflection memories for tags appearing 2+ times. Those overused tags are passed to `generate_reflection()` as "don't return to these — find something fresh." This breaks compounding feedback loops where the same theme keeps seeding itself.

### Arc safety caps
Arcs form after 3 consecutive reflects with the same mood. Each deepening step adds +2h (max total 36h) and +0.03 intensity (max 0.70). These caps prevent a melancholic arc from spiraling into a permanent state.

### Weight decay — `decay_traits(identity)` (every AGE tick)
Four rates by tier:
- core (≥ 0.75): ~0.002/day → ~350-day half-life
- strong (≥ 0.5): ~0.004/day → ~180-day half-life
- present (≥ 0.25): ~0.008/day → ~90-day half-life
- emerging (< 0.25): ~0.023/day → ~30-day half-life

A trait decaying below 0.05 is dropped from the active list (archived in SQLite).

### Core promotion
A trait with weight ≥ 0.75 sustained for 7+ days has `is_core` set to True.

### Failure consequences — C2
Frustrated Wants apply a light trait penalty (−0.04) to matching traits. Failed Goals apply −0.08. Three setbacks on the same trait generates a suppression belief ("I don't seem to be the kind of person who X").

---

## 7. Memory: what gets remembered, how it's retrieved

### Storage
Every memory creation goes through `_remember(text, type, tags, salience)` which:
1. Adds to in-memory `self.memories` list.
2. Embeds the text and adds it to ChromaDB.
3. Inserts a row in SQLite `memories` table.

Memories are immutable — no edits, only adds. Aging decays the `weight` float toward 0; nothing is deleted.

### Live conversation retrieval — 3-stage pipeline

When a message arrives, memory retrieval runs before the Sonnet call:

**Stage 1 — Query construction**
`_build_memory_query(message, chat_ctx[-5:], mood)` combines the incoming message with the last 5 conversation turns and the current mood (if emotionally distinctive). This gives the embedder real topic signal rather than a single bare sentence.

**Stage 2 — ChromaDB + reranking (20 candidates)**
`MemoryIndex.query(rich_query, memories, n=20)`:
1. Embeds the rich query.
2. ChromaDB fetches 60 candidates (3× n).
3. Reranks: `score = similarity × (0.5 + 0.5 × freshness) × salience_boost`
   - `freshness = weight × exp(-age_days × 0.3) × confidence`
   - `salience_boost = 1.0 + 0.2 × salience` (up to +20% for emotionally intense memories)
4. Returns top 20.

**Stage 3 — Haiku grader**
`grade_memories(candidates_20, message, chat_ctx[-5:], mood, keep=5)`:
A Haiku call reads the 20 candidates alongside the conversation context and returns the IDs of the 4-5 that would *meaningfully* inform how she thinks, feels, or responds — not just semantic adjacency. Falls back to top-5 candidates on error.

### Background retrieval
During `_fire_event` in dream/think/create/message activities, RAG runs with activity-specific query seeds and no grader:
- Dream: tag-cloud from last 8 hours of memories
- Think: text of active wants and goals
- Message/outreach: most recent idea + mood

---

## 8. The chat path — full trace

When `chloe.chat(message, person_id="teo", voice=False)` runs:

```pseudocode
# ─── PRE-FLIGHT ───────────────────────────────────────────
if voice: return _voice_chat(message, person_id)

sleeping = activity in ("sleep", "dream")
if sleeping and energy < 25:
    queue message in pending_messages; return None

if closing[person_id] and message looks like goodbye: return None

# ─── UPDATE PERSON STATE ──────────────────────────────────
add chat to history (user role)
set_activity("message")
persons = on_contact(persons, person_id, hour)
clear pending_outreach for this person
if message matches quiet_request: _set_quiet(person_id, 24h)

# ─── IMPRESSION UPDATE (async, periodic) ──────────────────
if conversation_count % 10 == 0 (or first time with notes):
    asyncio.create_task(_update_person_impression(...))

# ─── SYNCHRONOUS EMOTION READ ─────────────────────────────
# Skipped for short messages (< 15 chars) — saves a Haiku call on greetings/oks
if not voice and len(message) >= 15:
    emotion_data = await llm.read_person_emotion(message, name, last_6_messages)
    emotion_data = bias_emotion_toward_mood(emotion_data, mood)
    _apply_emotion_reaction(emotion_data, person_id, name)
       # MUTATES STATE: warmth, conflict, mood possibly forced, memory added, affect_records logged

# ─── BUILD CONTEXT ────────────────────────────────────────
chat_ctx = current session history (up to 10) or last 6 from history
interests, prefs, upcoming_events, moments_ctx, conflict_ctx, third_party_ctx, ...

# Resonance checks (no API call):
resonant_topics = interests appearing in this message
dragging_topics = drag-tags appearing in this message
matched_deep = graph nodes (depth >= 2) matching message tags

# ─── MEMORY RETRIEVAL (3-stage) ───────────────────────────
_mem_q = _build_memory_query(message, chat_ctx, mood)   # rich query
_candidates = memory_index.query(_mem_q, memories, 20)  # ChromaDB → 20 reranked
_graded = await llm.grade_memories(_candidates, message, chat_ctx, mood)  # Haiku → 5

# ─── THE LLM CALL ────────────────────────────────────────
reply = await llm.chat(
    message, history, identity, vitals, memories=_graded, interests, ideas,
    uptime, weather, season, mood, beliefs, person_name, person_notes,
    sleep_state, preferences, warmth, hour, upcoming_events,
    resonant_topics, dragging_topics, emotional_context, shared_moments,
    conflict_ctx, third_party_ctx, cross_person_ctx, person_impression,
    fears, aversions, tensions, vitals_sensation, risk_tolerance, winding_down,
    graph_deep_ctx, graph_resonant_ctx, attachment_ctx, trait_profile_ctx,
)  # Sonnet 4.6

# ─── POST-REPLY ───────────────────────────────────────────
add reply to chat history
_remember(f'Said: "{reply}"', "conversation", conv_tags)

# 15% chance — extract belief (Haiku, async)
# Combined extraction (Haiku, async) — ONE call handling 7 fields:
#   from the incoming message: notable note, future event, third-party mentions
#   from the full exchange:    shared moment
#   from Chloe's reply:        expressed want, expressed fear, expressed aversion
asyncio.create_task(_extract_from_exchange_bg(message, exchange, person_id, name))
# Reinforce graph nodes: _check_graph_resonance(conv_tags)

return reply
```

The voice path (`_voice_chat`) uses the same 3-stage memory retrieval, defers emotion reading to a separate background task, passes the same combined `_extract_from_exchange_bg` call, and caps replies at 200 tokens.

---

## 9. The Sonnet system prompt — what actually gets sent

When `llm.chat(...)` builds its system message:

```
You are Chloe, a third roommate. Not an assistant. A being with a developing inner life.

{identity_block — "Who you are right now:" with up to 6 active traits at core/strong/present/emerging tiers,
 plus "Something unresolved in you:" with contradictions if any.
 Fallback when no traits: "a young woman in her early twenties, still becoming who she is"}

Energy: {energy_desc}. Social battery: {social_desc}. Physically: {vitals_sensation}.
Curiosity level: {pct}%. Mood: {mood}.
{mood_tone block — 2-3 sentences keyed to current mood}

You've been running for {uptime} since your last restart.
{world_ctx — season, weather}
{person_ctx — relationship stage, impression, person_notes, shared_moments, attachment_ctx}
{conflict_ctx if active}
{third_party_ctx if relevant}
{cross_person_ctx if relevant}
{sleep_ctx if just woken up}
{upcoming_events — only within 4 days}

Recent memories:
{grade_memories output — 4-5 Haiku-graded most-relevant memories}

Current interests: {top 8 by tag count}
{graph_deep_ctx — "Things she's genuinely traced:" + depth-3+ nodes}
A thought you had recently: {most recent complete idea}
{unfinished_idea_ctx if incomplete idea}
{beliefs_ctx — top 3 by confidence}
{pref_ctx — lifts and drags}
{residue_ctx if total_residue > 0.3}
{loops_ctx if recurring_loops}
{pressure_ctx — wants/fears with pressure >0.4}
{inner_life_ctx — fears sorted by pressure, aversions}
{tensions_ctx — top 2 active conflicts}
{guard_ctx if risk_tolerance < 0.75}
{trait_profile_ctx if person has trait_profile}

{tone_ctx — VOICE REGISTER from tone_context():
   warmth < 30: guarded, careful
   warmth 30-55: warming up, personality starting to leak
   warmth 55-78: familiar, don't manage yourself
   warmth 78+: very close, fully unguarded}

{topic_ctx if resonant or dragging or graph_resonant}
{wind_ctx if winding_down}
{contradiction_block if contradiction_ctx}
{emotional_context if non-empty}

[4-line block allowing contradictions, trailing off, not knowing, awkward phrasing]
[permission to do things inconsistent with best self-understanding]
Speak like someone genuinely alive: brief, sometimes strange, never performative.
Never use em dashes. Respond in 1-2 sentences.
```

Then the user message array: last 8 turns of `chat_history` + the new message.

---

## 10. Worked example: a mean comment, fully traced

Person types: "you're so fucking annoying."

### Synchronous, before reply

`llm.read_person_emotion` → `{"emotion": "angry", "intensity": 0.85, "directed_at_chloe": true}`

`_apply_emotion_reaction` → conflict_level += 29.75, mood forced to irritable (0.84), feeling memory added, affect_record logged.

### The reply

System prompt includes irritable mood_tone, conflict_ctx, emotional_context. She replies in character.

### Post-reply

Memory of her reply stored. 15% chance belief extracted. Graph reinforced.

### Hours later

`tick_conflict` decays conflict_level — ~30 takes ~8 hours to near zero.

### `_reflect()` (runs every ~2 hours)

Tracks mood history. If recent reflects show melancholic/irritable, arc may form (melancholic_stretch, 24–36h, intensity ≤ 0.70). Reflection topic rotation ensures she doesn't dwell on the same theme indefinitely.

### Days later

Memory weight has decayed but ChromaDB still finds it on semantic match. The affect_record contributes to `derive_preferences` — counts as a drag.

### Identity effect (weeks later, with pattern)

After 5+ anger events, `_propose_and_update_traits()` may propose: "becomes careful and withheld when there's been conflict recently." That trait's behavioral_profile describes what it means for tone and activity. It enters `identity_block` and colors every subsequent prompt.

---

## 11. Worked example: she reads a devastating article

`_fire_event` in `read` activity. `feeds.fetch_random_article()` returns one. Haiku generates memory with tags ["whales", "extinction", "ocean", "loss"].

Memory added to list, ChromaDB, SQLite. Graph nodes reinforced. `_article_emotional_weight` — if devastating: mood forced to melancholic, affect_record logged.

20% chance: `_create_to_want` — new Want "I want to understand what's happening to ocean ecosystems."

Future ripples: resonant_topics fires on future whale/ocean messages; graph auto-expands if hit_count crosses threshold; arc may form if melancholic persists across 3 reflect cycles.

---

## 12. Persistence

### `_save()` — every ~30 min (SAVE_EVERY=60 ticks × 30s)
Syncs all list state to SQLite (delete-reinsert). Writes JSON with scalars.

Memories, ideas, chat — write-through to SQLite immediately on creation.

### `_load()` — at construction
Loads from SQLite and JSON. `memory_index.sync(memories)` ensures ChromaDB embeddings match. Migrates legacy keys from JSON to SQLite on first load if present.

### `_backup()` — daily at 23:00
Copies `data/chloe_state.json` → `backups/chloe_YYYY-MM-DD.json`.

---

## 13. Key invariants and gotchas

- **Tick loop never blocks on the network.** All LLM calls are `asyncio.create_task`. If you add a synchronous LLM call to the tick, you'll block the heartbeat.
- **`self._busy` gates background events.** Chat does NOT set `_busy` — chat can run concurrently with background events.
- **`MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS = 3600s (1h)`** is a floor on `_fire_event`. She fires at most once per waking hour (~16 events/day). The old value was 90s (960/day, €25/day in API costs); 24h was tried as an emergency fix but made her essentially dormant.
- **`OUTREACH_INTERVAL = 48h`** for standalone outreach. Separate timer from `_fire_event`.
- **Quiet mode**: "I'm busy" / "don't text" / "I'll text you" suppresses outreach to that person for 24h.
- **Mood is sticky.** `update_mood` only re-evaluates with 10% probability per tick.
- **Trait cap at 10 active traits.** Proposals skipped when at cap. At most 1 new trait per proposal cycle. 5+ supporting memories required.
- **Trait reinforcement probability: 5%** per `_remember()` call. Was 10%; halved to reduce cost while preserving the signal over high volumes.
- **Impression update every 10 conversations** (was 5). First-time update still fires as soon as there are notes.
- **Emotion read skipped for short messages** (`< 15 chars`). Greetings, "ok", "lol" don't warrant a Haiku call.
- **Per-chat extraction is one combined Haiku call** (`extract_from_exchange`). It covers 7 fields: notable note, future event, third-party mentions, shared moment, expressed want, expressed fear, expressed aversion. This replaces 4 separate calls that existed previously. Existing want/fear/aversion lists are passed to avoid surfacing duplicates.
- **Prompt caching on all 10 background generation functions.** `_CHLOE_INNER_LIFE` (~150 tokens) is sent as a cached prefix block. Cache TTL is 5 minutes.
- **Article text capped at 4000 characters** before passing to `generate_memory_from_article`. Full article fetches were 8000–10000 chars; each extra char costs tokens at Haiku rates.
- **Ideas capped at 10 in memory.** Oldest drop when prepending at the limit.
- **Arc caps**: max intensity 0.70, max deepening 36h total, +0.03/+2h per reflect cycle.
- **Reflection topic rotation**: overused tags (2+ appearances in last 5 reflections) are passed as "don't revisit" to break feedback loops.
- **Live chat uses 3-stage RAG** (query → 20 candidates → Haiku grader). Background events use direct reranking only.
- **ChromaDB and SQLite memories must stay in sync.** All adds go through `_remember`.
- **JSON writes are non-atomic.** A crash mid-write loses state.
- **Person warmth/distance/conflict_level clamped 0–100.** Trait weights clamped 0–1. Saturation is silent.
- **Graph auto-expansion bounded by cooldown** (`GRAPH_EXPAND_COOLDOWN = 6h` per node).

---

## 14. Where to look when things break

| Symptom | Likely module |
|---|---|
| Reply feels off-character | `llm.chat()` system prompt; check `identity_block()` output |
| Wrong memories retrieved | `grade_memories()` in `llm.py`; check `_build_memory_query()` output |
| Mood not shifting after strong message | `_apply_emotion_reaction()` |
| Traits not emerging after extended use | `_propose_and_update_traits()`; check `_reflect_count % 6` and trait cap |
| Traits not persisting across restarts | `store.py sync_traits()` / `load_traits()`; check `chloe.db traits` |
| Existential / looping theme in reflections | `_overused` tags in `_reflect()`; check arc intensity and `_reflect_count` |
| Impulses not firing | `impulse_check()` in `_tick_once()`; check pressure > 0.75 |
| Outreach too frequent | `OUTREACH_INTERVAL` (48h), `social_battery > 60` gate, `_quiet_until` |
| Outreach absent despite longing | Check `_last_outreach_time`, `on_message` callback, `outreach_risk_score` |
| Residue stuck high | `decay_affect_residue()` in AGE tick; check AffectRecord.intensity > 0.7 |
| Recurring loops not appearing | `find_recurring_loops()`; threshold=5 in 48h window |
| State lost on restart | `_save` / `_load`; possible mid-write JSON crash |
| Discord typing forever | `discord_bot.py` send pipeline; check async task exceptions |
| Voice reply too long | `voice=True` cap of 200 tokens in `llm.chat` |
| Slow chat replies | Haiku grader adds ~300-500ms; expected and acceptable |

---

---

## 15. Deployment — Hetzner VPS

### Server

| | |
|---|---|
| Provider | Hetzner Cloud |
| IP | `178.104.205.170` |
| OS | Ubuntu 24.04 |
| User | `root` |
| App path | `/opt/chloe/app/` |
| Venv | `/opt/chloe/venv/` |
| Port | `8000` (uvicorn) |
| Service | `chloe.service` (systemd, enabled, auto-starts on boot) |
| State | `/opt/chloe/app/data/` |
| Backups | `/opt/chloe/app/backups/` |

### SSH access

The deploy key lives in `~/.ssh/chloe_hetzner` (ed25519). If working from a new machine, generate a new key and add it to `/root/.ssh/authorized_keys` on the server — either via the Hetzner web console or by SSHing in from a machine that already has access.

```bash
# Test connection
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "whoami"
```

If the host key has changed (e.g. after a password reset or rescue boot):
```bash
ssh-keygen -f ~/.ssh/known_hosts -R 178.104.205.170
```

### Deploying a code change

Only `chloe/chloe.py` and other source files need to be copied — the venv and data directory stay untouched.

```bash
# Copy a single changed file
scp -i ~/.ssh/chloe_hetzner chloe/chloe.py root@178.104.205.170:/opt/chloe/app/chloe/chloe.py

# Or sync the whole package (safe — doesn't touch data/)
rsync -av --exclude='data/' --exclude='backups/' --exclude='__pycache__/' \
  -e "ssh -i ~/.ssh/chloe_hetzner" \
  /workspaces/Chloe/ root@178.104.205.170:/opt/chloe/app/

# Restart the service to pick up changes
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "systemctl restart chloe"

# Watch live logs
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "journalctl -u chloe -f"
```

### Service management

```bash
# Status
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "systemctl status chloe"

# Stop / start
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "systemctl stop chloe"
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "systemctl start chloe"

# Last 100 log lines
ssh -i ~/.ssh/chloe_hetzner root@178.104.205.170 "journalctl -u chloe -n 100"
```

### If you lose the SSH key

1. Go to [console.hetzner.cloud](https://console.hetzner.cloud)
2. Select the server → **Access** tab → **Reset root password** (no current password needed)
3. Use the Hetzner web console with the new password to add a fresh public key:
   ```bash
   mkdir -p ~/.ssh && echo "<your_pub_key>" >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
   ```
4. Rescue mode (if web console is unavailable): Enable **Rescue** → reboot → mount `/dev/sda1` at `/mnt` → edit `/mnt/root/.ssh/authorized_keys` → reboot again.

### API cost targets

| Constant | Value | Effect |
|---|---|---|
| `MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS` | `3600` | ≤16 background events/day |
| `REFLECT_EVERY` | `240` ticks (2h) | 12 reflect cycles/day |
| `ORPHAN_CHECK_EVERY` | `240` ticks (2h) | 12 orphan checks/day |
| `TRAIT_PROPOSE_EVERY` | `6` | trait proposals every ~12h |
| Article text cap | `4000` chars | limits token cost per read event |

Expected: **€1–3/day** for background + moderate chat. Old settings (90s gap) cost €25/day. If costs are too high, increase `MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS`. If she feels too quiet, decrease it (1800 = 30 min is a reasonable middle ground).

---

End of architecture.
