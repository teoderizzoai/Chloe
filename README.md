# Chloe

Chloe is a persistent AI entity designed as a "third roommate," not a task assistant.
She runs continuously, develops over time, forms memories and beliefs, tracks mood,
and reaches out unprompted.

<img src="https://i.ibb.co/fVnbm5jP/Chloe-Texting.png" alt="Chloe Texting" width="700" />

## What Chloe Is

- A long-running autonomous mind with an inner loop
- Personality that drifts over time (MBTI-style sliders)
- Memory system with decay, vividness, and tag-based retrieval
- Mood, wants, beliefs, goals, and journaling
- Interest graph that expands from lived experience
- Relational model for distinct people (Teo and Zuzu)
- Discord DM integration for autonomous and direct messaging

## Core Stack

| Layer | Tech |
|---|---|
| Language | Python 3.13 |
| API server | FastAPI + uvicorn |
| LLM | Anthropic SDK (`claude-opus-4-5` + `claude-haiku-4-5-20251001`) |
| Frontend | Plain HTML/CSS/JS (no build step) |
| Persistence | JSON files (`chloe_state.json`, `chloe_history.jsonl`) |
| Messaging | Discord DMs (`discord.py`) |
| Hosting target | Hetzner VPS + systemd |

## Project Structure

```text
Chloe/
├── chloe/
│   ├── __init__.py
│   ├── chloe.py          # central brain + async loop
│   ├── soul.py           # personality drift + MBTI mapping
│   ├── heart.py          # vitals, activities, circadian logic
│   ├── memory.py         # memory store and aging
│   ├── llm.py            # all Anthropic calls
│   ├── graph.py          # interest graph structures/expansion
│   ├── feeds.py          # RSS + page fetching
│   ├── weather.py        # Open-Meteo integration
│   ├── affect.py         # mood model and drift
│   ├── inner.py          # wants, beliefs, goals
│   ├── persons.py        # person profiles + relationship state
│   ├── discord_bot.py    # Discord DM bot
│   └── main.py           # terminal entry point
├── index.html            # single-file dashboard
├── server.py             # FastAPI endpoints
├── requirements.txt
├── chloe_state.json      # persisted full state
└── chloe_history.jsonl   # append-only event/history log
```

## Runtime Model (Heartbeat)

Every 5 seconds, Chloe runs one tick:

1. Updates vitals (energy/social/curiosity) using activity + circadian/day-of-week
2. Applies weather nudges
3. Updates mood (sticky drift model)
4. Drifts personality (soul)
5. Auto-decides activity when needed (sleep/wake/self-regulation)
6. Fires possible autonomous event (read, dream, think, create, message, etc.)
7. Ages memories and decays beliefs on schedule
8. Saves state periodically

## Features Implemented

- **Layer 1: Time awareness**
  - Circadian rhythm, day-night scheduling, day-of-week effects, uptime awareness
- **Layer 2: World perception**
  - RSS ingestion, webpage fetch on curiosity, weather awareness, season/time language
- **Layer 3: Inner life**
  - Mood system, wants, beliefs, dreams, creative outputs
- **Layer 4: Relational depth**
  - Person modeling, follow-up memory, relationship state, reach-out selection
- **Layer 5: Self-awareness**
  - Reflection, continuity notes, soft goals, nightly mood journal
- **Layer 6: Communication**
  - Discord DM messaging to Teo and Zuzu
- **Graph Intelligence (G1-G4)**
  - Node resonance, threshold auto-expansion, orphan tag surfacing, dream recurrence surfacing

## API Endpoints

From `server.py`:

- `GET /snapshot` - full current state
- `POST /chat` - send a message to Chloe
- `POST /activity` - manually set current activity
- `POST /expand` - expand an interest graph node
- `POST /soul` - nudge a soul trait
- `GET /log` - recent activity log
- `GET /weather` - weather + season
- `GET /health` - service health and tick count

## Quick Start (Windows)

1. Open PowerShell in the project root.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Set required environment variables.
5. Start the API server.
6. Open `index.html` in your browser.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Required for LLM calls
$env:ANTHROPIC_API_KEY = "your_key_here"

# Required for Discord DMs (Layer 6)
$env:DISCORD_BOT_TOKEN = "your_discord_bot_token"
$env:DISCORD_TEO_ID = "your_discord_user_id"
$env:DISCORD_ZUZU_ID = "your_discord_user_id"

uvicorn server:app --port 8000
```

Then open `index.html` from the project root.

## Important Notes

- Chloe is designed to evolve and may behave unpredictably by design.
- State is persisted in JSON files; backup if you care about long-term continuity.
- Current runtime is local-first; deployment hardening is part of the roadmap.

## Roadmap (High-Level)

- Tone awareness by person/time
- Conversation threading
- Notification preference learning
- Deeper emotional memory and likes/dislikes
- VPS deployment + systemd reliability
- Postgres migration
- Frontend authentication and mobile UX improvements
