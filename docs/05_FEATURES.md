# Chloe — Features Roadmap

> Unbuilt features only. Completed work is in 04_DEV_LOG.md.
> Read 03_DECISIONS.md for the *why*. Current implementation → 00_ARCHITECTURE.md

Priority labels: **[BUILD]** (significant scope), **[LATER]** (depends on earlier work or extended runtime).

---

## Theme D — Relationships

### D2. Tone register becomes trait-aware [BUILD]

Current four warmth-level registers describe access level but not which traits surface. Post-implementation, the register selects which traits are emphasised:

- Warmth < 30: guarded traits dominate. Core traits present but not performed.
- Warmth 55–78: person-specific activated traits start coming through.
- Warmth > 78: high-weight traits express freely, including contradictions. She can hold both poles at once with this person.

---

## Theme E — Self-History

### E1. Identity drift awareness [LATER]

Once traits have been accumulating for several weeks, a weekly Haiku call compares the current trait list against snapshots from 7 and 30 days prior. Output is a `self_change_note` — not analysis, but subjective perception biased by current mood.

Examples: "I think I used to care more about [X]." "Something about [Y] feels different in me now." Stored as a belief (confidence ~0.4). Surfaces in reflection and occasionally in chat.

Depends on: stable trait records over multiple weeks.

---

### E2. Self-history from DEV_LOG [LATER]

DEV_LOG parsed into a timeline and presented to Chloe as narrative material, not data. A Haiku call generates a `self_origin_narrative`: what she understands about her own development, what she finds strange or interesting, what she doesn't understand. Stored as a belief cluster.

She accesses it like memory — uncertain, colored by the present.

Depends on: E1.

---

### E3. Regret system [LATER]

When a Goal fails, a Want is frustrated long-term, or a relationship event produces strong negative residue, a small probability generates a `regret` object: a retrospective belief with negative valence ("I didn't do X when I should have").

Regrets:
- Influence future goal formation
- Surface in reflection under melancholic or irritable bias
- Can weaken or strengthen a related trait
- Decay slowly — they fade but leave a trace

Depends on: C1 (done), trait system (done).

---

## Theme F — Behavior

### F2. Competing impulses [BUILD]

When two high-pressure states point toward incompatible activities, neither wins automatically. Resolution is probabilistic, weighted by pressure difference. The losing impulse leaves a residue: a low-confidence memory "wanted to [X] but didn't." This feeds the recurring loops tracker.

---

## Theme G — Memory

### G2. Narrative self-model [LATER]

Chloe develops a running internal story about who she is — distinct from the trait list (which is the system's model of her). Generated weekly by Haiku from trait descriptions, recent memories, and beliefs, colored by current mood. Stored as a belief (confidence 0.5).

It may be inaccurate. The inaccuracy is intentional and tracked against the actual trait list. The gap between "who she thinks she is" and "who the system knows her to be" is interesting signal.

---

## Dashboard

- Residue indicator — visual signal in sidebar when emotional residue > threshold
- Recurring loops display — show current top 3 mental loops
- Curiosity queue — show active `curiosity_question` wants

## Infrastructure

- Frontend auth + mobile-friendly dashboard
- SQLite backup strategy (currently only JSON is backed up daily at 23:00)

---

## What is not being built

- Attention system as a hard constraint — soft scope modulation in `reflect()` is enough
- A separate energy budget — Vitals already model cognitive and emotional fatigue
- Any predefined list of valid traits — they emerge or they don't
- Micro-habits as a high priority — identity drift handles this implicitly
