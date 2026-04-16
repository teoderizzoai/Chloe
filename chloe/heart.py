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
    # Night values are stronger so that resting at night slowly drains energy
    # (makes natural sleep possible without hard clock overrides)
    (-0.45, -0.20),  # 00 — deep night
    (-0.50, -0.20),  # 01
    (-0.50, -0.20),  # 02
    (-0.50, -0.18),  # 03
    (-0.42, -0.15),  # 04
    (-0.25, -0.10),  # 05 — pre-dawn
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
    (-0.08, -0.05),  # 19
    (-0.18, -0.10),  # 20
    (-0.30, -0.15),  # 21 — wind-down begins
    (-0.40, -0.18),  # 22
    (-0.45, -0.20),  # 23
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


# ── DAY-OF-WEEK INFLUENCE ────────────────────────────────────
# Per-tick (energy, social) deltas indexed by weekday: 0=Mon … 6=Sun.
# Values are tiny — they accumulate over the day, not felt tick-by-tick.

_DAY_DELTAS: list[tuple[float, float]] = [
    (-0.03, -0.04),  # 0 Mon — heavy start, socially low
    (-0.01, -0.01),  # 1 Tue — settling in
    ( 0.00,  0.00),  # 2 Wed — neutral midpoint
    ( 0.01,  0.01),  # 3 Thu — building momentum
    ( 0.02,  0.04),  # 4 Fri — lighter, more social
    ( 0.01,  0.02),  # 5 Sat — exploratory, relaxed
    (-0.02,  0.01),  # 6 Sun — quiet, slightly withdrawn
]

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_delta(weekday: int) -> tuple[float, float]:
    """Return (energy_delta, social_delta) per tick for the given weekday (0=Mon)."""
    return _DAY_DELTAS[weekday % 7]


def day_name(weekday: int) -> str:
    """Return the name of the weekday (0=Mon)."""
    return _DAY_NAMES[weekday % 7]


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
        energy_per_tick=-2.0, social_per_tick=-0.8,
        event_chance=0.0,
        description="Chloe is offline. Soul consolidates.",
    ),
    "dream": Activity(
        id="dream", label="Dream", icon="💭",
        heart_state="DREAMING",
        energy_per_tick=-0.8, social_per_tick=-0.3,
        event_chance=0.02,
        description="Semi-conscious. Processing the day.",
    ),
    "rest": Activity(
        id="rest", label="Rest", icon="🛋️",
        heart_state="RESTING",
        energy_per_tick=-0.6, social_per_tick=-0.20,   # rest recovers social battery
        event_chance=0.005,
        description="Quiet. Watching. Present but still.",
    ),
    "read": Activity(
        id="read", label="Research", icon="🔍",
        heart_state="BROWSING",
        energy_per_tick=0.15, social_per_tick=0.05,
        event_chance=0.04,
        description="Browsing. Absorbing. Interest graph may expand.",
    ),
    "think": Activity(
        id="think", label="Think", icon="🧠",
        heart_state="THINKING",
        energy_per_tick=0.10, social_per_tick=0.0,
        event_chance=0.03,
        description="Deep reflection. Ideas may crystallise.",
    ),
    "message": Activity(
        id="message", label="Message", icon="💬",
        heart_state="CHATTING",
        energy_per_tick=0.25, social_per_tick=0.18,    # base; mood + personality adjust further
        event_chance=0.015,
        description="Reaching out. Social battery draining.",
    ),
    "create": Activity(
        id="create", label="Create", icon="✨",
        heart_state="EXCITED",
        energy_per_tick=0.35, social_per_tick=0.10,
        event_chance=0.05,
        description="Generative state. Curiosity at peak.",
    ),
}


# ── MOOD → ACTIVITY AFFINITY ─────────────────────────────────
# Canonical mapping: what activity each mood naturally pulls toward.
# Used by auto_decide for probability weighting; also queryable by
# other systems (e.g. dashboard, LLM prompts) that want to know
# her current mood preference without re-deriving it.

MOOD_ACTIVITY_AFFINITY: dict[str, list[str]] = {
    "restless":    ["create", "think"],   # kinetic — needs to act or process
    "melancholic": ["read",   "dream"],   # inward — quiet absorption or retreat
    "lonely":      ["message"],           # relational — reach toward someone
    "curious":     ["read",   "think"],   # intellectual — explore and absorb
    "energized":   ["create", "read"],    # generative — make or consume
    "serene":      ["rest"],              # still — no pressure to move
    "content":     ["rest",   "think"],   # settled — gentle reflection
    "irritable":   ["think",  "rest"],    # withdrawn — process alone, don't perform
}


