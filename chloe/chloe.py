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
from .inner  import (Want, Belief, Goal,
                     add_want, resolve_wants, wants_to_dicts, wants_from_dicts,
                     add_or_reinforce_belief, decay_beliefs, beliefs_to_dicts, beliefs_from_dicts,
                     add_goal, resolve_goals, goals_to_dicts, goals_from_dicts)
from .persons import (Person, PersonNote,
                      default_persons, on_contact, add_note, mark_followed_up,
                      pending_followups, tick_distance, choose_reach_out_target,
                      persons_to_dicts, persons_from_dicts, get_person)
from . import llm
from . import feeds
from . import weather as wthr
from .weather import WeatherState

TICK_SECONDS   = 5      # one heartbeat
AGE_EVERY      = 12     # age memories every N ticks (~1 min)
SAVE_EVERY     = 60     # persist state every N ticks (~5 min)
WEATHER_EVERY  = 720    # refresh weather every N ticks (~1 hour)
REFLECT_EVERY  = 240    # self-reflection + continuity check every N ticks (~20 min)
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

        # ── Layer 4: relational depth ──
        self.persons: list[Person] = default_persons()

        # ── Layer 5: self-awareness ──
        self.goals:            list[Goal] = []
        self.soul_baseline:    dict       = {}   # soul at last continuity check
        self.last_journal_date: str       = ""   # "YYYY-MM-DD"

        # ── Sleep / messaging ──
        self.pending_messages: list[dict] = []   # messages received during deep sleep
        self._prev_activity:   str        = "rest"

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

    async def chat(self, message: str, person_id: str = "teo") -> Optional[str]:
        """Send a message and get a reply.

        Returns None if she's in deep sleep and the message is queued.
        Returns a string reply otherwise.
        """
        sleeping = self.activity in ("sleep", "dream")

        # Deep sleep — queue message, reply when she wakes
        if sleeping and self.vitals.energy < 25:
            self._add_chat("user", message)
            self.pending_messages.append({
                "person_id": person_id,
                "text":      message,
                "time":      _ts(),
            })
            self._log(f"message queued — too tired to reply (energy {self.vitals.energy:.0f})")
            return None

        # Light sleep — wake her, reply groggily
        was_woken = sleeping
        self._add_chat("user", message)
        if was_woken:
            self.set_activity("message")
            self._log(f"woken by message from {person_id}")

        self.set_activity("message")
        self.persons = on_contact(self.persons, person_id)

        person = get_person(self.persons, person_id)
        person_name  = person.name if person else "Teo"
        person_notes = [n.to_dict() for n in (person.notes[:4] if person else [])]

        asyncio.create_task(self._extract_and_store_note(message, person_id, person_name))

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
                person_name=person_name,
                person_notes=person_notes,
                sleep_state="woken" if was_woken else "",
            )
        except Exception as e:
            reply = f"(something went quiet: {e})"

        self._add_chat("chloe", reply)
        self.memories = add(self.memories, f'Said: "{reply[:80]}"', "conversation",
                            derive_interests(self.memories)[:2])
        return reply

    async def _extract_and_store_note(self, message: str, person_id: str, person_name: str):
        """Background task: check if message contains something worth remembering."""
        try:
            notable = await asyncio.to_thread(
                llm.extract_notable, message, person_name, self.soul
            )
            if notable:
                self.persons = add_note(
                    self.persons, person_id,
                    notable["text"], notable.get("tags", [])
                )
                self._log(f'noted about {person_name}: "{notable["text"][:60]}…"')
        except Exception:
            pass

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
            # Layer 4
            "persons":     persons_to_dicts(self.persons),
            # Layer 5
            "goals":       goals_to_dicts(self.goals),
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
        prev_activity = self.activity
        override = auto_decide(self.vitals, self.activity, hour)
        if override:
            self.set_activity(override)

        # Detect wake transition — process queued messages
        just_woke = (
            prev_activity in ("sleep", "dream") and
            self.activity not in ("sleep", "dream") and
            self.pending_messages
        )
        if just_woke:
            asyncio.create_task(self._process_pending_messages())

        # 6. Autonomous events (only if LLM isn't already busy)
        if not self._busy and should_fire_event(self.activity):
            asyncio.create_task(self._fire_event())

        # 7. Age memories + decay beliefs + drift distance every AGE_EVERY ticks
        if self._tick % AGE_EVERY == 0:
            self.memories = age(self.memories)
            self.beliefs  = decay_beliefs(self.beliefs)
            self.persons  = tick_distance(self.persons)

        # 8. Self-reflection + continuity check every REFLECT_EVERY ticks (~20 min)
        if self._tick % REFLECT_EVERY == 0 and not self._busy:
            asyncio.create_task(self._reflect())

        # 9. Mood journal at 22:00 — before she falls asleep, not during
        today = f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        if hour == 22 and today != self.last_journal_date and not self._busy:
            self.last_journal_date = today
            asyncio.create_task(self._write_journal(today))

        # 10. Refresh weather every WEATHER_EVERY ticks (~1 hour)
        if self._tick % WEATHER_EVERY == 0:
            asyncio.create_task(self._refresh_weather())

        # 11. Persist every SAVE_EVERY ticks
        if self._tick % SAVE_EVERY == 0:
            self._save()

        # 12. Notify listeners
        if self.on_tick:
            self.on_tick(self.snapshot())

    async def _fire_event(self):
        """Run an autonomous LLM event in the background."""
        self._busy = True
        interests    = derive_interests(self.memories)
        vivid        = get_vivid(self.memories, 4)
        soul         = self.soul
        t            = time.localtime()
        season       = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"
        beliefs_d    = beliefs_to_dicts(self.beliefs)
        wants_d      = wants_to_dicts(self.wants)
        goals_d      = goals_to_dicts(self.goals)
        recent_ideas = self.ideas[:3]

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
                        article.title, text, interests, soul,
                        self.affect.mood, beliefs_d, wants_d, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'read "{article.title[:45]}" → "{mem["text"][:45]}…"')

                    # Resolve wants + goals that overlap with what was just read
                    self.wants = resolve_wants(self.wants, mem.get("tags", []))
                    self.goals = resolve_goals(self.goals, "read", mem.get("tags", []))

                    # 50% chance to extract a belief from this article
                    if random.random() < 0.5:
                        belief_data = await asyncio.to_thread(
                            llm.extract_belief,
                            article.title, text[:700],
                            beliefs_d, soul,
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
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, interests, soul,
                        self.affect.mood, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')

            elif self.activity == "dream":
                # Real dream pass — distorts recent memories, wants, ideas
                mem = await asyncio.to_thread(
                    llm.generate_dream, vivid, soul, self.vitals, self.weather, season,
                    wants_d, recent_ideas,
                )
                self.memories = add(self.memories, mem["text"], "dream", mem.get("tags", []))
                self._log(f'dream: "{mem["text"][:60]}…"')

            elif self.activity == "think":
                # 30% want · 15% goal · 55% idea
                roll = random.random()
                if roll < 0.30:
                    want_data = await asyncio.to_thread(
                        llm.generate_want, vivid, interests, soul,
                        beliefs_d, wants_d,
                    )
                    self.wants = add_want(self.wants, want_data["text"], want_data.get("tags", []))
                    self._log(f'want: "{want_data["text"][:60]}…"')
                elif roll < 0.45:
                    goal_data = await asyncio.to_thread(
                        llm.generate_goal, vivid, interests, soul,
                        wants_d, beliefs_d, goals_d,
                    )
                    self.goals = add_goal(self.goals, goal_data["text"], goal_data.get("tags", []))
                    self._log(f'goal: "{goal_data["text"][:60]}…"')
                else:
                    idea = await asyncio.to_thread(
                        llm.generate_idea, vivid, interests, soul,
                        self.affect.mood, beliefs_d, wants_d,
                    )
                    self.ideas = [idea, *self.ideas][:20]
                    self._log(f'idea: "{idea[:60]}…"')

            elif self.activity == "create":
                # High curiosity + energy → creative output; otherwise memory
                if self.vitals.curiosity > 65 and self.vitals.energy > 55:
                    piece = await asyncio.to_thread(
                        llm.generate_creative, vivid, interests, soul, self.affect.mood,
                        wants_d, beliefs_d, recent_ideas,
                    )
                    entry = {**piece, "time": _ts()}
                    self.creative_outputs = [entry, *self.creative_outputs][:5]
                    # Store first 150 chars as a creative memory
                    self.memories = add(
                        self.memories, piece["text"][:150], "creative", piece.get("tags", [])
                    )
                    self._log(f'created {piece.get("form","piece")}: "{piece["text"][:50]}…"')
                    self.goals = resolve_goals(self.goals, "create", piece.get("tags", []))
                else:
                    topic = interests[0] if interests else "something"
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, interests, soul,
                        self.affect.mood, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')

            elif self.activity == "message" and self.vitals.social_battery > 40:
                # Choose who to reach out to
                target = choose_reach_out_target(self.persons, self.affect.mood)
                if target:
                    p_name  = target.name
                    p_notes = [n.to_dict() for n in target.notes[:4]]
                    followups = pending_followups(target)

                    # 40% chance to follow up on something they shared earlier
                    if followups and random.random() < 0.40:
                        note = followups[0]
                        msg = await asyncio.to_thread(
                            llm.generate_followup,
                            p_name, note.text, soul, self.vitals, self.affect.mood,
                        )
                        self.persons = mark_followed_up(self.persons, target.id, note.id)
                        self._log(f'followed up with {p_name}: "{note.text[:45]}…"')
                    else:
                        msg = await asyncio.to_thread(
                            llm.generate_autonomous_message,
                            soul, self.vitals, vivid, interests, self.ideas,
                            self.weather, season, p_name, p_notes,
                        )
                        self._log(f"chloe reached out to {p_name} unprompted")
                else:
                    msg = await asyncio.to_thread(
                        llm.generate_autonomous_message,
                        soul, self.vitals, vivid, interests, self.ideas,
                        self.weather, season,
                    )
                    self._log("chloe reached out unprompted")

                self._add_chat("chloe", msg, autonomous=True)
                if self.on_message:
                    self.on_message(msg)

        except Exception as e:
            self._log(f"event error: {e}")

        self._busy = False

    async def _process_pending_messages(self):
        """Reply to messages that arrived while she was in deep sleep."""
        msgs = self.pending_messages[:]
        self.pending_messages = []

        t      = time.localtime()
        season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"

        for pm in msgs:
            person = get_person(self.persons, pm["person_id"])
            person_name  = person.name if person else "Teo"
            person_notes = [n.to_dict() for n in (person.notes[:4] if person else [])]
            self.persons = on_contact(self.persons, pm["person_id"])

            try:
                reply = await asyncio.to_thread(
                    llm.chat,
                    message=pm["text"],
                    history=self.chat_history[-6:],
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
                    person_name=person_name,
                    person_notes=person_notes,
                    sleep_state="missed",
                    missed_at=pm["time"],
                )
                self._add_chat("chloe", reply)
                self._log(f"replied to queued message from {person_name}")
                if self.on_message:
                    self.on_message(reply)
            except Exception as e:
                self._log(f"pending message reply error: {e}")

    async def _reflect(self):
        """Self-reflection + continuity check. Fires every REFLECT_EVERY ticks."""
        self._busy = True
        try:
            # 18. Self-reflection — looks inward and forms an observation
            mem = await asyncio.to_thread(
                llm.generate_reflection,
                get_vivid(self.memories, 6), self.ideas[:3],
                beliefs_to_dicts(self.beliefs[:4]), self.soul, self.affect.mood,
            )
            self.memories = add(self.memories, mem["text"], "reflection", mem.get("tags", []))
            self._log(f'reflection: "{mem["text"][:60]}…"')

            # 19. Continuity awareness — notice soul drift
            if self.soul_baseline:
                drift_total = sum(
                    abs(getattr(self.soul, t) - self.soul_baseline.get(t, 50))
                    for t in ("EI", "SN", "TF", "JP")
                )
                max_single = max(
                    abs(getattr(self.soul, t) - self.soul_baseline.get(t, 50))
                    for t in ("EI", "SN", "TF", "JP")
                )
                if drift_total > 15 or max_single > 10:
                    note = await asyncio.to_thread(
                        llm.generate_continuity_note,
                        self.soul_baseline, self.soul, self.affect.mood,
                    )
                    self.memories = add(self.memories, note["text"], "reflection", note.get("tags", []))
                    self._log(f'continuity: "{note["text"][:60]}…"')
                    # Reset baseline
                    self.soul_baseline = self.soul.to_dict()
            else:
                self.soul_baseline = self.soul.to_dict()

        except Exception as e:
            self._log(f"reflect error: {e}")
        self._busy = False

    async def _write_journal(self, today: str):
        """Write the end-of-day private journal entry."""
        self._busy = True
        try:
            t      = time.localtime()
            season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"
            entry  = await asyncio.to_thread(
                llm.generate_journal,
                get_vivid(self.memories, 8), self.affect.mood, self.vitals,
                self.soul, self.weather, season, day_name(t.tm_wday),
            )
            self.memories = add(self.memories, entry["text"], "journal", entry.get("tags", []))
            self._log(f'journal ({today}): "{entry["text"][:55]}…"')
        except Exception as e:
            self._log(f"journal error: {e}")
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
            # Layer 4
            "persons":  persons_to_dicts(self.persons),
            # Layer 5
            "goals":            goals_to_dicts(self.goals),
            "soul_baseline":    self.soul_baseline,
            "last_journal_date": self.last_journal_date,
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
            # Layer 4
            self.persons = persons_from_dicts(data.get("persons", []))
            # Layer 5
            self.goals             = goals_from_dicts(data.get("goals", []))
            self.soul_baseline     = data.get("soul_baseline", {})
            self.last_journal_date = data.get("last_journal_date", "")
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
