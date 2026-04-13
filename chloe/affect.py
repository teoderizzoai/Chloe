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


def _target_mood(vitals, weather, hour: int, activity: str) -> str:
    """Derive the ideal mood from current conditions."""
    e = vitals.energy
    s = vitals.social_battery
    c = vitals.curiosity

    rainy    = weather and any(
        w in weather.description.lower() for w in ("rain", "drizzle", "shower")
    )
    is_night = hour >= 22 or hour < 6
    is_morn  = 7 <= hour <= 10

    # Hard rules first (override everything)
    if s < 20 and activity not in ("message", "create"):
        return "lonely"
    if e < 25:
        return "melancholic" if (is_night or rainy) else "irritable"
    if s < 30 and activity == "message":
        return "irritable"

    # Positive peaks
    if e > 72 and s > 65:
        return "energized"
    if e > 58 and s > 50 and is_morn and not rainy:
        return "serene"

    # Curiosity-driven
    if c > 76 and e > 45:
        return "curious"
    if c > 60 and e < 48:
        return "restless"

    # Low-light states
    if e < 42 and (rainy or is_night):
        return "melancholic"

    return "content"


def update_mood(affect: Affect, vitals, weather, hour: int, activity: str) -> Affect:
    """Mood is sticky — only re-evaluates ~10% of ticks.
    When it shifts, it eases in at low intensity."""
    if random.random() > 0.10:
        return affect

    target = _target_mood(vitals, weather, hour, activity)

    if target == affect.mood:
        # Deepen current mood slowly
        return Affect(mood=affect.mood, intensity=min(1.0, affect.intensity + 0.04))

    # 55% chance to actually shift to target mood
    if random.random() < 0.55:
        return Affect(mood=target, intensity=0.40)

    return affect


def mood_color(mood: str) -> str:
    return MOODS.get(mood, {}).get("color", "#4a5568")


def mood_desc(mood: str) -> str:
    return MOODS.get(mood, {}).get("desc", "")
