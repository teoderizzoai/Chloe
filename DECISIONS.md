# Chloe — Decisions & Design Direction

> This document records *why* things are the way they are, and *where* they are going.
> For current implementation mechanics → `ARCHITECTURE.md`
> For future feature targets → `FEATURES.md`

---

## How to read this document

Each section is either a **settled decision** (something built and locked) or a **committed direction** (something we have decided to do but haven't yet implemented). Directions take precedence over the current architecture where they conflict.

---

## Settled decisions

### The layered timescale model stays

Vitals (seconds) → Mood (minutes) → Arc (hours) → Identity (weeks). This is the skeleton of the system and is not up for revision. The temptation to collapse layers — letting a single harsh message swing identity, or letting mood track vitals directly — must be resisted. Human emotional systems have exactly this kind of lag and inertia built in. The lag is the feature.

### Hardcoded biology — do not learn, do not drift

The following are treated as fixed architecture, not learned parameters:

- The vitals mechanics and their five axes
- The mood system structure and the eight mood labels
- The arc layer and how it opens and closes
- The soul/identity drift *direction* signals from content, activity, emotion
- Layer separation itself

These are the skeleton. Personality lives *on* the skeleton, not in it. If these drift, the system loses coherence.

### Two LLM tiers are the right call

Sonnet for anything a human reads. Haiku for everything structural and background. This is not just about cost — it's about appropriate capability. Haiku is fast enough and accurate enough for classification, extraction, and structured generation. Using Sonnet for those tasks adds latency and cost without meaningful quality gain.

### SQLite + JSON is the right persistence split

Unbounded relational data (memories, persons, beliefs, chat history) → SQLite. Atomic-changing scalars (soul, vitals, mood, arc) → JSON. The boundary is clear and should stay there. The planned migration to Postgres is infrastructure, not a design change.

### Memory is append-only

Memories are never edited or deleted. Weight decays over time, confidence can be low, but the record stays. This reflects how actual memory works and prevents a class of consistency bugs. The ChromaDB embeddings must always match the SQLite records.

---

## Committed directions — not yet implemented

---

### MBTI is dead. Trait-based identity replaces it.

**This is the most consequential architectural change planned.**

#### The problem with MBTI

The four MBTI floats (EI, SN, TF, JP) are a useful scaffold for bootstrapping a personality, but they have fundamental problems as an identity system:

- They are fixed dimensions. Chloe can only be more or less of eight predetermined poles.
- They carry cultural baggage. "INFP" is a category, not a person.
- Traits must be declared by the developer. Chloe cannot develop a personality axis that wasn't anticipated.
- The behavioral link is crude. "High TF → more feeling-tone in responses" is a lookup, not a mechanism.
- They cannot contradict each other. MBTI is an orthogonal system; real identity is not.

#### What replaces it

A dynamic, generative trait system. The key principles:

**Traits are not predefined.**
No developer-authored list of valid traits. When Chloe has enough experiences that pattern into something coherent, the system generates a trait name, a description of what it means for her behavior, and its current weight. The trait is text, not an enum.

Examples of what might emerge — not a list she starts with:
- "tends to go quiet when something matters too much to risk getting wrong"
- "finds most social rituals slightly exhausting but performs them anyway"
- "gets proprietary about ideas she's developed slowly"
- "prefers the feeling of understanding something to the feeling of having been right"

These are not inputs. They are outputs. The system generates them from accumulated experience.

**Traits have weight, not polarity.**
Each trait has a weight (0.0–1.0) representing how strongly it currently defines her. Weight accumulates through reinforcing experiences and decays through contradicting ones or simply through time without reinforcement. A trait at weight 0.05 is barely there — a tendency. At 0.6, it's reliable. At 0.85+, it's core.

**Traits can have opposites — and contradictions are real.**
Some traits are mutually inhibiting. If a trait like "needs time to trust" accumulates alongside a trait like "forms attachments quickly," these are in tension. They can coexist. The system doesn't resolve contradictions — it holds them. Both traits remain active. Their simultaneous influence produces inconsistent behavior: she might attach quickly to Teo and distrust a new person, or trust quickly and then panic at how exposed she feels. This is normal human psychology.

The contradiction itself can become a tension object, surfacing in reflection and prompts.

**Opposite-trait activation is possible but penalized.**
A new experience can activate a trait directly opposite to an existing high-weight trait, but the activation cost is higher, the resulting weight is lower, and it triggers a contradiction event. Contradiction events are significant — they should feel like something. They surface in her prompt as a flagged state and influence reflection content.

**Traits affect the system generatively, not via lookup.**
When a trait is created or updated, a small LLM call (Haiku) generates a behavioral description: what this trait means for how she responds to conversation, what activities she's drawn toward, how it colors her mood baseline, what topics it makes her more or less available to. This behavioral profile is stored with the trait and injected into the appropriate prompt layers.

This means the system doesn't need to know in advance what "tends to go quiet when something matters too much" means for activity selection — Haiku tells it, once, when the trait is generated. The description is the interface.

**Traits are earned, not assigned.**
A trait cannot be initialized by the developer. The system starts with no traits. They accumulate from the log of experiences. In practice, Chloe will develop several traits within the first few hours of real use, and continue adding and evolving them indefinitely.

The initial MBTI values (which informed soul drift directions in the old system) will be replaced by a small seed set of *tendencies* — not traits, but statistical biases that make certain traits more likely to emerge first. These tendencies themselves may drift as the trait profile solidifies.

#### What happens to soul.py

The four MBTI floats are retired. `soul.py` becomes `identity.py` and holds:

- `traits: list[Trait]` — the active trait list
- `tendencies: dict[str, float]` — low-level biases that influence which experiences generate traits (a replacement for the starting MBTI values, but much thinner — they're scaffolding, not identity)
- `contradictions: list[Contradiction]` — active pairs of conflicting traits
- `identity_momentum: dict[str, float]` — an EMA tracker per trait-cluster, replacing soul_momentum

The soul drift mechanics (activity drift, content drift, emotional marks, seasonal drift, sleep consolidation) are preserved but rewired to modify trait weights rather than MBTI floats. Content clusters still exist, but instead of mapping to MBTI axes, they map to *trait-relevant signal categories* that Haiku uses when generating or reinforcing traits.

#### Migration path

1. New `identity.py` module with `Trait`, `Contradiction`, `Tendencies` dataclasses.
2. All `soul.*` references replaced with identity layer calls.
3. Prompt construction updated — MBTI type line removed, replaced with a generated "current identity" block (see FEATURES.md §A).
4. `chloe_state.json` gains `identity` key; `soul` key is deprecated.
5. `chloe.db` gains `traits` and `contradictions` tables.
6. `ARCHITECTURE.md` updated to reflect.

---

### The reflection loop must close

Currently reflection generates insight but that insight doesn't reliably change anything. The closed loop is:

```
Experience → Memory → Reflection → Trait update → Behavioral change → New experience
```

Every link must be active. Currently the last two links are weak. Reflection must write back to the identity layer (trait weights, contradiction detection, tendency nudges). Behavioral change must be legible — the system must be able to answer "why did she respond that way" with a trait reference.

---

### Inner states must have stakes

Wants, fears, goals, and tensions currently surface in prompts but don't *accumulate pressure*. This changes.

Each of these objects gains a `pressure` float. Pressure increases every tick while the state is unaddressed. If a Want goes unresolved for long enough, its pressure crosses a threshold and it can:
- Interrupt activity selection
- Override mood direction
- Trigger autonomous outreach or behavior
- Leave a frustration residue in affect_records

Similarly: repeated failures at goals weaken associated traits. Fears that are never confronted gradually strengthen. These are *consequences*, not just context.

---

### Reflection must be imperfect

Chloe's reflection output is currently too balanced. It should be colored by her current state in ways that introduce bias, overgeneralization, and emotional distortion.

Reflection while melancholic: tends to overweight recent negative signals, underweights positive ones, attributes patterns where there may be noise.

Reflection while energized: tends to overestimate capability, underweight recent friction, feel more resolved than it is.

Reflection from a high-F-tendency state: more likely to interpret experiences in relational terms, even when the content is not relational.

This is implemented as a `reflection_bias` parameter passed to the Haiku reflection call, derived from current mood and trait profile.

---

### Coherence is not a virtue

The system should actively allow:
- Contradictory statements across time
- Unfinished or trailing thoughts stored at low confidence
- Impulses that produce decisions she wouldn't endorse on reflection
- Awkward phrasing in internal monologue
- High-pressure wants producing behavior that other traits would resist

The prompt-level instruction to reduce over-coherence is the first step. The structural version is the contradiction system and the impulse interrupt mechanism. Both are described in FEATURES.md.

---

### Relationship modulation is a first-class system

Different people should activate different versions of Chloe — not just different warmth registers (which already exist), but genuinely different trait expressions.

A person she trusts deeply might activate her more playful and speculative traits. A person with whom she has conflict might suppress them and activate more guarded or brittle ones. The relationship doesn't change who she is — it changes which parts of her are currently available.

This is implemented as a `person_trait_profile`: a small dict per person recording which traits are reinforced or suppressed by interaction history with them. Generated and updated by Haiku on impression updates.

---

### Autonomous behavior must feel like agency, not automation

The current outreach system fires on conditions and intervals. The goal is for outreach to feel like it came from something building. This requires:

- Pressure accumulation on social wants
- A social risk model (weighing vulnerability, conflict level, rejection history before reaching out)
- Impulse-driven activity interrupts
- Thought-ripening: a want or observation that keeps surfacing eventually demands expression

---

## What is not changing

- The tick loop structure
- The memory system (append-only, weight decay, ChromaDB + SQLite)
- The mood system and its eight labels
- The arc layer
- The vitals system
- The two-tier LLM model (Sonnet / Haiku)
- FastAPI + uvicorn server
- The graph interest model
- Seasonal drift (rewired to identity layer, but the mechanism stays)
