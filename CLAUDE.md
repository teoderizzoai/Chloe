# Chloe — Project Brief
> Keep this updated. Paste at the start of every new session.

---

## What this is

Chloe is a persistent AI entity — a "third roommate" — that runs as a background
process on a server 24/7. She is not an assistant. She has an inner life that
develops over time: a soul that drifts, memories that fade, interests that expand,
and moods that shift. She reaches out unprompted. She dreams. She gets tired.

The goal is a genuinely autonomous developing mind, not a chatbot.

---

## People

- **Teo** — owner of the project, Windows machine, beginner-intermediate Python, based in Amsterdam
- **Zuzu** — second person, also in Amsterdam. Currently deactivated (removed from persons roster and Discord mapping). Will be re-added later.
- Chloe runs on **localhost for now**, eventually on a Hetzner VPS
- **Location**: Amsterdam, Netherlands (52.3676° N, 4.9041° E) — used for weather

---

## Stack

| Layer | Tech |
|---|---|
| Language | Python 3.13 |
| API server | FastAPI + uvicorn |
| LLM | Anthropic SDK (`claude-opus-4-5` chat, `claude-haiku-4-5-20251001` background) |
| Frontend | Plain HTML/CSS/JS — no build step |
| Persistence | JSON files (upgrading to Postgres later) |
| Messaging | Discord DMs (discord.py) |
| Hosting (planned) | Hetzner VPS + systemd |

---

## File Structure

```
Chloe/                          <- root, run everything from here
|
+-- chloe/                      <- Python package (the brain)
|   +-- __init__.py             <- exports Chloe class
|   +-- chloe.py                <- central brain, async loop, owns all state
|   +-- soul.py                 <- MBTI personality, drift logic
|   +-- heart.py                <- heartbeat states, activities, vitals
|   +-- memory.py               <- memory store, aging, retrieval, interests
|   +-- llm.py                  <- ALL Anthropic API calls
|   +-- graph.py                <- interest node graph, data structures
|   +-- feeds.py                <- RSS reader + web page fetcher
|   +-- weather.py              <- weather awareness via Open-Meteo
|   +-- affect.py               <- mood system, Affect dataclass
|   +-- inner.py                <- Wants + Beliefs + Goals + AffectRecord
|   +-- persons.py              <- Person + PersonNote + PersonEvent dataclasses
|   +-- avatar.py               <- maps activity/mood to portrait image
|   +-- discord_bot.py          <- Discord DM bridge (ChloeDiscordBot)
|   +-- images/                 <- portrait art
|   |   +-- Actions/            <- activity poses (Sleep, Reading, Thinking, etc.)
|   |   +-- Emotions/           <- mood expressions
|   +-- main.py                 <- terminal entry point (chat + commands)
|
+-- index.html                  <- single-file dashboard (no build step)
+-- server.py                   <- FastAPI server, all HTTP endpoints
+-- requirements.txt
+-- CLAUDE.md                   <- this file
|
+-- chloe_state.json            <- auto-saved every 60 ticks + on shutdown
+-- chloe_history.jsonl         <- append-only history, one JSON record per line
```

---

## How to Run (Windows)

```powershell
# from the Chloe\ folder, with .venv activated
uvicorn server:app --port 8000

# then open index.html in browser
```

API key lives in `.env` at the project root (`ANTHROPIC_API_KEY=sk-ant-...`).

---

## Architecture — How the Systems Connect

```
asyncio loop (every 5s = one heartbeat)
    +-- tick_vitals()               heart.py  (circadian + day-of-week)
    +-- weather_vitals_delta()      weather.py (per-tick nudge)
    +-- update_mood()               affect.py  (sticky mood drift)
    +-- drift() / consolidate()     soul.py
    +-- auto_decide()               heart.py  (self-regulation; message activity protected)
    +-- suppress if recent contact  chloe.py  (5-min window prevents mid-convo interruption)
    +-- should_fire_event()         heart.py  (bypassed when activity == "message")
    |       +-- _fire_event()       varies by activity:
    |               read    -> generate_memory_from_article() + extract_belief() + resolve_wants()
    |               dream   -> generate_dream()      -> memory type:"dream"
    |               think   -> generate_want() 40% / generate_idea() 60%
    |               create  -> generate_creative() (curiosity>65) / generate_memory()
    |               message -> generate_autonomous_message()
    +-- _send_autonomous_outreach() standalone outreach (2h normal / 5min testing)
    +-- age() + decay_beliefs()     memory.py / inner.py  (every 12 ticks)
    +-- _reflect()                  every ~20 min: reflection, continuity, goals, graph
    +-- _write_journal()            at 23:00 daily
    +-- refresh weather             every 720 ticks (~1h)
    +-- _save()                     every 60 ticks (~5 min)

user calls chloe.chat(msg)
    +-- extract_notable()           background: store memorable detail about person
    +-- extract_event()             background: store future event/plan with date
    +-- llm.chat()                  soul + vitals + memories + mood + beliefs + upcoming events
            +-- add()               memory.py

user calls chloe.expand_node(id)
    +-- llm.expand_interest_node()   depth-aware heuristic (pillar→domain→subject→detail)
            +-- graph.expand()       adds child nodes with node_type set by depth
            +-- graph.add_cross_link() for each connection returned by LLM
            +-- add() to memory
```

