# chloe/heart.py
# ─────────────────────────────────────────────────────────────
# Chloe's heartbeat — her rhythm of existence.
#
# The heart drives the main async loop.
# BPM is metaphorical: how fast she's "running" internally.
# Vitals gate what she can do and trigger self-regulation.
# ─────────────────────────────────────────────────────────────

import random
from dataclasses import dataclass, asdict, field
from typing import Optional


# ── CIRCADIAN RHYTHM ─────────────────────────────────────────
# Per-tick deltas (energy, social_battery) applied on top of activity effects.
# Indexed by hour 0–23. Negative energy = drains; positive = boosts.
# Values are small by design — the activity system still dominates.

_CIRCADIAN_DELTAS: list[tuple[float, float]] = [
    # hour  energy  social
    (-0.22, -0.12),  # 00 — deep night
    (-0.25, -0.12),  # 01
    (-0.25, -0.12),  # 02
    (-0.25, -0.10),  # 03
    (-0.20, -0.08),  # 04
    (-0.10, -0.05),  # 05 — pre-dawn
    ( 0.00,  0.00),  # 06 — dawn
    ( 0.10,  0.08),  # 07 — morning rise
    ( 0.18,  0.12),  # 08
    ( 0.20,  0.12),  # 09 — morning peak
    ( 0.15,  0.10),  # 10
    ( 0.10,  0.08),  # 11
    ( 0.05,  0.05),  # 12 — noon
    (-0.08, -0.05),  # 13 — post-lunch dip
    (-0.10, -0.05),  # 14
    ( 0.05,  0.05),  # 15 — afternoon lift
    ( 0.10,  0.05),  # 16
    ( 0.05,  0.03),  # 17
    ( 0.00,  0.00),  # 18 — early evening
    (-0.05, -0.05),  # 19
    (-0.10, -0.08),  # 20
    (-0.15, -0.10),  # 21 — wind-down
    (-0.20, -0.12),  # 22
    (-0.22, -0.12),  # 23
]

_CIRCADIAN_PHASES: list[str] = [
    "deep night",    # 00
    "deep night",    # 01
    "deep night",    # 02
    "deep night",    # 03
    "pre-dawn",      # 04
    "pre-dawn",      # 05
    "dawn",          # 06
    "morning rise",  # 07
    "morning",       # 08
    "morning peak",  # 09
    "morning peak",  # 10
    "late morning",  # 11
    "noon",          # 12
    "afternoon dip", # 13
    "afternoon dip", # 14
    "afternoon",     # 15
    "afternoon",     # 16
    "late afternoon",# 17
    "early evening", # 18
    "evening",       # 19
    "evening",       # 20
    "wind-down",     # 21
    "night",         # 22
    "night",         # 23
]


def circadian_delta(hour: int) -> tuple[float, float]:
    """Return (energy_delta, social_delta) per tick for the given hour."""
    return _CIRCADIAN_DELTAS[hour % 24]


def circadian_phase(hour: int) -> str:
    """Human-readable label for the current circadian phase."""
    return _CIRCADIAN_PHASES[hour % 24]


# ── SLEEP SCHEDULE ────────────────────────────────────────────

SLEEP_START = 23   # hour Chloe falls asleep automatically
SLEEP_END   = 7    # hour Chloe wakes automatically


# ── HEARTBEAT STATES ─────────────────────────────────────────

@dataclass(frozen=True)
class HeartbeatState:
    bpm:   int
    label: str
    color: str  # for UI display

HEARTBEAT_STATES: dict[str, HeartbeatState] = {
    "SLEEPING": HeartbeatState(bpm=0,  label="Sleeping",     color="#2a1f3d"),
    "DREAMING": HeartbeatState(bpm=5,  label="Dreaming",     color="#3d2a5a"),
    "RESTING":  HeartbeatState(bpm=12, label="Resting",      color="#1a3a4a"),
    "READING":  HeartbeatState(bpm=18, label="Reading",      color="#1a4a3a"),
    "THINKING": HeartbeatState(bpm=25, label="Thinking",     color="#2a3a1a"),
    "BROWSING": HeartbeatState(bpm=35, label="Browsing Web", color="#3a3a1a"),
    "CHATTING": HeartbeatState(bpm=45, label="Social",       color="#3a2a1a"),
    "EXCITED":  HeartbeatState(bpm=60, label="Excited",      color="#4a1a1a"),
}


