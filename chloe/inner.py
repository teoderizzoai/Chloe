# chloe/inner.py
# ─────────────────────────────────────────────────────────────
# Chloe's inner life structures: wants and beliefs.
#
# Wants  — unresolved curiosities she pursues autonomously.
#          Generated during "think" events. Resolved when
#          something she reads covers the same territory.
#
# Beliefs — positions she holds, lightly.
#           Formed from reading. Confidence decays over time
#           unless reinforced by new material.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from dataclasses import dataclass, field, asdict

MAX_WANTS   = 8    # max active (unresolved) wants at once
MAX_BELIEFS = 12   # max beliefs in store


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
