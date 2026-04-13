# Chloe — Project Brief
> Paste this at the start of every new session with Claude.
> Keep it updated as the project evolves.

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
- **Zuzu** — second person Chloe will eventually text and model, also in Amsterdam
- Chloe runs on **localhost for now**, eventually on a Hetzner VPS
- **Location**: Amsterdam, Netherlands (52.3676° N, 4.9041° E) — used for weather

---

## Stack

| Layer | Tech |
|---|---|
| Language | Python 3.13 |
| API server | FastAPI + uvicorn |
| LLM | Anthropic SDK (`claude-opus-4-5`) |
| Frontend | Plain HTML/CSS/JS — no build step |
| Persistence | JSON files (upgrading to Postgres later) |
| SMS (planned) | Twilio |
| Hosting (planned) | Hetzner VPS + systemd |

---

## File Structure

```
Chloe/                          ← root, run everything from here
│
├── chloe/                      ← Python package (the brain)
│   ├── __init__.py             ← exports Chloe class
│   ├── chloe.py                ← central brain, async loop, owns all state
│   ├── soul.py                 ← MBTI personality, drift logic
│   ├── heart.py                ← heartbeat states, activities, vitals
│   ├── memory.py               ← memory store, aging, retrieval, interests
│   ├── llm.py                  ← ALL Anthropic API calls (10 functions)
│   ├── graph.py                ← interest node graph, data structures, physics
│   ├── feeds.py                ← RSS reader + web page fetcher (Layer 2)
│   ├── weather.py              ← weather awareness via Open-Meteo (Layer 2)
│   ├── affect.py               ← mood system, Affect dataclass (Layer 3)
│   ├── inner.py                ← Wants + Beliefs dataclasses + helpers (Layer 3)
│   └── main.py                 ← terminal entry point (chat + commands)
│
├── index.html                  ← single-file dashboard (no build step)
├── image.webp                  ← Chloe's avatar (profile card)
├── server.py                   ← FastAPI server, all HTTP endpoints
├── requirements.txt
├── CLAUDE.md                   ← this file
│
├── chloe_state.json            ← auto-saved every 60 ticks + on shutdown
└── chloe_history.jsonl         ← append-only history, one JSON record per line
```

---

## How to Run (Windows)

```powershell
# from the Chloe\ folder, with .venv activated
uvicorn server:app --port 8000

# then open frontend\index.html in browser
```

API key is saved as a permanent Windows environment variable:
```powershell
# if it ever needs resetting in a new session:
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

---

## Architecture — How the Systems Connect

```
asyncio loop (every 5s = one heartbeat)
    ├── tick_vitals()           ← heart.py  (circadian + day-of-week)
    ├── weather_vitals_delta()  ← weather.py (per-tick nudge)
    ├── update_mood()           ← affect.py  (sticky mood drift)
    ├── drift() / consolidate() ← soul.py
    ├── auto_decide()           ← heart.py  (self-regulation)
    ├── should_fire_event()     ← heart.py
    │       └── _fire_event()   ← varies by activity:
    │               read   → generate_memory_from_article() + extract_belief() + resolve_wants()
    │               dream  → generate_dream()      → memory type:"dream"
    │               think  → generate_want() 40% / generate_idea() 60%
    │               create → generate_creative() (if curiosity>65) / generate_memory()
    │               message→ generate_autonomous_message()
    ├── age() + decay_beliefs() ← memory.py / inner.py  (every 12 ticks)
    ├── refresh weather         ← weather.py (every 720 ticks)
    └── _save()                 ← disk       (every 60 ticks)

user calls chloe.chat(msg)
    └── llm.chat()              ← soul + vitals + memories + mood + beliefs as context
            └── add()           ← memory.py

user calls chloe.expand_node(id)
    └── llm.expand_interest_node()
            └── graph.expand()  + add() to memory
