# chloe/chloe.py
# ─────────────────────────────────────────────────────────────
# The central brain. Owns all of Chloe's state.
# Runs the async heartbeat loop.
# All other code talks to this class.
#
# Usage:
#   chloe = Chloe()
#   await chloe.start()          # starts the background loop
#   await chloe.chat("hey")      # talk to her
#   chloe.set_activity("read")   # change what she's doing
#   await chloe.stop()           # graceful shutdown
# ─────────────────────────────────────────────────────────────

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional

from .soul   import Soul, drift, consolidate, mbti_type, describe
from .heart  import Vitals, ACTIVITIES, tick_vitals, auto_decide, should_fire_event
from .memory import Memory, seed_memories, add, age, get_vivid, derive_interests, to_dicts, from_dicts
from .graph  import Graph, seed_graph, expand, clear_new_flags, get_labels
from . import llm

TICK_SECONDS   = 5      # one heartbeat
AGE_EVERY      = 12     # age memories every N ticks (~1 min)
SAVE_EVERY     = 60     # persist state every N ticks (~5 min)
STATE_FILE     = Path("chloe_state.json")


class Chloe:
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file

        # ── Core state ──
        self.soul:     Soul        = Soul()
        self.vitals:   Vitals      = Vitals()
        self.activity: str         = "rest"
        self.memories: list[Memory] = seed_memories()
        self.graph:    Graph        = seed_graph()
        self.chat_history: list[dict] = []
        self.ideas:    list[str]   = []
        self.log:      list[str]   = []

        # ── Runtime ──
        self._tick:    int         = 0
        self._running: bool        = False
        self._task:    Optional[asyncio.Task] = None
        self._busy:    bool        = False  # LLM call in progress

        # ── Optional callbacks (set by API layer) ──
        # Called with (message_text) when Chloe sends an autonomous message
        self.on_message: Optional[Callable[[str], None]] = None
        # Called on every tick with the current state snapshot
        self.on_tick: Optional[Callable[[dict], None]] = None

        self._load()

    # ── PUBLIC API ───────────────────────────────────────────

    async def start(self):
        """Start the heartbeat loop in the background."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._log("Chloe online.")

    async def stop(self):
        """Gracefully shut down."""
        self._running = False
        if self._task:
            self._task.cancel()
        self._save()
        self._log("Chloe offline. State saved.")

    async def chat(self, message: str) -> str:
        """Send a message and get a reply. Also stores both in chat history."""
        self._add_chat("user", message)
        self.set_activity("message")

        try:
            reply = await asyncio.to_thread(
                llm.chat,
                message=message,
                history=self.chat_history[-10:],
                soul=self.soul,
                vitals=self.vitals,
                memories=get_vivid(self.memories, 5),
                interests=derive_interests(self.memories),
                ideas=self.ideas[:3],
            )
        except Exception as e:
            reply = f"(something went quiet: {e})"

        self._add_chat("chloe", reply)
        self.memories = add(self.memories, f'Said: "{reply[:80]}"', "conversation",
                            derive_interests(self.memories)[:2])
        return reply

    def set_activity(self, activity_id: str):
        """Manually switch Chloe's activity."""
        if activity_id in ACTIVITIES:
            self.activity = activity_id
            self._log(f"activity → {ACTIVITIES[activity_id].label}")

    async def expand_node(self, node_id: str):
        """Expand an interest graph node using the LLM."""
        node = next((n for n in self.graph.nodes if n.id == node_id), None)
        if not node or self._busy:
            return

        self._busy = True
        self._log(f'exploring "{node.label}"…')

        try:
            defs = await asyncio.to_thread(
                llm.expand_interest_node,
                concept=node.label,
                existing_nodes=get_labels(self.graph),
                interests=derive_interests(self.memories),
            )
            self.graph = expand(self.graph, node_id, defs)
            labels = [d["label"] for d in defs]
            self._log(f'"{node.label}" → {", ".join(labels)}')

            # New nodes seed memories
            for d in defs:
                self.memories = add(self.memories, d.get("note", d["label"]),
                                    "interest", [d["label"]])

            await asyncio.sleep(1.5)
            self.graph = clear_new_flags(self.graph)
        except Exception as e:
            self._log(f"expand error: {e}")

        self._busy = False

    def snapshot(self) -> dict:
        """Full serialisable state — for the API / frontend."""
        return {
            "soul":        self.soul.to_dict(),
            "vitals":      self.vitals.to_dict(),
            "activity":    self.activity,
            "mbti_type":   mbti_type(self.soul),
            "soul_desc":   describe(self.soul),
            "interests":   derive_interests(self.memories),
            "memories":    to_dicts(get_vivid(self.memories, 10)),
            "ideas":       self.ideas[:5],
            "chat":        self.chat_history[-20:],
            "graph":       self.graph.to_dict(),
            "log":         self.log[:20],
            "tick":        self._tick,
            "busy":        self._busy,
        }

    # ── HEARTBEAT LOOP ───────────────────────────────────────

    async def _loop(self):
        while self._running:
            await asyncio.sleep(TICK_SECONDS)
            self._tick += 1
            await self._tick_once()

    async def _tick_once(self):
        """One heartbeat. Order matters."""

        # 1. Tick vitals
        self.vitals = tick_vitals(self.vitals, self.activity)

        # 2. Drift soul
        if self.activity == "sleep":
            self.soul = consolidate(self.soul)
        else:
            self.soul = drift(self.soul, self.activity)

        # 3. Auto-regulate
        override = auto_decide(self.vitals, self.activity)
        if override:
            self.set_activity(override)

        # 4. Autonomous events (only if LLM isn't already busy)
        if not self._busy and should_fire_event(self.activity):
            asyncio.create_task(self._fire_event())

        # 5. Age memories every AGE_EVERY ticks
        if self._tick % AGE_EVERY == 0:
            self.memories = age(self.memories)

        # 6. Persist every SAVE_EVERY ticks
        if self._tick % SAVE_EVERY == 0:
            self._save()

        # 7. Notify listeners
        if self.on_tick:
            self.on_tick(self.snapshot())

    async def _fire_event(self):
        """Run an autonomous LLM event in the background."""
        self._busy = True
        interests = derive_interests(self.memories)
        vivid     = get_vivid(self.memories, 3)
        soul      = self.soul

        try:
            if self.activity in ("read", "create"):
                topic = interests[0] if interests else "something"
                mem   = await asyncio.to_thread(llm.generate_memory, topic, interests, soul)
                self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                self._log(f'memory: "{mem["text"][:60]}…"')

            elif self.activity in ("think", "dream"):
                idea = await asyncio.to_thread(llm.generate_idea, vivid, interests, soul)
                self.ideas = [idea, *self.ideas][:20]
                self._log(f'idea: "{idea[:60]}…"')

            elif self.activity == "message" and self.vitals.social_battery > 40:
                msg = await asyncio.to_thread(
                    llm.generate_autonomous_message,
                    soul, self.vitals, vivid, interests, self.ideas
                )
                self._add_chat("chloe", msg, autonomous=True)
                self._log("chloe reached out unprompted")
                if self.on_message:
                    self.on_message(msg)

        except Exception as e:
            self._log(f"event error: {e}")

        self._busy = False

    # ── PERSISTENCE ──────────────────────────────────────────

    def _save(self):
        data = {
            "soul":     self.soul.to_dict(),
            "vitals":   self.vitals.to_dict(),
            "activity": self.activity,
            "memories": to_dicts(self.memories),
            "graph":    self.graph.to_dict(),
            "chat":     self.chat_history[-100:],
            "ideas":    self.ideas[:20],
            "tick":     self._tick,
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    def _load(self):
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text())
            self.soul          = Soul.from_dict(data["soul"])
            self.vitals        = Vitals.from_dict(data["vitals"])
            self.activity      = data.get("activity", "rest")
            self.memories      = from_dicts(data.get("memories", []))
            self.graph         = Graph.from_dict(data.get("graph", {}))
            self.chat_history  = data.get("chat", [])
            self.ideas         = data.get("ideas", [])
            self._tick         = data.get("tick", 0)
            self._log("State restored from disk.")
        except Exception as e:
            self._log(f"Could not load state: {e}. Starting fresh.")

    # ── HELPERS ──────────────────────────────────────────────

    def _log(self, msg: str):
        entry = f"[{_ts()}] {msg}"
        self.log = [entry, *self.log][:100]
        print(entry)

    def _add_chat(self, from_: str, text: str, autonomous: bool = False):
        self.chat_history.append({
            "from": from_, "text": text,
            "time": _ts(), "autonomous": autonomous,
        })
        if len(self.chat_history) > 200:
            self.chat_history = self.chat_history[-200:]


def _ts() -> str:
    t = time.localtime()
    return f"{t.tm_hour:02d}:{t.tm_min:02d}"