# ── SOUL → ACTIVITY AFFINITY (item 58) ──────────────────────
# How well a given activity aligns with current soul traits.
# Returns a probability multiplier (0.5–1.5) applied to soft-drift
# thresholds in auto_decide — higher = more likely to drift toward
# that activity. Hard gates (energy/sleep) are never modulated.
#
# Trait conventions: EI 0=E 100=I, SN 0=S 100=N, TF 0=T 100=F, JP 0=J 100=P

def soul_activity_affinity(soul, activity_id: str) -> float:
    """Return a probability multiplier for drifting toward activity_id.
    Neutral soul (all traits = 50) → 1.0. Strongly aligned → up to 1.5.
    Misaligned → down to 0.5."""
    ei = soul.EI / 100.0   # 0=full E, 1=full I
    sn = soul.SN / 100.0   # 0=full S, 1=full N
    tf = soul.TF / 100.0   # 0=full T, 1=full F
    jp = soul.JP / 100.0   # 0=full J, 1=full P

    if activity_id == "read":
        # N (intuitive) and T (thinking) are drawn to reading
        score = 0.5 * sn + 0.5 * (1.0 - tf)
    elif activity_id == "think":
        # I (introspective) + N (abstract) + T (analytical) → deep internal work
        score = 0.3 * ei + 0.4 * sn + 0.3 * (1.0 - tf)
    elif activity_id == "create":
        # N (imaginative) + P (open-ended) + slight E (expressive output)
        score = 0.4 * sn + 0.4 * jp + 0.2 * (1.0 - ei)
    elif activity_id == "message":
        # E (social energy) + F (relational warmth)
        score = 0.5 * (1.0 - ei) + 0.5 * tf
    elif activity_id == "rest":
        # I (recharges alone) + J (structured stillness)
        score = 0.5 * ei + 0.5 * (1.0 - jp)
    elif activity_id in ("sleep", "dream"):
        # I (withdraws naturally) + F (emotional processing in dreams)
        score = 0.5 * ei + 0.5 * tf
    else:
        return 1.0   # unknown activity — no modulation

    # score is 0.0–1.0 (neutral soul → ~0.5)
    # map to multiplier range 0.5–1.5  (score=0.5 → 1.0 neutral)
    return 0.5 + score * 1.0


# ── VITALS ───────────────────────────────────────────────────

@dataclass
class Vitals:
    energy:         float = 72.0   # 0–100: general capacity, recovers with sleep/rest
    social_battery: float = 65.0   # 0–100: desire for interaction; introverts drain faster, extroverts slower
    curiosity:      float = 80.0   # 0–100: drive to explore and learn
    focus:          float = 70.0   # 0–100: mental clarity; drains from multitasking, builds during quiet
    inspiration:    float = 55.0   # 0–100: creative charge; builds from reading/dreaming, discharges during create

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Vitals":
        # Graceful upgrade: old saves won't have focus/inspiration
        known = {k for k in cls.__dataclass_fields__}
        filtered = {k: float(v) for k, v in d.items() if k in known}
        return cls(**filtered)


# ── Per-activity focus and inspiration deltas (base, before personality) ──
#
# focus:       mental clarity — drains from demanding activities, recovers during quiet
# inspiration: creative charge — builds passively, discharges into create events
#
# Format: {activity_id: (focus_per_tick, inspiration_per_tick)}
# Positive = costs that vital; negative = recovers it.
_ACTIVITY_FOCUS_INSPIRATION: dict[str, tuple[float, float]] = {
    "sleep":   (-0.50, +0.10),   # deep restoration — focus fully rebuilds, slow inspiration seep
    "dream":   (-0.25, -0.45),   # dreaming is primary inspiration source; moderate focus recovery
    "rest":    (-0.30, -0.18),   # quiet rest rebuilds both; inspiration trickles in from observation
    "read":    (+0.06, -0.22),   # reading costs a little focus but charges inspiration strongly
    "think":   (+0.10, -0.08),   # thinking uses focus; can spark small inspiration
    "message": (+0.30, +0.05),   # context-switching drains focus hard; barely adds inspiration
    "create":  (+0.20, +1.40),   # create discharges inspiration; also costs focus (but less than message)
}


