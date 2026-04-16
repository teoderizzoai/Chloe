# Chloe — Project Brief

> Keep this updated. Paste at the start of every new session.

---

## What this is

Persistent AI “third roommate”: background loop, inner life (soul drift, mood, memories, wants/goals, graph), unprompted outreach and dreams. Goal is an autonomous developing mind, not a task assistant.

---

## People & place

- **Teo** — owner, Windows, Amsterdam, beginner–intermediate Python.
- **Zuzu** — in the model as a person; messaging off for now; may return later.
- **Runtime** — localhost today; **planned** Hetzner VPS + systemd.
- **Weather** — Amsterdam (52.3676° N, 4.9041° E).

---

## Stack

| Layer | Tech |
| --- | --- |
| Language | Python 3.13 (main app) |
| API | FastAPI + uvicorn (`server.py`) |
| LLM | Anthropic: Opus chat, Haiku background (`chloe/llm.py`) |
| UI | Single-file `index.html` (no build) |
| State | `chloe_state.json`, `chloe_history.jsonl` → Postgres later |
| Discord | `discord.py` — env `DISCORD_BOT_TOKEN`, `DISCORD_TEO_ID` |

**Optional voice** (`run_voice.py`): extra deps in `requirements_voice.txt`. Coqui **TTS** needs a **Python 3.11** venv (not 3.13).

---

## Repo layout (essentials)

```
Chloe/
  chloe/           # package — brain (chloe.py loop, soul, heart, memory, llm, …)
  server.py        # HTTP API
  index.html       # dashboard
  run_voice.py     # optional local voice UI
  requirements.txt
  requirements_voice.txt
  .env             # ANTHROPIC_API_KEY=…
```

---

## Run (Windows)

```powershell
cd Chloe
# .venv with Python 3.13 for the server
uvicorn server:app --port 8000
# Open index.html in the browser
```

Secrets: project root `.env` (`ANTHROPIC_API_KEY`).

---

## How it fits together (one picture)

`Chloe` (`chloe/chloe.py`) runs an asyncio heartbeat (~5s): vitals + mood + soul drift + `auto_decide` activity changes, optional autonomous **read/dream/think/create/message** events, periodic **reflect** / journal / save. **`chloe/llm.py`** owns all Anthropic calls and shared prompt character (`_CHLOE_INNER_LIFE`). **`server.py`** exposes snapshot, chat, activity, graph, testing, Discord status, etc.

**User chat** (`chloe.chat`): emotion read → reply via `llm.chat` (with winding-down when social battery is low), background extraction (notes, events, beliefs), memory add, closing-message handling.

<<<<<<< HEAD
**Detail** that used to live here (per-function constants, Discord typing pipeline, full endpoint list) is in code comments and `GPT.md` if you keep a longer design log.
=======
user calls chloe.expand_node(id)
    +-- llm.expand_interest_node()
            +-- graph.expand()  + add() to memory
