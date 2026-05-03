# Chloe

Chloe is a persistent AI entity — not a task assistant. She runs continuously as an async Python process, develops her own personality through lived experience, forms memories, has wants and fears, and reaches out unprompted. The goal is an autonomous, developing mind.

## What she is

- **Autonomous loop** — ticks every 30 seconds, independently decides what to do (read, dream, think, create, sleep, reach out)
- **Layered inner life** — vitals, mood, arcs, identity, memories, beliefs, wants, fears, tensions, relationships
- **Emergent personality** — traits arise from experience via Haiku; no predefined list. She starts with no traits and develops them from what happens to her
- **Persistent memory** — ChromaDB semantic index + SQLite, append-only, weight decay, recency reranking. Live conversations use a three-stage RAG pipeline: rich query → 20 candidates → Haiku grader → 5 most relevant
- **Relational model** — warmth, distance, conflict, shared moments, tone registers per person
- **Interest graph** — nodes expand from her own reading and thinking, not from a seed list
- **Discord integration** — optional DM bridge; she initiates contact at most once every 2 days when something is building

## Stack

| Layer | Tech |
|---|---|
| Runtime | Python 3.13, asyncio |
| API server | FastAPI + uvicorn |
| LLM | Anthropic — Sonnet 4.6 (chat) + Haiku 4.5 (all background work) |
| Semantic memory | ChromaDB |
| Persistence | SQLite (relational state) + JSON (scalars) |
| Dashboard | Plain HTML/JS, no build step |
| Voice | Fish Speech 1.5 + faster-whisper (Python 3.11, separate process) |
| Messaging | Discord DMs |
| Deployment | Hetzner VPS |

## Project structure

```
chloe/              core package — brain, identity, memory, persons, inner life, LLM calls
voice/              voice subsystem (separate process, Python 3.11)
  app.py            self-contained voice UI — starts brain server + Fish Speech automatically
  pipeline.py       zero-latency Deepgram streaming pipeline
  legacy.py         older push-to-talk interface
scripts/            one-time setup utilities (clone voice, generate interjections)
assets/images/      activity and mood portraits served by the dashboard
server.py           FastAPI endpoints
index.html          dashboard (polls /snapshot every 4s)
cli.py              terminal client (thin CLI, requires server running)
bin/start-server.sh Linux server launcher
```

State files (`data/chloe_state.json`, `data/chloe.db`, `data/memory_index/`) are created at first run.

## Running

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=your_key

uvicorn server:app --port 8000
# open index.html in a browser
```

To chat via terminal (server must be running):
```bash
python cli.py
```

### Discord (optional)

```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_TEO_ID=...        # your Discord user ID
```

Discord starts automatically when the env vars are set.

### Voice (optional, Python 3.11 + GPU recommended)

```bash
python -m venv .fishvenv --python=python3.11
source .fishvenv/bin/activate
pip install -r voice/requirements.txt

python voice/app.py              # starts brain server + Fish Speech + voice UI
```

Set `REF_AUDIO` to a 5-15s clean voice sample (default: `voice/sample.wav`).

## How it works

Every 30 seconds Chloe runs one tick: updates vitals, re-evaluates mood, checks for impulses, decides what activity to be in, and possibly fires a background LLM event (read an article, dream, think, create something, send a message). All LLM calls in the tick are async — the heartbeat never blocks.

Chat happens on a separate path: incoming message → emotion read → rich memory query (last 5 turns + mood) → 20 ChromaDB candidates → Haiku grader selects 5 relevant memories → Sonnet reply → background extraction (belief, moment, note, trait reinforcement).

Identity evolves from the `_reflect()` cycle (~every 2 hours): Haiku reviews recent memories and affect records, proposes traits when a coherent pattern spans 5+ experiences. Trait proposals run every 3rd reflect cycle, cap at 10 active traits, and produce at most 1 new trait per cycle. Traits must be broad behavioral tendencies — not situational reactions, not existential themes.

Full mechanics: `docs/00_ARCHITECTURE.md`. Feature roadmap: `docs/05_FEATURES.md`. Upcoming work: `docs/01_CHECKLIST.md`.

## Key invariants

- The tick loop never blocks on the network
- Memory is append-only — no edits, no deletes
- Sonnet for anything a human reads; Haiku for all background/structured work
- The eight mood labels are fixed; the trait system is not
- Live conversation uses a 3-stage graded RAG pipeline; background events use direct reranking
