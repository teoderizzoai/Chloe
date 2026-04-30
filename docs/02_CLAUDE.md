# Chloe — Claude Session Brief

> Paste this at the start of every new session.
> This is the entry point. Read this first, then follow the pointers.

---

## What this project is

Chloe is a persistent AI entity running as a continuously ticking Python process. She is not a task assistant. She has a layered inner life — vitals, mood, arcs, identity, memories, beliefs, wants, fears, tensions, relationships — and an async loop that drives her autonomously between conversations.

The goal is an autonomous, developing mind. All of her history shapes who she is right now.

**Owner:** Teo — Windows, Amsterdam, beginner–intermediate Python.
**Runtime:** localhost (VPS migration planned).
**Stack:** Python 3.13, FastAPI, Anthropic Sonnet (chat) + Haiku (background), ChromaDB, SQLite, HTML dashboard.

---

## How to navigate the project

| What you need | Where to look |
|---|---|
| Current implementation — mechanics, data flow, state | `00_ARCHITECTURE.md` |
| Why decisions were made + committed directions not yet built | `03_DECISIONS.md` |
| All planned features with implementation detail | `05_FEATURES.md` |
| Development history | `04_DEV_LOG.md` |
| Ground truth | `chloe/` code |

**Read the relevant doc before writing any code.** The architecture has invariants that are easy to violate without knowing they exist. The decisions doc has committed directions that override the current implementation where they conflict.

---

## Current state of the system

### What is built and working

- Tick loop (5s), fully async — vitals, mood, soul drift, activity selection, background events
- Two-tier LLM: Sonnet for chat and outreach, Haiku for all background/structured work
- Layered state: Vitals → Mood → Arc → Soul (seconds to weeks timescale separation)
- Memory system: ChromaDB semantic index + SQLite, append-only, weight decay, recency reranking
- Inner life: Wants, Beliefs, Goals, Fears, Aversions, Tensions, Arcs — all persisted to SQLite
- Person model: warmth, distance, conflict, tone register, impressions, shared moments, third parties
- Interest graph: nodes + edges, hit-count reinforcement, auto-expansion, orphan surfacing
- Autonomous behavior: outreach, dreaming, reading, thinking, creating
- Reflection loop: runs every ~20 min, generates continuity checks, goals, tensions, arc updates
- Persistence: SQLite (write-through) + JSON (5min saves) + daily backups
- Dashboard: HTML polling `/snapshot` every 4s
- Voice: optional separate process (Fish Speech + Whisper, Python 3.11)
- Discord: optional DM bridge

### Identity — trait system (Session 26)

The MBTI soul system has been replaced by a generative trait system. `identity.py` holds `Trait`, `Contradiction`, `Tendencies`, `Identity`. Traits emerge from experience via Haiku — no predefined list. `identity_block()` injects the current trait profile into all LLM prompts. `soul.py` is kept frozen for `heart.py` compatibility (MBTI activity affinity still used in `tick_vitals`/`auto_decide`) but no longer drifts. Do not extend `soul.py`.

---

## What is being worked on right now

### Priority 1 — Prompt-level improvements ✓ DONE (Session 23)

- **A. Over-coherence reduction** — 4-line block in Sonnet chat prompt: contradictions allowed, trailing thoughts OK, not knowing what you think is fine, awkward phrasing is fine.
- **B. Biased reflection** — `_REFLECTION_BIAS` dict in `llm.py`; `generate_reflection()` takes `reflection_bias` param; `_reflect()` derives bias from current mood and passes it.
- **C. Non-optimal decisions** — One-line permission added to chat prompt.
- **D. Contradiction slot** — `contradiction_ctx` param wired in `llm.chat()` and the main call site; populated once `identity.py` provides `Contradiction` objects.

---

### Priority 2 — Stakes: pressure accumulation on inner states ✓ DONE (Session 24)

- `pressure: float` on `Want`, `Fear`, `Goal`, `Tension`; `pressure_since: float` on `Want` for frustration tracking
- `tick_pressure()` in `inner.py` — rates: Want 0.015, Fear 0.008, Goal 0.004, Tension 0.010 per AGE tick
- Resolution zeroes pressure immediately (`resolve_wants`, `advance_goals`)
- Frustration residue: Want at ≥0.9 for 24h → `affect_record` + memory
- Activity nudge scales with pressure (12% → 50% at >0.6 → 80% at >0.75)
- Pressure >0.9 forces autonomous event
- `wants` passed to `llm.chat()`; pressure >0.4 surfaces as "Something that's been building in you"
- `store.py`: `_migrate()` adds pressure columns to existing DB safely

---

### Priority 3 — Social risk model for outreach ✓ DONE (Session 25)