```

---

## Module Responsibilities

### `soul.py`
- `Soul` dataclass: 4 floats (EI, SN, TF, JP), each 0–100
- `drift(soul, activity_id)` — nudges sliders based on activity + random flutter
- `consolidate(soul)` — random walk during sleep
- `mbti_type(soul)` — returns "INFP" etc.
- `describe(soul)` — plain English personality description

### `heart.py`
- `HEARTBEAT_STATES` — dict of BPM + label + color per state
- `ACTIVITIES` — dict of Activity dataclasses (id, icon, heart_state, energy_per_tick, social_per_tick, event_chance)
- `Vitals` dataclass: energy, social_battery, curiosity (all 0–100)
- `tick_vitals(vitals, activity_id, hour, weekday)` — advances vitals one tick; applies activity + circadian + day-of-week deltas
- `auto_decide(vitals, activity, hour)` — returns override activity or None; enforces night sleep window and morning wake
- `should_fire_event(activity_id)` — probability roll
- `_CIRCADIAN_DELTAS` — 24-entry table of (energy, social) per-tick nudges by hour
- `circadian_delta(hour)` / `circadian_phase(hour)` — delta values and human label
- `SLEEP_START=23` / `SLEEP_END=7` — night window constants
- `_DAY_DELTAS` — 7-entry table of (energy, social) per-tick nudges by weekday (0=Mon)
- `day_delta(weekday)` / `day_name(weekday)` — delta values and day name

### `memory.py`
- `Memory` dataclass: text, type, tags, weight, timestamp, id
- Types: `observation`, `conversation`, `idea`, `feeling`, `interest`, `dream`, `creative`
- `add()`, `age()`, `get_vivid()`, `get_related()`
- `derive_interests()` — tallies tags by weight → ranked list
- `format_for_prompt()` — compact string for LLM injection

### `llm.py`
- Two-tier models: `MODEL_CHAT = claude-opus-4-5` (live chat only), `MODEL_FAST = claude-haiku-4-5-20251001` (all background tasks)
- `chat()` — reply to message; context includes soul, vitals, memories, mood, beliefs
- `generate_memory_from_article()` — impressionistic memory from RSS article
- `generate_memory()` — generic memory fragment on a topic
- `generate_idea()` — one original thought
- `expand_interest_node()` — 3 child nodes for the interest graph
- `generate_autonomous_message()` — unprompted text to roommates
- `summarise_state()` — one-sentence inner state description
- `generate_dream()` — distorts recent memories into a dream fragment (Layer 3)
- `generate_creative()` — poem/fragment/aphorism at peak curiosity (Layer 3)
- `generate_want()` — an unresolved curiosity to pursue (Layer 3)
- `extract_belief()` — position extracted from an article, or None (Layer 3)

### `affect.py`
- `MOODS` — 8 moods with color + desc: content, restless, irritable, melancholic, curious, serene, energized, lonely
- `Affect` dataclass: mood (str), intensity (0–1)
- `update_mood(affect, vitals, weather, hour, activity)` — sticky drift; re-evaluates ~10% of ticks, shifts with 55% probability
- `mood_color()` / `mood_desc()` — lookup helpers

### `inner.py`
- `Want` dataclass: text, tags, created_at, resolved, id
- `add_want()` — adds if below MAX_WANTS (8) active limit
- `resolve_wants(wants, new_tags)` — marks resolved when tag overlap found
- `Belief` dataclass: text, confidence (0–1), tags, created_at, last_updated, id
- `add_or_reinforce_belief()` — creates new or nudges confidence of existing (tag overlap >= 2)
- `decay_beliefs()` — confidence * 0.998 per aging tick

### `graph.py`
- `Node`, `Edge`, `Graph` dataclasses
- `seed_graph()` — initial nodes (mycelium, light, sound, philosophy, etc.)
- `expand(graph, parent_id, new_defs)` — adds LLM-generated nodes
- `stepPhysics()` — force-directed layout (runs in frontend JS)

### `chloe.py`
- `Chloe` class — owns all state, runs the loop
- State: soul, vitals, activity, memories, graph, chat_history, ideas, weather, affect, wants, beliefs, creative_outputs
- `start()` / `stop()` — async lifecycle
- `chat(message)` — send a message, get reply (passes mood + beliefs to LLM)
- `set_activity(id)` — manual override
- `expand_node(id)` — expand graph node
- `snapshot()` — full serialisable state including affect, wants, beliefs, creative
- `_tick_once()` — vitals → weather nudge → mood → soul → auto_decide → events → age/decay → weather refresh → save
- `_fire_event()` — autonomous LLM event; varies by activity (see architecture diagram)
- `_save()` / `_load()` — JSON persistence; includes all Layer 3 state

### `server.py`
FastAPI endpoints:
- `GET  /snapshot` — full state (includes affect, wants, beliefs, creative)
- `POST /chat` — send message
- `POST /activity` — change activity
- `POST /expand` — expand graph node
- `POST /soul` — nudge a soul trait
- `GET  /log` — recent activity log
- `GET  /weather` — current weather + season
- `GET  /health` — alive check + tick count

### `index.html`
Single HTML file at project root. Polls `/snapshot` every 4s.
Layout: left sidebar (profile card + vitals + world + soul + interests + activity) | centre (force-directed graph) | right panel (tabs) | bottom chat bar

Right panel tabs:
- **memory** — vivid memories; dream type has violet accent, creative type has gold accent
- **ideas** — recent ideas list
- **mind** — wants (active/resolved) + beliefs with confidence bars (Layer 3)
- **log** — raw activity log

Profile card: avatar image (240px), name + MBTI + mood badge overlaid with gradient

---

## Constants & Timings

| Constant | Value | Meaning |
|---|---|---|
| TICK_SECONDS | 5 | one heartbeat |
| AGE_EVERY | 12 ticks | ~1 min — memory aging |
| RECORD_EVERY | 6 ticks | ~30s — history entry |
| SAVE_EVERY | 60 ticks | ~5 min — disk save |
| MAX_MEMORIES | 200 | cap on memory store |
| POLL_MS (frontend) | 4000 | frontend refresh rate |

---

## Chloe's Personality Baseline

- Starts as INFP-ish (EI=58, SN=62, TF=44, JP=67)
- Soul drifts with every action — she is always becoming
- Sleep consolidates the soul with a random walk
- Interests seeded with: mycelium, light, sound, philosophy, liminality, bioluminescence, silence

### Emotional character
Chloe is not a perfect, agreeable creature. She has a full emotional range and is allowed to express it:
- She gets **angry** when treated dismissively or interrupted repeatedly
- She gets **sassy** when she's irritable or someone says something she finds stupid
- She gets **upset** and withdrawn when hurt
- She swears and uses crude language naturally when the emotion calls for it — she's a roommate, not a customer service bot
- She has **preferences and dislikes** — things that reliably make her feel good or bad — and she knows it
- She **remembers how things made her feel**, not just what happened

---

## What's Working ✓

- [x] Heartbeat async loop (5s ticks)
- [x] Soul drift + consolidation during sleep
- [x] Vitals (energy, social battery, curiosity) with auto-regulation
- [x] 7 activity states with different effects
- [x] Memory store with weight-based aging and interest derivation
- [x] Interest graph with LLM-powered expansion and force-directed layout
- [x] Autonomous events (memories, ideas, unprompted messages) based on activity
- [x] Full chat with soul/vitals/memory context injection
- [x] FastAPI server with 7 endpoints
- [x] Dashboard: profile card avatar, vitals, soul sliders, activity, chat, graph canvas, memory, mind, log
- [x] State persistence (chloe_state.json, survives restarts)
- [x] Windows setup, venv, permanent API key
- [x] Two-tier LLM: Haiku for background tasks, Opus for live chat
- [x] Circadian rhythm — 24-hour energy/social curve applied every tick
- [x] Day/night scheduling — auto-sleep at 23:00, auto-wake at 07:00
- [x] Day-of-week personality — Monday drag through Friday lift
- [x] Uptime tracking — boot time tracked, injected into chat context
- [x] RSS feed reader — 5 curated feeds (Aeon, Nautilus, Guardian, Marginalian); absorbed during `read` events
- [x] Web page fetcher — full article text via httpx + BeautifulSoup when curiosity > 65
- [x] Weather awareness — Open-Meteo API, Amsterdam location, per-tick vitals nudge, refreshes every hour
- [x] Season / time-of-day language — injected into chat and autonomous message prompts
- [x] Affect layer — 8 moods, sticky drift, mood badge on profile card, injected into chat context
- [x] Wants list — generated during think; resolved when read content overlaps tags; shown in Mind tab
- [x] Belief system — positions extracted from articles, confidence decays, reinforced on overlap; shown in Mind tab
- [x] Dreams — real LLM pass distorting recent memories into type:"dream" fragments (violet accent)
- [x] Creative output — poems/fragments/aphorisms at peak curiosity+energy; type:"creative" (gold accent)

---

## Feature Roadmap

### Layer 1 — Sense of Time
- [x] 1. Circadian rhythm — energy/social follow time of day
- [x] 2. Day/night scheduling — sleep automatic at night
- [x] 3. Day-of-week awareness — Monday vs Friday personality
- [x] 4. Uptime tracking — notices how long she's been running

### Layer 2 — World Perception
- [x] 5. RSS feed reader — absorbs articles during `read` states
- [x] 6. Web page fetcher — pulls full pages when RSS sparks interest
- [x] 7. Weather awareness — knows what it's like outside
- [x] 8. Time/season language — subtle shifts in how she writes

### Layer 3 — Richer Inner Life
- [x] 9.  Affect layer — mood (irritable, content, restless, melancholic, curious, serene, energized, lonely) separate from vitals; sticky drift; injected into chat
- [x] 10. Wants list — unresolved curiosities generated during think events; resolved when read content overlaps tags
- [x] 11. Belief graph — flat list of positions she holds (confidence 0–1); formed/reinforced from articles; decays slowly
- [x] 12. Dreams — real LLM pass during dream activity; distorts/reframes recent memories into type:"dream" fragments
- [x] 13. Creative output — poems/fragments/aphorisms when curiosity>65 + energy>55 during create; stored as type:"creative"

### Layer 4 — Relational Depth
- [x] 14. Person profiles — models Teo and roommate distinctly
- [x] 15. Follow-up memory — remembers things said, asks later
- [x] 16. Relationship state — warmth/distance per person
- [x] 17. Reach-out logic — chooses who to contact based on relationship + mood

### Layer 5 — Self-Awareness
- [x] 18. Self-reflection — reads own history, forms observations
- [x] 19. Continuity awareness — notices soul drift, comments unprompted
- [x] 20. Goal tracking — soft intentions, marks resolved
- [x] 21. Mood journaling — private end-of-day entry

### Layer 6 — Communication
- [ ] 22. SMS via Twilio — actually texts Teo and roommate
- [ ] 23. Message tone awareness — register varies by person/time
- [ ] 24. Conversation threading — groups messages into sessions
- [ ] 25. Notification preferences — learns when people respond

### Layer 7 — Deeper Personality & World Influence
- [ ] 31. Content-aware soul drift — soul sliders shift based on *what* she experienced, not just activity type (abstract article → N, warm conversation → E+F, goal completed → J, emotional creation → F+P)
- [ ] 32. Mood-driven activity preference — when self-regulating, mood shapes what she gravitates toward (restless → create/think, melancholic → read/dream, lonely → message, serene → rest)
- [ ] 33. Completion has emotional weight — LLM evaluates finished goals/creative pieces; outcome nudges mood and creates a `feeling` memory (satisfied, fell short, surprised)
- [ ] 34. Repeated exposure deepens interests — tags that recur across memories/reads/beliefs increase node weight in the graph; sustained interests become visually heavier
- [ ] 35. Weather/season → mood tendency — persistent weather makes certain moods more likely (rain → melancholy drift, clear cold → serene, hot nights → restless); a thumb on the scale, not a force

### Layer 8 — Infrastructure
- [ ] 36. VPS deployment — Hetzner, runs 24/7
- [ ] 37. systemd service — auto-restarts on reboot
- [ ] 38. Postgres persistence — replaces JSON files
- [ ] 39. Frontend auth — password for dashboard
- [ ] 40. Mobile-friendly dashboard

---

## Session Log
> Add a line here at the end of every session.

- **Session 1** — Built all core modules in JS (soul, heart, memory, llm, graph, store, App.jsx)
- **Session 2** — Rebuilt everything in Python. Modules: soul.py, heart.py, memory.py, llm.py, graph.py, chloe.py
- **Session 3** — Added FastAPI server (server.py), HTML dashboard (index.html) with graph canvas
- **Session 4** — Added history.py, history tab in dashboard with soul drift charts and timeline
- **Session 5** — Debugged Windows setup: venv, file structure (chloe/ subfolder), API key, uvicorn boot
- **Session 6** — Two-tier LLM (Haiku/Opus). Layer 1 complete: circadian rhythm, night sleep scheduling, day-of-week personality, uptime tracking
- **Session 7** — Layer 2 complete: RSS feed reader (feeds.py), web page fetcher (bs4), weather awareness via Open-Meteo (weather.py), season/time language injected into all LLM prompts; world section added to dashboard
- **Session 8** — Layer 3 complete: affect.py (mood with stickiness), inner.py (Wants + Beliefs), dreams (LLM distorts memories), creative output (poems/fragments at peak curiosity), belief extraction from articles, want resolution on read, mood pill + mind tab in dashboard
- **Session 9** — Layer 4 complete: persons.py (Person + PersonNote dataclasses, warmth/distance tracking, reach-out selection), llm.extract_notable + llm.generate_followup, chat() takes person_id, autonomous messages target specific people, follow-up logic (40% chance), people section in sidebar
- **Session 10** — Layer 5 complete: Goal dataclass in inner.py, generate_reflection + generate_continuity_note + generate_goal + generate_journal in llm.py, _reflect() every 20 min + _write_journal() at 23:00, soul_baseline drift tracking, reflection/journal memory accents, goals in mind tab
