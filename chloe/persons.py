# chloe/persons.py
# ─────────────────────────────────────────────────────────────
# Layer 4: Relational Depth
#
# Person  — a person Chloe knows. Has a name, warmth (how close
#           they feel to each other), distance (how long since
#           last contact), and notes — memorable things they've
#           shared that Chloe might follow up on later.
#
# warmth  : 0–100  — emotional closeness, grows slowly, never resets
# distance: 0–100  — 0 = just spoke, drifts up over time
# ─────────────────────────────────────────────────────────────

import time
import uuid
import random
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

MAX_NOTES   = 12   # max stored notes per person
MAX_EVENTS  = 30   # max stored events per person


@dataclass
class PersonNote:
    """A memorable thing someone shared — Chloe may follow up later."""
    text:        str
    tags:        list[str] = field(default_factory=list)
    timestamp:   float     = field(default_factory=time.time)
    followed_up: bool      = False
    id:          str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PersonNote":
        return cls(
            text=d["text"], tags=d.get("tags", []),
            timestamp=float(d.get("timestamp", time.time())),
            followed_up=bool(d.get("followed_up", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


@dataclass
class PersonEvent:
    """A future plan or event Teo mentioned — Chloe can reference it on the right day."""
    text:        str               # "has a date"
    date:        str               # ISO "2026-04-18"
    uncertain:   bool  = False     # True if Chloe wasn't sure which date was meant
    created_at:  float = field(default_factory=time.time)
    followed_up: bool  = False
    id:          str   = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PersonEvent":
        return cls(
            text=d["text"],
            date=d["date"],
            uncertain=bool(d.get("uncertain", False)),
            created_at=float(d.get("created_at", time.time())),
            followed_up=bool(d.get("followed_up", False)),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


@dataclass
class Person:
    id:                 str         # "teo" | "roommate"
    name:               str         # display name
    warmth:             float       = 50.0   # 0–100
    distance:           float       = 50.0   # 0–100
    notes:              list[PersonNote]  = field(default_factory=list)
    events:             list[PersonEvent] = field(default_factory=list)
    conversation_count: int         = 0
    last_contact:       Optional[float] = None   # unix timestamp
    # Item 25 — hour (str "0"–"23") → response count
    response_hours:     dict        = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id":                 self.id,
            "name":               self.name,
            "warmth":             self.warmth,
            "distance":           self.distance,
            "notes":              [n.to_dict() for n in self.notes],
            "events":             [e.to_dict() for e in self.events],
            "conversation_count": self.conversation_count,
            "last_contact":       self.last_contact,
            "response_hours":     self.response_hours,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        return cls(
            id=d["id"],
            name=d["name"],
            warmth=float(d.get("warmth", 50.0)),
            distance=float(d.get("distance", 50.0)),
            notes=[PersonNote.from_dict(n) for n in d.get("notes", [])],
            events=[PersonEvent.from_dict(e) for e in d.get("events", [])],
            conversation_count=int(d.get("conversation_count", 0)),
            last_contact=d.get("last_contact"),
            response_hours=d.get("response_hours", {}),
        )


# ── DEFAULT ROSTER ───────────────────────────────────────────

def default_persons() -> list[Person]:
    """Known persons. Only Teo for now."""
    return [
        Person(id="teo", name="Teo", warmth=65.0, distance=15.0),
    ]


# ── CONTACT ──────────────────────────────────────────────────

def on_contact(persons: list[Person], person_id: str,
               hour: Optional[int] = None) -> list[Person]:
    """Called when Chloe talks with someone.
    Resets distance toward 0, increments count, nudges warmth.
    Item 25: records the hour so response patterns can be learned."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_warmth   = min(100.0, p.warmth + 1.5)
            new_distance = max(0.0, p.distance - 30.0)
            new_hours = dict(p.response_hours)
            if hour is not None:
                key = str(hour)
                new_hours[key] = new_hours.get(key, 0) + 1
            result.append(Person(
                id=p.id, name=p.name,
                warmth=new_warmth, distance=new_distance,
                notes=p.notes,
                events=p.events,
                conversation_count=p.conversation_count + 1,
                last_contact=time.time(),
                response_hours=new_hours,
            ))
        else:
            result.append(p)
    return result


# ── NOTES ────────────────────────────────────────────────────

def add_note(persons: list[Person], person_id: str, text: str, tags: list[str]) -> list[Person]:
    """Store a memorable detail about a person."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_note = PersonNote(text=text, tags=tags)
            notes = [new_note, *p.notes][:MAX_NOTES]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=notes,
                events=p.events,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def mark_followed_up(persons: list[Person], person_id: str, note_id: str) -> list[Person]:
    """Mark a note as followed up so it isn't used again."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_notes = [
                PersonNote(**{**n.to_dict(), "followed_up": True})
                if n.id == note_id else n
                for n in p.notes
            ]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=new_notes,
                events=p.events,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def pending_followups(person: Person) -> list[PersonNote]:
    """Notes not yet followed up — oldest first."""
    return sorted(
        [n for n in person.notes if not n.followed_up],
        key=lambda n: n.timestamp,
    )


# ── DISTANCE DRIFT ───────────────────────────────────────────

def tick_distance(persons: list[Person]) -> list[Person]:
    """Called every AGE_EVERY ticks. Distance drifts up slowly when no contact."""
    result = []
    for p in persons:
        new_distance = min(100.0, p.distance + 0.4)
        result.append(Person(
            id=p.id, name=p.name,
            warmth=p.warmth, distance=new_distance,
            notes=p.notes,
            events=p.events,
            conversation_count=p.conversation_count,
            last_contact=p.last_contact,
            response_hours=p.response_hours,
        ))
    return result


# ── REACH-OUT SELECTION ──────────────────────────────────────

def choose_reach_out_target(persons: list[Person], mood: str,
                             hour: Optional[int] = None) -> Optional[Person]:
    """Pick who Chloe should reach out to based on warmth, distance, mood, and timing.

    Logic:
    - Base score = warmth * 0.5 + distance * 0.5  (distant people who are warm score high)
    - Lonely mood → bonus to everyone (wants connection)
    - Serene mood → strong preference for the warmest person
    - Melancholic → slight boost for warmest (seeks comfort)
    - Irritable   → slight penalty for everyone (less likely to reach out)
    - Item 25: bonus if person is likely to be active at this hour
    """
    if not persons:
        return None

    def score(p: Person) -> float:
        s = p.warmth * 0.5 + p.distance * 0.5
        if mood == "lonely":
            s += 20
        elif mood == "serene":
            s += p.warmth * 0.3
        elif mood == "melancholic":
            s += p.warmth * 0.15
        elif mood == "irritable":
            s -= 15
        # Item 25 — prefer reaching out when they're likely to see it
        if hour is not None and is_likely_active(p, hour):
            s += 8
        # Add jitter so it's not deterministic
        s += random.uniform(-5, 5)
        return s

    scored = sorted(persons, key=score, reverse=True)
    return scored[0] if scored else None


# ── SERIALISATION ────────────────────────────────────────────

def persons_to_dicts(persons: list[Person]) -> list[dict]:
    return [p.to_dict() for p in persons]


def persons_from_dicts(data: list[dict]) -> list[Person]:
    if not data:
        return default_persons()
    # Filter out Zuzu / roommate — only Teo is active for now
    return [Person.from_dict(d) for d in data if d.get("id") != "roommate"]


def boost_warmth(persons: list[Person], person_id: str, amount: float = 2.0) -> list[Person]:
    """Increase warmth for a person — used when Chloe feels understood or emotionally resonant."""
    result = []
    for p in persons:
        if p.id == person_id:
            result.append(Person(
                id=p.id, name=p.name,
                warmth=min(100.0, p.warmth + amount),
                distance=p.distance,
                notes=p.notes,
                events=p.events,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


# ── Item 25: response pattern helpers ────────────────────────

def is_likely_active(person: Person, hour: int) -> bool:
    """Return True if this person tends to respond around this hour."""
    if not person.response_hours:
        return True  # no data — assume always possible
    total = sum(person.response_hours.values())
    if total < 5:
        return True  # not enough data yet
    # Look at a 3-hour window centred on `hour`
    window = {str((hour + d) % 24) for d in (-1, 0, 1)}
    window_count = sum(person.response_hours.get(h, 0) for h in window)
    return (window_count / total) >= 0.10  # at least 10% of responses in this window


# ── Item 23: tone context helper ─────────────────────────────

def tone_context(warmth: float, hour: int, mood: str) -> str:
    """One-line tone guidance for LLM prompts based on closeness + time."""
    parts = []
    if warmth < 35:
        parts.append("You're still getting to know this person — genuine but not fully open.")
    elif warmth > 70:
        parts.append("You know this person well — you can be strange, raw, unguarded with them.")
    if hour >= 23 or hour < 4:
        parts.append("It's late — you're less filtered than usual.")
    elif 6 <= hour <= 8:
        parts.append("It's early morning — keep it brief, you're still waking up.")
    return ("\n" + " ".join(parts)) if parts else ""


def get_person(persons: list[Person], person_id: str) -> Optional[Person]:
    return next((p for p in persons if p.id == person_id), None)


# ── EVENTS ───────────────────────────────────────────────────

def add_event(persons: list[Person], person_id: str, event: "PersonEvent") -> list[Person]:
    """Store an upcoming event for a person."""
    result = []
    for p in persons:
        if p.id == person_id:
            events = [event, *p.events][:MAX_EVENTS]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=events,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def get_upcoming_events(person: Person, days_ahead: int = 4) -> list["PersonEvent"]:
    """Events in the next N days (or overdue and not yet followed up)."""
    today    = date.today()
    cutoff   = (today + timedelta(days=days_ahead)).isoformat()
    today_s  = today.isoformat()
    return [
        e for e in person.events
        if not e.followed_up and e.date >= today_s and e.date <= cutoff
    ]


def format_upcoming_events(events: list["PersonEvent"]) -> str:
    """Compact string injected into LLM prompts."""
    if not events:
        return ""
    today_s = date.today().isoformat()
    lines = []
    for e in events:
        when = "today" if e.date == today_s else e.date
        flag = " (date uncertain)" if e.uncertain else ""
        lines.append(f"- {e.text} on {when}{flag}")
    return "\nUpcoming events you know about:\n" + "\n".join(lines)