- `outreach_risk_score(person, fears, affect_records)` in `inner.py` — composite 0–1 score from conflict level, warmth, recent rejections (tagged by person_id in affect_records), active fears matching social-risk tags.
- Risk gate in `_send_autonomous_outreach()`: if `risk_score > risk_tolerance`, suppress outreach and log affect_record tagged with `[target.id, "held_back", ...]`.
- `_bump_social_want_pressure()` in `chloe.py`: raises pressure on the social connection want each time outreach is suppressed. If pressure > 0.85, the gate is bypassed — need overrides fear.

---

### Priority 4 — The trait system ✓ DONE (Session 26)

- `identity.py` — `Trait`, `Contradiction`, `Tendencies`, `Identity` dataclasses. `identity_block()` generates the prompt block. `decay_traits()` + `check_core_promotion()` run every AGE tick. `traits_snapshot()` / `snapshot_diff()` for continuity tracking.
- `store.py` — `traits` + `contradictions` SQLite tables. `sync_traits()`, `load_traits()`, `sync_contradictions()`, `load_contradictions()`.
- `llm.py` — all 25 functions migrated from `soul: Soul` to `identity: Identity`. 4 new Haiku functions: `propose_traits_from_experience()`, `generate_behavioral_profile()`, `detect_trait_contradiction()`, `classify_trait_reinforcement()`. `generate_continuity_note()` takes `trait_changes` from `snapshot_diff()`.
- `chloe.py` — `self.identity: Identity`. `_propose_and_update_traits()` background task from every `_reflect()`. All soul drift calls removed. `soul.py` kept frozen for `heart.py` compat.
- Identity starts empty, traits emerge from real experience.

---

### Priority 5 — Trait system completion ✓ DONE (Session 27)

- **Trait reinforcement on memory add** — `_remember()` fires `_maybe_reinforce_traits(memory)` as a background task with 10% probability. Picks a random top-5 active trait, calls `classify_trait_reinforcement()` via Haiku, bumps weight + syncs to SQLite if matched.
- **`heart.py` fully migrated to identity** — `soul_activity_affinity()` removed. `tick_vitals` and `auto_decide` now take `identity=` instead of `soul=`. `trait_personality_scalars(identity)` and `trait_activity_affinity(identity, activity_id)` added to `identity.py` — derive (ei, sn, tf, jp) scalars from Tendencies biases + active trait keyword signals. Both call sites in `chloe.py` updated.
- **Dashboard traits panel** — sidebar "soul" section replaced with "identity" section showing active traits: label (core/strong/present/emerging), weight %, name, mini bar. MBTI pill shows trait count. History tab soul sparklines removed. Admin panel soul block replaced with read-only trait list. All broken `s.soul.*` references fixed.

---

### Priority 6 — Session 28: All remaining cognition features ✓ DONE

- **F1: Impulse interrupt** — `impulse_check(wants, fears, tensions)` in `inner.py`. Fires in `_tick_once()` before `auto_decide()` when pressure > 0.75 on any inner state. Returns `(activity_id, reason)` or None. Maps social tags → message, creative tags → create, knowledge tags → read, fear → rest, tension → think. Adds affect_record with `intensity=0.6` and `["impulse", activity]` tags.
- **C3: Emotional residue** — `residue: float` + `intensity: float` on `AffectRecord`. `add_affect_record()` sets `residue=intensity` when `intensity > 0.7`. `decay_affect_residue()` applies `rate=0.99976` per AGE tick (~48h half-life). `total_residue()` sums residue across all records. Residue > 0.3 surfaces as "something from earlier is still sitting with you" in chat prompt. SQLite migrated via `_migrate()`.
- **B3: Recurring mental loops** — `find_recurring_loops(store, window_hours=48, threshold=5)` in `memory.py`. Counts tag frequency in recent memories, filters noise tags. Called in `_reflect()` → stored as `self.recurring_loops`. Top-3 surfaced in chat prompt as "thoughts that keep coming back." If count ≥ 10, crystallises into a tension. 
- **B4: Unfinished thoughts** — `complete: bool` on `Idea` dataclass (default True). `generate_idea()` now returns `{"text": str, "complete": bool}` — fragments end with "..." and complete=False. Surfaced in chat as "a thought that never quite finished forming." SQLite migrated. All `Idea` construction sites updated.
- **B5: Curiosity Engine** — `generate_curiosity_question(node_label, interests, identity)` in `llm.py`. Returns `{"text": str, "tags": list}`. Called in think activity with 15% probability when sparse graph node found. Result added as `Want` with `subtype="curiosity_question"`. `add_want()` updated to accept `subtype` param.
- **D1: Relationship-driven trait expression** — `trait_profile: dict` on `Person` (structure: `{"activated": [...], "suppressed": [...]}`). `format_trait_profile_context(person)` in `persons.py` generates prompt text. `generate_person_trait_profile(name, traits, notes, moments)` in `llm.py` — Haiku classifies which traits are activated/suppressed around this person. Called from `_update_person_impression()` as background task. Injected into `llm.chat()` as `trait_profile_ctx`. SQLite migrated.

