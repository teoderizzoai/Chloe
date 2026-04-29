# chloe/inner.py
# ─────────────────────────────────────────────────────────────
# Chloe's inner life structures: wants, beliefs, and goals.
#
# Wants  — unresolved curiosities she pursues autonomously.
#          Generated during "think" events. Resolved when
#          something she reads covers the same territory.
#
# Beliefs — positions she holds, lightly.
#           Formed from reading. Confidence decays over time
#           unless reinforced by new material.
#
# Goals  — soft intentions about her own behaviour.
#          "I want to create something this week."
#          Resolved when matching activity fires.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from dataclasses import dataclass, field, asdict

MAX_WANTS          = 8    # max active (unresolved) wants at once
MAX_FEARS          = 8    # max active fears at once
MAX_AVERSIONS      = 8    # max aversions at once
MAX_BELIEFS        = 12   # max beliefs in store
MAX_GOALS          = 6    # max active goals at once
MAX_AFFECT_RECORDS = 60   # rolling log of mood-causing events
MAX_TENSIONS       = 5    # max active internal conflicts at once


# ── WANTS ─────────────────────────────────────────────────────

@dataclass
class Want:
    text:           str
    tags:           list[str] = field(default_factory=list)
    created_at:     float     = field(default_factory=time.time)
    resolved:       bool      = False
    id:             str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pressure:       float     = 0.0   # 0–1, urgency of this unmet want
    pressure_since: float     = 0.0   # timestamp when pressure first hit 0.9 (for frustration residue)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Want":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            resolved=bool(d.get("resolved", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
            pressure=float(d.get("pressure", 0.0)),
            pressure_since=float(d.get("pressure_since", 0.0)),
        )


def add_want(wants: list[Want], text: str, tags: list[str]) -> list[Want]:
    """Add a want unless already at the active limit."""
    active = sum(1 for w in wants if not w.resolved)
    if active >= MAX_WANTS:
        return wants
    return [Want(text=text, tags=tags), *wants]


def resolve_wants(wants: list[Want], new_tags: list[str]) -> list[Want]:
    """Mark wants as resolved when freshly-absorbed content shares their tags."""
    tag_set = {t.lower() for t in new_tags}
    return [
        Want(**{**w.to_dict(), "resolved": True, "pressure": 0.0, "pressure_since": 0.0})
        if (not w.resolved and {t.lower() for t in w.tags} & tag_set)
        else w
        for w in wants
    ]


def wants_to_dicts(wants: list[Want]) -> list[dict]:
    return [w.to_dict() for w in wants]


def wants_from_dicts(data: list[dict]) -> list[Want]:
    return [Want.from_dict(d) for d in data]


# ── FEARS ─────────────────────────────────────────────────────
# Things she dreads, is anxious about, or finds threatening.
# Formed when she articulates fear/dread in conversation or thought.

@dataclass
class Fear:
    text:       str
    tags:       list[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    resolved:   bool      = False   # resolved when she faces or works through it
    id:         str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pressure:   float     = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Fear":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            resolved=bool(d.get("resolved", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
            pressure=float(d.get("pressure", 0.0)),
        )


def add_fear(fears: list[Fear], text: str, tags: list[str]) -> list[Fear]:
    """Add a fear unless already at the active limit."""
    active = sum(1 for f in fears if not f.resolved)
    if active >= MAX_FEARS:
        return fears
    return [Fear(text=text, tags=tags), *fears]


def fears_to_dicts(fears: list[Fear]) -> list[dict]:
    return [f.to_dict() for f in fears]


def fears_from_dicts(data: list[dict]) -> list[Fear]:
    return [Fear.from_dict(d) for d in data]


# ── AVERSIONS ─────────────────────────────────────────────────
# Things she dislikes, hates, or finds repellent.
# Formed when she expresses strong dislike in conversation.

