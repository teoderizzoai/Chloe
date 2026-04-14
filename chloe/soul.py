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
    "message": {"EI": -0.0060, "SN": -0.0025, "TF": +0.0060, "JP": -0.0030},
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


def content_affect(
    soul: Soul, tags: list[str], current_mood: str = "content"
) -> tuple[str, list[str]] | None:
    """Evaluate whether content resonates with or chafes against this soul.

    Uses the same cluster matching as content_drift, but instead of nudging
    sliders it scores alignment: (cluster_delta × soul_lean).
    Positive = content pushes toward where she already sits → lift.
    Negative = content pushes against her grain → drag.

    Returns (mood, matched_keywords) for an affect record, or None if too weak.
    The keywords are the actual content concepts that triggered the reaction,
    so they accumulate as meaningful likes/dislikes over time.
    """
    if not tags:
        return None

    tag_text = " ".join(t.lower().replace("-", " ").replace("_", " ") for t in tags)

    alignment  = 0.0
    fired_tags: list[str] = []

    for keywords, trait, delta in _CONTENT_CLUSTERS:
        matched_kw = next((kw for kw in keywords if kw in tag_text), None)
        if matched_kw is None:
            continue
        soul_lean  = getattr(soul, trait) - 50.0   # −50 (low pole) → +50 (high pole)
        alignment += delta * soul_lean              # positive = aligned, negative = opposing
        fired_tags.append(matched_kw)

    if not fired_tags:
        return None

    # Threshold 1.5: one cluster with soul_lean > 19 (trait > 69 or < 31) fires it,
    # or two partial matches together. Keeps reactions to genuine leans, not noise.
    if alignment > 1.5:
        mood = current_mood if current_mood in ("serene", "curious", "energized", "content") else "curious"
        return (mood, list(dict.fromkeys(fired_tags))[:4])
    if alignment < -1.5:
        mood = current_mood if current_mood in ("melancholic", "irritable", "restless", "lonely") else "restless"
        return (mood, list(dict.fromkeys(fired_tags))[:4])

    return None


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


def drift(soul: Soul, activity_id: str, momentum: dict | None = None) -> Soul:
    """Nudge the soul one tick based on the current activity.
    Adds a small random flutter — Chloe is never perfectly predictable.
    If momentum is supplied (item 59), same-direction moves are amplified
    (up to 1.8×) and opposing moves are dampened (down to 0.5×)."""
    nudges = ACTIVITY_DRIFT.get(activity_id, {})

    def _apply(base: float, trait: str) -> float:
        if not momentum or base == 0:
            return base
        m = momentum.get(trait, 0.0)
        if m == 0:
            return base
        if (base > 0) == (m > 0):                    # same direction — amplify
            return base * (1.0 + 0.8 * min(abs(m), 1.0))
        else:                                          # opposing — dampen
            return base * max(0.2, 1.0 - 0.5 * min(abs(m), 1.0))

    return Soul(
        EI=_clamp(soul.EI + _apply(nudges.get("EI", 0), "EI") + _flutter()),
        SN=_clamp(soul.SN + _apply(nudges.get("SN", 0), "SN") + _flutter()),
        TF=_clamp(soul.TF + _apply(nudges.get("TF", 0), "TF") + _flutter()),
        JP=_clamp(soul.JP + _apply(nudges.get("JP", 0), "JP") + _flutter()),
    )


def update_soul_momentum(
    momentum: dict[str, float],
    old_soul: Soul,
    new_soul: Soul,
) -> dict[str, float]:
    """Item 59: Exponential moving average (α=0.015) of per-tick drift direction.
    Saturates at ≈ ±1.0 after ~67 ticks (~5.5 min) of consistent activity.
    Positive = trait has been drifting toward its higher pole recently."""
    alpha = 0.015
    result = {}
    for trait in ("EI", "SN", "TF", "JP"):
        delta     = getattr(new_soul, trait) - getattr(old_soul, trait)
        prev      = momentum.get(trait, 0.0)
        result[trait] = prev + alpha * (delta - prev)
    return result


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


def consolidate(soul: Soul, momentum: dict | None = None) -> Soul:
    """During sleep: random walk biased by recent momentum direction.
    Random component: ±0.03/tick → ~2.3 pts std dev over 8h.
    Momentum bias: up to 0.0004/tick × momentum → ~1.8 pts directional push at full momentum.
    Together: sleep tends to carry forward whatever direction waking life was going."""
    bias = momentum or {}
    return Soul(
        EI=_clamp(soul.EI + random.uniform(-0.03, 0.03) + bias.get("EI", 0.0) * 0.0004),
        SN=_clamp(soul.SN + random.uniform(-0.03, 0.03) + bias.get("SN", 0.0) * 0.0004),
        TF=_clamp(soul.TF + random.uniform(-0.03, 0.03) + bias.get("TF", 0.0) * 0.0004),
        JP=_clamp(soul.JP + random.uniform(-0.03, 0.03) + bias.get("JP", 0.0) * 0.0004),
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
