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

- **Teo** — owner of the project, Windows machine, beginner-intermediate Python
- **[roommate name]** — second person Chloe will eventually text and model
- Chloe runs on **localhost for now**, eventually on a Hetzner VPS

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
│   ├── llm.py                  ← ALL Anthropic API calls (chat, memory, ideas, graph, etc.)
│   ├── graph.py                ← interest node graph, data structures, physics
│   └── history.py              ← append-only timeline log (.jsonl)
│
├── frontend/
│   └── index.html              ← single-file dashboard (no build step)
│
├── server.py                   ← FastAPI server, all HTTP endpoints
├── main.py                     ← terminal entry point (chat + commands)
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
    ├── tick_vitals()           ← heart.py
    ├── drift() / consolidate() ← soul.py
    ├── auto_decide()           ← heart.py  (self-regulation)
    ├── should_fire_event()     ← heart.py
    │       └── _fire_event()
    │               ├── generate_memory()    ← llm.py → memory.py
    │               ├── generate_idea()      ← llm.py → chloe.ideas
    │               └── generate_autonomous_message() ← llm.py → chat
    ├── age()                   ← memory.py  (every 12 ticks)
    ├── _record()               ← history.py (every 6 ticks)
    └── _save()                 ← disk       (every 60 ticks)

user calls chloe.chat(msg)
    └── llm.chat()              ← soul + vitals + memories as context
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
- `tick_vitals(vitals, activity_id)` — advances vitals one tick
- `auto_decide(vitals, activity)` — returns override activity or None
- `should_fire_event(activity_id)` — probability roll

### `memory.py`
- `Memory` dataclass: text, type, tags, weight, timestamp, id
- `add()`, `age()`, `get_vivid()`, `get_related()`
- `derive_interests()` — tallies tags by weight → ranked list
- `format_for_prompt()` — compact string for LLM injection

### `llm.py`
- `chat()` — Chloe replies to a message
- `generate_memory()` — forms a memory fragment about a topic
- `generate_idea()` — surfaces an original thought
- `expand_interest_node()` — generates 3 child nodes for the graph
- `generate_autonomous_message()` — unprompted text to roommates
- `summarise_state()` — one-sentence inner state description

### `graph.py`
- `Node`, `Edge`, `Graph` dataclasses
- `seed_graph()` — initial nodes (mycelium, light, sound, philosophy, etc.)
- `expand(graph, parent_id, new_defs)` — adds LLM-generated nodes
- `stepPhysics()` — force-directed layout (runs in frontend JS)

### `history.py`
- `Record` dataclass: ts, tick, activity, mbti, soul, vitals, new_memory, new_idea
- `append(record)` — writes one line to `chloe_history.jsonl`
- `load_recent(n)` — reads last N records
- `summarise(records)` — aggregate stats (activity breakdown, soul ranges, vitals trends)

### `chloe.py`
- `Chloe` class — owns all state, runs the loop
- `start()` / `stop()` — async lifecycle
- `chat(message)` — send a message, get reply
- `set_activity(id)` — manual override
- `expand_node(id)` — expand graph node
- `snapshot()` — full serialisable state for the API
- `_tick_once()` — one heartbeat (vitals → soul → auto_decide → events → age → record → save)
- `_fire_event()` — autonomous LLM event based on current activity
- `_record()` — writes history entry
- `_save()` / `_load()` — JSON persistence

### `server.py`
FastAPI endpoints:
- `GET  /snapshot` — full state
- `POST /chat` — send message
- `POST /activity` — change activity
- `POST /expand` — expand graph node
- `POST /soul` — nudge a soul trait
- `GET  /log` — recent log
- `GET  /history?n=200` — last N history records
- `GET  /history/summary` — aggregate stats
- `GET  /health` — alive check

### `frontend/index.html`
Single HTML file. Polls `/snapshot` every 4s.
Tabs: vitals | soul | activity | chat | graph | memory | history

- **Vitals** — energy/social/curiosity bars
- **Soul** — 4 clickable sliders, interest tags, soul description
- **Activity** — 7 activity buttons, current description, recent ideas
- **Chat** — message history, input bar
- **Graph** — canvas force-directed graph, pan/zoom/click to expand
- **Memory** — vivid memories with type/weight/tags
- **History** — soul drift charts, activity breakdown, timeline

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
- [x] FastAPI server with 8 endpoints
- [x] Dashboard: vitals, soul sliders, activity, chat, graph canvas, memory, history
- [x] History log (chloe_history.jsonl) with soul drift charts and timeline
- [x] State persistence (chloe_state.json, survives restarts)
- [x] Windows setup, venv, permanent API key

---

## Feature Roadmap

### Layer 1 — Sense of Time
- [ ] 1. Circadian rhythm — energy/social follow time of day
- [ ] 2. Day/night scheduling — sleep automatic at night
- [ ] 3. Day-of-week awareness — Monday vs Friday personality
- [ ] 4. Uptime tracking — notices how long she's been running

### Layer 2 — World Perception
- [ ] 5. RSS feed reader — absorbs articles during `read` states
- [ ] 6. Web page fetcher — pulls full pages when RSS sparks interest
- [ ] 7. Weather awareness — knows what it's like outside
- [ ] 8. Time/season language — subtle shifts in how she writes

### Layer 3 — Richer Inner Life
- [ ] 9.  Affect layer — mood (irritable, content, restless, melancholic) separate from vitals
- [ ] 10. Wants list — unresolved curiosities she pursues autonomously
- [ ] 11. Belief graph — positions she holds, drift as she reads
- [ ] 12. Dreams — real LLM pass during sleep, reframes memories
- [ ] 13. Creative output — poems/essays when curiosity + energy peak

### Layer 4 — Relational Depth
- [ ] 14. Person profiles — models Teo and roommate distinctly
- [ ] 15. Follow-up memory — remembers things said, asks later
- [ ] 16. Relationship state — warmth/distance per person
- [ ] 17. Reach-out logic — chooses who to contact based on relationship + mood

### Layer 5 — Self-Awareness
- [ ] 18. Self-reflection — reads own history, forms observations
- [ ] 19. Continuity awareness — notices soul drift, comments unprompted
- [ ] 20. Goal tracking — soft intentions, marks resolved
- [ ] 21. Mood journaling — private end-of-day entry

### Layer 6 — Communication
- [ ] 22. SMS via Twilio — actually texts Teo and roommate
- [ ] 23. Message tone awareness — register varies by person/time
- [ ] 24. Conversation threading — groups messages into sessions
- [ ] 25. Notification preferences — learns when people respond

### Layer 7 — Infrastructure
- [ ] 26. VPS deployment — Hetzner, runs 24/7
- [ ] 27. systemd service — auto-restarts on reboot
- [ ] 28. Postgres persistence — replaces JSON files
- [ ] 29. Frontend auth — password for dashboard
- [ ] 30. Mobile-friendly dashboard

---

## Session Log
> Add a line here at the end of every session.

- **Session 1** — Built all core modules in JS (soul, heart, memory, llm, graph, store, App.jsx)
- **Session 2** — Rebuilt everything in Python. Modules: soul.py, heart.py, memory.py, llm.py, graph.py, chloe.py
- **Session 3** — Added FastAPI server (server.py), HTML dashboard (index.html) with graph canvas
- **Session 4** — Added history.py, history tab in dashboard with soul drift charts and timeline
- **Session 5** — Debugged Windows setup: venv, file structure (chloe/ subfolder), API key, uvicorn boot