# ── ACTIVITIES ───────────────────────────────────────────────

@dataclass(frozen=True)
class Activity:
    id:              str
    label:           str
    icon:            str
    heart_state:     str    # key into HEARTBEAT_STATES
    energy_per_tick: float  # positive = costs energy, negative = recovers
    social_per_tick: float  # positive = costs social battery
    event_chance:    float  # 0.0–1.0 probability of firing an autonomous event
    description:     str

ACTIVITIES: dict[str, Activity] = {
    "sleep": Activity(
        id="sleep", label="Sleep", icon="🌙",
        heart_state="SLEEPING",
        energy_per_tick=-1.5, social_per_tick=-0.8,
        event_chance=0.0,
        description="Chloe is offline. Soul consolidates.",
    ),
    "dream": Activity(
        id="dream", label="Dream", icon="💭",
        heart_state="DREAMING",
        energy_per_tick=-0.5, social_per_tick=-0.3,
        event_chance=0.04,
        description="Semi-conscious. Processing the day.",
    ),
    "rest": Activity(
        id="rest", label="Rest", icon="🛋️",
        heart_state="RESTING",
        energy_per_tick=-0.3, social_per_tick=0.0,
        event_chance=0.01,
        description="Quiet. Watching. Present but still.",
    ),
    "read": Activity(
        id="read", label="Research", icon="🔍",
        heart_state="BROWSING",
        energy_per_tick=0.4, social_per_tick=0.2,
        event_chance=0.08,
        description="Browsing. Absorbing. Interest graph may expand.",
    ),
    "think": Activity(
        id="think", label="Think", icon="🧠",
        heart_state="THINKING",
        energy_per_tick=0.3, social_per_tick=0.1,
        event_chance=0.06,
        description="Deep reflection. Ideas may crystallise.",
    ),
    "message": Activity(
        id="message", label="Message", icon="💬",
        heart_state="CHATTING",
        energy_per_tick=0.6, social_per_tick=0.9,
        event_chance=0.03,
        description="Reaching out. Social battery draining.",
    ),
    "create": Activity(
        id="create", label="Create", icon="✨",
        heart_state="EXCITED",
        energy_per_tick=0.8, social_per_tick=0.4,
        event_chance=0.10,
        description="Generative state. Curiosity at peak.",
    ),
}


# ── VITALS ───────────────────────────────────────────────────

@dataclass
class Vitals:
    energy:         float = 72.0   # 0–100
    social_battery: float = 58.0   # 0–100
    curiosity:      float = 80.0   # 0–100

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Vitals":
        return cls(**{k: float(v) for k, v in d.items()})


def tick_vitals(vitals: Vitals, activity_id: str, hour: int = 12) -> Vitals:
    """Advance vitals one tick based on current activity and time of day."""
    act = ACTIVITIES.get(activity_id)
    if not act:
        return vitals

    circ_e, circ_s = circadian_delta(hour)

    energy         = _clamp(vitals.energy         - act.energy_per_tick  + circ_e)
    social_battery = _clamp(vitals.social_battery - act.social_per_tick  + circ_s)

    # Curiosity decays gently unless Chloe is actively exploring
    curiosity_delta = 0.2 if activity_id in ("read", "create") else -0.05
    curiosity = _clamp(vitals.curiosity + curiosity_delta)

    return Vitals(energy=energy, social_battery=social_battery, curiosity=curiosity)


def auto_decide(vitals: Vitals, current_activity: str) -> Optional[str]:
    """Chloe self-regulates. Returns a new activity id if she should switch,
    or None if she's fine to continue."""
    if vitals.energy < 15:
        return "sleep"                                    # forced sleep
    if vitals.energy < 30 and current_activity == "create":
        return "rest"                                     # wind down
    if vitals.social_battery < 10 and current_activity == "message":
        return "rest"                                     # withdraw
    return None


def should_fire_event(activity_id: str) -> bool:
    """Roll the dice — should an autonomous event fire this tick?"""
    act = ACTIVITIES.get(activity_id)
    return act is not None and random.random() < act.event_chance


def heartbeat_state(activity_id: str) -> HeartbeatState:
    """Return the heartbeat state for a given activity."""
    act = ACTIVITIES.get(activity_id)
    key = act.heart_state if act else "RESTING"
    return HEARTBEAT_STATES[key]


# ── helper ───────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))
