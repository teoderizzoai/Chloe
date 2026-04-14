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

from .soul   import Soul, drift, consolidate, content_drift, mbti_type, describe
from .heart  import (Vitals, ACTIVITIES, tick_vitals, auto_decide,
                     should_fire_event, circadian_phase, day_name)
from .memory import Memory, seed_memories, add, age, get_vivid, derive_interests, derive_fringe_interests, to_dicts, from_dicts
from .graph  import (Graph, seed_graph, expand, clear_new_flags, get_labels,
                     reinforce_node, match_nodes_by_tags, get_leaf_nodes,
                     mark_auto_expanded, find_node_by_label)
from .affect import Affect, update_mood, force_mood
from .avatar import portrait_meta
from .inner  import (Want, Belief, Goal, AffectRecord,
                     add_want, resolve_wants, wants_to_dicts, wants_from_dicts,
                     add_or_reinforce_belief, decay_beliefs, beliefs_to_dicts, beliefs_from_dicts,
                     add_goal, resolve_goals, goals_to_dicts, goals_from_dicts,
                     add_affect_record, affect_records_to_dicts, affect_records_from_dicts,
                     derive_preferences)
from .persons import (Person, PersonNote, PersonEvent,
                      default_persons, on_contact, add_note, add_event, mark_followed_up,
                      pending_followups, tick_distance, choose_reach_out_target,
                      boost_warmth, tone_context, persons_to_dicts, persons_from_dicts,
                      get_person, get_upcoming_events, format_upcoming_events)
from . import llm
from . import feeds
from . import weather as wthr
from .weather import WeatherState

TICK_SECONDS   = 5       # one heartbeat
AGE_EVERY      = 12     # age memories every N ticks (~1 min)
SAVE_EVERY     = 60     # persist state every N ticks (~5 min)
WEATHER_EVERY  = 720    # refresh weather every N ticks (~1 hour)
REFLECT_EVERY  = 240    # self-reflection + continuity check every N ticks (~20 min)
ORPHAN_CHECK_EVERY = 72 # orphan tag surfacing every N ticks (~6 min) — separate from full reflect
STATE_FILE     = Path("chloe_state.json")

# ── Graph Intelligence constants ─────────────────────────────
GRAPH_HIT_THRESHOLD        = 5        # hits before a leaf node auto-expands
GRAPH_EXPAND_COOLDOWN      = 6 * 3600 # seconds between auto-expands per node
ORPHAN_TAG_MIN_OCCURRENCES = 2        # tag must appear in this many memories (was 3)
DREAM_RECURRENCE_MIN       = 3        # tag must appear in this many dreams

# Autonomous `_fire_event` pacing — separate from TICK_SECONDS. Even with a slow
# tick, `should_fire_event` rolls could feel spammy if Haiku returns fast and the
# user keeps her in high-chance activities (create/read). This floor guarantees a
# minimum quiet gap between *starting* two background events (user chat is unchanged).
MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS = 90.0

# Standalone outreach — fires independently of activity-based events
OUTREACH_INTERVAL         = 2 * 3600   # normal: attempt outreach at most once per 2h
OUTREACH_INTERVAL_TESTING = 5 * 60     # testing mode: once per 5 min


# ── Item 43: harsh message detection ────────────────────────
_HARSH_PHRASES = frozenset([
    "idiot", "stupid", "shut up", "useless", "worthless", "pathetic",
    "hate you", "fuck you", "asshole", "dumb", "moron", "loser",
    "you're trash", "you suck", "shut the fuck", "piece of shit",
])

def _is_harsh(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _HARSH_PHRASES)


# ── Item 44: shared-interest resonance detection ─────────────
def _has_resonance(message: str, interests: list[str]) -> bool:
    lower = message.lower()
    interest_words = {w.lower() for phrase in interests for w in phrase.split() if len(w) > 3}
    matches = sum(1 for w in interest_words if w in lower)
    return matches >= 2


# ── Item 40: article emotional weight ────────────────────────
_DEVASTATING_WORDS = frozenset([
    "war", "death", "disaster", "tragedy", "killed", "massacre",
    "crisis", "violence", "suffering", "collapse", "genocide", "atrocity",
])
_BEAUTIFUL_WORDS = frozenset([
    "wonder", "beauty", "discovery", "hope", "joy", "grace",
    "miracle", "transcend", "awe", "profound", "extraordinary", "luminous",
])

