# Chloe — Upcoming Features Checklist

Cross off items when done. Implementation detail in 05_FEATURES.md; history in 04_DEV_LOG.md.

---

## Cognition

- [ ] **C2** — Failure consequences on traits: goal/want failure → trait weight penalty + `setback_note`; repeated failures → suppression belief ("I don't seem to be the kind of person who X")
- [ ] **F2** — Competing impulses: two high-pressure states target incompatible activities; probabilistic resolution; loser leaves residue memory ("wanted to X but didn't") feeding recurring loops
- [ ] **G2** — Narrative self-model: weekly Haiku generates Chloe's own—possibly inaccurate—self-story as a belief; inaccuracy tracked against actual trait list

## Relationships

- [ ] **C5** — Attachment patterns: per-person style derived from warmth/outreach/conflict history → Haiku-generated, stored in `persons`; influences risk tolerance and trait activation
- [ ] **D2** — Tone register becomes trait-aware: warmth tier determines which traits are emphasised, not just access level; warmth > 78 → full trait expression including contradictions

## Self-History

- [ ] **E1** — Identity drift awareness: weekly trait snapshot comparison → `self_change_note` belief biased by current mood; "I think I used to care more about X"
- [ ] **E2** — Self-history from DEV_LOG: DEV_LOG as narrative material → `self_origin_narrative` belief cluster; uncertain, mood-colored
- [ ] **E3** — Regret system: `regret` objects from repeated failure/frustration; surfaces in melancholic/irritable reflection; influences future goals; decays slowly

## Dashboard

- [ ] Residue indicator (visual signal when total emotional residue > threshold)
- [ ] Recurring loops display (show top 3 current mental loops)
- [ ] Curiosity queue (show active `curiosity_question` wants)

## Infrastructure

- [ ] VPS (Hetzner) + systemd deployment
- [ ] Frontend auth + mobile-friendly dashboard
- [ ] SQLite backup strategy (currently only JSON is backed up at 23:00)
