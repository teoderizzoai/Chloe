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
import random
import time
from pathlib import Path
from typing import Callable, Optional

from .soul   import Soul, drift, consolidate, mbti_type, describe
from .heart  import (Vitals, ACTIVITIES, tick_vitals, auto_decide,
                     should_fire_event, circadian_phase, day_name)
from .memory import Memory, seed_memories, add, age, get_vivid, derive_interests, to_dicts, from_dicts
from .graph  import Graph, seed_graph, expand, clear_new_flags, get_labels
from .affect import Affect, update_mood
from .inner  import (Want, Belief,
                     add_want, resolve_wants, wants_to_dicts, wants_from_dicts,
                     add_or_reinforce_belief, decay_beliefs, beliefs_to_dicts, beliefs_from_dicts)
from . import llm
from . import feeds
from . import weather as wthr
from .weather import WeatherState

TICK_SECONDS   = 5      # one heartbeat
AGE_EVERY      = 12     # age memories every N ticks (~1 min)
SAVE_EVERY     = 60     # persist state every N ticks (~5 min)
WEATHER_EVERY  = 720    # refresh weather every N ticks (~1 hour)
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
        self.weather:  Optional[WeatherState] = None

        # ── Layer 3: inner life ──
        self.affect:           Affect        = Affect()
        self.wants:            list[Want]    = []
        self.beliefs:          list[Belief]  = []
        self.creative_outputs: list[dict]    = []   # last 5 creative pieces

        # ── Runtime ──
        self._tick:       int      = 0
        self._running:    bool     = False
        self._task:       Optional[asyncio.Task] = None
        self._busy:       bool     = False  # LLM call in progress
        self._start_time: float    = time.time()  # wall-clock boot time (not persisted)

        # ── Optional callbacks (set by API layer) ──
        self.on_message: Optional[Callable[[str], None]] = None
        self.on_tick:    Optional[Callable[[dict], None]] = None

        self._load()

    # ── PUBLIC API ───────────────────────────────────────────

    async def start(self):
        """Start the heartbeat loop in the background."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._log("Chloe online.")
        # Fetch weather immediately on boot (non-blocking)
        asyncio.create_task(self._refresh_weather())

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

        t      = time.localtime()
        season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"

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
                uptime=self._uptime_human(),
                weather=self.weather,
                season=season,
                mood=self.affect.mood,
                beliefs=beliefs_to_dicts(self.beliefs[:4]),
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
        t = time.localtime()
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
            "circadian":   circadian_phase(t.tm_hour),
            "day":         day_name(t.tm_wday),
            "uptime":      self._uptime_human(),
            "weather":     self.weather.to_dict() if self.weather else None,
            "season":      wthr.describe_season(t.tm_mon),
            # Layer 3
            "affect":      self.affect.to_dict(),
            "wants":       wants_to_dicts(self.wants),
            "beliefs":     beliefs_to_dicts(self.beliefs),
            "creative":    self.creative_outputs[:3],
        }

    # ── HEARTBEAT LOOP ───────────────────────────────────────

    async def _loop(self):
        while self._running:
            await asyncio.sleep(TICK_SECONDS)
            self._tick += 1
            await self._tick_once()

    async def _tick_once(self):
        """One heartbeat. Order matters."""

        # 1. Tick vitals (circadian + day-of-week injected here)
        t       = time.localtime()
        hour    = t.tm_hour
        weekday = t.tm_wday
        self.vitals = tick_vitals(self.vitals, self.activity, hour, weekday)

        # 2. Apply weather vitals nudge (subtle per-tick effect)
        if self.weather:
            delta = wthr.weather_vitals_delta(self.weather.condition)
            self.vitals = Vitals(
                energy=max(0.0, min(100.0, self.vitals.energy         + delta["energy"])),
                social_battery=max(0.0, min(100.0, self.vitals.social_battery + delta["social"])),
                curiosity=max(0.0, min(100.0, self.vitals.curiosity   + delta["curiosity"])),
            )

        # 3. Update mood (affect layer — runs before soul drift)
        self.affect = update_mood(self.affect, self.vitals, self.weather, hour, self.activity)

        # 4. Drift soul
        if self.activity == "sleep":
            self.soul = consolidate(self.soul)
        else:
            self.soul = drift(self.soul, self.activity)

        # 5. Auto-regulate (vitals + time-of-day scheduling)
        override = auto_decide(self.vitals, self.activity, hour)
        if override:
            self.set_activity(override)

        # 6. Autonomous events (only if LLM isn't already busy)
        if not self._busy and should_fire_event(self.activity):
            asyncio.create_task(self._fire_event())

        # 7. Age memories + decay beliefs every AGE_EVERY ticks
        if self._tick % AGE_EVERY == 0:
            self.memories = age(self.memories)
            self.beliefs  = decay_beliefs(self.beliefs)

        # 8. Refresh weather every WEATHER_EVERY ticks (~1 hour)
        if self._tick % WEATHER_EVERY == 0:
            asyncio.create_task(self._refresh_weather())

        # 9. Persist every SAVE_EVERY ticks
        if self._tick % SAVE_EVERY == 0:
            self._save()

        # 10. Notify listeners
        if self.on_tick:
            self.on_tick(self.snapshot())

    async def _fire_event(self):
        """Run an autonomous LLM event in the background."""
        self._busy = True
        interests = derive_interests(self.memories)
        vivid     = get_vivid(self.memories, 4)
        soul      = self.soul
        t         = time.localtime()
        season    = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"

        try:
            if self.activity == "read":
                # Absorb a real article from the world
                article = await feeds.fetch_random_article(interests)
                if article:
                    text = article.summary
                    if self.vitals.curiosity > 65:
                        full = await feeds.fetch_article_text(article.url)
                        if full:
                            text = full
                    mem = await asyncio.to_thread(
                        llm.generate_memory_from_article,
                        article.title, text, interests, soul
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'read "{article.title[:45]}" → "{mem["text"][:45]}…"')

                    # Resolve wants that overlap with what was just read
                    self.wants = resolve_wants(self.wants, mem.get("tags", []))

                    # 50% chance to extract a belief from this article
                    if random.random() < 0.5:
                        belief_data = await asyncio.to_thread(
                            llm.extract_belief,
                            article.title, text[:700],
                            beliefs_to_dicts(self.beliefs), soul,
                        )
                        if belief_data:
                            self.beliefs = add_or_reinforce_belief(
                                self.beliefs, belief_data["text"],
                                float(belief_data.get("confidence", 0.5)),
                                belief_data.get("tags", []),
                            )
                            self._log(f'belief: "{belief_data["text"][:55]}…"')
                else:
                    # Feeds unreachable — generic memory
                    topic = interests[0] if interests else "something"
                    mem   = await asyncio.to_thread(llm.generate_memory, topic, interests, soul)
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')

            elif self.activity == "dream":
                # Real dream pass — distorts recent memories
                mem = await asyncio.to_thread(
                    llm.generate_dream, vivid, soul, self.vitals, self.weather, season
                )
                self.memories = add(self.memories, mem["text"], "dream", mem.get("tags", []))
                self._log(f'dream: "{mem["text"][:60]}…"')

            elif self.activity == "think":
                # 40% chance: surface a want. 60%: generate an idea.
                if random.random() < 0.40:
                    want_data = await asyncio.to_thread(llm.generate_want, vivid, interests, soul)
                    self.wants = add_want(self.wants, want_data["text"], want_data.get("tags", []))
                    self._log(f'want: "{want_data["text"][:60]}…"')
                else:
                    idea = await asyncio.to_thread(llm.generate_idea, vivid, interests, soul)
                    self.ideas = [idea, *self.ideas][:20]
                    self._log(f'idea: "{idea[:60]}…"')

            elif self.activity == "create":
                # High curiosity + energy → creative output; otherwise memory
                if self.vitals.curiosity > 65 and self.vitals.energy > 55:
                    piece = await asyncio.to_thread(
                        llm.generate_creative, vivid, interests, soul, self.affect.mood
                    )
                    entry = {**piece, "time": _ts()}
                    self.creative_outputs = [entry, *self.creative_outputs][:5]
                    # Store first 150 chars as a creative memory
                    self.memories = add(
                        self.memories, piece["text"][:150], "creative", piece.get("tags", [])
                    )
                    self._log(f'created {piece.get("form","piece")}: "{piece["text"][:50]}…"')
                else:
                    topic = interests[0] if interests else "something"
                    mem   = await asyncio.to_thread(llm.generate_memory, topic, interests, soul)
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')

            elif self.activity == "message" and self.vitals.social_battery > 40:
                msg = await asyncio.to_thread(
                    llm.generate_autonomous_message,
                    soul, self.vitals, vivid, interests, self.ideas,
                    self.weather, season,
                )
                self._add_chat("chloe", msg, autonomous=True)
                self._log("chloe reached out unprompted")
                if self.on_message:
                    self.on_message(msg)

        except Exception as e:
            self._log(f"event error: {e}")

        self._busy = False

    async def _refresh_weather(self):
        """Fetch current weather and update state. Silent on failure."""
        w = await wthr.fetch_weather()
        if w:
            self.weather = w
            self._log(f"weather: {w.description}, {w.temperature_c}°C, {w.feels_like} in {w.location}")

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
            "weather":  self.weather.to_dict() if self.weather else None,
            # Layer 3
            "affect":   self.affect.to_dict(),
            "wants":    wants_to_dicts(self.wants),
            "beliefs":  beliefs_to_dicts(self.beliefs),
            "creative": self.creative_outputs[:5],
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
            w_data = data.get("weather")
            if w_data:
                try:
                    self.weather = WeatherState.from_dict(w_data)
                except Exception:
                    pass
            # Layer 3
            if data.get("affect"):
                self.affect = Affect.from_dict(data["affect"])
            self.wants            = wants_from_dicts(data.get("wants", []))
            self.beliefs          = beliefs_from_dicts(data.get("beliefs", []))
            self.creative_outputs = data.get("creative", [])
            self._log("State restored from disk.")
        except Exception as e:
            self._log(f"Could not load state: {e}. Starting fresh.")

    # ── HELPERS ──────────────────────────────────────────────

    def _uptime_human(self) -> str:
        """Human-readable uptime since last boot."""
        secs = int(time.time() - self._start_time)
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m"
        hours, mins_rem = divmod(mins, 60)
        if hours < 24:
            return f"{hours}h {mins_rem}m"
        days, hours_rem = divmod(hours, 24)
        return f"{days}d {hours_rem}h"

    def _log(self, msg: str):
        entry = f"[{_ts()}] {msg}"
        self.log = [entry, *self.log][:100]
        try:
            print(entry)
        except UnicodeEncodeError:
            print(entry.encode("ascii", errors="replace").decode("ascii"))

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
