# chloe/avatar.py
# ─────────────────────────────────────────────────────────────
# Portrait art for the dashboard — ties visible "face" to inner state.
#
# We only have two families of assets today:
#   • Actions/ — pose keyed to heartbeat activity (sleep, read, …)
#   • Emotions/ — expression keyed to affect.mood
#
# Design goals
# ------------
# 1. **Single place to edit rules** — snapshot exposes `avatar`; the HTML
#    stays dumb and just sets `<img src>`.
# 2. **Activity is the default story** — "what is she doing?" reads clearly.
# 3. **Mood still matters during passive rest** — if she's on `rest` but the
#    affect layer says she's lonely or irritable, showing only the generic
#    Rest sprite would lie to the viewer; we temporarily promote mood art.
# 4. **Graceful fallback** — unknown future activity/mood → no path so the
#    frontend keeps the classic `image.webp`.
#
# URL shape: mounted in server.py as `/media/chloe/…` pointing at this
# package's `images/` folder, so paths here are *relative to that root*.
# ─────────────────────────────────────────────────────────────

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

# Files on disk (Windows-friendly); values are relative to chloe/images/.
_ACTIVITY_FILES: Final[dict[str, str]] = {
    "sleep":   "Actions/Chloe_Sleep.png",
    "dream":   "Actions/Chloe_Dream.png",
    "rest":    "Actions/Chloe_Rest.png",
    # heart.py calls this id "read" while the UI label is "Research"
    "read":    "Actions/Chloe_Reading.png",
    "think":   "Actions/Chloe_Thinking.png",
    "message": "Actions/Chloe_Texting.png",
    "create":  "Actions/Chloe_Create.png",
}

# Every key in affect.MOODS should resolve so we never dead-end after choosing
# "mood mode". Missing keys would be a bug — keep in sync with affect.py.
_MOOD_FILES: Final[dict[str, str]] = {
    "content":     "Emotions/Chloe_Content.png",
    "restless":    "Emotions/Chloe_Restless.png",
    "irritable":   "Emotions/Chloe_Irritable.png",
    "melancholic": "Emotions/Chloe_Sad.png",
    "curious":     "Emotions/Chloe_Happy.png",
    "serene":      "Emotions/Chloe_Content.png",
    "energized":   "Emotions/Chloe_Happy.png",
    "lonely":      "Emotions/Chloe_Crying.png",
}

# When resting, vitals recovery is "neutral" activity — good moment to let
# facial expression carry more weight if the mood is strongly negative or
# agitated. Threshold is a trade-off: lower → more mood shots (less Rest art).
_REST_MOOD_OVERRIDE: Final[frozenset[str]] = frozenset(
    {"melancholic", "lonely", "irritable", "restless"}
)
_REST_MOOD_INTENSITY_MIN: Final[float] = 0.45


def _images_root() -> Path:
    """Absolute path to chloe/images — useful for tooling / one-off checks."""
    return Path(__file__).resolve().parent / "images"


def portrait_meta(activity: str, mood: str, mood_intensity: float) -> dict[str, Any]:
    """
    Decide which PNG the dashboard should show.

    Returns a dict suitable for JSON / snapshot:
      path  — str or None. If None, frontend should keep its default avatar.
      key   — short token for debugging ("activity:read", "mood:lonely", …).
      source — "activity" | "mood" | "default" for UI/debug if you extend later.
    """
    mood = (mood or "content").lower().strip()
    activity = (activity or "rest").lower().strip()
    try:
        intensity = float(mood_intensity)
    except (TypeError, ValueError):
        intensity = 0.5

    # --- 1) Rest + heavy / scratchy mood → show emotion art ---------------
    if (
        activity == "rest"
        and mood in _REST_MOOD_OVERRIDE
        and intensity >= _REST_MOOD_INTENSITY_MIN
    ):
        rel = _MOOD_FILES.get(mood)
        # We intentionally do **not** gate on Path.is_file() here: on some setups
        # (symlinks, packaged installs, odd cwd) the check falsely failed and the
        # snapshot returned path=null — the UI stayed on image.webp forever. If an
        # asset is missing, the <img> 404s and you know to fix the file layout.
        if rel:
            return {
                "path":   f"/media/chloe/{rel}",
                "key":    f"mood:{mood}",
                "source": "mood",
            }

    # --- 2) Otherwise prefer activity pose -------------------------------
    rel_act = _ACTIVITY_FILES.get(activity)
    if rel_act:
        return {
            "path":   f"/media/chloe/{rel_act}",
            "key":    f"activity:{activity}",
            "source": "activity",
        }

    # --- 3) Unknown activity → fall back to mood -------------------------
    rel_mood = _MOOD_FILES.get(mood)
    if rel_mood:
        return {
            "path":   f"/media/chloe/{rel_mood}",
            "key":    f"mood:{mood}",
            "source": "mood",
        }

    # --- 4) Nothing matched (bad state file, renamed assets, …) ----------
    return {"path": None, "key": "default", "source": "default"}
