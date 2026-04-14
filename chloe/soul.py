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
# Scale: ~0.001–0.002 per tick.
# At 5s/tick, 1 hour = 720 ticks → a value of 0.002 moves a trait ~1.4 pts/hour.
# Visible drift after a few hours of consistent activity; MBTI flip takes days–weeks.
ACTIVITY_DRIFT: dict[str, dict[str, float]] = {
    "sleep":   {"EI": +0.0010, "SN":  0.0000, "TF":  0.0000, "JP": +0.0010},
    "dream":   {"EI":  0.0000, "SN": +0.0020, "TF": +0.0010, "JP": +0.0010},
    "rest":    {"EI":  0.0000, "SN":  0.0000, "TF":  0.0000, "JP":  0.0000},
    "read":    {"EI": +0.0010, "SN": +0.0020, "TF": -0.0010, "JP": +0.0010},
    "think":   {"EI": +0.0010, "SN": +0.0020, "TF": -0.0020, "JP": +0.0020},
    "message": {"EI": -0.0020, "SN":  0.0000, "TF": +0.0020, "JP": -0.0010},
    "create":  {"EI": -0.0010, "SN": +0.0010, "TF": +0.0010, "JP": +0.0020},
}


# ── CONTENT-AWARE DRIFT (item 31) ────────────────────────────
# Tag keywords that signal a soul dimension. Each matched cluster
# nudges the corresponding trait by ~0.08 pts — small per event,
# meaningful over days of consistent exposure.

_CONTENT_CLUSTERS: list[tuple[list[str], str, float]] = [
    # (keywords, trait, delta)  delta positive = toward right pole
    (["abstract","pattern","possibility","theory","symbolic","conceptual",
      "philosophical","metaphor","systemic","emergent","speculative",
      "meaning","framework","invisible"],          "SN", +0.08),  # → Intuition
    (["concrete","practical","physical","embodied","specific","literal",
      "empirical","data","evidence","tangible","measurable"],      "SN", -0.08),  # → Sensing
    (["vulnerability","emotion","relationship","empathy","personal",
      "grief","love","compassion","identity","belonging","hurt",
      "care","longing","tenderness"],               "TF", +0.08),  # → Feeling
    (["logic","analysis","systematic","rational","objective","structure",
      "mechanism","efficiency","argument","critique","reasoning"],  "TF", -0.08),  # → Thinking
    (["open","explore","curious","discovery","uncertain","fluid",
      "wandering","question","unresolved","ambiguous","wonder"],    "JP", +0.08),  # → Perceiving
    (["resolve","complete","decide","plan","goal","commitment",
      "closure","order","finish","organised","deadline"],           "JP", -0.08),  # → Judging
    (["solitude","introspection","quiet","inner","alone","private",
      "withdrawal","reflection","internal","inward"],               "EI", +0.08),  # → Introversion
    (["social","community","connection","dialogue","collective",
      "shared","together","public","engage","outward"],             "EI", -0.08),  # → Extraversion
]


def content_drift(soul: Soul, tags: list[str]) -> Soul:
    """Nudge soul based on the conceptual content of what was just absorbed.
    Tags are matched against keyword clusters — abstract/philosophical content
    nudges N; emotional/relational content nudges F; etc.
    Cap: ±0.15 per trait per event so no single article hijacks the soul."""
    if not tags:
        return soul

    tag_text = " ".join(t.lower().replace("-", " ").replace("_", " ") for t in tags)
    nudges: dict[str, float] = {"EI": 0.0, "SN": 0.0, "TF": 0.0, "JP": 0.0}

    for keywords, trait, delta in _CONTENT_CLUSTERS:
        if any(kw in tag_text for kw in keywords):
            nudges[trait] += delta

    # Cap each trait nudge — multiple clusters can fire but total is bounded
    capped = {t: max(-0.15, min(0.15, v)) for t, v in nudges.items()}

    return Soul(
        EI=_clamp(soul.EI + capped["EI"] + _flutter()),
        SN=_clamp(soul.SN + capped["SN"] + _flutter()),
        TF=_clamp(soul.TF + capped["TF"] + _flutter()),
        JP=_clamp(soul.JP + capped["JP"] + _flutter()),
    )


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


# ── SEASONAL ACCUMULATION (item 39) ─────────────────────────
# Per-tick nudges that accumulate over weeks and months.
# At 5s/tick running 24/7, these add up to ~2 pts per trait per season.
# The pattern: winter pulls inward/feeling; spring opens up/perceiving;
# summer is extraverted/thinking; autumn turns inward/feeling/judging.
# No flutter — seasonal drift is a slow deterministic tide, not noise.

SEASONAL_DRIFT: dict[int, dict[str, float]] = {
    # month: {EI, SN, TF, JP}
    1:  {"EI": +0.0000016, "SN": +0.0000010, "TF": +0.0000010, "JP": +0.0000008},  # Jan — peak winter: inward, reflective
    2:  {"EI": +0.0000014, "SN": +0.0000006, "TF": +0.0000008, "JP": +0.0000005},  # Feb — late winter
    3:  {"EI": -0.0000008, "SN": +0.0000008, "TF":  0.0000000, "JP": +0.0000010},  # Mar — early spring: opening up
    4:  {"EI": -0.0000012, "SN": +0.0000008, "TF":  0.0000000, "JP": +0.0000012},  # Apr — spring: possibility, spontaneous
    5:  {"EI": -0.0000010, "SN": +0.0000005, "TF":  0.0000000, "JP": +0.0000008},  # May — late spring
    6:  {"EI": -0.0000010, "SN":  0.0000000, "TF": -0.0000006, "JP":  0.0000000},  # Jun — early summer: extraverted, clearer
    7:  {"EI": -0.0000012, "SN":  0.0000000, "TF": -0.0000006, "JP":  0.0000000},  # Jul — peak summer
    8:  {"EI": -0.0000010, "SN":  0.0000000, "TF": -0.0000005, "JP":  0.0000000},  # Aug — late summer
    9:  {"EI": +0.0000008, "SN":  0.0000000, "TF": +0.0000008, "JP": -0.0000008},  # Sep — early autumn: turning in
    10: {"EI": +0.0000010, "SN": +0.0000005, "TF": +0.0000010, "JP": -0.0000010},  # Oct — mid autumn: nostalgic
    11: {"EI": +0.0000012, "SN": +0.0000005, "TF": +0.0000010, "JP": -0.0000006},  # Nov — late autumn: closing up
    12: {"EI": +0.0000014, "SN": +0.0000010, "TF": +0.0000010, "JP": +0.0000005},  # Dec — early winter
}


def seasonal_drift(soul: Soul, month: int) -> Soul:
    """Per-tick seasonal soul accumulation. Accumulates ~2 pts per affected trait
    per 3-month season when running 24/7. Pulls personality toward winter-I/F,
    spring-E/N/P, summer-E/T, autumn-I/F/J. No random flutter — deterministic tide."""
    nudges = SEASONAL_DRIFT.get(month, {})
    if not nudges:
        return soul
    return Soul(
        EI=_clamp(soul.EI + nudges.get("EI", 0.0)),
        SN=_clamp(soul.SN + nudges.get("SN", 0.0)),
        TF=_clamp(soul.TF + nudges.get("TF", 0.0)),
        JP=_clamp(soul.JP + nudges.get("JP", 0.0)),
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
    # Small noise — same order of magnitude as drift so it adds texture
    # without burying the directional signal.
    return random.uniform(-0.0005, 0.0005)