_MOOD_SOCIAL_MODIFIER: dict[str, float] = {
    "curious":     0.45,   # engaged — conversation barely costs anything
    "energized":   0.50,   # charged up — barely draining
    "serene":      0.70,   # calm and present
    "content":     0.80,   # comfortable
    "lonely":      0.60,   # talking actually helps when lonely
    "restless":    1.00,   # neutral
    "melancholic": 1.25,   # talking when heavy is tiring
    "irritable":   1.50,   # very draining when already on edge
}


def tick_vitals(vitals: Vitals, activity_id: str, hour: int = 12,
                weekday: int = 2, soul=None, mood: str = "") -> Vitals:
    """Advance vitals one tick based on activity, time of day, day of week, and personality.

    Soul traits shape drain/recovery rates:
    - EI (0=E, 100=I):
        Introverts: messaging drains social more, rest/sleep recovers social more
        Extroverts: messaging barely drains social, but alone-time gives less recovery
    - SN (0=S, 100=N):
        Intuitive (high): curiosity and inspiration build faster from reading/dreaming
        Sensing (low):    more stable curiosity; less jump from abstract content
    - JP (0=J, 100=P):
        Perceiving (high): focus is spiky — drains faster but inspiration spikes higher
        Judging (low):     focus is disciplined — drains slower, rebuilds reliably
    """
    act = ACTIVITIES.get(activity_id)
    if not act:
        return vitals

    circ_e, circ_s = circadian_delta(hour)
    day_e,  day_s  = day_delta(weekday)

    # ── Extract personality scalars ───────────────────────────
    ei  = (soul.EI  / 100.0) if soul else 0.5   # 0=full E, 1=full I
    sn  = (soul.SN  / 100.0) if soul else 0.5   # 0=full S, 1=full N
    jp  = (soul.JP  / 100.0) if soul else 0.5   # 0=full J, 1=full P

    # ── Social battery — personality is the main differentiator ──
    base_social = act.social_per_tick
    if activity_id == "message":
        # Introverts drain much faster talking; extroverts barely feel it
        personality_mult = 0.4 + ei * 1.1
        # Mood modifier: engaged/curious conversations barely drain; irritable ones drain hard
        mood_mult = _MOOD_SOCIAL_MODIFIER.get(mood, 1.0) if mood else 1.0
        act_social = base_social * personality_mult * mood_mult
    elif activity_id in ("rest", "dream", "sleep"):
        # Introverts recharge faster alone; extroverts get slightly less benefit
        # EI=1.0 (full I): extra recovery = -0.18   EI=0.0 (full E): slight drain +0.06
        personality_recovery = -0.18 * ei + 0.06 * (1.0 - ei)
        act_social = base_social + personality_recovery
    else:
        act_social = base_social

    # ── Energy ───────────────────────────────────────────────
    energy = _clamp(vitals.energy - act.energy_per_tick + circ_e + day_e)
    social_battery = _clamp(vitals.social_battery - act_social + circ_s + day_s)

    # ── Curiosity — N types build faster; S types are more stable ──
    if activity_id in ("read", "create"):
        curiosity_delta = 0.18 + sn * 0.14    # N: +0.32/tick, S: +0.18/tick
    elif activity_id == "think":
        curiosity_delta = 0.05 + sn * 0.06
    else:
        curiosity_delta = -0.05 - sn * 0.02   # N types decay slightly faster at rest (restless minds)
    curiosity = _clamp(vitals.curiosity + curiosity_delta)

    # ── Focus — J types are disciplined; P types spiky ─────────
    base_focus_cost, base_insp_delta = _ACTIVITY_FOCUS_INSPIRATION.get(activity_id, (0.0, 0.0))

    if base_focus_cost > 0:
        # Drain: P types focus drains faster (scattered), J types slower (disciplined)
        focus_drain = base_focus_cost * (0.7 + jp * 0.7)    # J: 0.7×, P: 1.4×
    else:
        # Recovery: J types rebuild focus faster during rest
        focus_drain = base_focus_cost * (1.3 - jp * 0.5)    # J: 1.3×, P: 0.8×
    focus = _clamp(vitals.focus - focus_drain)

    # ── Inspiration — N types charge faster; P types spike higher ──
    # Convention matches energy: positive cost = drains, negative cost = recovers.
    # Applied as: new = old - cost  (same as energy and focus)
    if base_insp_delta < 0:
        # Recovery (negative base = inspiration builds): N and P get bigger boosts
        insp_cost = base_insp_delta * (0.8 + sn * 0.5) * (0.85 + jp * 0.35)
    else:
        # Discharge (positive base = inspiration spent): P types spend more freely
        insp_cost = base_insp_delta * (1.0 + jp * 0.3)
    inspiration = _clamp(vitals.inspiration - insp_cost)

    return Vitals(
        energy=energy,
        social_battery=social_battery,
        curiosity=curiosity,
        focus=focus,
        inspiration=inspiration,
    )


