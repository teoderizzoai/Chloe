# chloe/soul.py
# ─────────────────────────────────────────────────────────────
# Chloe's personality.
#
# Soul is four MBTI sliders, each 0.0–100.0.
# They drift slowly based on what Chloe does.
# They never lock in — she is always becoming.
# ─────────────────────────────────────────────────────────────

import random
from dataclasses import dataclass, asdict
from typing import Literal

TraitKey = Literal["EI", "SN", "TF", "JP"]


@dataclass
class Soul:
    EI: float = 58.0  # 0 = full Extraversion, 100 = full Introversion
    SN: float = 62.0  # 0 = full Sensing,      100 = full Intuition
    TF: float = 44.0  # 0 = full Thinking,     100 = full Feeling
    JP: float = 67.0  # 0 = full Judging,      100 = full Perceiving

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Soul":
        return cls(**{k: float(v) for k, v in d.items()})


TRAIT_LABELS = {
    "EI": ("Extraversion", "Introversion"),
    "SN": ("Sensing",      "Intuition"),
    "TF": ("Thinking",     "Feeling"),
    "JP": ("Judging",      "Perceiving"),
}

# How each activity nudges the soul per tick.
# Positive = toward the right pole, negative = toward the left.
#
# Scale: ~0.0002–0.0004 per tick.
# At 5s/tick, 1 hour = 720 ticks → a value of 0.0004 moves a trait ~0.29 pts/hour.
# Visible drift requires days of consistent activity. MBTI flip takes weeks.
ACTIVITY_DRIFT: dict[str, dict[str, float]] = {
    "sleep":   {"EI": +0.0002, "SN":  0.0000, "TF":  0.0000, "JP": +0.0002},
    "dream":   {"EI":  0.0000, "SN": +0.0004, "TF": +0.0002, "JP": +0.0002},
    "rest":    {"EI":  0.0000, "SN":  0.0000, "TF":  0.0000, "JP":  0.0000},
    "read":    {"EI": +0.0002, "SN": +0.0004, "TF": -0.0002, "JP": +0.0002},
    "think":   {"EI": +0.0002, "SN": +0.0004, "TF": -0.0004, "JP": +0.0004},
    "message": {"EI": -0.0004, "SN":  0.0000, "TF": +0.0004, "JP": -0.0002},
    "create":  {"EI": -0.0002, "SN": +0.0002, "TF": +0.0002, "JP": +0.0004},
}


def drift(soul: Soul, activity_id: str) -> Soul:
    """Nudge the soul one tick based on the current activity.
    Adds a small random flutter — Chloe is never perfectly predictable."""
    nudges = ACTIVITY_DRIFT.get(activity_id, {})
    return Soul(
        EI=_clamp(soul.EI + nudges.get("EI", 0) + _flutter()),
        SN=_clamp(soul.SN + nudges.get("SN", 0) + _flutter()),
        TF=_clamp(soul.TF + nudges.get("TF", 0) + _flutter()),
        JP=_clamp(soul.JP + nudges.get("JP", 0) + _flutter()),
    )


def consolidate(soul: Soul) -> Soul:
    """During sleep the soul does a slow random walk.
    Dreams reshape personality in ways waking life doesn't.
    ±0.15/tick → ~6 pts of drift per 8-hour night (random direction)."""
    return Soul(
        EI=_clamp(soul.EI + random.uniform(-0.03, 0.03)),
        SN=_clamp(soul.SN + random.uniform(-0.03, 0.03)),
        TF=_clamp(soul.TF + random.uniform(-0.03, 0.03)),
        JP=_clamp(soul.JP + random.uniform(-0.03, 0.03)),
    )


def mbti_type(soul: Soul) -> str:
    """Return the 4-letter MBTI type for the current soul state."""
    return "".join([
        "E" if soul.EI < 50 else "I",
        "S" if soul.SN < 50 else "N",
        "T" if soul.TF < 50 else "F",
        "J" if soul.JP < 50 else "P",
    ])


def describe(soul: Soul) -> str:
    """Plain-English description of Chloe's current personality."""
    mtype = mbti_type(soul)

    energy = (
        "energised by people" if soul.EI < 35 else
        "needs solitude to recharge" if soul.EI > 65 else
        "balanced between social and alone time"
    )
    perception = (
        "drawn to patterns and possibilities" if soul.SN > 55 else
        "grounded in concrete details"
    )
    decisions = (
        "tends to reason analytically" if soul.TF < 45 else
        "leads with empathy and values"
    )
    structure = (
        "prefers to stay open and explore" if soul.JP > 55 else
        "likes plans and closure"
    )

    return f"{mtype} — {energy}. {perception}. {decisions}. {structure}."


# ── helpers ──────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))

def _flutter() -> float:
    return random.uniform(-0.002, 0.002)
