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
MAX_BELIEFS        = 12   # max beliefs in store
MAX_GOALS          = 6    # max active goals at once
MAX_AFFECT_RECORDS = 60   # rolling log of mood-causing events


# ── WANTS ─────────────────────────────────────────────────────

@dataclass
class Want:
    text:       str
    tags:       list[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    resolved:   bool      = False
    id:         str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Want":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            resolved=bool(d.get("resolved", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
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
        Want(**{**w.to_dict(), "resolved": True})
        if (not w.resolved and {t.lower() for t in w.tags} & tag_set)
        else w
        for w in wants
    ]


def wants_to_dicts(wants: list[Want]) -> list[dict]:
    return [w.to_dict() for w in wants]


def wants_from_dicts(data: list[dict]) -> list[Want]:
    return [Want.from_dict(d) for d in data]


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

@dataclass
class Goal:
    """A soft intention about her own behaviour — something she means to do."""
    text:       str
    tags:       list[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    resolved:   bool      = False
    id:         str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            created_at=float(d.get("created_at", time.time())),
            resolved=bool(d.get("resolved", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


def add_goal(goals: list[Goal], text: str, tags: list[str]) -> list[Goal]:
    """Add a goal unless already at the active limit."""
    active = sum(1 for g in goals if not g.resolved)
    if active >= MAX_GOALS:
        return goals
    return [Goal(text=text, tags=tags), *goals]


def resolve_goals(goals: list[Goal], activity_id: str, new_tags: list[str]) -> list[Goal]:
    """Mark goals as resolved when the activity or tags match."""
    tag_set = {t.lower() for t in new_tags}
    result = []
    for g in goals:
        if g.resolved:
            result.append(g)
            continue
        goal_tags = {t.lower() for t in g.tags}
        # Resolve if activity matches any tag, or tag overlap ≥ 1
        activity_match = activity_id in goal_tags
        tag_match = bool(goal_tags & tag_set)
        if activity_match or tag_match:
            result.append(Goal(**{**g.to_dict(), "resolved": True}))
        else:
            result.append(g)
    return result


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
    return [r, *records][:MAX_AFFECT_RECORDS]


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