def auto_decide(vitals: Vitals, current_activity: str, hour: int = 12,
                mood: str = "", soul=None) -> Optional[str]:
    """Chloe self-regulates. Returns a new activity id if she should switch,
    or None if she's fine to continue.

    Hard gates fire immediately when thresholds are crossed.
    Soft drifts use probability rolls — the longer she stays, the more
    likely she'll shift. Mood colours the direction.
    Soul affinity (item 58) multiplies soft-drift thresholds so that
    the personality increasingly reinforces its own natural pulls.
    """
    e   = vitals.energy
    s   = vitals.social_battery
    c   = vitals.curiosity
    f   = vitals.focus
    ins = vitals.inspiration
    r   = random.random   # shorthand

    # Soul affinity multiplier — applied to soft-drift probability thresholds only.
    # Hard gates and safety-valve exits are never modulated.
    _aff = (lambda act: soul_activity_affinity(soul, act)) if soul else (lambda act: 1.0)

    daytime  = SLEEP_END <= hour < SLEEP_START      # 07:00–23:00
    morning  = SLEEP_END <= hour <= SLEEP_END + 2   # 07:00–09:00
    midday   = 10 <= hour <= 14                     # 10:00–14:00
    afternoon= 14 <= hour <= 19                     # 14:00–19:00
    evening  = 19 <= hour < SLEEP_START             # 19:00–23:00
    in_night = hour >= SLEEP_START or hour < SLEEP_END  # 23:00–07:00

    # ── HARD GATES (immediate, no dice roll) ──────────────────

    # Utterly exhausted → sleep no matter what
    if e < 8:
        return "sleep"

    # Social battery empty → stop messaging immediately
    if s < 8 and current_activity == "message":
        return "rest"

    # Too tired to keep creating
    if e < 22 and current_activity == "create":
        return "rest"

    # Inspiration fully spent → can't create anymore
    if ins < 5 and current_activity == "create":
        return "rest"

    # Completely scattered → can't read or think
    if f < 10 and current_activity in ("read", "think"):
        return "rest"

    # ── NIGHT WINDING-DOWN ────────────────────────────────────

    if in_night:
        if e < 18 and current_activity != "sleep":
            return "sleep"
        if e < 40 and current_activity in ("create", "read", "think", "message"):
            return "dream"
        if e < 55 and current_activity == "rest" and r() < 0.008:
            return "dream"     # drifting off while resting

    # ── WAKING UP ────────────────────────────────────────────

    if morning and current_activity in ("sleep", "dream"):
        if e > 70:
            return "rest"      # fully woken
        if e > 45 and r() < 0.04:
            return "rest"      # groggy but stirring

    # ── SLEEP → DREAM transition (light sleep after deep rest) ──
    if current_activity == "sleep" and e > 55 and daytime and r() < 0.03:
        return "dream"

    # ── DREAM → lighter states ────────────────────────────────
    if current_activity == "dream" and daytime:
        # Restless: can't stay in the dream, too much unresolved energy
        if mood == "restless" and e > 45 and r() < 0.014 * _aff("think"):
            return "think"
        # Lonely: surfaces wanting connection
        if mood == "lonely" and s > 25 and e > 40 and r() < 0.010 * _aff("message"):
            return "message"
        # Curious dream bleeds into wanting to read
        if mood == "curious" and e > 50 and c > 60 and r() < 0.012 * _aff("read"):
            return "read"
        # Default surfacing: rest when rested enough, or read if curious
        if e > 65 and r() < 0.02 * _aff("rest"):
            return "rest"
        if e > 50 and c > 60 and r() < 0.01 * _aff("read"):
            return "read"

    # ── FROM REST ─────────────────────────────────────────────
    if current_activity == "rest" and daytime:
        # ── Mood-driven exits (item 32) ───────────────────────
        # Mood is the primary driver when present; vitals are the fallback.
        if mood == "restless" and e > 35:
            target = "create" if c > 60 else "think"
            if r() < 0.015 * _aff(target):
                return target
        if mood == "melancholic":
            # Read first (quiet absorption); dream if low energy or no pull to act
            if e > 35 and r() < 0.012 * _aff("read"):
                return "read"
            if r() < 0.008 * _aff("dream"):
                return "dream"
        if mood == "lonely" and s > 30 and e > 35:
            if r() < 0.012 * _aff("message"):
                return "message"
        if mood == "curious" and e > 40:
            if r() < 0.012 * _aff("read"):
                return "read"
        if mood == "energized" and e > 55:
            target = "create" if c > 65 else "think"
            if r() < 0.012 * _aff(target):
                return target
        if mood == "irritable" and e > 30:
            if r() < 0.010 * _aff("think"):
                return "think"   # process the friction alone; doesn't want to create or connect
        if mood == "content" and e > 55 and c > 60:
            target = "think" if midday else "read"
            if r() < 0.007 * _aff(target):
                return target    # settled enough to engage gently
        # serene: she's happy resting — no mood-driven push out

        # ── Vitals-driven (fallback when mood has no strong pull) ──
        if e > 60 and c > 75:
            if r() < 0.010 * _aff("read"):
                return "read"
        if e > 50 and c > 65:
            target = "think" if midday else "read"
            if r() < 0.008 * _aff(target):
                return target
        if e > 45 and c > 55:
            if r() < 0.006 * _aff("read"):
                return "read"
        if e > 70 and c > 80 and afternoon:
            if r() < 0.008 * _aff("create"):
                return "create"
        # High inspiration pulls toward creating even outside peak hours
        if ins > 80 and e > 45 and f > 40:
            if r() < 0.012 * _aff("create"):
                return "create"
        # Low focus → prefer passive rest or dream over active reading
        if f < 35 and r() < 0.006:
            return "dream" if (e < 55 or not daytime) else "rest"

    # ── FROM READ ─────────────────────────────────────────────
    if current_activity == "read":
        # Low energy → step back regardless of mood
        if e < 25 and r() < 0.015:
            return "rest"
        # Low curiosity → lost the thread
        if c < 40 and r() < 0.010:
            return "rest"
        # Irritable while reading — can't concentrate, gives up
        if mood == "irritable" and r() < 0.012:
            return "rest"
        # Melancholic while reading — tips into retreat or dream
        if mood == "melancholic" and r() < 0.010:
            return "dream" if (in_night or e < 50) else "rest"
        # Restless while reading — passive absorption isn't enough, needs to make something
        if mood == "restless" and e > 40 and r() < 0.010:
            return "create" if c > 65 else "think"
        # Lonely while reading — article made her want to share or connect
        if mood == "lonely" and s > 30 and e > 35 and r() < 0.008:
            return "message"
        # Curious resistance: if curious and energised, she lingers (lower drift probability)
        if mood == "curious" and e > 50 and c > 65:
            pass   # reduced exit pull — let the vitals rules below handle it at lower prob
        # Absorbed something → move to thinking
        if e > 35 and r() < 0.006 * _aff("think"):
            return "think"
        # Very high curiosity + good energy → creative leap
        if c > 85 and e > 55 and afternoon and r() < 0.005 * _aff("create"):
            return "create"
        # Evening: reading winds into rest or a message
        if evening and e < 55 and r() < 0.006:
            return "rest" if s < 40 else "message"

    # ── FROM THINK ────────────────────────────────────────────
    if current_activity == "think":
        # Tired thinking → rest
        if e < 28 and r() < 0.015:
            return "rest"
        # Restless: thought becomes action
        if mood == "restless" and e > 45 and r() < 0.012 * _aff("create"):
            return "create"
        # Lonely: thinking about someone → reach out
        if mood == "lonely" and s > 25 and e > 35 and r() < 0.012 * _aff("message"):
            return "message"
        # Melancholic: thinking turns to introspection → read or dream
        if mood == "melancholic" and r() < 0.010:
            return "read" if e > 45 else "dream"
        # Irritable: thinking is making it worse — stop, step back
        if mood == "irritable" and r() < 0.010:
            return "rest"
        # Energized: thought crystallised into something to make
        if mood == "energized" and e > 55 and r() < 0.010 * _aff("create"):
            return "create"
        # Serene: thinking flows into gentle curiosity
        if mood == "serene" and c > 60 and r() < 0.007 * _aff("read"):
            return "read"
        # Thought itself into more curiosity → go read
        if c > 70 and e > 40 and r() < 0.007 * _aff("read"):
            return "read"
        # Thought crystallised → create
        if c > 75 and e > 55 and r() < 0.006 * _aff("create"):
            return "create"
        # Low curiosity while thinking → drifting
        if c < 45 and r() < 0.008:
            return "rest" if e < 50 else "read"
        # Evening thinking → wind toward rest
        if evening and e < 50 and r() < 0.007:
            return "rest"

    # ── FROM CREATE ───────────────────────────────────────────
    if current_activity == "create":
        # Energized → hold the momentum
        if mood == "energized" and e > 50:
            pass
        else:
            # Melancholic while creating — forced output feels hollow, retreat
            if mood == "melancholic" and r() < 0.012:
                return "rest"
            # Irritable while creating — can't get into flow, give up
            if mood == "irritable" and r() < 0.012:
                return "rest"
            # Lonely while creating — wants to share something she just made
            if mood == "lonely" and s > 25 and e > 35 and r() < 0.010:
                return "message"
            # Restless: creation itself satisfies — lower drift, but not zero
            if mood == "restless" and e > 40:
                pass   # mild resistance to leaving; let energy/curiosity decide
            # Energy fading → rest
            if e < 40 and r() < 0.010:
                return "rest"
            # Finished burst — content or energized → want to share
            if e > 45 and s > 35 and mood in ("content", "energized", "lonely") and r() < 0.006 * _aff("message"):
                return "message"
            # Process what was created
            if e > 40 and c > 60 and r() < 0.005 * _aff("think"):
                return "think"
            # Curiosity spent by output → rest
            if c < 50 and r() < 0.008:
                return "rest"

    # ── FROM MESSAGE ──────────────────────────────────────────
    if current_activity == "message":
        # Drained social battery → retreat immediately
        if s < 20 and r() < 0.015:
            return "rest"
        # Irritable: conversation has worn thin, needs space
        if mood == "irritable" and r() < 0.012:
            return "rest"
        # Melancholic: talking didn't fill the void, retreats inward
        if mood == "melancholic" and r() < 0.010:
            return "dream" if e < 50 else "rest"
        # Lonely + social drained: talking didn't help — step back
        if mood == "lonely" and s < 35 and r() < 0.008:
            return "rest"
        # Conversation sparked curiosity → go read or think
        if c > 70 and e > 40:
            target = "read" if c > 80 else "think"
            if r() < 0.008 * _aff(target):
                return target
        # Content/serene after connecting → settle into rest or think
        if mood in ("content", "serene") and r() < 0.006:
            return "rest" if e < 55 else "think"
        # Energized after connection — wants to make something
        if mood == "energized" and e > 50 and r() < 0.006 * _aff("create"):
            return "create"
        # Evening messaging naturally winds down
        if evening and s < 45 and r() < 0.008:
            return "rest"

    return None


def should_fire_event(activity_id: str, tick_seconds: float = 5.0) -> bool:
    """Roll the dice — should an autonomous event fire this tick?

    event_chance values are calibrated for 5-second ticks.
    Pass the actual tick_seconds so the wall-clock frequency stays
    consistent regardless of how fast the heartbeat runs.
    """
    act = ACTIVITIES.get(activity_id)
    if act is None:
        return False
    # scale: with longer ticks, raise the per-tick probability proportionally
    adjusted = act.event_chance * (tick_seconds / 5.0)
    return random.random() < min(adjusted, 0.95)


def heartbeat_state(activity_id: str) -> HeartbeatState:
    """Return the heartbeat state for a given activity."""
    act = ACTIVITIES.get(activity_id)
    key = act.heart_state if act else "RESTING"
    return HEARTBEAT_STATES[key]


# ── helper ───────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))
