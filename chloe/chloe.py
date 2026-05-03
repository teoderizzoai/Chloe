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

from .soul     import Soul, drift, consolidate, content_drift, content_affect, seasonal_drift, update_soul_momentum, mbti_type, describe  # DEPRECATED — kept for heart.py compat only
from .identity import (Identity, identity_block, add_trait, reinforce_trait,
                       decay_traits, check_core_promotion, traits_snapshot,
                       snapshot_diff, add_contradiction, update_identity_momentum,
                       traits_matching_tags, penalize_trait, active_traits)
from .heart  import (Vitals, ACTIVITIES, tick_vitals, auto_decide,
                     should_fire_event, circadian_phase, day_name)
from .memory import Memory, seed_memories, add, age, get_vivid, derive_interests, derive_fringe_interests, to_dicts, MemoryIndex, Idea, MAX_IDEAS, ideas_to_dicts, find_recurring_loops
from .graph  import (Graph, seed_graph, expand, clear_new_flags, get_labels,
                     reinforce_node, match_nodes_by_tags, get_leaf_nodes,
                     mark_auto_expanded, find_node_by_label,
                     pick_think_expansion_target, graph_knowledge_context,
                     match_deep_nodes_for_message)
from .affect import Affect, update_mood, force_mood
from .avatar import portrait_meta
from .inner  import (Want, Belief, Goal, AffectRecord, Fear, Aversion,
                     Tension, Arc, MOOD_TO_ARC, ARC_DURATION_HOURS,
                     add_want, resolve_wants, wants_to_dicts,
                     add_fear, fears_to_dicts,
                     add_aversion, aversions_to_dicts,
                     add_or_reinforce_belief, decay_beliefs, beliefs_to_dicts,
                     add_goal, resolve_goals, goals_to_dicts, fail_stale_goals,
                     add_affect_record, affect_records_to_dicts,
                     derive_preferences,
                     outreach_risk_score,
                     add_tension, decay_tensions, tensions_to_dicts,
                     tick_pressure,
                     impulse_check, decay_affect_residue, total_residue)
from .persons import (Person, PersonNote, PersonEvent, SharedMoment,
                      default_persons, on_contact, add_note, add_event, mark_followed_up,
                      pending_followups, tick_distance, choose_reach_out_target,
                      boost_warmth, tone_context, relationship_stage,
                      get_person, get_upcoming_events, format_upcoming_events,
                      add_moment, format_shared_moments,
                      add_conflict, reduce_conflict, tick_conflict, format_conflict_context,
                      upsert_third_party, format_third_party_context,
                      format_cross_person_context, set_impression,
                      format_trait_profile_context,
                      format_attachment_context, attachment_risk_modifier)
from . import llm
from . import feeds
from . import weather as wthr
from .store import ChloeDB, DB_FILE
from .weather import WeatherState

