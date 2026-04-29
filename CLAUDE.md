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
| Current implementation — mechanics, data flow, state | `ARCHITECTURE.md` |
| Why decisions were made + committed directions not yet built | `DECISIONS.md` |
| All planned features with implementation detail | `FEATURES.md` |
| Development history | `DEV_LOG.md` |
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

### What is currently MBTI-based (to be replaced)

The identity layer is currently four MBTI floats: `soul.EI`, `soul.SN`, `soul.TF`, `soul.JP`. These live in `soul.py` and drift via activity, content, emotional marks, seasonal cycles, and sleep consolidation.

**This entire system is being replaced.** See `DECISIONS.md → "MBTI is dead"` and `FEATURES.md → Theme A`. Do not extend or refactor `soul.py` — work on it only if fixing a live bug. New identity work goes into `identity.py`.

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

### Priority 3 — Social risk model for outreach

Target: `chloe.py → _send_autonomous_outreach()`.

**What to build:**
- `outreach_risk_score(person, fears, affect_records)` function
- Inputs: conflict_level, warmth, recent rejection count (from affect_records), active fears matching ["rejection", "ignored", "distance"]
- If `risk_score > risk_tolerance`: suppress outreach, log affect_record "wanted to reach out to [name] but held back"
- Suppression accumulates as pressure on the social want

Full formula: `FEATURES.md → C4`.

---

### Priority 4 — The trait system (big architectural work)

This is the largest planned change and will take multiple sessions. Do not rush it.

**Read before starting:** `DECISIONS.md → "MBTI is dead"` in full. Then `FEATURES.md → Theme A` in full.

**The sequence:**
1. Write `identity.py` — `Trait`, `Contradiction`, `Tendencies` dataclasses. No logic yet.
2. Add SQLite tables: `traits`, `contradictions`. Update `store.py`.
3. Write the trait emergence logic in `_reflect()` — Haiku call that proposes traits from experience patterns.
4. Write `behavioral_profile` generation — Haiku call at trait creation time.
5. Wire trait weight reinforcement into the memory/reflection pipeline.
6. Wire trait weight decay into the AGE tick.
7. Add contradiction detection to trait proposal.
8. Update prompt construction in `llm.py` — replace MBTI line with trait identity block.
9. Retire `soul.py` (keep file, mark deprecated, zero out usage).
10. Update `chloe_state.json` schema: add `identity` key, deprecate `soul`.

**Core principle for the trait system:**
- No predefined list of valid traits. They emerge from experience.
- The behavioral_profile is generated by Haiku at trait creation — the system doesn't know what a trait means for activity or tone until Haiku says so.
- Contradictions are not resolved. They coexist and produce inconsistent behavior.
- Opposite-trait activation is possible but penalized and triggers a contradiction.

---

## Next after that

Once the trait system is stable and accumulating real traits:

- **Recurring mental loops** (`FEATURES.md → B3`) — tag cluster frequency tracking, loops surface in prompts
- **Unfinished thoughts** (`FEATURES.md → B4`) — incomplete ideas stored at low confidence, surface as fragments
- **Emotional residue** (`FEATURES.md → C3`) — high-intensity affect_records leave decay-rate residue on mood baseline
- **Curiosity Engine** (`FEATURES.md → B5`) — Want subtype for open questions that drive exploration
- **Relationship-driven trait expression** (`FEATURES.md → D1`) — person_trait_profile, different people activate different traits
- **Impulse interrupt** (`FEATURES.md → F1`) — high-pressure states can interrupt activity selection

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
- **Do not extend `soul.py`.** It is being retired. Bugfix only.

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
    soul.py         — MBTI floats + drift [BEING RETIRED — do not extend]
    identity.py     — [PLANNED] trait system, replaces soul.py
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
  server.py         — FastAPI app
  index.html        — dashboard
  voice_app.py      — voice UI (separate process, Python 3.11)
  ARCHITECTURE.md   — current implementation
  DECISIONS.md      — why + committed future directions
  FEATURES.md       — full feature roadmap with implementation detail
  CLAUDE.md         — this file
```

---

## Quick session startup

If you are starting a new session to work on a specific feature, say so and specify which priority. Then:

1. Claude reads this file (done).
2. Claude reads the relevant section of `FEATURES.md` for implementation detail.
3. Claude reads the relevant section of `DECISIONS.md` if the feature touches identity or any committed direction.
4. Claude reads the relevant module from `chloe/` before writing any code.
5. Work starts.

If you are debugging, describe the symptom. Check `ARCHITECTURE.md → §14` (where to look when things break) first.
