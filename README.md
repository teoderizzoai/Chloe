# Chloe — Python

A living AI entity. Runs as a persistent async process.

## Structure

```
chloe/
├── __init__.py    clean public imports
├── soul.py        MBTI personality, drift logic
├── heart.py       heartbeat states, activities, vitals, auto-regulation
├── memory.py      memory store, aging, retrieval, interest derivation
├── llm.py         all Anthropic API calls
├── graph.py       interest node graph, data structures, mutations
└── chloe.py       central brain — owns all state, runs the async loop

main.py            terminal entry point (chat + commands)
requirements.txt
chloe_state.json   auto-created on first run, persists between sessions
```

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python main.py
```

## How the systems connect

```
asyncio loop (every 5s)
    ├── tick_vitals()          ← heart.py
    ├── drift() / consolidate() ← soul.py
    ├── auto_decide()          ← heart.py  (self-regulation)
    ├── should_fire_event()    ← heart.py
    │       └── generate_memory()      ← llm.py → memory.py
    │           generate_idea()        ← llm.py
    │           generate_autonomous_message() ← llm.py
    ├── age()                  ← memory.py (every 12 ticks)
    └── _save()                ← chloe.py  (every 60 ticks → disk)

user calls chloe.chat()
    └── llm.chat()             ← llm.py  (soul + vitals + memories as context)
            └── add()          ← memory.py

user calls chloe.expand_node()
    └── llm.expand_interest_node() ← llm.py
            └── graph.expand()     ← graph.py
            └── add()              ← memory.py
```

## Next steps

| Want to add...         | What to do                                      |
|------------------------|-------------------------------------------------|
| Web API                | `pip install fastapi uvicorn` + wrap `Chloe` in routes |
| SMS / texting          | Set `chloe.on_message` callback → Twilio        |
| Always-on server       | Deploy to Hetzner VPS, run with `systemd`       |
| Better persistence     | Swap `chloe_state.json` for SQLite / Postgres   |
| Web search             | Add `llm.browse()` triggered from `read` activity |