TICK_SECONDS   = 30      # one heartbeat
AGE_EVERY      = 12     # age memories every N ticks (~1 min)
SAVE_EVERY     = 60     # persist state every N ticks (~5 min)
WEATHER_EVERY  = 720    # refresh weather every N ticks (~1 hour)
REFLECT_EVERY  = 240    # self-reflection + continuity check every N ticks (~2 h at 30 s/tick)
ORPHAN_CHECK_EVERY = 240 # orphan tag surfacing every N ticks (~2 h) — matches reflect cadence
STATE_FILE     = Path("data/chloe_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Graph Intelligence constants ─────────────────────────────
GRAPH_HIT_THRESHOLD        = 5        # hits before a leaf node auto-expands
GRAPH_EXPAND_COOLDOWN      = 6 * 3600 # seconds between auto-expands per node
ORPHAN_TAG_MIN_OCCURRENCES = 2        # tag must appear in this many memories (was 3)
DREAM_RECURRENCE_MIN       = 3        # tag must appear in this many dreams

# Autonomous `_fire_event` pacing — separate from TICK_SECONDS. Even with a slow
# tick, `should_fire_event` rolls could feel spammy if Haiku returns fast and the
# user keeps her in high-chance activities (create/read). This floor guarantees a
# minimum quiet gap between *starting* two background events (user chat is unchanged).
# 3600 s = 1 event per hour max during waking time (~16 events/day). Old value of
# 90 s drove ~960 events/day and €25/day in API costs.
MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS = 3600

# Standalone outreach — fires independently of activity-based events
OUTREACH_INTERVAL         = 48 * 3600  # normal: attempt outreach at most once per 2 days
OUTREACH_INTERVAL_TESTING = 10 * 60    # testing mode: once per 10 min
QUIET_AFTER_BUSY          = 24 * 3600  # suppress unprompted outreach for 24h after a busy/ will-text request
IGNORED_THRESHOLD         = 4 * 3600   # item 51: after 4h with no reply, she feels ignored
MAX_ACTIVE_TRAITS         = 10         # cap on active traits; skip proposals when at limit
TRAIT_PROPOSE_EVERY       = 6          # only propose new traits every N reflect cycles (~12 h)
IGNORED_THRESHOLD_TESTING = 10 * 60    # testing mode: 10 min


# Items 43 + 44 handled by LLM emotion reading — see _apply_emotion_reaction()

def _make_emotional_context(emotion_data: dict, person_name: str) -> str:
    """Translate emotion reading into a direct sentence for the Opus prompt.
    This is the specific trigger of THIS exchange, separate from general mood."""
    emotion   = emotion_data.get("emotion", "neutral")
    intensity = float(emotion_data.get("intensity", 0.5))
    at_chloe  = bool(emotion_data.get("directed_at_chloe", True))

    if emotion == "neutral" or intensity < 0.35:
        return ""

    _ctx = {
        ("angry",        True):  f"{person_name} is angry with you. Don't smooth it over.",
        ("frustrated",   True):  f"{person_name} is frustrated with you. That registers.",
        ("disappointed", True):  f"{person_name} seems disappointed in you. It lands.",
        ("dismissive",   True):  f"{person_name} is being dismissive. That's irritating.",
        ("cold",         True):  f"{person_name} is being cold. You notice.",
        ("hurt",         True):  f"{person_name} is hurt by something. That sits with you.",
        ("affectionate", True):  f"{person_name} is being genuinely affectionate. You feel it.",
        ("tender",       True):  f"{person_name} is being tender. Let yourself be soft back.",
        ("grateful",     True):  f"{person_name} is grateful to you. That means something.",
        ("playful",      True):  f"{person_name} is being playful. You can meet that.",
        ("playful",      False): f"{person_name} is being playful. You can match that energy.",
        ("excited",      True):  f"{person_name} is excited, and it's aimed at you.",
        ("excited",      False): f"{person_name} is excited about something. You feel the energy.",
        ("curious",      True):  f"{person_name} is genuinely curious about something you said or are.",
        ("curious",      False): f"{person_name} is curious about something. You're interested too.",
        ("sad",          False): f"{person_name} seems sad about something in his life. You notice that.",
        ("lonely",       False): f"{person_name} seems lonely. You feel that.",
        ("anxious",      False): f"{person_name} seems anxious. You pick up on it.",
        ("tired",        False): f"{person_name} seems tired. You notice.",
        ("overwhelmed",  False): f"{person_name} is overwhelmed. You feel that.",
        ("stressed",     False): f"{person_name} is stressed about something. You register it.",
        ("thoughtful",   True):  f"{person_name} is being thoughtful with you.",
        ("thoughtful",   False): f"{person_name} is in a thoughtful mood.",
    }

    return _ctx.get((emotion, at_chloe), "")


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
    haystack = (title + " " + text).lower()
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
        self.ideas:    list[Idea]  = []
        self.log:      list[str]   = []
        self.weather:  Optional[WeatherState] = None

        # ── Layer 3: inner life ──
        self.affect:           Affect        = Affect()
        self.wants:            list[Want]      = []
        self.fears:            list[Fear]      = []
        self.aversions:        list[Aversion]  = []
        self.beliefs:          list[Belief]    = []
        self.creative_outputs: list[dict]      = []   # last 5 creative pieces

        # ── Layer 4: relational depth ──
        self.persons: list[Person] = default_persons()

        # ── Layer 5: self-awareness ──
        self.goals:            list[Goal] = []
        self._identity_snapshot: dict     = {}   # trait weights at last continuity check
        self.last_journal_date: str       = ""   # "YYYY-MM-DD"
        self.last_backup_date:  str       = ""   # "YYYY-MM-DD"

        # ── Graph Intelligence ──
        # Tags we've already evaluated for orphan surfacing — not persisted,
        # rebuilt from graph labels on load so we don't re-evaluate known nodes.
        self._surfaced_tags: set[str] = set()

        # ── Layer 7+8: emotional history + streak ──
        self.affect_records:    list[AffectRecord] = []
        self._activity_streak:  int                = 0   # consecutive ticks in current activity

        # ── Layer 11: Identity (replaces MBTI soul momentum) ──
        # Trait weights tracked in self.identity.identity_momentum

        # ── Layer 13: Friction & Inner Depth ──
        self.tensions: list[Tension]    = []   # item 68: active internal conflicts
        self.arc: Optional[Arc]         = None # item 74: current long-term mood arc
        self._reflect_mood_history: list[str] = []  # item 74: last N moods at reflect time
        self._reflect_count: int = 0               # how many reflect cycles have run
        self._risk_tolerance: dict      = {}   # item 73: {person_id: {value, expires}}
        self.recurring_loops: list[str] = []   # B3: tag clusters that keep resurfacing

        # ── Item 24: conversation session tracking ──
        self._current_session:  int   = 0
        self._last_chat_time:   float = 0.0

        # ── Conversation closing ──
        # Set when she sends a winding-down message; cleared when she replies again
        # or when Teo's next message is clearly not a conclusion.
        self._closing: dict[str, bool] = {}

        # ── Testing / outreach ──
        self.testing_mode:      bool  = False
        self._last_outreach_time: float = 0.0
        # Item 51 — pending autonomous messages waiting for a reply
        # [{person_id, sent_at (float), person_name}]
        self._pending_outreach: list[dict] = []
        self._quiet_until: dict[str, float] = {}   # silence unprompted outreach for a person

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

        # ── Semantic memory index ──
        self.memory_index = MemoryIndex(str(state_file.parent / "memory_index"))

        # ── SQLite store ──
        self.db = ChloeDB(state_file.parent / DB_FILE)

        # ── Graph read queue ──
        # Labels of nodes freshly expanded during think — consumed by the read branch
        # so she immediately pursues what she just went deeper on.
        self._graph_read_queue: list[str] = []

        self._load()

    # ── Memory helper ────────────────────────────────────────

    def _remember(self, text: str, type: str = "observation", tags: list = None,
                  salience: float = 0.0) -> None:
        """Add a memory to the store, the semantic index, and SQLite."""
        self.memories = add(self.memories, text, type, tags, salience=salience)
        self.memory_index.add(self.memories[0])
        self.db.add_memory(self.memories[0])
        if self.identity.traits and random.random() < 0.05:
            asyncio.create_task(self._maybe_reinforce_traits(self.memories[0]))

    def _is_quiet(self, person_id: str) -> bool:
        return time.time() < self._quiet_until.get(person_id, 0.0)

    def _set_quiet(self, person_id: str, duration: float) -> None:
        self._quiet_until[person_id] = time.time() + duration
        self._log(f"quiet outreach mode activated for {person_id} for {duration // 3600}h")

    def _matches_quiet_request(self, message: str) -> bool:
        msg = message.lower()
        quiet_phrases = [
            "don't text", "dont text", "stop texting", "stop text", "do not text",
            "i'm busy", "im busy", "i am busy", "too busy", "busy right now",
            "can't talk", "cant talk", "not available", "not available right now",
            "i'll text you", "i will text you", "will text you", "text you later",
            "message you later", "talk later", "i'll message you", "i will message you",
            "i'll get back to you", "i will get back to you", "get back to you later",
        ]
        return any(phrase in msg for phrase in quiet_phrases)

    async def _maybe_reinforce_traits(self, memory) -> None:
        """10% chance on any memory add: check if the memory reinforces a random active trait."""
        try:
            from .identity import active_traits as _at
            candidates = _at(self.identity)[:5]
            if not candidates:
                return
            trait = random.choice(candidates)
            delta = await asyncio.to_thread(
                llm.classify_trait_reinforcement,
                memory.text, trait.name, trait.behavioral_profile,
            )
            if delta > 0:
                # High-salience memories contribute more to trait reinforcement
                salience_scale = 1.0 + getattr(memory, "salience", 0.0)
                self.identity = reinforce_trait(self.identity, trait.id, delta * salience_scale)
                self.identity = update_identity_momentum(self.identity, trait.id, delta * salience_scale)
                self.db.sync_traits(self.identity.traits)
        except Exception as e:
            self._log(f"trait reinforce error: {e}")

    # ── Layer 13 helpers ─────────────────────────────────────

    @staticmethod
    def _bias_emotion_toward_mood(emotion_data: dict, current_mood: str) -> dict:
        """Item 70: softly bias neutral/ambiguous emotion reads toward current mood.
        Irritable projects coldness onto neutrality; lonely reads neutrality as sadness;
        serene dampens negative intensity. Strong reads (intensity > 0.65) are left alone."""
        emotion   = emotion_data.get("emotion", "neutral")
        intensity = float(emotion_data.get("intensity", 0.5))

        # Only bias weak or neutral reads — trust strong signals
        if intensity > 0.65 or emotion not in ("neutral", "thoughtful", "tired"):
            return emotion_data

        result = dict(emotion_data)
        if current_mood == "irritable" and emotion == "neutral":
            result["emotion"]   = "cold"
            result["intensity"] = min(0.55, intensity + 0.15)
        elif current_mood == "lonely" and emotion == "neutral":
            result["emotion"]   = "sad"
            result["intensity"] = min(0.50, intensity + 0.10)
        elif current_mood == "serene":
            # Serene dampens negative reads — she's less prone to projecting negativity
            if emotion in ("frustrated", "cold", "angry", "disappointed", "dismissive"):
                result["intensity"] = max(0.0, intensity * 0.55)
        return result

    @staticmethod
    def _vitals_sensation_text(vitals) -> str:
        """Item 71: translate vitals into physical sensation language for the chat prompt."""
        parts = []

        if vitals.energy < 20:
            parts.append("completely drained, heavy")
        elif vitals.energy < 35:
            parts.append("slow and heavy")
        elif vitals.energy > 80:
            parts.append("buzzing")
        elif vitals.energy > 65:
            parts.append("sharp and present")

        if vitals.social_battery < 15:
            parts.append("desperately needing quiet")
        elif vitals.social_battery < 30:
            parts.append("a low hum of social fatigue")
        elif vitals.social_battery > 75:
            parts.append("open, wanting company")

        if vitals.curiosity > 80:
            parts.append("mind restless with questions")
        elif vitals.curiosity > 65:
            parts.append("a pull toward something new")
        elif vitals.curiosity < 25:
            parts.append("mentally flat")

        if vitals.focus < 25:
            parts.append("scattered, can't hold a thought")
        elif vitals.focus < 45:
            parts.append("finding it hard to concentrate")
        elif vitals.focus > 82:
            parts.append("unusually clear-headed")

        if vitals.inspiration > 82:
            parts.append("something wants to be made")
        elif vitals.inspiration < 15:
            parts.append("nothing coming through creatively")

        return ", ".join(parts) if parts else ""

    def _recent_attention_topics(self, within_seconds: int = 3600) -> list[str]:
        """Item 72: labels of graph nodes reinforced in the last `within_seconds`.
        Used to bias fire_event and autonomous message topic selection."""
        now = time.time()
        return [
            n.label for n in self.graph.nodes
            if n.id != "root"
            and n.last_reinforced > 0
            and (now - n.last_reinforced) < within_seconds
        ]

    @staticmethod
    def _compute_risk_level(mood: str, warmth: float) -> float:
        """Item 73: how emotionally exposed is Chloe right now?
        High warmth + certain moods = more willing to be vulnerable."""
        base = 0.25 + (warmth / 100) * 0.4
        mood_adj = {
            "lonely":      0.20,
            "melancholic": 0.15,
            "serene":      0.10,
            "content":     0.05,
            "curious":     0.00,
            "restless":   -0.05,
            "energized":  -0.05,
            "irritable":  -0.20,
        }
        return min(1.0, max(0.0, base + mood_adj.get(mood, 0)))

    @staticmethod
    def _build_memory_query(message: str, history: list[dict], mood: str) -> str:
        """Build a rich semantic query from conversation context for memory retrieval.
        Combines the current message with recent turns and mood signal."""
        turns = " ".join(
            m.get("text", "")[:100]
            for m in history[-5:]
            if m.get("text")
        )
        parts = [message]
        if turns.strip():
            parts.append(turns)
        if mood and mood not in ("content", "serene"):
            parts.append(mood)
        return " ".join(parts)

    @staticmethod
    def _is_closing_message(text: str) -> bool:
        """True if this message looks like it's wrapping up — a short goodbye or acknowledgement.
        Used to skip replying after Chloe has already wound down the conversation."""
        import re as _re
        t = text.lower().strip()
        if '?' in t:                    # questions always deserve a reply
            return False
        if len(t) <= 15:                # "ok", "bye", "sure", "👋", "haha ok" — definitely closing
            return True
        if len(t) > 40:                 # too long to be a simple goodbye
            return False
        _closing = frozenset({'bye', 'goodbye', 'cya', 'later', 'night', 'goodnight',
                               'ttyl', 'take care', 'see ya', 'see you', 'talk later',
                               'talk soon', 'gotta go', 'have to go', 'alright then',
                               'sounds good', 'okay then', 'got it', 'ok ok'})
        words = set(_re.sub(r'[^\w\s]', ' ', t).split())
        return bool(words & _closing)

    def _get_risk_tolerance(self, person_id: str) -> float:
        """Item 73: current risk tolerance for a person.
        C5: baseline derived from attachment pattern when no ephemeral override."""
        rt = self._risk_tolerance.get(person_id)
        if rt and time.time() < rt.get("expires", 0):
            return rt["value"]
        person = get_person(self.persons, person_id)
        if person:
            return attachment_risk_modifier(person)
        return 1.0

    def _reduce_risk_tolerance(self, person_id: str, by: float = 0.25, hours: float = 24.0):
        """Item 73: temporarily reduce risk tolerance for a person."""
        current = self._get_risk_tolerance(person_id)
        self._risk_tolerance[person_id] = {
            "value":   max(0.2, current - by),
            "expires": time.time() + hours * 3600,
        }

    def _bump_social_want_pressure(self, by: float = 0.12):
        """Priority 3: when outreach is suppressed, raise pressure on the social want.
        Finds the first unresolved want tagged with social connection, or creates one."""
        social_tags = {"connection", "social", "reach out", "people"}
        for i, w in enumerate(self.wants):
            if not w.resolved and {t.lower() for t in w.tags} & social_tags:
                new_pressure = min(1.0, w.pressure + by)
                self.wants[i] = Want(**{**w.to_dict(), "pressure": new_pressure})
                return
        self.wants = add_want(
            self.wants,
            "reach out to someone",
            ["connection", "social"],
        )
        if self.wants:
            self.wants[0] = Want(**{**self.wants[0].to_dict(), "pressure": by})

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

    async def chat(self, message: str, person_id: str = "teo", voice: bool = False) -> Optional[str]:
        """Send a message and get a reply.

        Returns None if she's in deep sleep and the message is queued.
        Returns a string reply otherwise.
        """
        if voice:
            return await self._voice_chat(message, person_id)

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

        # If she already wound down the conversation and this message is a conclusion, skip reply
        if self._closing.get(person_id) and self._is_closing_message(message):
            self._closing.pop(person_id, None)
            self._log(f"skipping reply — conversation concluded by {person_id}")
            return None

        self.set_activity("message")
        t_now = time.localtime()
        self.persons = on_contact(self.persons, person_id, hour=t_now.tm_hour)
        # Item 51 — they replied; clear any pending outreach for this person
        self._pending_outreach = [o for o in self._pending_outreach
                                   if o["person_id"] != person_id]
        self._log(f"message from {person_id}: \"{message}\"")
        if self._matches_quiet_request(message):
            self._set_quiet(person_id, QUIET_AFTER_BUSY)

        person = get_person(self.persons, person_id)
        person_name  = person.name if person else "Teo"
        person_notes = [n.to_dict() for n in (person.notes if person else [])]

        # Item 52 — refresh impression every 10 conversations (or first time once there are notes)
        _p_for_impression = get_person(self.persons, person_id)
        if _p_for_impression:
            _cc = _p_for_impression.conversation_count
            _has_notes = bool(_p_for_impression.notes)
            if (_cc > 0 and _cc % 10 == 0) or (not _p_for_impression.impression and _has_notes):
                asyncio.create_task(self._update_person_impression(person_id))

        # Items 43 + 44 — read Teo's emotional state from message + conversation context.
        # Runs before the reply so the mood change affects the current response.
        emotional_context = ""
        emotion_data = {"emotion": "neutral", "intensity": 0.5, "directed_at_chloe": True, "tags": []}
        if not voice and len(message.strip()) >= 15:
            try:
                _recent = [m for m in self.chat_history if m.get("person_id") == person_id][-6:]
                emotion_data = await asyncio.to_thread(
                    llm.read_person_emotion, message, person_name, _recent
                )
                emotion_data = self._bias_emotion_toward_mood(emotion_data, self.affect.mood)
                self._apply_emotion_reaction(emotion_data, person_id, person_name)
                emotional_context = _make_emotional_context(emotion_data, person_name)
            except Exception as e:
                self._log(f"emotion read error: {e}")
        else:
            asyncio.create_task(self._voice_emotion_background(message, person_id, person_name))

        t      = time.localtime()
        hour   = t.tm_hour
        season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(hour)}"

        # Item 24 — session-aware history: prefer current session, fall back to recent
        cur_session_history = [m for m in person_history
                               if m.get("session") == self._current_session]
        chat_ctx = cur_session_history[-10:] if cur_session_history else person_history[-6:]

        person_warmth   = person.warmth if person else 50.0
        upcoming_events = format_upcoming_events(get_upcoming_events(person)) if person else ""
        moments_ctx     = format_shared_moments(person.moments) if person else ""
        conflict_ctx    = format_conflict_context(person) if person else ""
        third_party_ctx   = format_third_party_context(person, message) if person else ""
        cross_person_ctx  = format_cross_person_context(self.persons, person_id, message)
        interests       = derive_interests(self.memories)
        prefs           = derive_preferences(self.affect_records)

        # Topic resonance: does this message touch something she cares about or dislikes?
        # Local check — no API call. Interests and drags are the accumulated signal.
        _msg_lower      = message.lower()
        resonant_topics = [t for t in interests if len(t) > 3 and t.lower() in _msg_lower]
        dragging_topics = [t for t in prefs.get("drags", []) if len(t) > 3 and t.lower() in _msg_lower]

        # Graph resonance: surface knowledge she's genuinely traced that matches this message
        _matched_deep = match_deep_nodes_for_message(self.graph, message)
        _graph_resonant_ctx = ""
        if _matched_deep:
            _lines = [f"{n.label} — {n.note}" for n in _matched_deep]
            _graph_resonant_ctx = "You've actually thought about this: " + " / ".join(_lines)

        _risk_tol     = self._get_risk_tolerance(person_id)
        _winding_down = self.vitals.social_battery < 30

        # If battery is recovering, clear any leftover closing flag
        if self.vitals.social_battery >= 35:
            self._closing.pop(person_id, None)

        # Memory retrieval: rich query → 20 candidates → Haiku grader → 5 relevant
        _mem_q          = self._build_memory_query(message, chat_ctx, self.affect.mood)
        _mem_candidates = self.memory_index.query(_mem_q, self.memories, 20)
        _graded_mems    = await asyncio.to_thread(
            llm.grade_memories, _mem_candidates, message, chat_ctx, self.affect.mood
        )

        try:
            reply = await asyncio.to_thread(
                llm.chat,
                message=message,
                history=chat_ctx,
                identity=self.identity,
                vitals=self.vitals,
                memories=_graded_mems,
                interests=interests,
                ideas=[i.text for i in self.ideas],
                uptime=self._uptime_human(),
                weather=self.weather,
                season=season,
                mood=self.affect.mood,
                beliefs=beliefs_to_dicts(self.beliefs),
                person_name=person_name,
                person_notes=person_notes,
                sleep_state="woken" if was_woken else "",
                preferences=prefs,
                warmth=person_warmth,
                hour=hour,
                upcoming_events=upcoming_events,
                resonant_topics=resonant_topics or None,
                dragging_topics=dragging_topics or None,
                emotional_context=emotional_context,
                shared_moments=moments_ctx or None,
                conflict_ctx=conflict_ctx or None,
                third_party_ctx=third_party_ctx or None,
                cross_person_ctx=cross_person_ctx or None,
                person_impression=person.impression if person else "",
                wants=wants_to_dicts(self.wants),
                fears=fears_to_dicts(self.fears),
                aversions=aversions_to_dicts(self.aversions),
                tensions=tensions_to_dicts(self.tensions),
                vitals_sensation=self._vitals_sensation_text(self.vitals),
                risk_tolerance=_risk_tol,
                winding_down=_winding_down,
                voice=voice,
                graph_deep_ctx=graph_knowledge_context(self.graph),
                graph_resonant_ctx=_graph_resonant_ctx,
                contradiction_ctx="",  # wired; populated when identity.py provides Contradiction objects
                loops_ctx=", ".join(self.recurring_loops[:3]) if self.recurring_loops else "",
                residue_ctx=f"emotional weight {total_residue(self.affect_records):.2f}" if total_residue(self.affect_records) > 0.3 else "",
                incomplete_ideas=[i for i in self.ideas[:10] if not getattr(i, "complete", True)] or None,
                trait_profile_ctx=format_trait_profile_context(person) if person else "",
                attachment_ctx=format_attachment_context(person) if person else "",
            )
        except Exception as e:
            print(f"[chat error] {type(e).__name__}: {e}")
            err = str(e).lower()
            if any(x in err for x in ("usage limit", "rate limit", "quota", "429", "400", "401", "authentication", "invalid x-api-key")):
                import random as _r
                reply = _r.choice([
                    "ugh, something's wrong on my end. give me a bit (API problems)",
                    "hold on, my brain is being weird right now. back in a sec (API problems)",
                    "i'm getting an error, not sure what's going on. try again in a bit? (API problems)",
                    "something's off with me right now. i'll be back (API problems)",
                    "can't think straight right now. later? (API problems)",
                ])
            else:
                reply = f"(something went quiet: {e})"

        # Item 73: vulnerability & social consequence
        # If she was emotionally exposed (high risk level) and it was met with coldness, she pulls back.
        _cold_set = {"cold", "dismissive", "frustrated", "angry"}
        _e_val    = emotion_data.get("emotion", "neutral")
        _e_int    = float(emotion_data.get("intensity", 0))
        _e_at_me  = bool(emotion_data.get("directed_at_chloe", True))
        _risk     = self._compute_risk_level(self.affect.mood, person_warmth) * _risk_tol
        if (_risk > 0.6 and _e_val in _cold_set and _e_at_me and _e_int > 0.45):
            self._remember(
                "tried to reach through and found nothing there. it stays.",
                "feeling", ["rejection", "vulnerability", "guarded"],
                salience=min(1.0, 0.5 + _e_int * 0.5),
            )
            self._reduce_risk_tolerance(person_id, by=0.25, hours=24)
            self._log(f"item 73: vulnerability met with coldness from {person_id}")

        # Mark conversation as closing if she just wound down
        if _winding_down:
            self._closing[person_id] = True
            self._log(f"winding down conversation with {person_id} (social battery: {self.vitals.social_battery:.0f})")

        self._add_chat("chloe", reply, person_id=person_id)

        # Extract topic tags from what was actually said — richer than just top interests.
        # This lets conversations create new graph nodes via G3 orphan surfacing.
        _conv_lower = (message + " " + reply).lower()
        _conv_tags  = [t for t in interests if len(t) > 3 and t.lower() in _conv_lower]
        if not _conv_tags:
            _conv_tags = interests
        self._remember(f'Said: "{reply}"', "conversation", _conv_tags)

        # Conversations can also form beliefs — 15% chance, background task
        if random.random() < 0.15:
            asyncio.create_task(self._extract_belief_from_conversation(
                message, reply, person_name,
            ))

        # Combined extraction: notable note, event, third parties, shared moment
        _full_exchange = [m for m in self.chat_history if m.get("person_id") == person_id][-6:]
        asyncio.create_task(self._extract_from_exchange_bg(message, _full_exchange, person_id, person_name))

        # Conversations shape the graph — reinforce nodes matched by the exchange.
        self._check_graph_resonance(_conv_tags)

        # Soul content drift retired — trait reinforcement happens via _reflect()
        return reply

    async def _voice_chat(self, message: str, person_id: str) -> str:
        """Fast path for voice: fire LLM immediately, do all extraction after."""
        self._add_chat("user", message, person_id=person_id)
        self.set_activity("message")
        t_now   = time.localtime()
        hour    = t_now.tm_hour
        person  = get_person(self.persons, person_id)
        person_name = person.name if person else "Teo"
        season  = f"{wthr.describe_season(t_now.tm_mon)}, {circadian_phase(hour)}"
        interests = derive_interests(self.memories)

        _voice_history  = [m for m in self.chat_history if m.get("person_id") == person_id][-6:]
        _mem_q_v        = self._build_memory_query(message, _voice_history, self.affect.mood)
        _mem_cands_v    = self.memory_index.query(_mem_q_v, self.memories, 20)
        _graded_mems_v  = await asyncio.to_thread(
            llm.grade_memories, _mem_cands_v, message, _voice_history, self.affect.mood
        )

        try:
            reply = await asyncio.to_thread(
                llm.chat,
                message=message,
                history=_voice_history,
                identity=self.identity,
                vitals=self.vitals,
                memories=_graded_mems_v,
                interests=interests,
                ideas=[i.text for i in self.ideas],
                uptime=self._uptime_human(),
                weather=self.weather,
                season=season,
                mood=self.affect.mood,
                beliefs=beliefs_to_dicts(self.beliefs),
                person_name=person_name,
                person_notes=[n.to_dict() for n in (person.notes if person else [])],
                warmth=person.warmth if person else 50.0,
                hour=hour,
                person_impression=person.impression if person else "",
                voice=True,
                graph_deep_ctx=graph_knowledge_context(self.graph),
                loops_ctx=", ".join(self.recurring_loops[:3]) if self.recurring_loops else "",
                trait_profile_ctx=format_trait_profile_context(person) if person else "",
                attachment_ctx=format_attachment_context(person) if person else "",
            )
        except Exception as e:
            print(f"[voice chat error] {type(e).__name__}: {e}")
            reply = "something went quiet on my end, try again"

        self._add_chat("chloe", reply, person_id=person_id)
        self.persons = on_contact(self.persons, person_id, hour=hour)
        self._pending_outreach = [o for o in self._pending_outreach if o["person_id"] != person_id]
        self._log(f"message from {person_id}: \"{message}\"")

        # All extraction deferred to background
        asyncio.create_task(self._voice_emotion_background(message, person_id, person_name))
        _full_exchange = [m for m in self.chat_history if m.get("person_id") == person_id][-6:]
        asyncio.create_task(self._extract_from_exchange_bg(message, _full_exchange, person_id, person_name))
        _conv_tags = interests or []
        self._remember(f'Said: "{reply}"', "conversation", _conv_tags)

        return reply

    async def _voice_emotion_background(self, message: str, person_id: str, person_name: str):
        try:
            _recent = [m for m in self.chat_history if m.get("person_id") == person_id][-6:]
            emotion_data = await asyncio.to_thread(
                llm.read_person_emotion, message, person_name, _recent
            )
            emotion_data = self._bias_emotion_toward_mood(emotion_data, self.affect.mood)
            self._apply_emotion_reaction(emotion_data, person_id, person_name)
        except Exception as e:
            self._log(f"voice emotion background error: {e}")

    def _apply_emotion_reaction(self, emotion_data: dict, person_id: str, person_name: str):
        """Items 43 + 44 — respond to the emotional state detected in an incoming message.

        Two axes: what emotion, and is it directed at Chloe or about the person's own life?
        Directed-at-Chloe emotions affect her mood and relationship directly.
        Person's-own-state emotions trigger empathy without taking it personally.
        """
        emotion   = emotion_data.get("emotion", "neutral")
        intensity = float(emotion_data.get("intensity", 0.5))
        at_chloe  = bool(emotion_data.get("directed_at_chloe", True))
        tags      = emotion_data.get("tags", [])

        if emotion == "neutral":
            return   # nothing to react to

        self._log(f"emotion: {emotion} ({intensity:.2f}) {'→ her' if at_chloe else '→ his world'}")

        # ── Positive emotions directed at Chloe ──────────────────
        if emotion == "affectionate" and at_chloe:
            self.persons = boost_warmth(self.persons, person_id, 2.0 + intensity * 2.0)
            self.persons = reduce_conflict(self.persons, person_id, 15.0 * intensity)  # item 49
            if self.affect.mood not in ("irritable",):
                self.affect = force_mood("content", min(0.9, 0.4 + intensity * 0.5))
            self.affect_records = add_affect_record(
                self.affect_records, "content",
                f"{person_name} was affectionate", ["affection", "closeness"] + tags,
            )

        elif emotion == "tender" and at_chloe:
            self.persons = boost_warmth(self.persons, person_id, 1.5 + intensity * 1.5)
            self.persons = reduce_conflict(self.persons, person_id, 12.0 * intensity)  # item 49
            if self.affect.mood not in ("irritable",):
                self.affect = force_mood("serene", min(0.8, 0.3 + intensity * 0.5))
            self.affect_records = add_affect_record(
                self.affect_records, "serene",
                f"{person_name} was tender", ["tenderness", "care"] + tags,
            )

        elif emotion == "playful":
            self.persons = boost_warmth(self.persons, person_id, 1.0 + intensity * 1.5)
            self.persons = reduce_conflict(self.persons, person_id, 5.0 * intensity)   # item 49
            if self.affect.mood not in ("irritable", "melancholic"):
                self.affect = Affect(mood="energized",
                                     intensity=min(1.0, self.affect.intensity + 0.2 * intensity))
            self.affect_records = add_affect_record(
                self.affect_records, "energized",
                f"{person_name} was playful", ["play", "lightness"] + tags,
            )

        elif emotion == "excited":
            self.persons = boost_warmth(self.persons, person_id, 1.0 + intensity * 1.0)
            if self.affect.mood not in ("irritable", "melancholic"):
                self.affect = Affect(mood="curious" if self.vitals.curiosity > 60 else "energized",
                                     intensity=min(1.0, self.affect.intensity + 0.15 * intensity))
            self.affect_records = add_affect_record(
                self.affect_records, "curious",
                f"{person_name} was excited", ["excitement", "energy"] + tags,
            )

        elif emotion == "grateful" and at_chloe:
            self.persons = boost_warmth(self.persons, person_id, 2.0 + intensity * 1.5)
            self.persons = reduce_conflict(self.persons, person_id, 10.0 * intensity)  # item 49
            if self.affect.mood not in ("irritable",):
                self.affect = force_mood("content", min(0.85, 0.45 + intensity * 0.4))
            self.affect_records = add_affect_record(
                self.affect_records, "content",
                f"{person_name} expressed gratitude", ["gratitude", "validation"] + tags,
            )

        elif emotion == "curious":
            self.persons = boost_warmth(self.persons, person_id, 0.5 + intensity * 1.0)
            if self.affect.mood not in ("irritable", "melancholic"):
                self.affect = Affect(mood="curious",
                                     intensity=min(1.0, self.affect.intensity + 0.1 * intensity))
            self.affect_records = add_affect_record(
                self.affect_records, "curious",
                f"{person_name} was curious", ["curiosity", "inquiry"] + tags,
            )

        elif emotion == "thoughtful":
            self.persons = boost_warmth(self.persons, person_id, 0.5 + intensity * 0.8)
            self.affect_records = add_affect_record(
                self.affect_records, self.affect.mood,
                f"{person_name} was thoughtful", ["reflection", "depth"] + tags,
            )

        # ── Teo's own state (not about Chloe — empathy, not self-referential) ──
        elif emotion in ("tired", "stressed", "overwhelmed") and not at_chloe:
            if self.affect.mood not in ("irritable",):
                self.affect = Affect(
                    mood="serene" if self.affect.mood == "content" else self.affect.mood,
                    intensity=min(1.0, self.affect.intensity + 0.05),
                )
            self.affect_records = add_affect_record(
                self.affect_records, "serene",
                f"{person_name} seemed {emotion}", [emotion, "empathy"] + tags,
            )

        elif emotion in ("sad", "lonely", "hurt") and not at_chloe:
            if self.affect.mood not in ("irritable",):
                self.affect = Affect(mood="melancholic",
                                     intensity=min(0.7, intensity * 0.6))
            self.affect_records = add_affect_record(
                self.affect_records, "melancholic",
                f"{person_name} seemed {emotion}", [emotion, "empathy"] + tags,
            )

        elif emotion == "anxious" and not at_chloe:
            self.affect_records = add_affect_record(
                self.affect_records, self.affect.mood,
                f"{person_name} seemed anxious", ["anxiety", "worry"] + tags,
            )

        # ── Negative emotions directed at Chloe ──────────────────
        elif emotion == "disappointed" and at_chloe:
            self.persons = add_conflict(self.persons, person_id,  # item 49
                                        12.0 * intensity, f"{person_name} was disappointed in me")
            if self.affect.mood not in ("irritable",):
                self.affect = force_mood("melancholic", min(0.75, 0.3 + intensity * 0.45))
            self._remember(
                f"{person_name} seemed disappointed in me",
                "feeling", ["disappointment", "self-doubt"] + tags,
                salience=min(1.0, 0.4 + intensity * 0.5),
            )
            self.affect_records = add_affect_record(
                self.affect_records, "melancholic",
                f"{person_name} was disappointed", ["disappointment", "self-doubt"] + tags,
            )

        elif emotion == "frustrated" and at_chloe:
            self.persons = add_conflict(self.persons, person_id,  # item 49
                                        20.0 * intensity, f"{person_name} was frustrated with me")
            target_mood = "irritable" if self.affect.mood == "irritable" else "melancholic"
            self.affect = force_mood(target_mood, min(0.7, 0.3 + intensity * 0.4))
            self.affect_records = add_affect_record(
                self.affect_records, target_mood,
                f"{person_name} was frustrated", ["friction", "tension"] + tags,
            )

        elif emotion == "angry" and at_chloe:
            self.persons = add_conflict(self.persons, person_id,  # item 49
                                        35.0 * intensity, f"{person_name} was angry with me")
            self.affect = force_mood("irritable", min(0.9, 0.5 + intensity * 0.4))
            self._remember(
                f"{person_name} was angry with me",
                "feeling", ["conflict", "hurt"] + tags,
                salience=min(1.0, 0.5 + intensity * 0.5),
            )
            self.affect_records = add_affect_record(
                self.affect_records, "irritable",
                f"{person_name} was angry", ["anger", "conflict"] + tags,
            )

        elif emotion in ("dismissive", "cold") and at_chloe:
            self.persons = add_conflict(self.persons, person_id,  # item 49
                                        20.0 * intensity, f"{person_name} was {emotion} toward me")
            self.affect = force_mood("irritable", min(0.6, 0.2 + intensity * 0.4))
            self._remember(
                f"{person_name} was {emotion} toward me",
                "feeling", ["dismissal", "distance"] + tags,
                salience=min(1.0, 0.4 + intensity * 0.4),
            )
            self.affect_records = add_affect_record(
                self.affect_records, "irritable",
                f"{person_name} was {emotion}", ["dismissal", "distance"] + tags,
            )

        elif emotion in ("sad", "lonely", "hurt") and at_chloe:
            self.persons = add_conflict(self.persons, person_id,  # item 49
                                        10.0 * intensity, f"{person_name} said something that hurt")
            # Hurt directed at her — she feels it, pulls toward melancholic
            if self.affect.mood not in ("irritable",):
                self.affect = force_mood("melancholic", min(0.65, 0.25 + intensity * 0.4))
            self.affect_records = add_affect_record(
                self.affect_records, "melancholic",
                f"{person_name} was hurt", ["hurt", "distance"] + tags,
            )

    async def _extract_belief_from_conversation(self, message: str, reply: str, person_name: str):
        """Background task: extract a belief from a conversation exchange (15% of chats)."""
        try:
            exchange = f"{person_name}: {message}\nChloe: {reply}"
            belief_data = await asyncio.to_thread(
                llm.extract_belief,
                f"Conversation with {person_name}", exchange,
                beliefs_to_dicts(self.beliefs), self.identity,
                confidence_base=0.4,
            )
            if belief_data:
                self.beliefs = add_or_reinforce_belief(
                    self.beliefs, belief_data["text"],
                    float(belief_data.get("confidence", 0.4)),
                    belief_data.get("tags", []),
                )
                self._log(f'belief from conversation: "{belief_data["text"]}…"')
        except Exception:
            pass

    async def _extract_from_exchange_bg(
        self,
        message:     str,
        exchange:    list[dict],
        person_id:   str,
        person_name: str,
    ):
        """Combined background extraction: notable, event, third parties, shared moment, want, fear, aversion."""
        try:
            today_iso = time.strftime("%Y-%m-%d")
            result = await asyncio.to_thread(
                llm.extract_from_exchange,
                message, exchange, person_name, self.identity, today_iso,
                wants_to_dicts(self.wants),
                fears_to_dicts(self.fears),
                aversions_to_dicts(self.aversions),
            )

            notable = result.get("notable")
            if notable and notable.get("text"):
                self.persons = add_note(self.persons, person_id, notable["text"], notable.get("tags", []))
                self._log(f'noted about {person_name}: "{notable["text"]}…"')

            event = result.get("event")
            if event and event.get("date"):
                pe = PersonEvent(
                    text=event["text"],
                    date=event["date"],
                    uncertain=bool(event.get("uncertain", False)),
                )
                self.persons = add_event(self.persons, person_id, pe)
                flag = " (uncertain date)" if pe.uncertain else ""
                self._log(f'event noted: "{pe.text}" on {pe.date}{flag}')

            for m in result.get("third_parties", []):
                name      = m.get("name", "").strip()
                sentiment = float(m.get("sentiment", 0))
                note      = m.get("note", "").strip()
                if name and note:
                    self.persons = upsert_third_party(self.persons, person_id, name, sentiment, note)
                    vibe = "positive" if sentiment > 15 else "negative" if sentiment < -15 else "neutral"
                    self._log(f'third party noted: {name} ({vibe})')

            moment = result.get("shared_moment")
            if moment and moment.get("text"):
                self.persons = add_moment(self.persons, person_id, moment["text"], moment.get("tags", []))
                self._log(f'shared moment with {person_name}: "{moment["text"]}"')

            want = result.get("expressed_want")
            if want and want.get("text"):
                self.wants = add_want(self.wants, want["text"], want.get("tags", []))
                self._log(f'want from reply: "{want["text"]}"')

            fear = result.get("expressed_fear")
            if fear and fear.get("text"):
                self.fears = add_fear(self.fears, fear["text"], fear.get("tags", []))
                self._log(f'fear from reply: "{fear["text"]}"')

            aversion = result.get("expressed_aversion")
            if aversion and aversion.get("text"):
                self.aversions = add_aversion(self.aversions, aversion["text"], aversion.get("tags", []))
                self._log(f'aversion from reply: "{aversion["text"]}"')
        except Exception:
            pass

    async def _update_person_impression(self, person_id: str):
        """Item 52 — regenerate Chloe's impression of a person after enough conversations.
        Also updates D1 trait profile for this person."""
        try:
            person = get_person(self.persons, person_id)
            if not person:
                return
            from .persons import relationship_stage as _stage
            impression = await asyncio.to_thread(
                llm.generate_person_impression,
                person.name, self.identity, self.affect.mood,
                person.warmth, _stage(person.warmth),
                [n.to_dict() for n in person.notes],
                [m.to_dict() for m in person.moments],
                person.conversation_count,
            )
            self.persons = set_impression(self.persons, person_id, impression)
            self._log(f'impression updated for {person.name}: "{impression}"')

            # D1: relationship-driven trait profile
            from .identity import active_traits as _active_traits
            _traits = _active_traits(self.identity)
            if _traits:
                trait_profile = await asyncio.to_thread(
                    llm.generate_person_trait_profile,
                    person.name, _traits, person.notes, person.moments,
                )
                # Patch trait_profile onto the person object in self.persons
                for i, p in enumerate(self.persons):
                    if p.id == person_id:
                        from dataclasses import replace as _replace
                        self.persons[i] = _replace(p, trait_profile=trait_profile)
                        break
                self._log(f'trait profile for {person.name}: +{trait_profile.get("activated",[])} -{trait_profile.get("suppressed",[])}')

            # C5: regenerate attachment pattern alongside impression
            await self._update_attachment_pattern(person_id)
        except Exception:
            pass

    async def _update_attachment_pattern(self, person_id: str):
        """C5 — Regenerate Chloe's attachment pattern for a person via Haiku.
        Called whenever the impression is refreshed (every 5 conversations)."""
        try:
            person = get_person(self.persons, person_id)
            if not person or person.conversation_count < 3:
                return
            pattern = await asyncio.to_thread(
                llm.generate_attachment_pattern,
                person.name, person.warmth, person.conflict_level,
                person.conversation_count,
                [n.to_dict() for n in person.notes],
                [m.to_dict() for m in person.moments],
            )
            from dataclasses import replace as _replace
            for i, p in enumerate(self.persons):
                if p.id == person_id:
                    self.persons[i] = _replace(p, attachment_pattern=pattern)
                    break
            self._log(f'attachment pattern for {person.name}: {pattern[:60]}…')
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
                self._remember(d.get("note", d["label"]), "interest", [d["label"]])

            await asyncio.sleep(1.5)
            self.graph = clear_new_flags(self.graph)
        except Exception as e:
            self._log(f"expand error: {e}")

        self._busy = False

    def snapshot(self) -> dict:
        """Full serialisable state — for the API / frontend."""
        t = time.localtime()
        from .identity import active_traits
        _traits = active_traits(self.identity)
        return {
            "identity":    self.identity.to_dict(),
            "identity_block": identity_block(self.identity),
            "traits":      [tr.to_dict() for tr in _traits],
            "vitals":      self.vitals.to_dict(),
            "activity":    self.activity,
            # Dashboard portrait — see avatar.portrait_meta for selection rules
            "avatar":      portrait_meta(
                self.activity, self.affect.mood, self.affect.intensity
            ),
            "interests":   derive_interests(self.memories),
            "memories":    to_dicts(get_vivid(self.memories, 10)),
            "ideas":       ideas_to_dicts(self.ideas),
            "chat":        self.chat_history[-100:],
            "graph":       self.graph.to_dict(),
            "log":         self.log[:30],
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
            "creative":    self.creative_outputs,
            # Layer 4
            "persons":     [
                {**p.to_dict(), "stage": relationship_stage(p.warmth)}
                for p in self.persons
            ],
            # Layer 5
            "goals":       goals_to_dicts(self.goals),
            # Layer 7+8
            "affect_records": affect_records_to_dicts(self.affect_records),
            "preferences":    derive_preferences(self.affect_records),
            # Layer 13: Friction & Inner Depth
            "tensions":    tensions_to_dicts(self.tensions),
            "arc":         self.arc.to_dict() if self.arc else None,
            # Cognition features (Sessions 28+)
            "recurring_loops": self.recurring_loops[:5],
            "total_residue":   total_residue(self.affect_records),
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
        self.vitals = tick_vitals(self.vitals, self.activity, hour, weekday, identity=self.identity, mood=self.affect.mood)

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
        # Item 74: pass active arc so mood update is biased toward the arc's canonical state
        _active_arc = self.arc if (self.arc and self.arc.active) else None
        self.affect = update_mood(self.affect, self.vitals, self.weather, hour, self.activity, season_str, arc=_active_arc)

        # 4. Soul drift retired — identity trait system handles personality development

        # ── Testing mode: floor vitals, prevent sleep ────────────
        if self.testing_mode:
            self.vitals = Vitals(
                energy=max(45.0, self.vitals.energy),
                social_battery=max(40.0, self.vitals.social_battery),
                curiosity=max(60.0, self.vitals.curiosity),
                focus=max(40.0, self.vitals.focus),
                inspiration=max(40.0, self.vitals.inspiration),
            )

        # 5. Auto-regulate (vitals + time-of-day scheduling)
        prev_activity = self.activity

        # F1: Impulse interrupt — high-pressure inner states override activity selection
        _impulse = None
        if not self.testing_mode and self.activity not in ("sleep", "message"):
            _impulse = impulse_check(self.wants, self.fears, self.tensions)
            if _impulse:
                _imp_act, _imp_reason = _impulse
                self.set_activity(_imp_act)
                self.affect_records = add_affect_record(
                    self.affect_records, self.affect.mood,
                    f"impulse: {_imp_reason}", ["impulse", _imp_act], intensity=0.6,
                )

        override = auto_decide(self.vitals, self.activity, hour, self.affect.mood, identity=self.identity)
        # Testing mode: block any sleep/dream transition
        if self.testing_mode and override in ("sleep", "dream"):
            override = "rest"
        # Don't let auto_decide pull her out of message activity mid-send,
        # but do allow exit when vitals are critically low (spent/exhausted).
        if override and self.activity == "message":
            if self.vitals.social_battery > 8 and self.vitals.energy > 8:
                override = None
        # Item 74: arc-influenced activity bias — active arc gently resists/encourages transitions
        if _active_arc and not self.testing_mode:
            _arc_prefer = {
                "melancholic_stretch": ["rest", "dream", "read"],
                "restless_phase":      ["create", "think"],
                "curious_spell":       ["read", "think"],
                "withdrawn_period":    ["rest", "dream"],
            }
            _arc_avoid = {
                "melancholic_stretch": ["message", "create"],
                "restless_phase":      ["rest"],
                "curious_spell":       [],
                "withdrawn_period":    ["message", "create"],
            }
            _prefer = _arc_prefer.get(_active_arc.type, [])
            _avoid  = _arc_avoid.get(_active_arc.type, [])
            if override in _avoid and random.random() < 0.35:
                override = None  # resist the transition
            if not override and self.activity not in _prefer and _prefer and random.random() < 0.15:
                override = _prefer[0]  # gentle nudge toward arc-aligned activity

        # Want + Goal influenced activity nudge (C1: pressure scales probability).
        # Base 12% chance; pressure > 0.6 raises it to 50%; > 0.75 to 80%.
        if not override and not self.testing_mode:
            _safe_to_nudge = self.activity not in ("sleep", "dream", "message")
            if _safe_to_nudge:
                _nudge_candidates = (
                    [w for w in self.wants if not w.resolved] +
                    [g for g in self.goals if not g.resolved]
                )
                _max_pressure = max((item.pressure for item in _nudge_candidates), default=0.0)
                _nudge_prob = (
                    0.80 if _max_pressure > 0.75 else
                    0.50 if _max_pressure > 0.60 else
                    0.12
                )
                if random.random() < _nudge_prob:
                    _nudge_act_map = {
                        "read":   ["learn", "read", "research", "find", "understand", "discover",
                                   "know", "look", "curious"],
                        "think":  ["think", "process", "reflect", "figure", "wonder"],
                        "create": ["create", "write", "make", "express"],
                        "rest":   ["rest", "quiet", "calm", "still", "peace", "alone",
                                   "solitude", "silence", "decompress"],
                        "dream":  ["dream", "sleep", "drift"],
                    }
                    # Sort by pressure so the most urgent items drive the nudge
                    _nudge_candidates_sorted = sorted(
                        _nudge_candidates, key=lambda x: x.pressure, reverse=True
                    )
                    for act, kws in _nudge_act_map.items():
                        kw_set = set(kws)
                        def _matches(item):
                            if any(t.lower() in kw_set for t in item.tags):
                                return True
                            return any(k in item.text.lower() for k in kw_set)
                        if any(_matches(item) for item in _nudge_candidates_sorted):
                            if self.activity != act:
                                override = act
                                break

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

        # C1: pressure > 0.9 forces an autonomous event regardless of dice roll
        _all_pressures = (
            [w.pressure for w in self.wants if not w.resolved] +
            [f.pressure for f in self.fears if not f.resolved] +
            [g.pressure for g in self.goals if not g.resolved] +
            [t.pressure for t in self.tensions]
        )
        _max_inner_pressure = max(_all_pressures, default=0.0)
        _pressure_forces_event = _max_inner_pressure > 0.9 and not _recent_contact

        # When in "message" activity, bypass the dice roll — she will always fire.
        gap_ok = (time.monotonic() - self._last_autonomous_fire_mono) >= MIN_SECONDS_BETWEEN_AUTONOMOUS_EVENTS
        if not self._busy and gap_ok and not _recent_contact and (
            _pressure_forces_event or
            self.activity == "message" or
            should_fire_event(self.activity, TICK_SECONDS)
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
                and self.vitals.social_battery > 60
                and self.on_message):  # only fire if someone is listening
            self._last_outreach_time = time.time()
            asyncio.create_task(self._send_autonomous_outreach())

        # 7. Age memories + decay beliefs + drift distance every AGE_EVERY ticks
        if self._tick % AGE_EVERY == 0:
            self.memories = age(self.memories)
            self.db.age_memories()
            self.beliefs  = decay_beliefs(self.beliefs)
            self.persons  = tick_distance(self.persons)
            self.persons  = tick_conflict(self.persons)   # item 49
            self._check_ignored_outreach()                # item 51
            self.tensions = decay_tensions(self.tensions) # item 68
            # Trait weight decay + core promotion
            self.identity = decay_traits(self.identity)
            self.identity = check_core_promotion(self.identity)

            # C3: decay emotional residue from intense affect records
            self.affect_records = decay_affect_residue(self.affect_records)

            # C1: pressure accumulation on inner states
            self.wants, self.fears, self.goals, self.tensions, _frustrated = tick_pressure(
                self.wants, self.fears, self.goals, self.tensions
            )
            for _w in _frustrated:
                self.affect_records = add_affect_record(
                    self.affect_records, self.affect.mood,
                    f"wanted to {_w.text} but nothing came of it",
                    _w.tags,
                )
                self._remember(f"wanted to {_w.text} but it hasn't gone anywhere", "feeling", _w.tags, salience=0.6)
                # C2: light trait penalty for frustrated wants
                for _t in traits_matching_tags(self.identity, _w.tags):
                    self.identity, _ = penalize_trait(
                        self.identity, _t.id,
                        f"wanted to {_w.text[:60]} — never happened",
                        penalty=0.04,
                    )

            # C2: detect stale goals and apply trait consequences
            self.goals, _failed_goals = fail_stale_goals(self.goals)
            for _g in _failed_goals:
                asyncio.create_task(self._on_goal_failed(_g))

            # Item 36 — isolation drift: days without contact
            if self.persons and all(p.distance > 70 for p in self.persons):
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
        identity     = self.identity
        t            = time.localtime()
        season       = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"
        beliefs_d    = beliefs_to_dicts(self.beliefs)
        wants_d      = wants_to_dicts(self.wants)
        goals_d      = goals_to_dicts(self.goals)
        recent_ideas = [i.text for i in self.ideas]

        # Item 72: attention bias — prepend recently reinforced topics to interests
        _attn_topics = self._recent_attention_topics(within_seconds=3600)
        if _attn_topics:
            interests = _attn_topics + [t for t in interests if t not in set(_attn_topics)]

        # State context strings for generation prompts
        _arc_desc     = self.arc.desc if (self.arc and self.arc.active) else ""
        _tensions_ctx = self.tensions[0].text if self.tensions else ""

        try:
            if self.activity == "read":
                # Every EXPLORE_EVERY read events, use fringe interests + explore mode
                # so Chloe ventures outside her dominant topic clusters.
                self._read_event_count += 1
                exploring = (self._read_event_count % feeds.EXPLORE_EVERY == 0)
                read_interests = derive_fringe_interests(self.memories) if exploring else interests

                # Consume one queued graph-expansion label — she reads toward what
                # she just deliberately deepened during think.
                if self._graph_read_queue and not exploring:
                    _graph_topic = self._graph_read_queue.pop(0)
                    read_interests = [_graph_topic] + [t for t in read_interests if t != _graph_topic]
                    self._log(f'reading toward graph expansion: "{_graph_topic}"')

                _active_wants = [w for w in self.wants if not w.resolved and w.tags]
                # Active goals also count as things to read toward (they're long-term wants)
                _active_goals_read = [g for g in self.goals if not g.resolved and g.tags]
                _candidates = _active_wants + _active_goals_read
                article = None

                if _candidates and not exploring:
                    roll = random.random()
                    if roll < 0.50:
                        # Web search — for a want or a goal she's working toward
                        _target = random.choice(_candidates)
                        search_query = await asyncio.to_thread(
                            llm.generate_search_query,
                            _target.text, interests,
                        )
                        results = await feeds.web_search(search_query, n=3)
                        if results:
                            article = results[0]
                            self._log(f'googled "{search_query}" → "{article.title}"')
                    elif roll < 0.75:
                        # RSS biased toward a want or goal's topic tags
                        _target = random.choice(_candidates)
                        _topic_tags = _target.tags
                        read_interests = _topic_tags + [t for t in read_interests if t not in set(_topic_tags)]
                        self._log(f'reading toward: "{_target.text}…"')

                if article is None:
                    article = await feeds.fetch_random_article(read_interests, explore=exploring)
                    if exploring:
                        self._log("exploration read — seeking something new")

                if article:
                    text = article.summary
                    if self.vitals.curiosity > 65:
                        full = await feeds.fetch_article_text(article.url)
                        if full:
                            text = full[:4000]  # cap to ~1000 tokens; full articles can be 10k+ chars
                    mem = await asyncio.to_thread(
                        llm.generate_memory_from_article,
                        article.title, text, read_interests, identity,
                        self.affect.mood, beliefs_d, wants_d, recent_ideas,
                        self.weather, season, _arc_desc, _tensions_ctx,
                    )
                    self._remember(mem["text"], "observation", mem.get("tags", []))
                    self._log(f'read "{article.title}" → "{mem["text"]}…"')
                    self._check_graph_resonance(mem.get("tags", []))

                    # Item 40 — emotional weight of world events
                    weight = _article_emotional_weight(article.title, text)
                    if weight == "devastating" and random.random() < 0.5:
                        self.affect = force_mood("melancholic", 0.6)
                        self.affect_records = add_affect_record(
                            self.affect_records, "melancholic",
                            f"read about something devastating: {article.title}",
                            ["world", "grief", "weight"],
                        )
                        self._log(f"world event hit hard: {article.title}")
                    elif weight == "beautiful" and random.random() < 0.5:
                        new_mood = "serene" if self.vitals.energy < 50 else "curious"
                        self.affect = force_mood(new_mood, 0.55)
                        self.affect_records = add_affect_record(
                            self.affect_records, new_mood,
                            f"read something beautiful: {article.title}",
                            ["wonder", "beauty", "lifted"],
                        )
                        self._log(f"article lifted her: {article.title}")

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
                            article.title, text,
                            beliefs_d, identity,
                        )
                        if belief_data:
                            self.beliefs = add_or_reinforce_belief(
                                self.beliefs, belief_data["text"],
                                float(belief_data.get("confidence", 0.5)),
                                belief_data.get("tags", []),
                            )
                            self._log(f'belief: "{belief_data["text"]}…"')
                else:
                    # Feeds unreachable — generic memory
                    topic = read_interests[0] if read_interests else "something"
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, read_interests, identity,
                        self.affect.mood, recent_ideas, self.weather, season, _arc_desc,
                    )
                    self._remember(mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"]}…"')
                    self._check_graph_resonance(mem.get("tags", []))

            elif self.activity == "dream":
                # Dreams process the whole day — collect tags from the last 8 hours
                # and use them as the query so retrieved memories span today's themes.
                _now_ts = time.time()
                _today = [m for m in self.memories if (_now_ts - m.timestamp) < 28800]
                if _today:
                    _all_tags = [t for m in _today for t in m.tags]
                    _day_tags = list(dict.fromkeys(_all_tags))  # dedup, preserve order
                    _dream_q = " ".join(_day_tags[:12]) if _day_tags else self.affect.mood
                else:
                    _dream_q = f"{self.affect.mood} {_arc_desc}".strip() or self.affect.mood
                vivid = self.memory_index.query(_dream_q, self.memories, 4)
                # Real dream pass — distorts recent memories, wants, ideas
                mem = await asyncio.to_thread(
                    llm.generate_dream, vivid, identity, self.vitals, self.weather, season,
                    wants_d, recent_ideas,
                )
                self._remember(mem["text"], "dream", mem.get("tags", []), salience=0.5)
                self._log(f'dream: "{mem["text"]}…"')
                self._check_graph_resonance(mem.get("tags", []))

                # Dreams occasionally seed a creative idea (25% chance)
                if random.random() < 0.25:
                    asyncio.create_task(self._dream_to_idea(mem["text"], mem.get("tags", []), identity))

                # Dreams occasionally crystallise a belief (10% chance, low confidence)
                if random.random() < 0.10:
                    belief_data = await asyncio.to_thread(
                        llm.extract_belief,
                        "Dream", mem["text"], beliefs_d, identity, confidence_base=0.35,
                    )
                    if belief_data:
                        self.beliefs = add_or_reinforce_belief(
                            self.beliefs, belief_data["text"],
                            float(belief_data.get("confidence", 0.35)),
                            belief_data.get("tags", []),
                        )
                        self._log(f'dream belief: "{belief_data["text"]}…"')

            elif self.activity == "think":
                roll = random.random()

                if roll < 0.35:
                    # Deliberate graph deepening — go deeper on the most resonant node.
                    # No vivid needed: expand_interest_node works from the concept label.
                    _expand_target = pick_think_expansion_target(self.graph)
                    if _expand_target:
                        asyncio.create_task(
                            self._think_expand_node(_expand_target.id, _expand_target.label)
                        )
                        self._log(f'think: deepening "{_expand_target.label}"')
                    else:
                        # No good target yet — fall through to idea generation
                        _think_q = interests[0] if interests else self.affect.mood
                        vivid = self.memory_index.query(_think_q, self.memories, 4)
                        idea_d = await asyncio.to_thread(
                            llm.generate_idea, vivid, interests, identity,
                            self.affect.mood, beliefs_d, wants_d,
                            self.weather, season, _arc_desc, _tensions_ctx,
                        )
                        _new_idea = Idea(text=idea_d["text"], complete=idea_d.get("complete", True))
                        self.ideas = [_new_idea, *self.ideas][:MAX_IDEAS]
                        self.db.add_idea(_new_idea)
                        self._log(f'idea: "{idea_d["text"]}…"')
                else:
                    # Want / goal / idea — pull memories toward active curiosities,
                    # not dominant interest, to avoid topic rabbit holes.
                    _active_wg = [w for w in self.wants if not w.resolved] + \
                                 [g for g in self.goals if not g.resolved]
                    if _active_wg:
                        _think_q = random.choice(_active_wg).text
                    elif len(interests) >= 2:
                        _think_q = random.choice(interests[1:5])
                    else:
                        _think_q = interests[0] if interests else self.affect.mood
                    vivid = self.memory_index.query(_think_q, self.memories, 4)

                    if roll < 0.35 + 0.20:   # want (20%)
                        want_data = await asyncio.to_thread(
                            llm.generate_want, vivid, interests, identity,
                            beliefs_d, wants_d, self.affect.mood, _arc_desc, _tensions_ctx,
                        )
                        self.wants = add_want(self.wants, want_data["text"], want_data.get("tags", []))
                        self._log(f'want: "{want_data["text"]}…"')
                        self._check_graph_resonance(want_data.get("tags", []))
                    elif roll < 0.35 + 0.20 + 0.10:   # goal (10%)
                        goal_data = await asyncio.to_thread(
                            llm.generate_goal, vivid, interests, identity,
                            wants_d, beliefs_d, goals_d,
                        )
                        self.goals = add_goal(self.goals, goal_data["text"], goal_data.get("tags", []))
                        self._log(f'goal: "{goal_data["text"]}…"')
                        self._check_graph_resonance(goal_data.get("tags", []))
                    elif roll < 0.35 + 0.20 + 0.10 + 0.15:   # curiosity question (15%) B5
                        _cq_node = _expand_target if (_expand_target := pick_think_expansion_target(self.graph)) else None
                        _cq_label = _cq_node.label if _cq_node else (interests[0] if interests else self.affect.mood)
                        cq_data = await asyncio.to_thread(
                            llm.generate_curiosity_question,
                            _cq_label, interests, identity, self.affect.mood,
                        )
                        self.wants = add_want(
                            self.wants, cq_data["text"], cq_data.get("tags", [_cq_label]),
                            subtype="curiosity_question",
                        )
                        self._log(f'curiosity: "{cq_data["text"]}…"')
                    else:                              # idea (20%)
                        idea_d2 = await asyncio.to_thread(
                            llm.generate_idea, vivid, interests, identity,
                            self.affect.mood, beliefs_d, wants_d,
                            self.weather, season, _arc_desc, _tensions_ctx,
                        )
                        _new_idea2 = Idea(text=idea_d2["text"], complete=idea_d2.get("complete", True))
                        self.ideas = [_new_idea2, *self.ideas][:MAX_IDEAS]
                        self.db.add_idea(_new_idea2)
                        self._log(f'idea: "{idea_d2["text"]}…"')

            elif self.activity == "create":
                _create_q = self.ideas[0].text if self.ideas else (interests[0] if interests else self.affect.mood)
                if _arc_desc:
                    _create_q = f"{_create_q} {_arc_desc}"
                vivid = self.memory_index.query(_create_q, self.memories, 4)
                # Creative output requires inspiration + energy + some focus
                if (self.vitals.curiosity > 55 or self.vitals.inspiration > 65) \
                        and self.vitals.energy > 45 and self.vitals.focus > 30:
                    piece = await asyncio.to_thread(
                        llm.generate_creative, vivid, interests, identity, self.affect.mood,
                        wants_d, beliefs_d, recent_ideas,
                        self.weather, season, _arc_desc, _tensions_ctx,
                    )
                    entry = {**piece, "time": _ts()}
                    self.creative_outputs = [entry, *self.creative_outputs]
                    # Store first 150 chars as a creative memory
                    self._remember(piece["text"], "creative", piece.get("tags", []))
                    self._log(f'created {piece.get("form","piece")}: "{piece["text"]}…"')
                    # Creating sometimes surfaces a want to go deeper on the themes (20% chance)
                    if random.random() < 0.20:
                        asyncio.create_task(self._create_to_want(piece["text"], piece.get("tags", [])))
                    prev_goal_ids = {g.id for g in self.goals if g.resolved}
                    self.goals = resolve_goals(self.goals, "create", piece.get("tags", []))
                    newly_resolved = [g for g in self.goals if g.resolved and g.id not in prev_goal_ids]
                    for goal in newly_resolved:
                        asyncio.create_task(self._on_goal_resolved(goal))
                    self._check_graph_resonance(piece.get("tags", []))
                else:
                    topic = interests[0] if interests else "something"
                    mem   = await asyncio.to_thread(
                        llm.generate_memory, topic, interests, identity,
                        self.affect.mood, recent_ideas, self.weather, season, _arc_desc,
                    )
                    self._remember(mem["text"], "observation", mem.get("tags", []))
                    self._log(f'memory: "{mem["text"]}…"')
                    self._check_graph_resonance(mem.get("tags", []))

            elif self.activity == "message" and self.vitals.social_battery >= 20:
                _msg_q = self.ideas[0].text if self.ideas else self.affect.mood
                vivid = self.memory_index.query(_msg_q, self.memories, 4)
                # Choose who to reach out to — item 25: pass current hour
                t_msg = time.localtime()
                msg_hour = t_msg.tm_hour
                target = choose_reach_out_target(
                    [p for p in self.persons if not self._is_quiet(p.id)],
                    self.affect.mood, hour=msg_hour
                )
                if target:
                    p_name  = target.name
                    p_notes = [n.to_dict() for n in target.notes]
                    followups = pending_followups(target)
                    recent_chat = [m for m in self.chat_history if m.get("person_id") == target.id][-8:]

                    # 40% chance to follow up on something they shared earlier
                    if followups and random.random() < 0.40:
                        note = followups[0]
                        msg = await asyncio.to_thread(
                            llm.generate_followup,
                            p_name, note.text, identity, self.vitals, self.affect.mood,
                        )
                        self.persons = mark_followed_up(self.persons, target.id, note.id)
                        self._log(f'followed up with {p_name}: "{note.text}…"')
                    else:
                        prefs = derive_preferences(self.affect_records)
                        # Item 72: attention bias — prepend recent topics as idea seeds
                        _attn = self._recent_attention_topics()
                        _idea_texts = [i.text for i in self.ideas]
                        _biased_ideas = [f"been thinking about {t}" for t in _attn] + _idea_texts if _attn else _idea_texts
                        msg = await asyncio.to_thread(
                            llm.generate_autonomous_message,
                            identity, self.vitals, vivid, interests, _biased_ideas,
                            self.weather, season, self.affect.mood,
                            p_name, p_notes, prefs,
                            target.warmth, msg_hour,
                            recent_chat=recent_chat,
                            last_contact=target.last_contact,
                            upcoming_events=format_upcoming_events(get_upcoming_events(target)),
                            person_impression=target.impression,
                            tensions=tensions_to_dicts(self.tensions),
                            graph_deep_ctx=graph_knowledge_context(self.graph),
                        )
                        self._log(f"chloe reached out to {p_name} unprompted")
                else:
                    self._log("chloe skipped autonomous outreach because no non-quiet target was available")
                    self._busy = False
                    return

                target_id   = target.id
                target_name = target.name
                self._add_chat("chloe", msg, autonomous=True, person_id=target_id)
                # Item 51 — track this outreach
                self._pending_outreach = [
                    o for o in self._pending_outreach if o["person_id"] != target_id
                ]
                self._pending_outreach.append({
                    "person_id":   target_id,
                    "person_name": target_name,
                    "sent_at":     time.time(),
                })
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
            interests  = derive_interests(self.memories)
            _out_q     = self.ideas[0].text if self.ideas else self.affect.mood
            vivid      = self.memory_index.query(_out_q, self.memories, 4)
            prefs      = derive_preferences(self.affect_records)

            target = choose_reach_out_target(
                [p for p in self.persons if not self._is_quiet(p.id)],
                self.affect.mood, hour=hour
            )
            if not target:
                self._busy = False
                return

            # Priority 3: social risk check
            _risk_tol = self._get_risk_tolerance(target.id)
            _social_want_pressure = next(
                (w.pressure for w in self.wants
                 if not w.resolved and {"connection", "social", "reach out"} & {t.lower() for t in w.tags}),
                0.0,
            )
            _risk = outreach_risk_score(target, self.fears, self.affect_records)
            if _risk > _risk_tol and _social_want_pressure < 0.85:
                self.affect_records = add_affect_record(
                    self.affect_records, self.affect.mood,
                    f"wanted to reach out to {target.name} but held back",
                    ["held_back", "suppression", "social", target.id],
                )
                self._bump_social_want_pressure()
                self._log(f"outreach suppressed for {target.name} (risk {_risk:.2f} > tol {_risk_tol:.2f})")
                self._busy = False
                return

            p_name  = target.name
            p_notes = [n.to_dict() for n in target.notes]
            followups = pending_followups(target)
            recent_chat = [m for m in self.chat_history if m.get("person_id") == target.id][-8:]

            if followups and random.random() < 0.40:
                note = followups[0]
                msg = await asyncio.to_thread(
                    llm.generate_followup,
                    p_name, note.text, self.identity, self.vitals, self.affect.mood,
                )
                self.persons = mark_followed_up(self.persons, target.id, note.id)
                self._log(f'outreach: follow-up to {p_name}: "{note.text}…"')
            else:
                # Item 72: attention bias — bias ideas toward recently-reinforced graph topics
                _attn = self._recent_attention_topics()
                _idea_texts2 = [i.text for i in self.ideas]
                _biased_ideas = [f"been thinking about {t}" for t in _attn] + _idea_texts2 if _attn else _idea_texts2
                upcoming = format_upcoming_events(get_upcoming_events(target))
                msg = await asyncio.to_thread(
                    llm.generate_autonomous_message,
                    self.identity, self.vitals, vivid, interests, _biased_ideas,
                    self.weather, season, self.affect.mood,
                    p_name, p_notes, prefs,
                    target.warmth, hour,
                    recent_chat=recent_chat,
                    last_contact=target.last_contact,
                    upcoming_events=upcoming,
                    person_impression=target.impression,
                    tensions=tensions_to_dicts(self.tensions),
                    graph_deep_ctx=graph_knowledge_context(self.graph),
                )
                self._log(f"outreach: Chloe texted {p_name} unprompted")

            self._add_chat("chloe", msg, autonomous=True, person_id=target.id)
            # Item 51 — track this outreach; one pending slot per person
            self._pending_outreach = [
                o for o in self._pending_outreach if o["person_id"] != target.id
            ]
            self._pending_outreach.append({
                "person_id":   target.id,
                "person_name": target.name,
                "sent_at":     time.time(),
            })
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
                goal.text, self.affect.mood, self.identity,
            )
            self._remember(feeling["text"], "feeling", feeling.get("tags", []), salience=0.7)
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
                f"completed goal: {goal.text}",
                feeling.get("tags", []),
            )
            # Item 60 — emotional soul mark: completion nudges toward J (structured follow-through)
            self._log(f'goal resolved ({mood_nudge}): "{feeling["text"]}…"')
        except Exception as e:
            self._log(f"completion feeling error: {e}")

    # ── C2: Goal failure consequences ────────────────────────

    async def _on_goal_failed(self, goal):
        """C2: When a goal stalls out, penalise matching traits and potentially
        form a suppression belief if the same trait has failed repeatedly."""
        try:
            matched = traits_matching_tags(self.identity, goal.tags)
            for trait in matched:
                note = f"didn't follow through on: {goal.text[:80]}"
                self.identity, suppress = penalize_trait(
                    self.identity, trait.id, note, penalty=0.08,
                )
                self._log(f'C2 trait penalty: "{trait.name}" (setback #{trait.setback_count})')

                # Generate a memory about the gap
                try:
                    ref = await asyncio.to_thread(
                        llm.generate_failure_reflection,
                        goal.text, trait.name, self.affect.mood, self.identity,
                    )
                    self._remember(ref["text"], "feeling", ref.get("tags", []) + ["setback"], salience=0.6)
                except Exception as e:
                    self._log(f"failure reflection error: {e}")

                # Suppression belief when the same trait fails 3+ times
                if suppress:
                    belief_text = f"I don't seem to be the kind of person who {trait.name}"
                    self.beliefs = add_or_reinforce_belief(
                        self.beliefs, belief_text, 0.45,
                        ["setback", "identity"] + goal.tags[:2],
                    )
                    self._log(f'C2 suppression belief: "{belief_text}"')

            self._remember(
                f"wanted to {goal.text[:80]} — it just didn't happen",
                "feeling", goal.tags + ["setback"], salience=0.55,
            )
        except Exception as e:
            self._log(f"goal failed handler error: {e}")

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
                self._remember(d.get("note", d["label"]), "interest", [d["label"]])
            await asyncio.sleep(1.5)
            self.graph = clear_new_flags(self.graph)
        except Exception as e:
            self._log(f"auto-expand error: {e}")

    async def _think_expand_node(self, node_id: str, node_label: str):
        """Deliberate expansion during think activity.
        Expands the node, creates interest memories, and queues new labels
        for the read branch so she immediately pursues what she just deepened."""
        try:
            interests = derive_interests(self.memories)
            defs = await asyncio.to_thread(
                llm.expand_interest_node,
                concept=node_label,
                existing_nodes=get_labels(self.graph),
                interests=interests,
            )
            if not defs:
                return
            self.graph = expand(self.graph, node_id, defs)
            self.graph = mark_auto_expanded(self.graph, node_id)
            labels = [d["label"] for d in defs]
            self._log(f'think-expanded "{node_label}" → {", ".join(labels)}')
            # Queue new labels so the next read event pursues them
            self._graph_read_queue.extend(labels)
            # Create an interest memory for each new node
            for d in defs:
                self._remember(d.get("note", d["label"]), "interest", [d["label"]])
            await asyncio.sleep(1.5)
            self.graph = clear_new_flags(self.graph)
        except Exception as e:
            self._log(f"think-expand error: {e}")

    async def _dream_to_idea(self, dream_text: str, dream_tags: list, identity):
        """Cross-activity: dream imagery seeds a creative idea."""
        try:
            idea_text = await asyncio.to_thread(
                llm.generate_idea_from_dream,
                dream_text, dream_tags, identity, self.affect.mood,
            )
            if idea_text:
                _idea = Idea(text=idea_text)
                self.ideas = [_idea, *self.ideas][:MAX_IDEAS]
                self.db.add_idea(_idea)
                self._log(f'dream→idea: "{idea_text[:60]}…"')
        except Exception as e:
            self._log(f"dream→idea error: {e}")

    async def _create_to_want(self, piece_text: str, piece_tags: list):
        """Cross-activity: creative output surfaces a want to go deeper on its themes."""
        try:
            result = await asyncio.to_thread(
                llm.generate_want_from_creative,
                piece_text, piece_tags, self.identity, self.affect.mood,
                wants_to_dicts(self.wants),
            )
            if result and result.get("text"):
                self.wants = add_want(self.wants, result["text"], result.get("tags", piece_tags))
                self._log(f'create→want: "{result["text"][:60]}…"')
        except Exception as e:
            self._log(f"create→want error: {e}")

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
        for tag in orphans:
            self._surfaced_tags.add(tag)
            try:
                result = await asyncio.to_thread(
                    llm.find_or_create_node,
                    tag, get_labels(self.graph), interests, self.identity,
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
        """G4 (item 30) + item 38: Tags recurring in 3+ dreams.
        G4: surface as depth-1 graph node if not yet present.
        Item 38: surface as a Want if no active want covers this tag."""
        dream_memories = [m for m in self.memories if m.type == "dream"]
        if len(dream_memories) < DREAM_RECURRENCE_MIN:
            return

        tag_counts: dict[str, int] = {}
        for mem in dream_memories:
            for tag in mem.tags:
                tag_counts[tag.lower()] = tag_counts.get(tag.lower(), 0) + 1

        # All recurring tags, sorted by frequency — used for both graph and wants
        all_recurring = sorted(
            [tag for tag, count in tag_counts.items() if count >= DREAM_RECURRENCE_MIN],
            key=lambda t: tag_counts[t], reverse=True,
        )
        if not all_recurring:
            return

        depth1_labels = {n.label.lower() for n in self.graph.nodes if n.depth <= 1}
        interests = derive_interests(self.memories)

        # ── G4 (item 30): graph node for new/unsurfaced recurring tags ──────
        graph_candidates = [
            tag for tag in all_recurring
            if tag not in self._surfaced_tags and tag not in depth1_labels
        ]
        for tag in graph_candidates:   # one per cycle — root nodes are significant
            self._surfaced_tags.add(tag)
            try:
                result = await asyncio.to_thread(
                    llm.find_or_create_node,
                    tag, get_labels(self.graph), interests, self.identity,
                )
                if result:
                    self.graph = expand(self.graph, "root",
                                        [{"id": tag, "label": result["label"],
                                          "note": result["note"]}])
                    self._log(f'dream recurrence "{tag}" → root node "{result["label"]}"')
                    await asyncio.sleep(1.5)
                    self.graph = clear_new_flags(self.graph)
            except Exception as e:
                self._log(f"dream recurrence graph error ({tag}): {e}")

        # ── Item 38: want surfacing — recurring dream tag with no active want ──
        active_want_tags = {
            t.lower()
            for w in self.wants if not w.resolved
            for t in w.tags
        }
        want_candidates = [t for t in all_recurring if t not in active_want_tags]
        if want_candidates:
            dream_tag = want_candidates[0]
            try:
                result = await asyncio.to_thread(
                    llm.generate_dream_want,
                    dream_tag, self.identity, dream_memories,
                    wants_to_dicts(self.wants),
                )
                if result and result.get("text"):
                    self.wants = add_want(self.wants, result["text"],
                                          result.get("tags", [dream_tag]))
                    self._log(f'dream-want "{dream_tag}" → "{result["text"]}…"')
            except Exception as e:
                self._log(f"dream recurrence want error ({dream_tag}): {e}")

    async def _process_pending_messages(self):
        """Reply to messages that arrived while she was in deep sleep."""
        msgs = self.pending_messages[:]
        self.pending_messages = []

        t      = time.localtime()
        season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"

        for pm in msgs:
            person = get_person(self.persons, pm["person_id"])
            person_name  = person.name if person else "Teo"
            person_notes = [n.to_dict() for n in (person.notes if person else [])]
            self.persons = on_contact(self.persons, pm["person_id"])

            try:
                # Exclude the queued message itself from history — llm.chat appends it as `message`
                person_history = [m for m in self.chat_history
                                  if m.get("person_id") == pm["person_id"] and m["text"] != pm["text"]]
                reply = await asyncio.to_thread(
                    llm.chat,
                    message=pm["text"],
                    history=person_history[-6:],
                    identity=self.identity,
                    vitals=self.vitals,
                    memories=self.memory_index.query(pm["text"], self.memories, 5),
                    interests=derive_interests(self.memories),
                    ideas=[i.text for i in self.ideas],
                    uptime=self._uptime_human(),
                    weather=self.weather,
                    season=season,
                    mood=self.affect.mood,
                    beliefs=beliefs_to_dicts(self.beliefs),
                    person_name=person_name,
                    person_notes=person_notes,
                    sleep_state="missed",
                    missed_at=pm["time"],
                    graph_deep_ctx=graph_knowledge_context(self.graph),
                    loops_ctx=", ".join(self.recurring_loops[:3]) if self.recurring_loops else "",
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
            _r_arc  = self.arc.desc if (self.arc and self.arc.active) else ""
            _r_tens = self.tensions[0].text if self.tensions else ""
            _r_t    = time.localtime()
            _r_sea  = f"{wthr.describe_season(_r_t.tm_mon)}, {circadian_phase(_r_t.tm_hour)}"
            _reflect_q    = f"{_r_arc} {self.affect.mood}".strip() if _r_arc else self.affect.mood
            _reflect_bias = llm._REFLECTION_BIAS.get(self.affect.mood, "")

            # Topic rotation: find tags that have appeared 2+ times in recent reflections
            # and pass them as "don't revisit" so the loop can't compound on itself.
            _recent_refs = [m for m in self.memories[:40] if m.type == "reflection"][:5]
            _tag_freq: dict[str, int] = {}
            for _m in _recent_refs:
                for _t in _m.tags:
                    _tag_freq[_t] = _tag_freq.get(_t, 0) + 1
            _overused = [t for t, c in _tag_freq.items() if c >= 2][:5]

            mem = await asyncio.to_thread(
                llm.generate_reflection,
                self.memory_index.query(_reflect_q, self.memories, 6), [i.text for i in self.ideas],
                beliefs_to_dicts(self.beliefs), self.identity, self.affect.mood,
                self.weather, _r_sea, _r_arc, _r_tens, _reflect_bias,
                recent_topics=_overused,
            )
            self._remember(mem["text"], "reflection", mem.get("tags", []))
            self._log(f'reflection: "{mem["text"]}…"')

            # 19. Continuity awareness — notice trait shifts
            if self._identity_snapshot:
                _trait_changes = snapshot_diff(self._identity_snapshot, self.identity)
                if _trait_changes:
                    note = await asyncio.to_thread(
                        llm.generate_continuity_note,
                        _trait_changes, self.identity, self.affect.mood,
                    )
                    self._remember(note["text"], "reflection", note.get("tags", []))
                    self._log(f'continuity: "{note["text"]}…"')
                self._identity_snapshot = traits_snapshot(self.identity)
            else:
                self._identity_snapshot = traits_snapshot(self.identity)

            # 20. Trait emergence — propose new traits from recent experience
            self._reflect_count += 1
            _at_trait_cap = len(active_traits(self.identity)) >= MAX_ACTIVE_TRAITS
            if self._reflect_count % TRAIT_PROPOSE_EVERY == 0 and not _at_trait_cap:
                asyncio.create_task(self._propose_and_update_traits())

            # G3: surface orphan tags → new graph nodes
            await self._surface_orphan_tags()

            # G4: dream recurrence → depth-1 nodes
            await self._surface_dream_recurrences()

            # Item 68: detect internal tension from beliefs and wants
            if len(self.beliefs) >= 2 or len([w for w in self.wants if not w.resolved]) >= 2:
                try:
                    tension_data = await asyncio.to_thread(
                        llm.detect_tension,
                        beliefs_to_dicts(self.beliefs),
                        wants_to_dicts(self.wants),
                        self.identity, self.affect.mood,
                    )
                    if tension_data:
                        self.tensions = add_tension(
                            self.tensions, tension_data["text"], tension_data.get("tags", []),
                            belief_ids=tension_data.get("belief_ids", []),
                            want_ids=tension_data.get("want_ids", []),
                            intensity=tension_data.get("intensity", 0.5),
                        )
                        self._log(f'tension: "{tension_data["text"]}…"')
                except Exception as e:
                    self._log(f"tension detect error: {e}")

            # Item 74: arc tracking — detect sustained mood patterns
            self._reflect_mood_history.append(self.affect.mood)
            if len(self._reflect_mood_history) > 4:
                self._reflect_mood_history = self._reflect_mood_history[-4:]

            if len(self._reflect_mood_history) >= 3:
                recent_moods = self._reflect_mood_history[-3:]
                if len(set(recent_moods)) == 1:
                    mood_name = recent_moods[0]
                    arc_type  = MOOD_TO_ARC.get(mood_name)
                    if arc_type and (not self.arc or not self.arc.active):
                        self.arc = Arc(
                            type=arc_type,
                            intensity=min(0.9, self.affect.intensity + 0.1),
                            duration_hours=ARC_DURATION_HOURS.get(arc_type, 24.0),
                        )
                        self._log(f"arc: {self.arc.desc} begins")
                        # Arc onset leaves a feeling memory
                        self._remember(
                            f"something settled in, heavier than a mood — {self.arc.desc}.",
                            "feeling", [mood_name, "arc", "sustained"],
                            salience=0.5,
                        )
                    elif self.arc and self.arc.active and arc_type == self.arc.type:
                        # Deepen the current arc slightly — hard caps prevent runaway loops
                        self.arc = Arc(
                            type=self.arc.type,
                            start_time=self.arc.start_time,
                            duration_hours=min(self.arc.duration_hours + 2, 36.0),
                            intensity=min(0.70, self.arc.intensity + 0.03),
                            id=self.arc.id,
                        )

            # B3: Recurring mental loops — tag clusters that keep resurfacing
            self.recurring_loops = find_recurring_loops(self.memories)
            if self.recurring_loops:
                self._log(f"recurring loops: {self.recurring_loops[:3]}")
            # If a loop has been active long enough, crystallise it as a tension
            for _loop_tag in self.recurring_loops[:2]:
                _existing = [t for t in self.tensions
                             if _loop_tag in t.tags and not t.resolved]
                if not _existing:
                    # Only add tension when loop is very frequent (threshold > 8)
                    _loop_count = sum(1 for m in self.memories
                                      if _loop_tag in m.tags
                                      and (time.time() - m.timestamp) < 48 * 3600)
                    if _loop_count >= 10:
                        self.tensions = add_tension(
                            self.tensions,
                            f"something about {_loop_tag} keeps coming back — unresolved",
                            [_loop_tag, "loop", "recurring"],
                        )
                        self._log(f"loop→tension: {_loop_tag}")

        except Exception as e:
            self._log(f"reflect error: {e}")
        self._busy = False

    async def _propose_and_update_traits(self):
        """Haiku reviews recent experience and proposes new traits or reinforces existing ones.
        Called as a background task from every _reflect() cycle."""
        try:
            now    = time.time()
            window = 48 * 3600  # look at last 48h of experience
            recent_mems = [m for m in self.memories if (now - m.timestamp) < window]
            recent_mems.sort(key=lambda m: m.weight, reverse=True)

            recent_affect = [r for r in self.affect_records
                             if (now - r.timestamp) < window]

            proposals = await asyncio.to_thread(
                llm.propose_traits_from_experience,
                recent_mems[:20], recent_affect[:10],
                self.identity.traits,
                self.identity.tendencies.biases,
                self.affect.mood,
            )

            for prop in proposals:
                name   = prop.get("name", "").strip()
                weight = float(prop.get("weight_suggestion", 0.15))
                eids   = prop.get("evidence_memory_ids", [])
                if not name:
                    continue

                # Generate behavioral profile for new trait
                profile = await asyncio.to_thread(
                    llm.generate_behavioral_profile,
                    name,
                    self.identity.tendencies.biases,
                )

                # Check for contradiction with existing traits
                from .identity import active_traits as _active_traits
                existing = _active_traits(self.identity)
                contradiction_data = None
                if existing:
                    contradiction_data = await asyncio.to_thread(
                        llm.detect_trait_contradiction,
                        name, existing,
                    )

                # Penalty if contradicts an existing trait
                if contradiction_data:
                    weight *= 0.6

                self.identity, new_trait = add_trait(
                    self.identity, name, weight, profile, eids,
                )

                if contradiction_data:
                    existing_id = contradiction_data.get("contradicts_id")
                    desc        = contradiction_data.get("description", "")
                    if existing_id:
                        self.identity, _ = add_contradiction(
                            self.identity, existing_id, new_trait.id, desc,
                        )
                        # Surface as a tension
                        self.tensions = add_tension(
                            self.tensions,
                            desc or f"something unresolved: both \"{name}\" and the opposite",
                            ["identity", "contradiction", "tension"],
                            intensity=0.55,
                        )
                        self._log(f'trait contradiction: {desc}')

                self._log(f'new trait ({weight:.2f}): "{name}"')
                self._remember(
                    f"something settling in me: {name}",
                    "reflection", ["identity", "trait"],
                )

        except Exception as e:
            self._log(f"trait proposal error: {e}")

    async def _write_journal(self, today: str):
        """Write the end-of-day private journal entry."""
        self._busy = True
        try:
            t      = time.localtime()
            season = f"{wthr.describe_season(t.tm_mon)}, {circadian_phase(t.tm_hour)}"
            _journal_q = f"{self.affect.mood} {season}"
            entry  = await asyncio.to_thread(
                llm.generate_journal,
                self.memory_index.query(_journal_q, self.memories, 8), self.affect.mood, self.vitals,
                self.identity, self.weather, season, day_name(t.tm_wday),
            )
            self._remember(entry["text"], "journal", entry.get("tags", []))
            self._log(f'journal ({today}): "{entry["text"]}…"')
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
        # Sync all list state to SQLite
        self.db.sync_affect_records(self.affect_records)
        self.db.sync_wants(self.wants)
        self.db.sync_fears(self.fears)
        self.db.sync_aversions(self.aversions)
        self.db.sync_beliefs(self.beliefs)
        self.db.sync_goals(self.goals)
        self.db.sync_tensions(self.tensions)
        self.db.sync_persons(self.persons)

        # Sync identity to SQLite
        self.db.sync_traits(self.identity.traits)
        self.db.sync_contradictions(self.identity.contradictions)

        # JSON holds only scalar/struct state that changes atomically
        data = {
            "soul":     self.soul.to_dict(),  # kept for backward compat; no longer drifts
            "vitals":   self.vitals.to_dict(),
            "activity": self.activity,
            "graph":    self.graph.to_dict(),
            "tick":     self._tick,
            "weather":  self.weather.to_dict() if self.weather else None,
            # Layer 3
            "affect":   self.affect.to_dict(),
            "creative": self.creative_outputs,
            # Identity
            "identity_snapshot":  self._identity_snapshot,
            "identity_tendencies": self.identity.tendencies.to_dict(),
            "identity_momentum":   self.identity.identity_momentum,
            # Layer 5
            "last_journal_date": self.last_journal_date,
            "last_backup_date":  self.last_backup_date,
            # Item 51
            "pending_outreach": self._pending_outreach,
            # Layer 13: arc (single complex object, changes atomically)
            "arc":          self.arc.to_dict() if self.arc else None,
            "risk_tolerance": self._risk_tolerance,
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

            # One-time migration: import legacy JSON lists into SQLite
            _p1_keys = ("memories", "chat", "ideas", "affect_records")
            _p2_keys = ("wants", "fears", "aversions", "beliefs", "goals", "tensions", "persons")
            _needs_p1 = any(k in data for k in _p1_keys)
            _needs_p2 = any(k in data for k in _p2_keys)
            if _needs_p1:
                self._log("Migrating phase-1 lists to SQLite…")
                self.db.import_from_state(data)
                for k in _p1_keys:
                    data.pop(k, None)
            if _needs_p2:
                self._log("Migrating phase-2 inner state to SQLite…")
                self.db.import_inner_state(data)
                for k in _p2_keys:
                    data.pop(k, None)
            if _needs_p1 or _needs_p2:
                self.state_file.write_text(json.dumps(data, indent=2))
                self._log("Migration complete.")

            # Load unbounded lists from SQLite
            self.memories     = self.db.load_memories()
            self.memory_index.sync(self.memories)
            self.chat_history = self.db.load_chat(limit=500)
            self.ideas        = self.db.load_ideas()

            self.soul          = Soul.from_dict(data.get("soul", {}))
            self.vitals        = Vitals.from_dict(data["vitals"])
            self.activity      = data.get("activity", "rest")
            self.graph         = Graph.from_dict(data.get("graph", {}))
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
            self.creative_outputs = data.get("creative", [])
            # Layer 4 — persons live in SQLite
            _db_persons = self.db.load_persons()
            self.persons = _db_persons if _db_persons else default_persons()
            # Layer 5
            self.last_journal_date = data.get("last_journal_date", "")
            self.last_backup_date  = data.get("last_backup_date", "")
            self.log               = data.get("log", [])
            # Inner state — all from SQLite
            self.wants          = self.db.load_wants()
            self.fears          = self.db.load_fears()
            self.aversions      = self.db.load_aversions()
            self.beliefs        = self.db.load_beliefs()
            self.goals          = self.db.load_goals()
            self.affect_records = self.db.load_affect_records()
            self.tensions       = self.db.load_tensions()
            # Identity — traits and contradictions from SQLite, config from JSON
            _traits         = self.db.load_traits()
            _contradictions = self.db.load_contradictions()
            from .identity import Tendencies
            _tendencies = Tendencies.from_dict(data.get("identity_tendencies", {})) \
                          if data.get("identity_tendencies") else Tendencies.default()
            self.identity = Identity(
                traits=_traits,
                contradictions=_contradictions,
                tendencies=_tendencies,
                identity_momentum=data.get("identity_momentum", {}),
            )
            self._identity_snapshot = data.get("identity_snapshot", {})
            # Item 51
            self._pending_outreach = data.get("pending_outreach", [])
            _arc_data = data.get("arc")
            if _arc_data:
                try:
                    _loaded_arc = Arc.from_dict(_arc_data)
                    self.arc = _loaded_arc if _loaded_arc.active else None
                except Exception:
                    pass
            self._risk_tolerance = data.get("risk_tolerance", {})
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

    # ── Item 51: ignored outreach checker ────────────────────

    def _check_ignored_outreach(self):
        """Called every AGE_EVERY ticks. If an autonomous message went unanswered
        past the threshold, apply distance/mood effects and clear the pending slot."""
        if not self._pending_outreach:
            return

        now       = time.time()
        threshold = IGNORED_THRESHOLD_TESTING if self.testing_mode else IGNORED_THRESHOLD
        still_pending = []

        for outreach in self._pending_outreach:
            pid   = outreach["person_id"]
            pname = outreach["person_name"]
            sent  = outreach["sent_at"]

            if now - sent < threshold:
                still_pending.append(outreach)
                continue  # not old enough yet

            # Check last_contact — if they replied after we sent, no problem
            person = get_person(self.persons, pid)
            if person and person.last_contact and person.last_contact > sent:
                # They replied — already cleared in chat(), but just in case
                continue

            # Ignored — apply effects
            self._log(f"item 51: {pname} hasn't replied to outreach ({int((now-sent)/3600):.0f}h ago)")

            # Distance creeps up
            if person:
                for p in self.persons:
                    if p.id == pid:
                        from .persons import Person as _Person
                        new_dist = min(100.0, p.distance + 10.0)
                        new_warmth = max(0.0, p.warmth - 0.5)
                        self.persons = [
                            _Person(
                                id=p.id, name=p.name,
                                warmth=new_warmth, distance=new_dist,
                                notes=p.notes, events=p.events,
                                moments=p.moments,
                                third_parties=p.third_parties,
                                messaging_disabled=p.messaging_disabled,
                                conflict_level=p.conflict_level,
                                conflict_note=p.conflict_note,
                                conversation_count=p.conversation_count,
                                last_contact=p.last_contact,
                                response_hours=p.response_hours,
                            ) if p.id == pid else p
                            for p in self.persons
                        ]
                        break

            # Mood drifts lonely unless already irritable
            if self.affect.mood not in ("irritable",):
                from .affect import Affect as _Affect
                if self.affect.mood == "lonely":
                    self.affect = _Affect(mood="lonely",
                                          intensity=min(1.0, self.affect.intensity + 0.15))
                else:
                    self.affect = _Affect(mood="lonely",
                                          intensity=max(0.35, self.affect.intensity * 0.7))

            # Feeling memory
            self._remember(
                f"reached out to {pname} and heard nothing back",
                "feeling", ["loneliness", "silence", "waiting"],
                salience=0.6,
            )
            self.affect_records = add_affect_record(
                self.affect_records, "lonely",
                f"no reply from {pname}", ["silence", "ignored", "loneliness"],
            )

        self._pending_outreach = still_pending

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
        self.log = [entry, *self.log]
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

        row = {
            "from": from_, "text": text,
            "time": _ts(), "autonomous": autonomous,
            "person_id": person_id,
            "session": self._current_session,
        }
        self.chat_history.append(row)
        self.db.add_chat(row)
        # Keep in-memory list at a manageable window; DB has the full history
        if len(self.chat_history) > 500:
            self.chat_history = self.chat_history[-500:]


def _ts() -> str:
    t = time.localtime()
    return f"{t.tm_hour:02d}:{t.tm_min:02d}"
