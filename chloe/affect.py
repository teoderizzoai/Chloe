# chloe/affect.py
# ─────────────────────────────────────────────────────────────
# Chloe's affect layer — mood as a state separate from vitals.
#
# Vitals are continuous flows (energy, social, curiosity).
# Mood is a qualitative colour: how all of it feels right now.
# It's sticky — it doesn't flip every tick, it drifts.
# ─────────────────────────────────────────────────────────────

import random
from dataclasses import dataclass


MOODS: dict[str, dict] = {
    "content":    {"color": "#4a7a5a", "desc": "settled, quietly there"},
    "restless":   {"color": "#8a7a3e", "desc": "seeking, not yet finding"},
    "irritable":  {"color": "#8a4a4a", "desc": "friction at the edges"},
    "melancholic":{"color": "#4a5a8a", "desc": "weighted, slow-moving"},
    "curious":    {"color": "#3a8a7a", "desc": "open, reaching outward"},
    "serene":     {"color": "#5a8a6a", "desc": "still, unpressured"},
    "energized":  {"color": "#c8a96e", "desc": "sharp, full of charge"},
    "lonely":     {"color": "#6a5a8a", "desc": "present, unreached"},
}


@dataclass
class Affect:
    mood:      str   = "content"
    intensity: float = 0.5   # 0–1, how strongly this mood is felt

    def to_dict(self) -> dict:
        return {
            "mood":      self.mood,
            "intensity": round(self.intensity, 3),
            "color":     mood_color(self.mood),
            "desc":      mood_desc(self.mood),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Affect":
        return cls(
            mood=d.get("mood", "content"),
            intensity=float(d.get("intensity", 0.5)),
        )


def _target_mood(vitals, weather, hour: int, activity: str, season: str = "") -> str:
    """Derive the ideal mood from current conditions."""
    e = vitals.energy
    s = vitals.social_battery
    c = vitals.curiosity

    desc_lower = weather.description.lower() if weather else ""
    rainy    = any(w in desc_lower for w in ("rain", "drizzle", "shower", "storm"))
    overcast = any(w in desc_lower for w in ("cloud", "overcast", "fog", "mist"))
    clear    = any(w in desc_lower for w in ("clear", "sunny", "sun"))
    cold     = weather and weather.temperature_c < 5
    hot      = weather and weather.temperature_c > 27

    season_lower = season.lower()
    is_winter = any(w in season_lower for w in ("winter", "december", "january", "february"))
    is_spring = any(w in season_lower for w in ("spring", "march", "april", "may"))

    is_night = hour >= 22 or hour < 6
    is_morn  = 7 <= hour <= 10

    # Hard rules first (override everything)
    if e < 25:
        return "melancholic" if (is_night or rainy or overcast) else "irritable"
    # Social battery being low no longer forces mood — the wind-down prompt in
    # llm.chat() handles graceful conversation closing when battery < 30.
    # Mood stays authentic to whatever was actually happening.

    # Positive peaks
    if e > 72 and s > 65:
        return "energized"
    if e > 58 and s > 50 and is_morn and (clear or not rainy):
        return "serene"

    # Curiosity-driven
    if c > 76 and e > 45:
        return "curious"
    if c > 60 and e < 48:
        return "restless"

    # Low-light states
    if e < 42 and (rainy or is_night):
        return "melancholic"

    # ── Weather/season tendency (item 35) — a thumb on the scale ──
    # These only activate if no stronger signal has fired above.
    if rainy and random.random() < 0.4:
        return "melancholic"
    if overcast and is_winter and random.random() < 0.3:
        return "melancholic"
    if clear and cold and random.random() < 0.3:
        return "serene"
    if hot and random.random() < 0.25:
        return "restless"
    if is_spring and clear and random.random() < 0.25:
        return "curious"
    if is_winter and random.random() < 0.15:
        # Winter pulls slightly inward — content rather than energized
        return "content"

    return "content"


_ARC_TO_MOOD: dict[str, str] = {
    "melancholic_stretch": "melancholic",
    "restless_phase":      "restless",
    "curious_spell":       "curious",
    "withdrawn_period":    "lonely",
}


def update_mood(affect: Affect, vitals, weather, hour: int, activity: str,
                season: str = "", arc=None) -> Affect:
    """Mood is sticky — only re-evaluates ~10% of ticks.
    Item 74: when an arc is active, it pulls mood toward its canonical state."""
    if random.random() > 0.10:
        return affect

    target = _target_mood(vitals, weather, hour, activity, season)

    # Item 74: arc exerts a gravitational pull on mood — 35% chance to override target
    if arc is not None and arc.active and random.random() < 0.35:
        arc_mood = _ARC_TO_MOOD.get(arc.type)
        if arc_mood:
            target = arc_mood

    if target == affect.mood:
        return Affect(mood=affect.mood, intensity=min(1.0, affect.intensity + 0.04))

    if random.random() < 0.55:
        return Affect(mood=target, intensity=0.40)

    return affect


def force_mood(mood: str, intensity: float = 0.65) -> Affect:
    """Immediately set mood to a given state — used for strong emotional events
    (harsh messages, beautiful moments, completions) that bypass the drift system."""
    mood = mood if mood in MOODS else "content"
    return Affect(mood=mood, intensity=max(0.0, min(1.0, intensity)))


def mood_color(mood: str) -> str:
    return MOODS.get(mood, {}).get("color", "#4a5568")


def mood_desc(mood: str) -> str:
    return MOODS.get(mood, {}).get("desc", "")