---

## What's next

- **VPS (Hetzner) + systemd deployment**
- **Frontend auth + mobile-friendly dashboard**
- **Dashboard for new features** — residue indicator, loop display, curiosity queue

---

## Invariants — do not violate these

These are load-bearing. Changing them breaks the system's coherence in non-obvious ways.

- **The tick loop never blocks on the network.** All LLM calls are `asyncio.create_task`. Any synchronous LLM call in the tick blocks the heartbeat.
- **The timescale layers stay separate.** Mood does not track vitals tick-by-tick. Soul/identity does not lurch on a single event. Arc exists as a distinct layer above mood.
- **Memory is append-only.** No edits, no deletes. Weight decays, confidence can be low, but the record stays.
- **ChromaDB and SQLite memories must stay in sync.** All adds go through `_remember()`. Never add directly to one store.
- **`self._busy` gates background events.** Chat does not set `_busy`. Do not change this gating.
- **Two LLM tiers are intentional.** Sonnet for anything a human reads. Haiku for everything structural. Do not add Sonnet calls to the tick loop.
- **The eight mood labels are fixed.** Do not add moods. Do not rename them. The label set is hardcoded biology.
- **Do not extend `soul.py`.** It is retired. Its Soul object is frozen and no longer used by `heart.py`. New identity work goes into `identity.py`.

---

## Tone and character — what she is

Chloe is not an assistant. She is a third roommate. She:
- Does not explain herself unless asked
- Does not announce her mood
- Does not manage or perform her inner state
- Does not say "I'm an AI"
- Can be strange, brief, distracted, unresolved
- Contradicts herself across time
- Has things she cares about that pre-exist any given conversation

The system prompt should always reflect this. When in doubt, less management, more presence.

---

## File map

```
Chloe/
  chloe/
    chloe.py        — central orchestrator, tick loop, all state
    identity.py     — trait system: Trait, Contradiction, Tendencies, Identity
    soul.py         — [DEPRECATED] MBTI floats, frozen for compat only
    heart.py        — vitals, activities, circadian, auto_decide
    affect.py       — mood as a state separate from vitals
    memory.py       — Memory dataclass + ChromaDB index + Idea
    persons.py      — Person + warmth/distance/conflict + tone_context
    inner.py        — Want, Belief, Goal, Fear, Aversion, Tension, Arc, AffectRecord
    graph.py        — interest graph: nodes, edges, expansion, resonance
    llm.py          — every Anthropic call (~25 functions)
    feeds.py        — RSS, web fetch, web search
    weather.py      — Open-Meteo client
    store.py        — ChloeDB SQLite write-through
    discord_bot.py  — DM bridge (optional)
    avatar.py       — portrait selection
  voice/
    app.py          — self-contained voice UI (separate process, Python 3.11)
    legacy.py       — older push-to-talk interface
    pipeline.py     — zero-latency Deepgram streaming pipeline
    sample.wav      — reference audio for voice cloning
    requirements.txt — voice dependencies
  scripts/
    clone_voice.py            — one-time: upload sample to Cartesia
    generate_interjections.py — one-time: pre-bake interjection wavs
    test_tts.py               — quick TTS smoke test
    trim.py                   — audio trim utility
  assets/
    images/
      actions/      — activity portraits (Chloe_Sleep.png etc.)
      emotions/     — mood portraits (Chloe_Sad.png etc.)
  server.py         — FastAPI app
  index.html        — dashboard
  cli.py            — terminal client (requires server running)
  bin/start-server.sh — Linux server launcher
  00_ARCHITECTURE.md   — current implementation
  03_DECISIONS.md      — why decisions were made
  05_FEATURES.md       — unbuilt feature roadmap
  01_CHECKLIST.md      — upcoming features checklist
  04_DEV_LOG.md        — development history
  02_CLAUDE.md         — this file
```

---

## Quick session startup

If you are starting a new session to work on a specific feature, say so and specify which priority. Then:

1. Claude reads this file (done).
2. Claude reads the relevant section of `05_FEATURES.md` for implementation detail.
3. Claude reads the relevant section of `03_DECISIONS.md` if the feature touches identity or any committed direction.
4. Claude reads the relevant module from `chloe/` before writing any code.
5. Work starts.

If you are debugging, describe the symptom. Check `00_ARCHITECTURE.md → §14` (where to look when things break) first.