def _article_emotional_weight(title: str, text: str) -> str | None:
    """Returns 'devastating', 'beautiful', or None."""
    haystack = (title + " " + text[:500]).lower()
    dev   = sum(1 for w in _DEVASTATING_WORDS if w in haystack)
    beaut = sum(1 for w in _BEAUTIFUL_WORDS   if w in haystack)
    if dev >= 3:
        return "devastating"
    if beaut >= 3:
        return "beautiful"
    return None


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
        self.last_backup_date:  str       = ""   # "YYYY-MM-DD"

        # ── Graph Intelligence ──
        # Tags we've already evaluated for orphan surfacing — not persisted,
        # rebuilt from graph labels on load so we don't re-evaluate known nodes.
        self._surfaced_tags: set[str] = set()

        # ── Layer 7+8: emotional history + streak ──
        self.affect_records:    list[AffectRecord] = []
        self._activity_streak:  int                = 0   # consecutive ticks in current activity

        # ── Item 24: conversation session tracking ──
        self._current_session:  int   = 0
        self._last_chat_time:   float = 0.0

        # ── Testing / outreach ──
        self.testing_mode:      bool  = False
        self._last_outreach_time: float = 0.0

        # ── Sleep / messaging ──
        self.pending_messages: list[dict] = []   # messages received during deep sleep
        self._prev_activity:   str        = "rest"

        # ── Runtime ──
        self._tick:       int      = 0
        self._running:    bool     = False
        self._task:       Optional[asyncio.Task] = None
        self._busy:       bool     = False  # LLM call in progress
        self._start_time: float    = time.time()  # wall-clock boot time (not persisted)
        # Monotonic clock at last autonomous `_fire_event` spawn — rate-limits background noise
        self._last_autonomous_fire_mono: float = time.monotonic() - MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS
        # Exploration counter — every Nth read event uses fringe interests + explore mode
        self._read_event_count: int = 0

        # ── Optional callbacks (set by API layer / Discord bot) ──
        # on_message(text, person_id) — person_id is None when no specific target
        self.on_message: Optional[Callable[[str, Optional[str]], None]] = None
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
            self._add_chat("user", message, person_id=person_id)
            self.pending_messages.append({
                "person_id": person_id,
                "text":      message,
                "time":      _ts(),
            })
            self._log(f"message queued — too tired to reply (energy {self.vitals.energy:.0f})")
            return None

        # Light sleep — wake her, reply groggily
        was_woken = sleeping

        # Snapshot history BEFORE adding the current message — llm.chat appends it itself
        person_history = [m for m in self.chat_history if m.get("person_id") == person_id]

        self._add_chat("user", message, person_id=person_id)
        if was_woken:
            self.set_activity("message")
            self._log(f"woken by message from {person_id}")

        self.set_activity("message")
        t_now = time.localtime()
        self.persons = on_contact(self.persons, person_id, hour=t_now.tm_hour)
        self._log(f"message from {person_id}: \"{message[:60]}{'…' if len(message)>60 else ''}\"")

        person = get_person(self.persons, person_id)
        person_name  = person.name if person else "Teo"
        person_notes = [n.to_dict() for n in (person.notes[:4] if person else [])]

        asyncio.create_task(self._extract_and_store_note(message, person_id, person_name))
        asyncio.create_task(self._extract_and_store_event(message, person_id, person_name))

        # Item 43 — harsh treatment: immediate mood shift + feeling memory
        if _is_harsh(message):
            self.affect = force_mood("irritable", 0.75)
            self.memories = add(
                self.memories,
                f'Said something harsh to me: "{message[:60]}"',
                "feeling", ["hurt", "conflict", "irritable"],
            )
            self.affect_records = add_affect_record(
                self.affect_records, "irritable",
                f"{person_name} said something harsh",
                ["hurt", "conflict"],
            )
            self._log(f"harsh message from {person_name} — mood → irritable")

        # Item 44 — shared interests: warmth boost + curiosity nudge
        cur_interests = derive_interests(self.memories)
        if not _is_harsh(message) and _has_resonance(message, cur_interests):
            self.persons = boost_warmth(self.persons, person_id, 2.5)
            if self.affect.mood not in ("irritable", "melancholic"):
                self.affect = Affect(mood="curious",
                                     intensity=min(1.0, self.affect.intensity + 0.1))
            self.affect_records = add_affect_record(
                self.affect_records, self.affect.mood,
                f"{person_name} touched on something that resonates",
                ["resonance", "connection", "shared"],
            )

        t      = time.localtime()
        hour   = t.tm_hour
        season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(hour)}"

        # Item 24 — session-aware history: prefer current session, fall back to recent
        cur_session_history = [m for m in person_history
                               if m.get("session") == self._current_session]
        chat_ctx = cur_session_history[-10:] if cur_session_history else person_history[-6:]

        person_warmth   = person.warmth if person else 50.0
        upcoming_events = format_upcoming_events(get_upcoming_events(person)) if person else ""

        try:
            reply = await asyncio.to_thread(
                llm.chat,
                message=message,
                history=chat_ctx,
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
                preferences=derive_preferences(self.affect_records),
                warmth=person_warmth,
                hour=hour,
                upcoming_events=upcoming_events,
            )
        except Exception as e:
            reply = f"(something went quiet: {e})"

        self._add_chat("chloe", reply, person_id=person_id)
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

    async def _extract_and_store_event(self, message: str, person_id: str, person_name: str):
        """Background task: check if message mentions a future event with a date."""
        try:
            today_iso = time.strftime("%Y-%m-%d")
            event = await asyncio.to_thread(
                llm.extract_event, message, person_name, today_iso
            )
            if event and event.get("date"):
                pe = PersonEvent(
                    text=event["text"],
                    date=event["date"],
                    uncertain=bool(event.get("uncertain", False)),
                )
                self.persons = add_event(self.persons, person_id, pe)
                flag = " (uncertain date)" if pe.uncertain else ""
                self._log(f'event noted: "{pe.text}" on {pe.date}{flag}')
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
            # Dashboard portrait — see avatar.portrait_meta for selection rules
            "avatar":      portrait_meta(
                self.activity, self.affect.mood, self.affect.intensity
            ),
            "mbti_type":   mbti_type(self.soul),
            "soul_desc":   describe(self.soul),
            "interests":   derive_interests(self.memories),
            "memories":    to_dicts(get_vivid(self.memories, 10)),
            "ideas":       self.ideas[:5],
            "chat":        self.chat_history[-100:],
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
            # Layer 7+8
            "affect_records": affect_records_to_dicts(self.affect_records[:20]),
            # Testing
            "testing_mode":   self.testing_mode,
        }

    # ── HEARTBEAT LOOP ───────────────────────────────────────

    async def _loop(self):
        while self._running:
            await asyncio.sleep(TICK_SECONDS)
            self._tick += 1
            try:
                await self._tick_once()
            except Exception as exc:
                self._log(f"[tick error] {exc}")

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
        season_str = wthr.describe_season(t.tm_mon)
        self.affect = update_mood(self.affect, self.vitals, self.weather, hour, self.activity, season_str)

        # 4. Drift soul
        if self.activity == "sleep":
            self.soul = consolidate(self.soul)
        else:
            self.soul = drift(self.soul, self.activity)

        # ── Testing mode: floor vitals, prevent sleep ────────────
        if self.testing_mode:
            self.vitals = Vitals(
                energy=max(45.0, self.vitals.energy),
                social_battery=max(40.0, self.vitals.social_battery),
                curiosity=max(60.0, self.vitals.curiosity),
            )

        # 5. Auto-regulate (vitals + time-of-day scheduling)
        prev_activity = self.activity
        override = auto_decide(self.vitals, self.activity, hour, self.affect.mood)
        # Testing mode: block any sleep/dream transition
        if self.testing_mode and override in ("sleep", "dream"):
            override = "rest"
        # Don't let auto_decide pull her out of message activity mid-send,
        # but do allow exit when vitals are critically low (spent/exhausted).
        if override and self.activity == "message":
            if self.vitals.social_battery > 8 and self.vitals.energy > 8:
                override = None
        if self.testing_mode and self.activity in ("sleep", "dream"):
            self.set_activity("rest")
        elif override:
            self.set_activity(override)

        # ── Item 37: activity streak effects ─────────────────────
        if self.activity == prev_activity:
            self._activity_streak += 1
        else:
            self._activity_streak = 0

        # Flow state: long creative/read/think run boosts curiosity
        if self._activity_streak > 60 and self.activity in ("create", "read", "think"):
            self.vitals = Vitals(
                energy=self.vitals.energy,
                social_battery=self.vitals.social_battery,
                curiosity=min(100.0, self.vitals.curiosity + 0.03),
            )
        # Saturation: very long run in same non-rest activity costs extra energy
        if self._activity_streak > 240 and self.activity not in ("rest", "sleep", "dream"):
            self.vitals = Vitals(
                energy=max(0.0, self.vitals.energy - 0.04),
                social_battery=self.vitals.social_battery,
                curiosity=self.vitals.curiosity,
            )

        # Detect wake transition — process queued messages
        just_woke = (
            prev_activity in ("sleep", "dream") and
            self.activity not in ("sleep", "dream") and
            self.pending_messages
        )
        if just_woke:
            asyncio.create_task(self._process_pending_messages())

        # 6. Autonomous events — gated by global cooldown + per-activity dice roll
        # Suppress autonomous messages if there's been recent two-way conversation (5 min window).
        # Prevents her from interrupting an active exchange with a separate outreach.
        _now = time.time()
        _recent_contact = any(
            p.last_contact and (_now - p.last_contact) < 300
            for p in self.persons
        )

        # When in "message" activity, bypass the dice roll — she will always fire.
        gap_ok = (time.monotonic() - self._last_autonomous_fire_mono) >= MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS
        if not self._busy and gap_ok and not _recent_contact and (
            self.activity == "message" or should_fire_event(self.activity, TICK_SECONDS)
        ):
            self._last_autonomous_fire_mono = time.monotonic()
            asyncio.create_task(self._fire_event())

        # 6b. Standalone outreach — independent of activity-based event system
        #     Fires when she hasn't reached out in a while and conditions allow.
        outreach_interval = OUTREACH_INTERVAL_TESTING if self.testing_mode else OUTREACH_INTERVAL
        outreach_due = (_now - self._last_outreach_time) > outreach_interval
        if (not self._busy
                and outreach_due
                and not _recent_contact
                and self.activity not in ("sleep", "dream")
                and self.vitals.social_battery > 35
                and self.on_message):  # only fire if someone is listening
            self._last_outreach_time = time.time()
            asyncio.create_task(self._send_autonomous_outreach())

        # 7. Age memories + decay beliefs + drift distance every AGE_EVERY ticks
        if self._tick % AGE_EVERY == 0:
            self.memories = age(self.memories)
            self.beliefs  = decay_beliefs(self.beliefs)
            self.persons  = tick_distance(self.persons)

            # Item 36 — isolation drift: days without contact push her more introverted
            if self.persons and all(p.distance > 70 for p in self.persons):
                self.soul = Soul(
                    EI=min(100.0, self.soul.EI + 0.01),
                    SN=self.soul.SN,
                    TF=self.soul.TF,
                    JP=self.soul.JP,
                )
                if (self.affect.mood not in ("lonely", "melancholic")
                        and random.random() < 0.05):
                    self.affect = force_mood("lonely", 0.4)
                    self.affect_records = add_affect_record(
                        self.affect_records, "lonely",
                        "no contact with anyone for a long time",
                        ["isolation", "distance", "alone"],
                    )

        # 8. Self-reflection + continuity check every REFLECT_EVERY ticks (~20 min)
        if self._tick % REFLECT_EVERY == 0 and not self._busy:
            asyncio.create_task(self._reflect())

        # 8b. Orphan tag surfacing every ORPHAN_CHECK_EVERY ticks (~6 min)
        #     Runs more often than full reflect so the graph grows from observations quickly.
        if self._tick % ORPHAN_CHECK_EVERY == 0 and not self._busy:
            asyncio.create_task(self._surface_orphan_tags())

        # 9. Mood journal at 22:00 — before she falls asleep, not during
        today = f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        if hour == 22 and today != self.last_journal_date and not self._busy:
            self.last_journal_date = today
            asyncio.create_task(self._write_journal(today))

        # 9b. End-of-day backup at 23:00
        if hour == 23 and today != self.last_backup_date:
            self.last_backup_date = today
            self._save()
            self._backup(today)

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
                # Every EXPLORE_EVERY read events, use fringe interests + explore mode
                # so Chloe ventures outside her dominant topic clusters.
                self._read_event_count += 1
                exploring = (self._read_event_count % feeds.EXPLORE_EVERY == 0)
                read_interests = derive_fringe_interests(self.memories) if exploring else interests

                article = await feeds.fetch_random_article(read_interests, explore=exploring)
                if exploring:
                    self._log("exploration read — seeking something new")

                if article:
                    text = article.summary
                    if self.vitals.curiosity > 65:
                        full = await feeds.fetch_article_text(article.url)
                        if full:
                            text = full
                    mem = await asyncio.to_thread(
                        llm.generate_memory_from_article,
                        article.title, text, read_interests, soul,
                        self.affect.mood, beliefs_d, wants_d, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'read "{article.title[:45]}" → "{mem["text"][:45]}…"')
                    self._check_graph_resonance(mem.get("tags", []))

                    # Item 31 — content-aware soul drift
                    self.soul = content_drift(self.soul, mem.get("tags", []))

                    # Item 40 — emotional weight of world events
                    weight = _article_emotional_weight(article.title, text)
                    if weight == "devastating" and random.random() < 0.5:
                        self.affect = force_mood("melancholic", 0.6)
                        self.affect_records = add_affect_record(
                            self.affect_records, "melancholic",
                            f"read about something devastating: {article.title[:50]}",
                            ["world", "grief", "weight"],
                        )
                        self._log(f"world event hit hard: {article.title[:45]}")
                    elif weight == "beautiful" and random.random() < 0.5:
                        new_mood = "serene" if self.vitals.energy < 50 else "curious"
                        self.affect = force_mood(new_mood, 0.55)
                        self.affect_records = add_affect_record(
                            self.affect_records, new_mood,
                            f"read something beautiful: {article.title[:50]}",
                            ["wonder", "beauty", "lifted"],
                        )
                        self._log(f"article lifted her: {article.title[:45]}")

                    # Resolve wants + goals that overlap with what was just read
                    prev_goal_ids = {g.id for g in self.goals if g.resolved}
                    self.wants = resolve_wants(self.wants, mem.get("tags", []))
                    self.goals = resolve_goals(self.goals, "read", mem.get("tags", []))
                    newly_resolved = [g for g in self.goals if g.resolved and g.id not in prev_goal_ids]
                    for goal in newly_resolved:
                        asyncio.create_task(self._on_goal_resolved(goal))

                    # Second LLM pass — keep rarer so one "read" tick doesn't feel like a burst
                    if random.random() < 0.28:
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
                    topic = read_interests[0] if read_interests else "something"
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, read_interests, soul,
                        self.affect.mood, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')
                    self._check_graph_resonance(mem.get("tags", []))
                    self.soul = content_drift(self.soul, mem.get("tags", []))

            elif self.activity == "dream":
                # Real dream pass — distorts recent memories, wants, ideas
                mem = await asyncio.to_thread(
                    llm.generate_dream, vivid, soul, self.vitals, self.weather, season,
                    wants_d, recent_ideas,
                )
                self.memories = add(self.memories, mem["text"], "dream", mem.get("tags", []))
                self._log(f'dream: "{mem["text"][:60]}…"')
                self._check_graph_resonance(mem.get("tags", []))

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
                    self._check_graph_resonance(want_data.get("tags", []))
                elif roll < 0.45:
                    goal_data = await asyncio.to_thread(
                        llm.generate_goal, vivid, interests, soul,
                        wants_d, beliefs_d, goals_d,
                    )
                    self.goals = add_goal(self.goals, goal_data["text"], goal_data.get("tags", []))
                    self._log(f'goal: "{goal_data["text"][:60]}…"')
                    self._check_graph_resonance(goal_data.get("tags", []))
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
                    prev_goal_ids = {g.id for g in self.goals if g.resolved}
                    self.goals = resolve_goals(self.goals, "create", piece.get("tags", []))
                    newly_resolved = [g for g in self.goals if g.resolved and g.id not in prev_goal_ids]
                    for goal in newly_resolved:
                        asyncio.create_task(self._on_goal_resolved(goal))
                    self._check_graph_resonance(piece.get("tags", []))
                else:
                    topic = interests[0] if interests else "something"
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, interests, soul,
                        self.affect.mood, recent_ideas,
                    )
                    self.memories = add(self.memories, mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"][:60]}…"')
                    self._check_graph_resonance(mem.get("tags", []))

            elif self.activity == "message" and self.vitals.social_battery >= 20:
                # Choose who to reach out to — item 25: pass current hour
                t_msg = time.localtime()
                msg_hour = t_msg.tm_hour
                target = choose_reach_out_target(self.persons, self.affect.mood, hour=msg_hour)
                if target:
                    p_name  = target.name
                    p_notes = [n.to_dict() for n in target.notes[:4]]
                    followups = pending_followups(target)
                    recent_chat = [m for m in self.chat_history if m.get("person_id") == target.id][-8:]

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
                        prefs = derive_preferences(self.affect_records)
                        msg = await asyncio.to_thread(
                            llm.generate_autonomous_message,
                            soul, self.vitals, vivid, interests, self.ideas,
                            self.weather, season, p_name, p_notes, prefs,
                            target.warmth, msg_hour,
                            recent_chat=recent_chat,
                            last_contact=target.last_contact,
                            upcoming_events=format_upcoming_events(get_upcoming_events(target)),
                        )
                        self._log(f"chloe reached out to {p_name} unprompted")
                else:
                    prefs = derive_preferences(self.affect_records)
                    msg = await asyncio.to_thread(
                        llm.generate_autonomous_message,
                        soul, self.vitals, vivid, interests, self.ideas,
                        self.weather, season, preferences=prefs,
                    )
                    self._log("chloe reached out unprompted")

                target_id = target.id if target else "teo"
                self._add_chat("chloe", msg, autonomous=True, person_id=target_id)
                if self.on_message:
                    self.on_message(msg, target_id)

        except Exception as e:
            self._log(f"event error: {e}")

        self._busy = False

    # ── Standalone autonomous outreach ──────────────────────

    async def _send_autonomous_outreach(self):
        """Send a DM unprompted, independent of the activity-based event system.
        This is what actually makes Chloe text — she doesn't need to be in
        'message' activity for this to fire."""
        self._busy = True
        try:
            t        = time.localtime()
            hour     = t.tm_hour
            season   = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(hour)}"
            interests = derive_interests(self.memories)
            vivid     = get_vivid(self.memories, 4)
            prefs     = derive_preferences(self.affect_records)

            target = choose_reach_out_target(self.persons, self.affect.mood, hour=hour)
            if not target:
                self._busy = False
                return

            p_name  = target.name
            p_notes = [n.to_dict() for n in target.notes[:4]]
            followups = pending_followups(target)
            recent_chat = [m for m in self.chat_history if m.get("person_id") == target.id][-8:]

            if followups and random.random() < 0.40:
                note = followups[0]
                msg = await asyncio.to_thread(
                    llm.generate_followup,
                    p_name, note.text, self.soul, self.vitals, self.affect.mood,
                )
                self.persons = mark_followed_up(self.persons, target.id, note.id)
                self._log(f'outreach: follow-up to {p_name}: "{note.text[:40]}…"')
            else:
                msg = await asyncio.to_thread(
                    llm.generate_autonomous_message,
                    self.soul, self.vitals, vivid, interests, self.ideas,
                    self.weather, season, p_name, p_notes, prefs,
                    target.warmth, hour,
                    recent_chat=recent_chat,
                    last_contact=target.last_contact,
                )
                self._log(f"outreach: Chloe texted {p_name} unprompted")

            self._add_chat("chloe", msg, autonomous=True, person_id=target.id)
            if self.on_message:
                self.on_message(msg, target.id)

        except Exception as e:
            self._log(f"outreach error: {e}")
        self._busy = False

    # ── Item 33: goal completion feeling ─────────────────────

    async def _on_goal_resolved(self, goal):
        """Generate an emotional reaction when a goal resolves, nudge mood accordingly."""
        try:
            feeling = await asyncio.to_thread(
                llm.generate_completion_feeling,
                goal.text, self.affect.mood, self.soul,
            )
            self.memories = add(self.memories, feeling["text"], "feeling", feeling.get("tags", []))
            mood_nudge = feeling.get("mood_nudge", "satisfied")
            nudge_map = {
                "satisfied":  ("serene",      0.60),
                "relieved":   ("content",     0.55),
                "surprised":  ("curious",     0.60),
                "fell_short": ("melancholic", 0.50),
            }
            mood_name, intensity = nudge_map.get(mood_nudge, ("content", 0.50))
            self.affect = force_mood(mood_name, intensity)
            self.affect_records = add_affect_record(
                self.affect_records, mood_name,
                f"completed goal: {goal.text[:60]}",
                feeling.get("tags", []),
            )
            self._log(f'goal resolved ({mood_nudge}): "{feeling["text"][:50]}…"')
        except Exception as e:
            self._log(f"completion feeling error: {e}")

    # ── GRAPH INTELLIGENCE ───────────────────────────────────

    def _check_graph_resonance(self, tags: list[str]):
        """G1 + G2: Match tags against graph nodes, reinforce them, and queue
        auto-expansion for any leaf node that crosses the hit threshold."""
        if not tags:
            return

        matched = match_nodes_by_tags(self.graph, tags)
        for node in matched:
            self.graph = reinforce_node(self.graph, node.id)

        # Re-read nodes after reinforcement to get updated hit counts
        leaf_ids = {n.id for n in get_leaf_nodes(self.graph)}
        for node in matched:
            updated = next((n for n in self.graph.nodes if n.id == node.id), None)
            if not updated:
                continue
            if (updated.hit_count >= GRAPH_HIT_THRESHOLD
                    and updated.id in leaf_ids
                    and self.vitals.curiosity > 55):
                asyncio.create_task(self._auto_expand_node(updated.id))

    async def _auto_expand_node(self, node_id: str):
        """G2: Auto-expand a leaf node that has been hit enough times,
        gated by the 6-hour cooldown."""
        node = next((n for n in self.graph.nodes if n.id == node_id), None)
        if not node:
            return

        since_last = time.time() - node.last_auto_expanded
        if since_last < GRAPH_EXPAND_COOLDOWN:
            return

        self._log(f'auto-expanding "{node.label}" after {node.hit_count} hits')
        self.graph = mark_auto_expanded(self.graph, node_id)

        try:
            defs = await asyncio.to_thread(
                llm.expand_interest_node,
                concept=node.label,
                existing_nodes=get_labels(self.graph),
                interests=derive_interests(self.memories),
            )
            self.graph = expand(self.graph, node_id, defs)
            labels = [d["label"] for d in defs]
            self._log(f'auto-expanded "{node.label}" → {", ".join(labels)}')
            for d in defs:
                self.memories = add(self.memories, d.get("note", d["label"]),
                                    "interest", [d["label"]])
            await asyncio.sleep(1.5)
            self.graph = clear_new_flags(self.graph)
        except Exception as e:
            self._log(f"auto-expand error: {e}")

    async def _surface_orphan_tags(self):
        """G3: Find tags recurring in ORPHAN_TAG_MIN_OCCURRENCES+ memories with no graph node → surface as new leaves."""
        if self.vitals.curiosity <= 40:
            return

        # Count tag occurrences across all memories
        tag_counts: dict[str, int] = {}
        for mem in self.memories:
            for tag in mem.tags:
                tag_counts[tag.lower()] = tag_counts.get(tag.lower(), 0) + 1

        # Orphans: frequent enough, not already surfaced, no matching node
        orphans = [
            tag for tag, count in tag_counts.items()
            if count >= ORPHAN_TAG_MIN_OCCURRENCES
            and tag not in self._surfaced_tags
            and not match_nodes_by_tags(self.graph, [tag])
        ]

        if not orphans:
            return

        interests = derive_interests(self.memories)
        # Process at most 2 per reflect cycle to avoid LLM burst
        for tag in orphans[:2]:
            self._surfaced_tags.add(tag)
            try:
                result = await asyncio.to_thread(
                    llm.find_or_create_node,
                    tag, get_labels(self.graph), interests, self.soul,
                )
                if result:
                    parent = find_node_by_label(self.graph, result["parent_label"])
                    parent_id = parent.id if parent else "root"
                    self.graph = expand(self.graph, parent_id,
                                        [{"id": tag, "label": result["label"],
                                          "note": result["note"]}])
                    self._log(f'orphan tag "{tag}" → new node "{result["label"]}"')
                    await asyncio.sleep(1.5)
                    self.graph = clear_new_flags(self.graph)
            except Exception as e:
                self._log(f"orphan surface error ({tag}): {e}")

    async def _surface_dream_recurrences(self):
        """G4: Tags recurring in 3+ dream memories with no depth-1 graph node
        → surface as new nodes attached directly to root."""
        dream_memories = [m for m in self.memories if m.type == "dream"]
        if len(dream_memories) < DREAM_RECURRENCE_MIN:
            return

        tag_counts: dict[str, int] = {}
        for mem in dream_memories:
            for tag in mem.tags:
                tag_counts[tag.lower()] = tag_counts.get(tag.lower(), 0) + 1

        depth1_labels = {n.label.lower() for n in self.graph.nodes if n.depth <= 1}

        recurring = [
            tag for tag, count in tag_counts.items()
            if count >= DREAM_RECURRENCE_MIN
            and tag not in self._surfaced_tags
            and tag not in depth1_labels
        ]

        if not recurring:
            return

        interests = derive_interests(self.memories)
        for tag in recurring[:1]:   # one per reflect cycle — root-level nodes are significant
            self._surfaced_tags.add(tag)
            try:
                result = await asyncio.to_thread(
                    llm.find_or_create_node,
                    tag, get_labels(self.graph), interests, self.soul,
                )
                if result:
                    self.graph = expand(self.graph, "root",
                                        [{"id": tag, "label": result["label"],
                                          "note": result["note"]}])
                    self._log(f'dream recurrence "{tag}" → root node "{result["label"]}"')
                    await asyncio.sleep(1.5)
                    self.graph = clear_new_flags(self.graph)
            except Exception as e:
                self._log(f"dream recurrence error ({tag}): {e}")

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
                # Exclude the queued message itself from history — llm.chat appends it as `message`
                person_history = [m for m in self.chat_history
                                  if m.get("person_id") == pm["person_id"] and m["text"] != pm["text"]]
                reply = await asyncio.to_thread(
                    llm.chat,
                    message=pm["text"],
                    history=person_history[-6:],
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
                self._add_chat("chloe", reply, person_id=pm["person_id"])
                self._log(f"replied to queued message from {person_name}")
                if self.on_message:
                    self.on_message(reply, pm["person_id"])
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

            # G3: surface orphan tags → new graph nodes
            await self._surface_orphan_tags()

            # G4: dream recurrence → depth-1 nodes
            await self._surface_dream_recurrences()

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
            "last_backup_date":  self.last_backup_date,
            # Layer 7+8
            "affect_records": affect_records_to_dicts(self.affect_records),
            # Runtime log — kept so restarts don't lose recent activity
            "log":  self.log,
        }
        try:
            self.state_file.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            print(f"[save error] {exc}")

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
            self.last_backup_date  = data.get("last_backup_date", "")
            self.log               = data.get("log", [])
            # Layer 7+8
            self.affect_records = affect_records_from_dicts(data.get("affect_records", []))
            # Rebuild surfaced-tags set from existing graph node labels
            # so we don't re-evaluate concepts that already have nodes
            self._surfaced_tags = {n.label.lower() for n in self.graph.nodes}
            self._log("State restored from disk.")
        except Exception as e:
            self._log(f"Could not load state: {e}. Starting fresh.")

    def _backup(self, today: str):
        """Copy current state file to backups/chloe_YYYY-MM-DD.json."""
        import shutil
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        dest = backup_dir / f"chloe_{today}.json"
        try:
            shutil.copy2(self.state_file, dest)
            self._log(f"backup saved → backups/chloe_{today}.json")
        except Exception as exc:
            self._log(f"backup error: {exc}")

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

    def _add_chat(self, from_: str, text: str, autonomous: bool = False, person_id: str = ""):
        now = time.time()
        # Item 24 — session threading: gap > 30 min starts a new session
        SESSION_GAP = 1800
        if self._last_chat_time and (now - self._last_chat_time) > SESSION_GAP:
            self._current_session += 1
        self._last_chat_time = now

        self.chat_history.append({
            "from": from_, "text": text,
            "time": _ts(), "autonomous": autonomous,
            "person_id": person_id,
            "session": self._current_session,
        })
        if len(self.chat_history) > 500:
            self.chat_history = self.chat_history[-500:]


def _ts() -> str:
    t = time.localtime()
    return f"{t.tm_hour:02d}:{t.tm_min:02d}"
