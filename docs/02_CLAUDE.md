# Chloe — Claude Session Brief

> Paste this at the start of every new session.
> This is the entry point. Read this first, then follow the pointers.

---

## What this project is

Chloe is a persistent AI entity running as a continuously ticking Python process. She is not a task assistant. She has a layered inner life — vitals, mood, arcs, identity, memories, beliefs, wants, fears, tensions, relationships — and an async loop that drives her autonomously between conversations.

The goal is an autonomous, developing mind. All of her history shapes who she is right now.

**Owner:** Teo — dev from Codespace, Amsterdam.
**Runtime:** Hetzner VPS `178.104.205.170`, systemd service `chloe.service`.
**Stack:** Python 3.13, FastAPI, Gemini 2.5 Pro (chat) + Gemini 2.5 Flash (background), ChromaDB, SQLite, HTML dashboard.

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

- Tick loop (30s), fully async — vitals, mood, activity selection, background events
- Two-tier LLM: Sonnet 4.6 for chat and outreach, Haiku 4.5 for all background/structured work
- Prompt caching: `_CHLOE_INNER_LIFE` cached as ephemeral prefix block in all 10 background generation functions
- Layered state: Vitals → Mood → Arc → Identity (seconds to weeks timescale separation)
- Memory system: ChromaDB semantic index + SQLite, append-only, weight decay, 3-stage graded RAG for live chat
- Inner life: Wants, Beliefs, Goals, Fears, Aversions, Tensions, Arcs — all persisted to SQLite; pressure accumulation on all four; expressed wants/fears/aversions extracted from Chloe's own replies
- Person model: warmth, distance, conflict, tone register, impressions, attachment patterns, shared moments, third parties, trait profiles
- Interest graph: nodes + edges, hit-count reinforcement, auto-expansion, orphan surfacing
- Autonomous behavior: outreach, dreaming, reading, thinking, creating — ≤16 events/day (MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS=3600)
- Social risk model: outreach suppressed when risk > tolerance; accumulated longing (pressure > 0.85) overrides
- Reflection loop: runs every ~2h, generates continuity checks, goals, tensions, arc updates; topic rotation prevents feedback loops
- Trait system: emergent, experience-driven; max 10 active; proposals every ~12h; failure consequences (setbacks, suppression beliefs)
- Persistence: SQLite (write-through) + JSON (30min saves) + daily backups; deployed on Hetzner VPS under systemd
- Dashboard: HTML polling `/snapshot` every 4s
- Voice: optional separate process (Fish Speech + Whisper, Python 3.11)
- Discord: optional DM bridge

### Identity — trait system (Sessions 26–27)

The MBTI soul system has been replaced by a generative trait system. `identity.py` holds `Trait`, `Contradiction`, `Tendencies`, `Identity`. Traits emerge from experience via Haiku — no predefined list. `identity_block()` injects the current trait profile into all LLM prompts. `soul.py` is kept frozen but no longer referenced by active code. Do not extend `soul.py`.

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

- **Trait reinforcement on memory add** — `_remember()` fires `_maybe_reinforce_traits(memory)` as a background task with 5% probability. Picks a random top-5 active trait, calls `classify_trait_reinforcement()` via Haiku, bumps weight + syncs to SQLite if matched.
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

### Priority: Sessions 29–31 — Failure consequences, attachment patterns, pacing ✓ DONE

**Session 29 — C2 Failure consequences**: `setback_count` + `setback_notes` on `Trait`. `traits_matching_tags()` + `penalize_trait()` in `identity.py`. Frustrated wants apply −0.04 penalty; failed goals −0.08. Three setbacks on same trait generates suppression belief. `fail_stale_goals()` in AGE tick. Haiku generates honest failure reflection as feeling memory.

**Session 30 — C5 Attachment patterns**: `attachment_pattern: str` on `Person`. `generate_attachment_pattern()` in `llm.py`. `format_attachment_context()` and `attachment_risk_modifier()` in `persons.py`. Called from `_update_person_impression()`. `tick_distance` rewritten with `dataclasses.replace()` to avoid silently dropping new fields.

**Session 31 — Pacing + 3-stage RAG**: TICK_SECONDS 5→30. OUTREACH_INTERVAL 2h→48h. MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS 90s→3600s (≤16 events/day, was 960). Quiet mode (`_matches_quiet_request`). Trait proposal controls: max 10 traits, every 6th reflect, 1 per cycle, 5+ memories required. Anti-escalation: reflection topic rotation, arc caps (max 0.70 intensity, 36h duration). 3-stage RAG: rich query → 20 ChromaDB candidates → Haiku grader → 4-5 genuinely relevant.

---

### Priority: Session 32 — API cost optimisation ✓ DONE

- **Prompt caching**: `_call()` gains `cache_prefix` param; `_CHLOE_INNER_LIFE` (~150 tokens) cached as ephemeral block in all 10 background generation functions. Cache TTL 5 min; reads cost 90% less.
- **Combined extraction**: 4 per-chat Haiku calls merged into `extract_from_exchange()` returning 7 fields: notable, event, third_parties, shared_moment, expressed_want, expressed_fear, expressed_aversion. Single `_extract_from_exchange_bg()` task on both chat paths.
- **Expressed inner states wired up**: want/fear/aversion extraction from Chloe's replies was previously defined but never called — now active via the combined function.
- **Minor reductions**: trait reinforcement 10%→5%, impression cadence 5→10 conversations, emotion read skipped for messages < 15 chars.

---

## What's next

- **D2 — Tone register becomes trait-aware**: `tone_context()` selects which traits are emphasised per warmth tier, not just access level (see `05_FEATURES.md`)
- **Dashboard for new features** — residue indicator, loop display, curiosity queue
- **Frontend auth + mobile-friendly dashboard**
- **SQLite backup strategy** (currently only JSON is backed up at 23:00)

---

## Invariants — do not violate these

These are load-bearing. Changing them breaks the system's coherence in non-obvious ways.

- **The tick loop never blocks on the network.** All LLM calls are `asyncio.create_task`. Any synchronous LLM call in the tick blocks the heartbeat.
- **The timescale layers stay separate.** Mood does not track vitals tick-by-tick. Identity does not lurch on a single event. Arc exists as a distinct layer above mood.
- **Memory is append-only.** No edits, no deletes. Weight decays, confidence can be low, but the record stays.
- **ChromaDB and SQLite memories must stay in sync.** All adds go through `_remember()`. Never add directly to one store.
- **`self._busy` gates background events.** Chat does not set `_busy`. Do not change this gating.
- **Two LLM tiers are intentional.** Sonnet for anything a human reads. Haiku for everything structural. Do not add Sonnet calls to the tick loop.
- **The eight mood labels are fixed.** Do not add moods. Do not rename them. The label set is hardcoded biology.
- **Do not extend `soul.py`.** It is retired and frozen. New identity work goes into `identity.py`.
- **Per-chat extraction is one combined Haiku call.** `extract_from_exchange()` handles 7 fields. Do not add separate per-chat extraction calls — extend the combined function instead.
- **Prompt caching prefix is separate from the dynamic system string.** Pass `_CHLOE_INNER_LIFE` (or any static prefix) as `cache_prefix=`, not embedded in the `system` string.

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
    llm.py          — every Gemini call (~25 functions)
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