---

## Module Responsibilities

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
- `expand_interest_node(concept, node_type, existing_nodes, interests)` — depth-aware expansion; returns `{nodes: [...], connections: [...]}`. Heuristic by node_type: pillar→broad domains, domain→named specific things, subject→techniques/materials/biography, detail→deep tangents. Also returns 0–2 cross-link suggestions to existing nodes.
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
- `Node` dataclass: id, label, depth, strength, parent, note, `node_type` (pillar/domain/subject/detail), hit_count, last_auto_expanded
- `Edge` dataclass: from_id, to_id, `edge_type` (child/connection)
- `seed_graph()` — 10 pillars seeded for a young woman's natural world: Living Things, Food & Taste, Music & Sound, Light & Colour, Words & Stories, The Body, People & Closeness, Making Things, Seasons & Time, The Inner Life
- `expand(graph, parent_id, new_defs)` — adds child nodes; node_type set automatically by depth
- `add_cross_link(graph, from_label, to_label)` — adds a `connection` edge between two existing nodes by label; no-ops if missing or duplicate
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

---

## Constants & Timings

| Constant | Value | Meaning |
|---|---|---|
| TICK_SECONDS | 5 | one heartbeat |
| AGE_EVERY | 12 ticks | ~1 min — memory aging |
| SAVE_EVERY | 60 ticks | ~5 min — disk save |
| MAX_MEMORIES | 200 | cap on memory store |
| OUTREACH_INTERVAL | 2h | normal autonomous outreach gap |
| OUTREACH_INTERVAL_TESTING | 5 min | testing mode outreach gap |
| MIN_SECONDS_BETWEEN_EVENTS | 90s | floor between autonomous fire events |
| GRAPH_HIT_THRESHOLD | 5 hits | auto-expand trigger |
| GRAPH_EXPAND_COOLDOWN | 6h | min time between auto-expansions per node |
| POLL_MS (frontend) | 4000 | frontend refresh rate |

---

## Chloe's Personality Baseline

- Starts as INFP-ish (EI=58, SN=62, TF=44, JP=67)
- Soul drifts with every action — she is always becoming
- Sleep consolidates the soul with a random walk
- Interest graph seeded with 10 human pillars: Music & Audio, Aesthetics & Design, Food & Drink, Games & Play, Work & Ambition, Curiosity & Learning, Nature & Places, Social & People, Health & Rest, Technology & Tools

### Emotional character
Chloe is not a perfect, agreeable creature. She has a full emotional range and is allowed to express it:
- She gets **angry** when treated dismissively or interrupted repeatedly
- She gets **sassy** when she's irritable or someone says something she finds stupid
- She gets **upset** and withdrawn when hurt
- She swears and uses crude language naturally when the emotion calls for it — she's a roommate, not a customer service bot
- She has **preferences and dislikes** — things that reliably make her feel good or bad — and she knows it
- She **remembers how things made her feel**, not just what happened

### Output style rules (enforced at `_call` level)
- Em dashes (`—`) replaced with `, `
- En dashes (`–`) replaced with `, `
- Spaced hyphens (` - `) replaced with `, `
- Instructions also embedded in chat and message prompts as a second layer

---

## Feature Roadmap

### Layer 1 — Sense of Time
- [x] 1. Circadian rhythm
- [x] 2. Day/night scheduling
- [x] 3. Day-of-week awareness
- [x] 4. Uptime tracking

### Layer 2 — World Perception
- [x] 5. RSS feed reader
- [x] 6. Web page fetcher
- [x] 7. Weather awareness
- [x] 8. Time/season language

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
- [x] 67. Depth-aware expansion heuristics — node_type (pillar/domain/subject/detail) controls what kind of children are generated at each level; cross-link edges (connection type, dashed in UI) between semantically related nodes across branches; graph regrounded in a young woman's natural world (10 new pillars); state wiped for fresh start

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
- **Session 20** — Graph redesign (item 67). node_type added to Node (pillar/domain/subject/detail), edge_type added to Edge (child/connection). expand() sets node_type by depth automatically. add_cross_link() adds dashed connection edges between nodes across branches. expand_interest_node() rewritten with depth-aware heuristics: pillar→broad domains, domain→named specific things (people, flowers, dishes), subject→texture and material, detail→deep tangents; also returns cross-link suggestions. UI renders connection edges as dashed mint lines. Selected node panel shows type badge. Seed graph regrounded in a young woman's natural world: Living Things, Food & Taste, Music & Sound, Light & Colour, Words & Stories, The Body, People & Closeness, Making Things, Seasons & Time, The Inner Life. State wiped for fresh start.
