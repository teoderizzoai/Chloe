# chloe/emotions.py
# ─────────────────────────────────────────────────────────────
# Layer 8: Emotional Memory
#
# AffectEntry — a single record of something that moved Chloe's
# emotional state. Logged at meaningful moments (reading, chat,
# creating), not every tick.
#
# Over time the log feeds pattern-derivation: she starts to know
# what tends to lift her, what drains her, what she likes.
# ─────────────────────────────────────────────────────────────

import time
from dataclasses import dataclass, field, asdict

MAX_AFFECT_LOG = 100   # keep last N entries


@dataclass
class AffectEntry:
    trigger:   str          # e.g. "chat:teo", "read:philosophy", "create", "dream"
    tags:      list[str]    # topic tags from the event
    mood:      str          # mood at the time of entry
    valence:   int          # +1 positive, 0 neutral, -1 negative
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AffectEntry":
        return cls(
            trigger=d.get("trigger", ""),
            tags=d.get("tags", []),
            mood=d.get("mood", "content"),
            valence=int(d.get("valence", 0)),
            timestamp=float(d.get("timestamp", time.time())),
        )


def add_affect_entry(
    log:     list[AffectEntry],
    trigger: str,
    tags:    list[str],
    mood:    str,
    valence: int,
) -> list[AffectEntry]:
    """Append a new entry, capped at MAX_AFFECT_LOG."""
    entry = AffectEntry(trigger=trigger, tags=tags, mood=mood, valence=valence)
    return [entry, *log][:MAX_AFFECT_LOG]


def affect_log_to_dicts(log: list[AffectEntry]) -> list[dict]:
    return [e.to_dict() for e in log]


def affect_log_from_dicts(data: list[dict]) -> list[AffectEntry]:
    return [AffectEntry.from_dict(d) for d in data]