```
>>>>>>> cefd2f8bf88c6e346c1723441208399aff869c75

---

## Module map (one glance)

<<<<<<< HEAD
| File | Role |
| --- | --- |
| `chloe.py` | Orchestration, tick loop, chat, fire_event, reflect, persistence |
| `heart.py` | Activities, vitals tick, auto_decide, sleep window, event dice |
| `soul.py` | MBTI sliders, drift, consolidate, seasonal nudge |
| `affect.py` | Moods, arc-influenced drift |
| `memory.py` | Store, age, confidence, tags, prompt formatting |
| `inner.py` | Wants, goals, beliefs, fears, tensions, arc |
| `persons.py` | People, warmth/distance, events, tone, reach-out |
| `llm.py` | All model calls |
| `graph.py` | Interest nodes/edges, expand, cross-links |
| `feeds.py` | RSS, fetch page text, web search |
| `weather.py` | Open-Meteo |
| `discord_bot.py` | DM bridge, realistic send pipeline |
| `avatar.py` | Portrait paths for snapshot/UI |
=======
### `soul.py`
- `Soul` dataclass: 4 floats (EI, SN, TF, JP), each 0-100
- `drift(soul, activity_id)` — nudges sliders based on activity + random flutter
- `content_drift(soul, tags)` — shifts sliders based on keyword clusters in memory tags
- `consolidate(soul)` — random walk during sleep
- `mbti_type(soul)` / `describe(soul)` — type string + plain English description

### `heart.py`
- `HEARTBEAT_STATES` — dict of BPM + label + color per state
- `ACTIVITIES` — dict of Activity dataclasses (id, icon, heart_state, energy_per_tick, social_per_tick, event_chance)
- `Vitals` dataclass: energy, social_battery, curiosity (all 0-100)
- `tick_vitals(vitals, activity_id, hour, weekday)` — one tick; circadian + day-of-week deltas
- `auto_decide(vitals, activity, hour, mood)` — returns override or None; enforces sleep window
- `should_fire_event(activity_id, tick_seconds)` — probability roll (bypassed for message activity)
- `SLEEP_START=23` / `SLEEP_END=7` — night window constants

### `memory.py`
- `Memory` dataclass: text, type, tags, weight, timestamp, id
- Types: `observation`, `conversation`, `idea`, `feeling`, `interest`, `dream`, `creative`
- `add()`, `age()`, `get_vivid()`, `get_related()`
- `derive_interests()` / `derive_fringe_interests()` — ranked tag lists (deep + emerging)
- `format_for_prompt()` — compact string for LLM injection

### `llm.py`
- All API calls centralised here. Output post-processed to strip em dashes, en dashes, spaced hyphens.
- Two-tier: `MODEL_CHAT = claude-opus-4-5` (live chat), `MODEL_FAST = claude-haiku-4-5-20251001` (background)
- `chat()` — reply; injects soul, vitals, memories, mood, beliefs, upcoming events
- `generate_memory_from_article()` — impressionistic memory from RSS article
- `generate_memory()` — generic memory fragment on a topic
- `generate_idea()` — one original thought
- `expand_interest_node()` — 3 child nodes for the interest graph
- `find_or_create_node()` — G3/G4: decide if orphan tag warrants a new graph node
- `generate_autonomous_message()` — unprompted text; aware of recent convo + upcoming events; hard constraint against fabricating threads
- `extract_event()` — detect future plan/event in a message, resolve date, flag if uncertain
- `extract_notable()` — detect something worth remembering about a person
- `generate_followup()` — check-in on something the person mentioned earlier
- `summarise_state()` — one-sentence inner state (novel-line style)
- `generate_dream()` — distorts recent memories into a dream fragment
- `generate_creative()` — poem/fragment/aphorism at peak curiosity
- `generate_want()` — unresolved curiosity to pursue
- `generate_goal()` — soft intention about her own behaviour
- `generate_journal()` — private end-of-day entry
- `generate_reflection()` — self-observation
- `generate_continuity_note()` — notices soul drift
- `generate_completion_feeling()` — emotional reaction to finishing a goal
- `extract_belief()` — position from an article, or None

### `affect.py`
- `MOODS` — 8 moods: content, restless, irritable, melancholic, curious, serene, energized, lonely
- `Affect` dataclass: mood (str), intensity (0-1)
- `update_mood(affect, vitals, weather, hour, activity)` — sticky drift with weather/season tendency
- `force_mood(mood, intensity)` — immediate override (used for harsh messages, goal completion, etc.)

### `inner.py`
- `Want` dataclass + `add_want()`, `resolve_wants()`
- `Belief` dataclass + `add_or_reinforce_belief()`, `decay_beliefs()`
- `Goal` dataclass + `add_goal()`, `resolve_goals()`
- `AffectRecord` dataclass — log of what caused emotional shifts (max 60)
- `add_affect_record()`, `derive_preferences(records)` — lifts/drags from affect history

### `persons.py`
- `PersonNote` dataclass — memorable thing someone shared (text, tags, followed_up)
- `PersonEvent` dataclass — future plan with resolved date (text, date ISO, uncertain flag)
- `Person` dataclass: id, name, warmth, distance, notes, events, conversation_count, last_contact, response_hours
- `on_contact()`, `add_note()`, `add_event()`, `mark_followed_up()`, `tick_distance()`, `boost_warmth()`
- `pending_followups()`, `get_upcoming_events(person, days_ahead=4)`, `format_upcoming_events()`
- `choose_reach_out_target(persons, mood, hour)` — scores by warmth + distance + mood + active hours
- `tone_context(warmth, hour, mood)` — one-line tone guidance for LLM prompts
- `is_likely_active(person, hour)` — response-hour pattern check
- Only Teo active; Zuzu filtered out on load

### `avatar.py`
- Maps activity + mood to portrait PNG path
- Activity images: Sleep, Dream, Rest, Reading, Thinking, Texting, Create
- Mood images (used when resting + strong negative mood): Content, Restless, Irritable, Sad, Happy, Crying
- Returns `{path, key, source}` dict for snapshot

### `graph.py`
- `Node` (id, label, note, strength, hit_count, last_auto_expanded), `Edge`, `Graph` dataclasses
- `seed_graph()` — initial nodes (10 human pillars)
- `expand(graph, parent_id, new_defs)` — adds LLM-generated nodes
- `reinforce_node()`, `match_nodes_by_tags()`, `get_leaf_nodes()`, `mark_auto_expanded()`

### `discord_bot.py`
- `ChloeDiscordBot` — runs as background asyncio task alongside FastAPI
- Handles incoming DMs, routes to `chloe.chat()`, sends reply
- `on_message` / `on_tick` callbacks registered on Chloe at startup
- Avatar updates on state change (rate-limited to 1 per 5.5 min)
- `status()` — connection health for `/discord/status` endpoint
- Env vars: `DISCORD_BOT_TOKEN`, `DISCORD_TEO_ID`

### `chloe.py`
- `Chloe` class — owns all state, runs the loop
- State: soul, vitals, activity, memories, graph, chat_history, ideas, weather, affect, wants, beliefs, goals, creative_outputs, persons, affect_records, testing_mode
- `start()` / `stop()` — async lifecycle
- `chat(message, person_id)` — reply; extracts notes + events from message in background
- `set_activity(id)` — manual override (message activity protected from auto_decide)
- `expand_node(id)` — manual graph expansion
- `snapshot()` — full serialisable state
- `_tick_once()` — full tick pipeline
- `_fire_event()` — autonomous LLM event by activity type
- `_send_autonomous_outreach()` — standalone outreach (independent of activity)
- `_reflect()` — self-reflection, continuity, goals, graph intelligence (every ~20 min)
- `_write_journal()` — end-of-day private journal at 23:00
- `_save()` / `_load()` — JSON persistence
- `testing_mode` — floors vitals, blocks sleep, outreach every 5 min, bypass activity locks

### `server.py`
FastAPI endpoints:
- `GET  /snapshot` — full state
- `POST /chat` — send message (`{message, person_id}`)
- `GET  /persons` — relationship state for known persons
- `POST /activity` — change activity
- `POST /expand` — expand graph node
- `POST /soul` — nudge a soul trait
- `POST /vitals` — set vitals values
- `POST /affect` — set mood
- `DELETE /graph/{node_id}` — remove graph node
- `GET  /log` — recent activity log
- `GET  /weather` — current weather + season
- `GET  /health` — alive check + tick count
- `POST /testing` — toggle/set testing (cocaine) mode
- `GET  /discord/status` — Discord bot connection health

### `index.html`
Single HTML file. Polls `/snapshot` every 4s.
Tabs: **graph** (force-directed, default) | **memory** | **ideas** | **mind** | **log** | **admin** | **people**
- Admin tab: cocaine mode toggle, vitals nudge, mood override, activity override, soul sliders
- Chat bar at bottom; person selector for Teo (others when added)
- Profile card: portrait image, name, MBTI, mood badge
>>>>>>> cefd2f8bf88c6e346c1723441208399aff869c75

---

## Useful constants (approximate)

| Name | Meaning |
| --- | --- |
| Tick | ~5 s |
| `SAVE_EVERY` | ~5 min save |
| `REFLECT_EVERY` | ~20 min deeper pass |
| `OUTREACH_INTERVAL` | 2 h (shorter in testing mode) |
| `MIN_SECONDS_BETWEEN_EVENTS` | ~90 s floor between autonomous events |

Exact numbers live next to the definitions in `chloe.py` / `heart.py`.

---

## Character defaults (for prompts, not rigid lore)

- Starting vibe: INFP-ish; soul and graph **change over time**.
- Full emotional range; can be sharp or warm; not customer-service tone.
- **Output cleanup** in LLM layer: em dash / en dash / spaced hyphen normalization.

---

## Roadmap — what is actually left

Infrastructure and polish not done yet:

- VPS + systemd 24/7
- Postgres instead of JSON
- Dashboard auth + mobile-friendly UI

<<<<<<< HEAD
Everything else in the old “Layer 1–14” checklist is implemented; treat the codebase as source of truth for behavior and tuning.
=======
### Layer 3 — Richer Inner Life
- [x] 9.  Affect layer — 8 moods, sticky drift
- [x] 10. Wants list — unresolved curiosities
- [x] 11. Belief graph — positions with confidence
- [x] 12. Dreams — LLM distorts recent memories
- [x] 13. Creative output — poems/fragments/aphorisms

### Layer 4 — Relational Depth
- [x] 14. Person profiles — warmth/distance per person
- [x] 15. Follow-up memory — remembers things said, asks later
- [x] 16. Relationship state — warmth/distance
- [x] 17. Reach-out logic — scores by warmth + distance + mood + active hours
- [x] 18. Event tracking — future plans extracted from messages, stored with resolved date; uncertain dates flagged; injected into prompts when date is near; Chloe can ask for clarification

### Layer 5 — Self-Awareness
- [x] 19. Self-reflection
- [x] 20. Continuity awareness — notices soul drift
- [x] 21. Goal tracking — soft intentions, marks resolved
- [x] 22. Mood journaling — private end-of-day entry

### Layer 6 — Communication
- [x] 23. Discord DMs — Chloe texts Teo via Discord DMs; env: DISCORD_BOT_TOKEN / DISCORD_TEO_ID
- [x] 24. Message tone awareness — register varies by warmth + time of day
- [x] 25. Conversation threading — 30-min gap = new session
- [x] 26. Notification preferences — learns when Teo responds (response_hours per person)

### Layer 7 — Graph Intelligence
- [x] 27. Node resonance — fire_events reinforce matching graph nodes (hit_count + strength)
- [x] 28. Strength-threshold auto-expansion — leaf nodes expand after 5 hits (curiosity>55, 6h cooldown)
- [x] 29. Orphan tag surfacing — tags in 3+ memories with no node → LLM decides, max 2/reflect
- [x] 30. Dream recurrence — tags in 3+ dreams → depth-1 node off root, 1/reflect

### Layer 8 — Deeper Personality & World Influence
- [x] 31. Content-aware soul drift — soul sliders shift based on article/conversation content
- [x] 32. Mood-driven activity preference — restless → create, melancholic → read/dream, lonely → message
- [x] 33. Completion has emotional weight — goal/creative finish → feeling memory + mood nudge
- [x] 34. Repeated exposure deepens interests — recurring tags increase node weight visually
- [x] 35. Weather/season → mood tendency
- [x] 36. Isolation drift — EI shifts toward I + lonely mood when all persons distant
- [x] 37. Activity streak effects — flow state + saturation
- [x] 38. Dream recurrence — recurring dream tags increase want surfacing
- [x] 39. Seasonal personality accumulation — slow multi-week drift
- [x] 40. Emotional weight of world events — devastating/beautiful articles hit mood harder

### Layer 9 — Emotional Memory & Self-Knowledge
- [x] 41. Affect record — rolling log of what caused emotional shifts; informs likes/dislikes
- [x] 42. Likes and dislikes — derived from affect record; injected into chat and messages
- [x] 43. Harsh treatment reactions — dismissive messages → irritable mood + feeling memory
- [x] 44. Emotional resonance — shared interests → warmth boost + curious nudge
- [x] 45. Full authentic emotional range — anger, sass, sulking in natural language incl. profanity

### Layer 10 — Relational Depth (Human Interaction)
- [x] 46. Shared moments / inside jokes
- [x] 47. Warmth-scaled voice — guarded at low warmth, loose and strange at high warmth
- [x] 48. Relationship stage — "getting to know" / "familiar" / "close" / "very close"
- [x] 49. Conflict tracking
- [x] 50. Cross-person references (Zuzu re-added with messaging_disabled=True; cross-reference fires when relevant)
- [x] 51. Ignored after reaching out — distance increases, mood drifts toward lonely
- [x] 52. Teo and Zuzu as fully distinct — per-person impression (generate_person_impression, Haiku), injected into chat + autonomous message prompts; Zuzu messaging disabled, present in system

### Layer 11 — Personality Crystallisation
- [x] 58. Soul → activity feedback loop — `soul_activity_affinity()` modulates auto_decide soft-drift probabilities; aligned activities become more likely as traits strengthen
- [x] 59. Trait momentum — EMA (α=0.015) of per-tick drift; same-direction moves amplified up to 1.8×, opposing dampened to 0.5×; saturates ≈ ±1.0 after ~5.5 min of consistent activity
- [x] 60. Emotional events leave soul marks — harsh message → +I+F; devastating article → +F; beautiful article → +N+P; goal completion → +J; creative breakthrough → +N+P
- [x] 61. Sleep reinforces recent drift — consolidate() biased by momentum (0.0004×/tick); over 8h sleep, pushes ~1.8 pts in the direction waking life was heading

### Layer 12 — Infrastructure
- [ ] 62. VPS deployment — Hetzner, runs 24/7
- [ ] 63. systemd service — auto-restarts on reboot
- [ ] 64. Postgres persistence — replaces JSON files
- [ ] 65. Frontend auth — password for dashboard
- [ ] 66. Mobile-friendly dashboard

---

## Session Log

- **Session 1** — Built all core modules in JS (soul, heart, memory, llm, graph, store, App.jsx)
- **Session 2** — Rebuilt everything in Python. Modules: soul.py, heart.py, memory.py, llm.py, graph.py, chloe.py
- **Session 3** — Added FastAPI server (server.py), HTML dashboard (index.html) with graph canvas
- **Session 4** — Added history.py, history tab in dashboard with soul drift charts and timeline
- **Session 5** — Debugged Windows setup: venv, file structure (chloe/ subfolder), API key, uvicorn boot
- **Session 6** — Two-tier LLM (Haiku/Opus). Layer 1 complete: circadian rhythm, night sleep scheduling, day-of-week personality, uptime tracking
- **Session 7** — Layer 2 complete: RSS feed reader (feeds.py), web page fetcher (bs4), weather awareness via Open-Meteo (weather.py), season/time language injected into all LLM prompts
- **Session 8** — Layer 3 complete: affect.py, inner.py, dreams, creative output, belief extraction, want resolution, mood pill + mind tab
- **Session 9** — Layer 4 complete: persons.py, extract_notable, generate_followup, person_id in chat, follow-up logic, people section in sidebar
- **Session 10** — Layer 5 complete: Goal dataclass, generate_reflection/continuity/goal/journal, _reflect() + _write_journal(), soul_baseline drift, goals in mind tab
- **Session 11** — UI redesign: 2-column layout, graph as main tab, persistent chat bar, cleaner tab bar. Designed Graph Intelligence spec (G1-G4)
- **Session 12** — Pivoted Layer 6 to Discord DMs. discord_bot.py; on_message callback with person_id; Discord starts in server.py lifespan; env vars DISCORD_BOT_TOKEN / DISCORD_TEO_ID / DISCORD_ZUZU_ID
- **Session 13** — Layer 7 complete (27-30): node resonance, threshold auto-expansion, orphan tag surfacing, dream recurrence root nodes
- **Session 14** — Layer 8+9 complete: items 31, 33, 35, 36, 37, 40, 41, 43, 44. Content-aware soul drift; goal completion feeling; weather mood tendency; isolation drift; activity streak effects; world event emotional weight; AffectRecord; harsh message detection; shared-interest resonance
- **Session 15** — Messaging reliability (message mode bypasses dice roll, protected from auto_decide override, social gate fixed). Zuzu removed (filtered on load, removed from Discord mapping). Testing/cocaine mode (POST /testing, UI toggle in admin). Discord status endpoint. Em dash stripping at _call level (covers all outputs). No-fabricated-continuity rule in autonomous messages. Active-conversation suppression (5-min window). PersonEvent — extract future plans from messages, resolve dates, inject into prompts when near. avatar.py reading image fix. Layer 6 item 23 updated (Teo only). Item 18 added (event tracking).
- **Session 16** — Item 32: mood-driven activity preference. Added MOOD_ACTIVITY_AFFINITY dict (all 8 moods → preferred activities). Exhaustive mood checks across all 7 activity states in auto_decide: restless/melancholic/lonely/curious/energized/irritable/serene/content each drive transitions from dream, rest, read, think, create, and message. Item 34: hit_count now drives node visual weight (log-scale radius factor, opacity/stroke boost) and displays "N resonances" in selected node panel. Items 38+39: dream recurrence now also surfaces a Want from the recurring tag (generate_dream_want in llm.py, Haiku call); seasonal_drift() added to soul.py with per-month MBTI nudges (~2 pts/trait/season at 24/7 runtime), called every tick from _tick_once.
- **Session 18** — Layer 9 properly implemented. Items 41+42: `preferences` (lifts/drags) added to snapshot; mind tab now shows emotional history and lifts/drags sections. Item 45: explicit per-mood tone instructions in chat and autonomous message prompts. Likes/dislikes now form organically via `content_affect()` — scores every article/conversation/memory against soul alignment, logging affect records with real content tags. Items 43+44: replaced brittle keyword detection with `read_person_emotion` (Haiku, runs before reply with 6-message conversation context). Detects full emotional range (affectionate, playful, excited, grateful, tender, curious, thoughtful, neutral, tired, sad, anxious, stressed, lonely, overwhelmed, disappointed, frustrated, angry, dismissive, cold, hurt) with directed_at_chloe flag — emotions about Chloe shift her mood/soul/warmth directly; emotions about Teo's own life trigger empathy responses. `_apply_emotion_reaction` handles each case with graduated mood shifts, warmth boosts, feeling memories, soul marks, and meaningful affect record tags.
- **Session 19** — Layer 10 complete: items 46+47+48+49+50+51+52 + third-party tracking extension. Item 51: _pending_outreach list on Chloe; recorded when autonomous outreach fires (both _fire_event and _send_autonomous_outreach paths); cleared immediately when person replies in chat(); _check_ignored_outreach() runs every AGE_EVERY ticks — if sent_at + 4h (10min testing) has passed and person.last_contact < sent_at, applies distance+10, warmth-0.5, mood→lonely, feeling memory + affect record; persisted across restarts. Item 50: messaging_disabled field on Person; Zuzu re-added to default_persons() with messaging_disabled=True; choose_reach_out_target filters disabled persons; discord _on_chloe_message checks flag before sending; Discord maps Zuzu for incoming but won't initiate; persons_from_dicts ensures Zuzu is always present; format_cross_person_context() matches other persons' notes/moments by tag overlap and injects naturally into chat prompt. Item 46: SharedMoment dataclass added to persons.py (text, tags, timestamp, reference_count); moments field on Person with serialization; add_moment(), format_shared_moments(), increment_moment_reference() helpers; extract_shared_moment() in llm.py (Haiku, detects memorable exchanges post-chat); _extract_and_store_moment() background task in chloe.py; shared_moments injected into chat() prompt; people tab shows moments section with reference count badges. Item 47: tone_context() rewritten with 4 distinct voice registers keyed to warmth (0–30 guarded, 30–55 warming up, 55–78 familiar, 78+ very close) — each with specific behavioral instructions about what Chloe reveals, how filtered she is, whether strangeness is allowed, whether shared history is accessible. Time-of-day modifier preserved. Applies to both chat() and generate_autonomous_message().
- **Session 17** — Soul drift fix: ACTIVITY_DRIFT values 5× larger (0.001–0.002/tick), flutter reduced 4× (±0.0005); trait values now display to 1 decimal with trend arrows (32s rolling window). Layer 11 Personality Crystallisation complete: item 58 (soul_activity_affinity — soul traits modulate auto_decide soft-drift probabilities), item 59 (trait momentum via EMA α=0.015, amplifies/dampens drift in drift() and consolidate()), item 60 (emotional soul marks at 5 locations: harsh message +I+F, devastating article +F, beautiful article +N+P, goal completion +J, creative output +N+P), item 61 (consolidate() biased by momentum — sleep carries forward waking drift direction). Conversation soul impact: message ACTIVITY_DRIFT tripled in magnitude and now includes SN=-0.0025/tick (toward S — conversations are concrete and present); content_drift now runs on every chat() call using the full text of message + reply, so the actual content of conversations shapes the soul the same way articles do.
>>>>>>> cefd2f8bf88c6e346c1723441208399aff869c75