@dataclass
class Aversion:
    text:       str
    tags:       list[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    id:         str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Aversion":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


def add_aversion(aversions: list[Aversion], text: str, tags: list[str]) -> list[Aversion]:
    """Add an aversion unless already at the limit (oldest dropped)."""
    new = [Aversion(text=text, tags=tags), *aversions]
    return new[:MAX_AVERSIONS]


def aversions_to_dicts(aversions: list[Aversion]) -> list[dict]:
    return [a.to_dict() for a in aversions]


def aversions_from_dicts(data: list[dict]) -> list[Aversion]:
    return [Aversion.from_dict(d) for d in data]


# ── BELIEFS ───────────────────────────────────────────────────

@dataclass
class Belief:
    text:         str
    confidence:   float      = 0.55    # 0–1
    tags:         list[str]  = field(default_factory=list)
    created_at:   float      = field(default_factory=time.time)
    last_updated: float      = field(default_factory=time.time)
    id:           str        = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Belief":
        return cls(
            text=d["text"], confidence=float(d.get("confidence", 0.55)),
            tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            last_updated=float(d.get("last_updated", time.time())),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


def add_or_reinforce_belief(
    beliefs: list[Belief], text: str, confidence: float, tags: list[str]
) -> list[Belief]:
    """Add a new belief, or reinforce an existing one if tags overlap enough."""
    tag_set = {t.lower() for t in tags}
    for b in beliefs:
        if len({t.lower() for t in b.tags} & tag_set) >= 2:
            # Reinforce — nudge confidence up slightly
            new_conf = min(0.95, b.confidence + 0.07)
            return [
                Belief(**{**b.to_dict(), "confidence": new_conf, "last_updated": time.time()})
                if bel.id == b.id else bel
                for bel in beliefs
            ]

    # New belief — evict the weakest if at capacity
    store = beliefs
    if len(store) >= MAX_BELIEFS:
        store = sorted(store, key=lambda x: x.confidence, reverse=True)[:MAX_BELIEFS - 1]

    return [Belief(text=text, confidence=confidence, tags=tags), *store]


def decay_beliefs(beliefs: list[Belief]) -> list[Belief]:
    """Confidence erodes slowly — she becomes less certain unless reinforced."""
    return [
        Belief(**{**b.to_dict(), "confidence": max(0.10, b.confidence * 0.998)})
        for b in beliefs
    ]


def beliefs_to_dicts(beliefs: list[Belief]) -> list[dict]:
    return [b.to_dict() for b in beliefs]


def beliefs_from_dicts(data: list[dict]) -> list[Belief]:
    return [Belief.from_dict(d) for d in data]


# ── GOALS ─────────────────────────────────────────────────────

_GOAL_DEFAULT_THRESHOLD = 5   # interactions needed to complete a goal


@dataclass
class Goal:
    """A longer-term ambition — something she works toward over days or a week.
    Not an immediate task: a genuine understanding she wants to reach,
    something she wants to develop or figure out over time.
    Resolves gradually through accumulated related activity (progress → threshold)."""
    text:      str
    tags:      list[str] = field(default_factory=list)
    created_at: float    = field(default_factory=time.time)
    resolved:  bool      = False
    progress:  int       = 0                          # times related content was encountered
    threshold: int       = _GOAL_DEFAULT_THRESHOLD   # progress needed to resolve
    id:        str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pressure:  float     = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            resolved=bool(d.get("resolved", False)),
            progress=int(d.get("progress", 0)),
            threshold=int(d.get("threshold", _GOAL_DEFAULT_THRESHOLD)),
            id=d.get("id", str(uuid.uuid4())[:8]),
            pressure=float(d.get("pressure", 0.0)),
        )


def add_goal(goals: list[Goal], text: str, tags: list[str]) -> list[Goal]:
    """Add a goal unless already at the active limit."""
    active = sum(1 for g in goals if not g.resolved)
    if active >= MAX_GOALS:
        return goals
    return [Goal(text=text, tags=tags), *goals]


def advance_goals(goals: list[Goal], new_tags: list[str]) -> list[Goal]:
    """Advance progress on goals whose tags overlap with new content.
    Goals resolve only when progress reaches their threshold — they take time."""
    tag_set = {t.lower() for t in new_tags}
    result = []
    for g in goals:
        if g.resolved:
            result.append(g)
            continue
        if {t.lower() for t in g.tags} & tag_set:
            new_progress = g.progress + 1
            resolved = new_progress >= g.threshold
            result.append(Goal(**{**g.to_dict(), "progress": new_progress, "resolved": resolved,
                                  "pressure": 0.0 if resolved else g.pressure}))
        else:
            result.append(g)
    return result


# Keep backward compat alias — old call sites pass activity_id which we ignore
def resolve_goals(goals: list[Goal], activity_id: str, new_tags: list[str]) -> list[Goal]:
    return advance_goals(goals, new_tags)


def goals_to_dicts(goals: list[Goal]) -> list[dict]:
    return [g.to_dict() for g in goals]


def goals_from_dicts(data: list[dict]) -> list[Goal]:
    return [Goal.from_dict(d) for d in data]


# ── AFFECT RECORDS ────────────────────────────────────────────
# Item 41 — a rolling log of what caused mood shifts.
# Lets Chloe know her own patterns over time.

@dataclass
class AffectRecord:
    """One entry in the mood history log — what caused a shift."""
    mood:      str
    cause:     str
    tags:      list[str] = field(default_factory=list)
    timestamp: float     = field(default_factory=time.time)
    id:        str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AffectRecord":
        return cls(
            mood=d["mood"], cause=d["cause"],
            tags=d.get("tags", []),
            timestamp=float(d.get("timestamp", time.time())),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


def add_affect_record(
    records: list[AffectRecord], mood: str, cause: str, tags: list[str]
) -> list[AffectRecord]:
    r = AffectRecord(mood=mood, cause=cause, tags=tags)
    return [r, *records]  # no cap — SQLite is unbounded


def affect_records_to_dicts(records: list[AffectRecord]) -> list[dict]:
    return [r.to_dict() for r in records]


def affect_records_from_dicts(data: list[dict]) -> list[AffectRecord]:
    return [AffectRecord.from_dict(d) for d in data]


# ── Item 42: likes and dislikes from affect history ───────────

_POSITIVE_MOODS = frozenset({"serene", "curious", "energized", "content"})
_NEGATIVE_MOODS = frozenset({"melancholic", "irritable", "lonely", "restless"})


def derive_preferences(records: list[AffectRecord], n: int = 5) -> dict:
    """Tally which tags correlate with positive vs negative moods.
    Returns {"lifts": [...top tags...], "drags": [...top tags...]}"""
    if not records:
        return {"lifts": [], "drags": []}

    pos_tally: dict[str, int] = {}
    neg_tally: dict[str, int] = {}

    for r in records[-40:]:   # recent window — preferences can shift over time
        if r.mood in _POSITIVE_MOODS:
            for tag in r.tags:
                pos_tally[tag] = pos_tally.get(tag, 0) + 1
        elif r.mood in _NEGATIVE_MOODS:
            for tag in r.tags:
                neg_tally[tag] = neg_tally.get(tag, 0) + 1

    lifts = sorted(pos_tally, key=pos_tally.__getitem__, reverse=True)[:n]
    drags = sorted(neg_tally, key=neg_tally.__getitem__, reverse=True)[:n]
    return {"lifts": lifts, "drags": drags}


# ── SOCIAL RISK MODEL (Priority 3) ────────────────────────────

def recent_rejection_count(
    person_id: str, records: list[AffectRecord], hours: float = 48.0
) -> int:
    """Count affect records from the last N hours that signal rejection from a specific person."""
    cutoff = time.time() - hours * 3600
    return sum(
        1 for r in records
        if r.timestamp >= cutoff
        and person_id in r.tags
        and any(t in r.tags for t in ("rejection", "ignored", "held_back"))
    )


def active_fear_match(fears: list, target_tags: list[str]) -> float:
    """Return 1.0 if any active fear's tags overlap target_tags, else 0.0."""
    target_set = {t.lower() for t in target_tags}
    for f in fears:
        if not f.resolved and {t.lower() for t in f.tags} & target_set:
            return 1.0
    return 0.0


def outreach_risk_score(person, fears: list, affect_records: list[AffectRecord]) -> float:
    score = 0.0
    score += (person.conflict_level / 100) * 0.4
    score += (100 - person.warmth) / 100 * 0.2
    score += recent_rejection_count(person.id, affect_records, hours=48) * 0.3
    score += active_fear_match(fears, ["rejection", "ignored", "distance"]) * 0.25
    return min(1.0, max(0.0, score))


# ── TENSIONS (Item 68) ────────────────────────────────────────
# Internal conflicts — two beliefs or wants that pull in opposite directions.
# Detected during _reflect(). Max 5 active. Decay if neither side fires.
# Injected into prompts as "you feel torn between X and Y".

@dataclass
class Tension:
    """An unresolved internal conflict — two things that don't sit well together."""
    text:       str
    tags:       list[str] = field(default_factory=list)
    intensity:  float     = 0.5       # 0-1, how sharply it sits with her
    belief_ids: list[str] = field(default_factory=list)
    want_ids:   list[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    last_fired: float     = field(default_factory=time.time)  # last time either side was active
    id:         str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pressure:   float     = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Tension":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            intensity=float(d.get("intensity", 0.5)),
            belief_ids=d.get("belief_ids", []),
            want_ids=d.get("want_ids", []),
            created_at=float(d.get("created_at", time.time())),
            last_fired=float(d.get("last_fired", time.time())),
            id=d.get("id", str(uuid.uuid4())[:8]),
            pressure=float(d.get("pressure", 0.0)),
        )


def add_tension(tensions: list["Tension"], text: str, tags: list[str],
                belief_ids: list[str] = None, want_ids: list[str] = None,
                intensity: float = 0.5) -> list["Tension"]:
    """Add a tension unless a similar one exists (by tag overlap) or at limit."""
    tag_set = {t.lower() for t in tags}
    for t in tensions:
        if len({t2.lower() for t2 in t.tags} & tag_set) >= 2:
            return tensions  # similar tension already tracked
    if len(tensions) >= MAX_TENSIONS:
        # Evict the weakest
        tensions = sorted(tensions, key=lambda t: t.intensity, reverse=True)[:MAX_TENSIONS - 1]
    return [Tension(text=text, tags=tags, intensity=intensity,
                    belief_ids=belief_ids or [], want_ids=want_ids or []), *tensions]


def decay_tensions(tensions: list["Tension"]) -> list["Tension"]:
    """Tensions that haven't fired recently lose intensity and eventually dissolve."""
    now = time.time()
    result = []
    for t in tensions:
        hours_silent = (now - t.last_fired) / 3600
        if hours_silent > 24:
            new_intensity = t.intensity * 0.985
            if new_intensity > 0.08:
                result.append(Tension(**{**t.to_dict(), "intensity": new_intensity}))
            # else: tension resolved itself quietly — drop it
        else:
            result.append(t)
    return result


def tensions_to_dicts(tensions: list["Tension"]) -> list[dict]:
    return [t.to_dict() for t in tensions]


def tensions_from_dicts(data: list[dict]) -> list["Tension"]:
    return [Tension.from_dict(d) for d in data]


# ── ARC (Item 74) ─────────────────────────────────────────────
# A sustained mood pattern — not a single feeling but a stretch of them.
# Set during _reflect() when the same mood appears 3+ consecutive times.
# Influences mood drift weights and activity preference for its duration.

ARC_TYPES = frozenset({"melancholic_stretch", "restless_phase", "curious_spell", "withdrawn_period"})

MOOD_TO_ARC: dict[str, str] = {
    "melancholic": "melancholic_stretch",
    "restless":    "restless_phase",
    "curious":     "curious_spell",
    "lonely":      "withdrawn_period",
}

ARC_DURATION_HOURS: dict[str, float] = {
    "melancholic_stretch": 36.0,
    "restless_phase":      24.0,
    "curious_spell":       20.0,
    "withdrawn_period":    48.0,
}

_ARC_DESCRIPTIONS: dict[str, str] = {
    "melancholic_stretch": "a stretch of heaviness",
    "restless_phase":      "a restless phase",
    "curious_spell":       "a curious spell",
    "withdrawn_period":    "a withdrawn period",
}


@dataclass
class Arc:
    """A sustained mood pattern lasting hours to days."""
    type:           str
    start_time:     float = field(default_factory=time.time)
    duration_hours: float = 24.0
    intensity:      float = 0.5
    id:             str   = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def active(self) -> bool:
        return (time.time() - self.start_time) < (self.duration_hours * 3600)

    @property
    def desc(self) -> str:
        return _ARC_DESCRIPTIONS.get(self.type, self.type.replace("_", " "))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["active"] = self.active
        d["desc"]   = self.desc
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Arc":
        return cls(
            type=d.get("type", "melancholic_stretch"),
            start_time=float(d.get("start_time", time.time())),
            duration_hours=float(d.get("duration_hours", 24.0)),
            intensity=float(d.get("intensity", 0.5)),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


# ── PRESSURE ACCUMULATION ─────────────────────────────────────
# Called every AGE tick (~1 min). Returns updated state plus a list of
# Wants that have just crossed the 24h frustration threshold (pressure ≥ 0.9
# for ≥ 86400 s without resolution) — the caller logs affect_records for these.

_WANT_PRESSURE_RATE    = 0.015   # hits 0.9 in ~60 AGE ticks (~60 min)
_FEAR_PRESSURE_RATE    = 0.008   # hits 0.9 in ~112 ticks (~2 h)
_GOAL_PRESSURE_RATE    = 0.004   # hits 0.9 in ~225 ticks (~3.75 h)
_TENSION_PRESSURE_RATE = 0.010   # hits 0.9 in ~90 ticks (~1.5 h)
_FRUSTRATION_WINDOW    = 86400.0 # 24 h in seconds


def tick_pressure(
    wants:    list[Want],
    fears:    list[Fear],
    goals:    list[Goal],
    tensions: list[Tension],
) -> tuple[list[Want], list[Fear], list[Goal], list[Tension], list[Want]]:
    """Accumulate pressure on all unresolved inner states.
    Returns (wants, fears, goals, tensions, frustrated_wants).
    frustrated_wants are Wants that have been at pressure ≥ 0.9 for 24 h — the
    caller should log an affect_record and a memory for each."""
    now = time.time()
    frustrated: list[Want] = []

    new_wants: list[Want] = []
    for w in wants:
        if w.resolved:
            new_wants.append(w)
            continue
        new_p = min(1.0, w.pressure + _WANT_PRESSURE_RATE)
        # Track when pressure first crosses 0.9
        new_since = w.pressure_since
        if new_p >= 0.9 and w.pressure < 0.9:
            new_since = now
        elif new_p < 0.9:
            new_since = 0.0
        # Detect 24 h frustration
        if new_since > 0.0 and (now - new_since) >= _FRUSTRATION_WINDOW:
            frustrated.append(w)
            new_since = 0.0  # reset so we don't fire repeatedly
        new_wants.append(Want(**{**w.to_dict(), "pressure": new_p, "pressure_since": new_since}))

    new_fears = [
        Fear(**{**f.to_dict(), "pressure": min(1.0, f.pressure + _FEAR_PRESSURE_RATE)})
        if not f.resolved else f
        for f in fears
    ]

    new_goals = [
        Goal(**{**g.to_dict(), "pressure": min(1.0, g.pressure + _GOAL_PRESSURE_RATE)})
        if not g.resolved else g
        for g in goals
    ]

    new_tensions = [
        Tension(**{**t.to_dict(), "pressure": min(1.0, t.pressure + _TENSION_PRESSURE_RATE)})
        for t in tensions
    ]

    return new_wants, new_fears, new_goals, new_tensions, frustrated
