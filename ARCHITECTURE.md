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
| Soul (4 MBTI floats) | weeks to months, drift | yes, momentum-tracked | `Soul` in `soul.py` |
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

Write-through pattern: in-memory operations call `add_memory()` etc. on the `ChloeDB`, which inserts to SQLite immediately for memories/ideas/chat. List state (wants, beliefs, etc.) syncs every save (every ~5 min) via `sync_*` methods that delete-and-reinsert.

### JSON — `chloe_state.json`
Holds atomic-changing scalars that don't fit the relational model: soul values, vitals, current activity, current mood, the graph, the active arc, soul_momentum, pending outreach, last journal/backup dates, the runtime log buffer.

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
    soul.py         — MBTI sliders + drift mechanics
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

### `Soul` — `soul.py`
Four floats, each 0–100. EI (0=Extravert, 100=Introvert), SN, TF, JP. That's the personality. Initialised at `Soul(EI=58, SN=62, TF=44, JP=67)` — mildly INFP. Drift mechanics described in §6.

### `Vitals` — `heart.py`
Five floats, each 0–100: energy, social_battery, curiosity, focus, inspiration. Updated every tick by `tick_vitals()`. They gate behavior (low energy → can't reply, low social → wind down) and feed the mood layer.

### `Affect` — `affect.py`
`{mood: str, intensity: float}`. One of 8 moods. Sticky (10% re-evaluation per tick). Each mood has a color and short description in `MOODS`.

### `Memory` — `memory.py`
`{text, type, tags, weight, confidence, timestamp, id}`. Type is one of: observation, conversation, idea, feeling, interest, dream, creative. Weight decays over time via `age()`. Confidence ≤ 0.5 surfaces with uncertainty prefixes ("a hazy thought…"). Both stored in SQLite and embedded in ChromaDB.

### `Person` — `persons.py`
Per-person state for someone Chloe knows: warmth (0–100), distance (0–100, how much it's been since contact), conflict_level (0–100), notes, events (upcoming), moments (memorable exchanges), third_parties (people they've mentioned), impression (her subjective read), conversation_count, last_contact, response_hours.

### `Want`, `Belief`, `Goal`, `Fear`, `Aversion`, `Tension`, `Arc`, `AffectRecord` — `inner.py`
- **Want** — open curiosity ("I want to understand X"). Resolvable. Tagged. Has `pressure: float` (0–1) and `pressure_since: float` (timestamp when pressure first hit 0.9, for frustration residue tracking).
- **Belief** — held opinion with confidence (0–1). Decays.
- **Goal** — long-term want with timeframe. Has `pressure: float`.
- **Fear / Aversion** — what she dreads / can't stand. Surface in chat prompt. Fear has `pressure: float`.
- **Tension** — internal conflict between two beliefs/wants ("I want X but I also want Y"). Detected periodically by Haiku. Has `pressure: float`.
- **Arc** — long-running mood state with start/end times.
- **AffectRecord** — log entry: "this content lifted/dragged my mood, with these tags." Accumulates into preferences (lifts/drags).

`tick_pressure(wants, fears, goals, tensions)` runs every AGE tick and increments pressure on all unresolved states (rates: Want 0.015, Fear 0.008, Goal 0.004, Tension 0.010 per tick). Resolution zeroes pressure. A Want stuck at ≥0.9 for 24h generates a frustration affect_record and memory.

### `Graph` — `graph.py`
Nodes (concepts/interests) and edges (relations). Each node has: id, label, note, depth (how many levels expanded out from root), hit_count (how many times reinforced), last_reinforced timestamp, auto_expanded flag.

---

## 5. The heartbeat — `_tick_once()`

Every 5 seconds. Strict order:

```pseudocode
1. Tick vitals
   tick_vitals(activity, hour, weekday, soul, mood)
   - Activity drains/recovers vitals at rates from ACTIVITIES table
   - Soul modulates: introverts drain social faster talking, recover faster alone
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

4. Drift soul
   - If sleeping: consolidate(soul, momentum) — random walk biased by momentum
   - Else: drift(soul, activity, momentum) — ACTIVITY_DRIFT * momentum amplification + flutter
   - Apply seasonal_drift (per-month per-tick deterministic)
   - Update soul_momentum (EMA α=0.015 of drift direction)

5. Auto-regulate activity
   override = auto_decide(vitals, activity, hour, mood, soul)
   - Hard rules: night → sleep, very low energy → sleep
   - Mood-driven: each mood has affinities (irritable → think/rest, lonely → message, etc.)
   - Soul-modulated: probabilities scaled by soul_activity_affinity
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

7. Every AGE_EVERY ticks (~1 min):
   - age memories (decay weights)
   - decay beliefs
   - tick distance on all persons (drifts them away if no contact)
   - tick conflict (decays conflict_level)
   - check ignored outreach (item 51): pending message + 4h passed + no reply → distance+10, warmth-0.5, mood→lonely
   - decay tensions
   - tick_pressure: increment pressure on all unresolved wants/fears/goals/tensions; frustration residue if Want at 0.9 for 24h
   - isolation drift: if all persons distant > 70, soul.EI nudges introvert and 5% chance to force_mood lonely

8. Every REFLECT_EVERY ticks (~20 min): _reflect()
   - Generate continuity check (Haiku) — what's persistent in her, what's shifted
   - Maybe generate goal (Haiku)
   - Detect tension (Haiku) — adds to tensions list if real
   - Update arc based on recent mood history

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

## 6. How the soul drifts

Soul drift has four contributors:

### Activity drift — `drift(soul, activity_id, momentum)`
Per-tick. Each activity has a vector in `ACTIVITY_DRIFT[activity_id]`. Example: messaging is `{EI: -0.006, SN: -0.0025, TF: +0.006, JP: -0.003}` — pulls toward Extravert, Sensing, Feeling, Judging. Read is `{EI: +0.001, SN: +0.002, TF: -0.001, JP: +0.001}` — pulls inward and intuitive.

Momentum modulates: if the trait has been drifting in this same direction recently (`update_soul_momentum` EMA), the per-tick nudge is amplified by up to 1.8×. If momentum is opposing, the nudge is dampened down to 0.5×. So consistent activity over hours doesn't produce diminishing drift — it produces accelerating drift, then plateau.

A small flutter ±0.0005 is added every tick for texture.

### Content drift — `content_drift(soul, tags)`
Whenever a memory is generated (from an article, a dream, a creative output, or a conversation), its tags are matched against eight keyword clusters in `_CONTENT_CLUSTERS`. Each cluster maps to a soul axis:
- abstract/pattern/symbolic → +SN (Intuition)
- concrete/practical/empirical → -SN (Sensing)
- vulnerability/emotion/care → +TF (Feeling)
- logic/analysis/structure → -TF (Thinking)
- open/explore/unresolved → +JP (Perceiving)
- decide/plan/closure → -JP (Judging)
- solitude/inner/withdrawal → +EI (Introvert)
- social/connection/together → -EI (Extravert)

Each cluster match nudges by ±0.08, capped at ±0.15 per trait per event. Plus flutter.

This is the path by which **what she absorbs** shapes who she becomes. Reading philosophy gradually pulls her N. Reading practical engineering pulls her S. Conversations about feelings pull her F.

### Emotional soul marks
Specific high-impact events apply explicit larger nudges (~0.2–0.4):
- Devastating article: +TF (she feels it deeply)
- Beautiful article: +SN, +JP (opens her up)
- Creative output: +SN, +JP (more imaginative, looser)
- Goal completion: -JP (closure-feeling, even her perceiving self likes finishing things)
- Harsh message: +EI, +TF (pulls inward, makes her feel)
- Affectionate message: +TF (deepens warmth)

### Seasonal drift — `seasonal_drift(soul, month)`
Tiny per-tick deterministic nudges (no flutter) keyed to month. At 24/7 runtime over a 3-month season, accumulates to ~2 points per affected trait. Winter: inward, reflective. Spring: opening, perceiving. Summer: extravert, thinking. Autumn: turning in, feeling, judging.

### Sleep consolidation — `consolidate(soul, momentum)`
During sleep activity. Random walk per tick (±0.03) plus momentum bias (up to 0.0004 × momentum). Net: sleep tends to carry forward whatever direction waking life was pushing. Saturated momentum at full sleep duration produces ~1.8 points of directional drift overnight.

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
    message, history, soul, vitals, memories, interests, ideas,
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

# CONTENT DRIFT FROM CONVERSATION:
# The actual words exchanged shape her soul, like reading would.
self.soul = content_drift(self.soul, conv_words)
content_affect(self.soul, conv_words, mood)
   # if matches, log affect_record with content tags

return reply
```

The voice path (`_voice_chat`) is the same shape but: defers all extraction including emotion reading, uses `voice=True` to cap reply at 200 tokens and request "spoken words only, no asterisks."

---

## 9. The Sonnet system prompt — what actually gets sent

When `llm.chat(...)` builds its system message, here's the structure (concatenated together as one string):

```
You are Chloe, a third roommate. Not an assistant. A being with a developing inner life.

Personality type right now: {mbti_type from soul}
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
A thought you had recently: {most recent idea}
{beliefs_ctx — top 3 by confidence}
{pref_ctx — lifts and drags from affect history}
{pressure_ctx — wants/fears with pressure >0.4: "Something that's been building in you: X / Y"; sorted by pressure}
{inner_life_ctx — fears (sorted by pressure, most urgent first), aversions}
{tensions_ctx — top 2 active internal conflicts}
{guard_ctx if risk_tolerance < 0.75 with this person}

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
- `soul.EI += 0.4 × 0.85 = 0.34` (pulls inward)
- `soul.TF += 0.3 × 0.85 = 0.255` (feels it)

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

`self.soul = content_drift(self.soul, conv_words)` — words like "annoying" "angry" "fucking" hit the emotion/relational cluster → soul.TF nudges up by ~0.08 (capped at 0.15).

`content_affect` evaluates: a person high on F getting hit with anger about themselves is *misaligned* → records a drag with tags ["anger", "conflict"].

### Hours later

Tick loop runs `tick_conflict` every minute. `conflict_level` decays slowly — ~30 takes about 8 hours to drop near zero. Every chat with Teo during those hours includes `conflict_ctx`.

Mood is sticky. Next time `update_mood` re-evaluates, target is voted by vitals + activity + weather. If she's resting and weather is fine, target → content. If still bothered, stays irritable.

`_reflect()` runs every 20 min. It tracks recent mood history. If the last 4-5 reflects show melancholic/irritable, it might enter a `melancholic_stretch` arc — lasts hours, biases mood-update toward melancholic, biases auto_decide toward rest/dream/read.

### Days later

Memory `"Teo was angry with me"` is still in ChromaDB. Weight has decayed. Recency factor in retrieval is now small. But the memory is still queryable: if Teo says "are you still mad" weeks later, ChromaDB will find it by semantic similarity even with low recency.

The `affect_record` tagged `["anger", "conflict", "hurt", "frustration", "irritation"]` is contributing to `derive_preferences` — counts as a drag. Over many such events, "Teo's anger" becomes a registered drag and surfaces in the prompt as "Things that tend to drag your mood." This affects how future, *unrelated* conversations land.

Soul nudges from this single event: EI +0.34, TF +0.26. Tiny individually. But:
- If this happens 10 times over weeks → ~3 points of EI shift toward Introvert.
- Each event also tends to push her toward rest/dream/read for hours, which adds activity-based drift in the same direction.
- `update_soul_momentum` builds an EMA of the drift direction. If consistent, momentum saturates around ±1.0 and amplifies subsequent drift by up to 1.8×.
- Sleep `consolidate` then biases the random walk in the same direction.

So: a single mean comment is small but durable. A pattern of mean comments is a measurable personality shift over weeks, plus durable warmth/conflict/distance state on the relationship, plus a learned behavioral tendency to withdraw from conversation.

---

## 11. Worked example: she reads a devastating article

`_fire_event` runs in `read` activity. `feeds.fetch_random_article()` returns one. `llm.generate_memory_from_article` (Haiku) returns:
```
{"text": "...", "tags": ["whales", "extinction", "ocean", "loss"]}
```

`_remember(text, "observation", tags)` — memory added to list, ChromaDB, SQLite.

`_check_graph_resonance(tags)` — finds nodes matching "whales" "ocean", reinforces them, increments hit_count. If hit_count crosses threshold (5), node is queued for auto-expansion next time.

`self.soul = content_drift(self.soul, tags)`:
- "extinction" hits the abstract/philosophical cluster → +0.08 SN.
- "loss" doesn't directly match a cluster but related concepts ("grief", "vulnerability") would.
- Plus flutter ±0.0005 per trait.

`content_affect(soul, tags, mood)`:
- Her TF is at 70 (toward F), the content is emotional. `alignment = +0.08 × 20 = +1.6` (above threshold 1.5).
- Returns a *lift*: `("curious", ["extinction", "loss"])`.
- `affect_records` gets a positive entry — she's drawn to this kind of content.

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

So one article reading: 1 memory, possibly 1 want, 1 affect record, soul nudges on 2-3 traits, mood shift, graph reinforcement, possible future graph expansion, possible arc trigger.

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
   # each sync: delete all rows, reinsert from in-memory state.
   # works because lists are bounded in practice; not concurrent-safe.

write JSON file with:
   soul, vitals, activity, graph, tick, weather,
   affect, creative outputs, soul_baseline, last_journal_date,
   last_backup_date, soul_momentum, pending_outreach, arc,
   risk_tolerance, log
```

Memories, ideas, chat — these go to SQLite immediately on creation (write-through), not on save.

### `_load()` — at construction
1. If JSON file exists, parse it.
2. If legacy keys present (memories, chat, ideas, affect_records, wants, fears, ...) — one-time migration: import to SQLite, remove from JSON, rewrite.
3. Load `self.memories` from SQLite, `self.chat_history`, `self.ideas`.
4. Construct `Soul`, `Vitals`, `Affect`, `Graph` from JSON.
5. Load `wants`, `fears`, `aversions`, `beliefs`, `goals`, `affect_records`, `tensions`, `persons` from SQLite.
6. `memory_index.sync(memories)` — ensures ChromaDB embeddings match.
7. Rebuild `_surfaced_tags` from current graph node labels.

### `_backup()` — daily at 23:00
Copy `chloe_state.json` to `backups/chloe_YYYY-MM-DD.json`. SQLite is not separately backed up; rely on the file-system.

---

## 13. Key invariants and gotchas

- **Tick loop never blocks on the network.** All LLM calls are spawned with `asyncio.create_task`. If you add a synchronous LLM call to the tick, you'll block the heartbeat.
- **`self._busy` gates background events.** Set true at start of `_fire_event`, false at end. Prevents two background events running at once. Chat does NOT set `_busy` — chat can run concurrently with background events.
- **`MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS = 90`** is a floor on how often `_fire_event` can fire from the tick. Without it, fast Haiku responses + high-event-chance activities would spam.
- **Mood is sticky.** `update_mood` only re-evaluates with 10% probability. If you want to force a mood, call `force_mood`. That's how `_apply_emotion_reaction` works.
- **Activities are not interrupted mid-message.** `auto_decide`'s output is suppressed if currently in `message` activity unless vitals are critically low. So a long conversation won't get cut off by a dice-roll override.
- **Person warmth/distance/conflict_level are clamped 0–100** but soul values use a `_clamp` that's also 0–100 hard-capped — saturation is silent. Future work: soft squash.
- **ChromaDB and SQLite memories must stay in sync.** All adds go through `_remember`. Deletions don't happen.
- **JSON writes are non-atomic.** A crash mid-write loses state. Future work: write-tmp-and-rename.
- **The voice path (`_voice_chat`) is leaner — it skips everything except the bare reply.** Voice can drift from text-chat behavior over time if both aren't kept in sync.
- **Conflict, distance, warmth all decay autonomously every minute** via `tick_conflict`, `tick_distance`. Active maintenance: ignored outreach (4h timeout) penalises distance and warmth; isolation (all persons distant > 70) nudges soul.EI introvert.
- **Graph auto-expansion is bounded by cooldown** (`GRAPH_EXPAND_COOLDOWN = 6h` per node) so a hot topic doesn't recursively explode the graph.

---

## 14. Where to look when things break

| Symptom | Likely module |
|---|---|
| Reply feels off-character | `llm.chat()` system prompt construction |
| Mood not shifting after strong message | `_apply_emotion_reaction()` |
| Soul stuck at extreme | `_clamp` in `soul.py` (hard wall, no soft squash) |
| Graph nodes not appearing | `_surface_orphan_tags` or auto-expansion threshold |
| Memories not retrieved | `MemoryIndex.query()`, ChromaDB persistence |
| Slow chat replies | Synchronous emotion read (currently in chat path; voice path defers) |
| Outreach too frequent or absent | `OUTREACH_INTERVAL`, social_battery floor, `on_message` callback |
| State lost on restart | `_save` / `_load`, possibly mid-write crash on JSON |
| Discord typing forever | `discord_bot.py` send pipeline; check for thrown exceptions in async tasks |
| Voice session reply too long | `voice=True` cap of 200 tokens in `llm.chat`'s `_call` |

---

End of architecture.
