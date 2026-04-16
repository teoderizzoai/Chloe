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

**Detail** that used to live here (per-function constants, Discord typing pipeline, full endpoint list) is in code comments and `GPT.md` if you keep a longer design log.

---

## Module map (one glance)

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

Everything else in the old “Layer 1–14” checklist is implemented; treat the codebase as source of truth for behavior and tuning.
