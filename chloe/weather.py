# chloe/weather.py
# ─────────────────────────────────────────────────────────────
# Weather awareness — Chloe knows what it's like outside.
# Uses Open-Meteo (free, no API key needed).
#
# Also provides season and time-of-day language helpers (Feature 8).
# ─────────────────────────────────────────────────────────────

import time
from dataclasses import dataclass, asdict
from typing import Optional

import httpx

# Default location — Amsterdam, Netherlands.
DEFAULT_LAT   = 52.3676
DEFAULT_LON   = 4.9041
LOCATION_NAME = "Amsterdam"

# WMO Weather Interpretation Codes → (condition_key, human_description)
_WMO_CODES: dict[int, tuple[str, str]] = {
    0:  ("clear",  "clear sky"),
    1:  ("clear",  "mainly clear"),
    2:  ("cloudy", "partly cloudy"),
    3:  ("cloudy", "overcast"),
    45: ("fog",    "foggy"),
    48: ("fog",    "icy fog"),
    51: ("rain",   "light drizzle"),
    53: ("rain",   "drizzle"),
    55: ("rain",   "heavy drizzle"),
    61: ("rain",   "light rain"),
    63: ("rain",   "rain"),
    65: ("rain",   "heavy rain"),
    71: ("snow",   "light snow"),
    73: ("snow",   "snow"),
    75: ("snow",   "heavy snow"),
    77: ("snow",   "snow grains"),
    80: ("rain",   "light showers"),
    81: ("rain",   "showers"),
    82: ("rain",   "heavy showers"),
    85: ("snow",   "snow showers"),
    86: ("snow",   "heavy snow showers"),
    95: ("storm",  "thunderstorm"),
    96: ("storm",  "thunderstorm with hail"),
    99: ("storm",  "severe thunderstorm"),
}

# Per-tick vitals nudge by weather condition.
# Ticks are 5 seconds — these are intentionally tiny.
# Over a full day (~17 280 ticks) clear sky → +207 energy (offset by circadian drain).
_CONDITION_DELTA: dict[str, dict[str, float]] = {
    "clear":  {"energy":  0.012, "social":  0.006, "curiosity":  0.000},
    "cloudy": {"energy":  0.000, "social":  0.000, "curiosity":  0.000},
    "rain":   {"energy": -0.008, "social": -0.004, "curiosity":  0.006},
    "snow":   {"energy":  0.002, "social": -0.002, "curiosity":  0.010},
    "fog":    {"energy": -0.004, "social": -0.002, "curiosity":  0.008},
    "storm":  {"energy": -0.010, "social": -0.010, "curiosity":  0.015},
}

_SEASONS: dict[int, str] = {
    1: "deep winter",  2: "late winter",  3: "early spring",
    4: "mid spring",   5: "late spring",  6: "early summer",
    7: "midsummer",    8: "late summer",  9: "early autumn",
    10: "mid autumn",  11: "late autumn", 12: "early winter",
}


@dataclass
class WeatherState:
    condition:     str    # clear | cloudy | rain | snow | fog | storm
    description:   str    # e.g. "light rain"
    temperature_c: float
    feels_like:    str    # freezing | cold | cool | mild | warm | hot
    location:      str
    fetched_at:    float  # unix timestamp

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WeatherState":
        return cls(**d)


async def fetch_weather(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Optional[WeatherState]:
    """Fetch current conditions from Open-Meteo. Returns None on any failure."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code"
        "&timezone=auto"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
        data    = r.json()
        current = data["current"]
        code    = int(current.get("weather_code", 0))
        temp    = float(current.get("temperature_2m", 15.0))
        app_t   = float(current.get("apparent_temperature", temp))

        condition, description = _WMO_CODES.get(code, ("cloudy", "cloudy"))

        return WeatherState(
            condition=condition,
            description=description,
            temperature_c=round(temp, 1),
            feels_like=_feels_like(app_t),
            location=LOCATION_NAME,
            fetched_at=time.time(),
        )
    except Exception:
        return None


def weather_vitals_delta(condition: str) -> dict:
    """Per-tick vitals nudge for the given weather condition."""
    return _CONDITION_DELTA.get(condition, {"energy": 0.0, "social": 0.0, "curiosity": 0.0})


def describe_season(month: int) -> str:
    """Poetic season label for the given month (1–12)."""
    return _SEASONS.get(month, "midyear")


def _feels_like(apparent_c: float) -> str:
    if apparent_c < 0:  return "freezing"
    if apparent_c < 8:  return "cold"
    if apparent_c < 14: return "cool"
    if apparent_c < 20: return "mild"
    if apparent_c < 27: return "warm"
    return "hot"
