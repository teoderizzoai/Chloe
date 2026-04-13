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
from typing import Optional

MAX_NOTES = 12   # max stored notes per person


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
class Person:
    id:                 str         # "teo" | "roommate"
    name:               str         # display name
    warmth:             float       = 50.0   # 0–100
    distance:           float       = 50.0   # 0–100
    notes:              list[PersonNote] = field(default_factory=list)
    conversation_count: int         = 0
    last_contact:       Optional[float] = None   # unix timestamp

    def to_dict(self) -> dict:
        return {
            "id":                 self.id,
            "name":               self.name,
            "warmth":             self.warmth,
            "distance":           self.distance,
            "notes":              [n.to_dict() for n in self.notes],
            "conversation_count": self.conversation_count,
            "last_contact":       self.last_contact,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        return cls(
            id=d["id"],
            name=d["name"],
            warmth=float(d.get("warmth", 50.0)),
            distance=float(d.get("distance", 50.0)),
            notes=[PersonNote.from_dict(n) for n in d.get("notes", [])],
            conversation_count=int(d.get("conversation_count", 0)),
            last_contact=d.get("last_contact"),
        )


# ── DEFAULT ROSTER ───────────────────────────────────────────

def default_persons() -> list[Person]:
    """Chloe's two roommates. Warmth starts warm, distance starts low."""
    return [
        Person(id="teo",      name="Teo",          warmth=65.0, distance=15.0),
        Person(id="roommate", name="Zuzu",           warmth=50.0, distance=30.0),
    ]


# ── CONTACT ──────────────────────────────────────────────────

def on_contact(persons: list[Person], person_id: str) -> list[Person]:
    """Called when Chloe talks with someone.
    Resets distance toward 0, increments count, nudges warmth."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_warmth   = min(100.0, p.warmth + 1.5)
            new_distance = max(0.0, p.distance - 30.0)
            result.append(Person(
                id=p.id, name=p.name,
                warmth=new_warmth, distance=new_distance,
                notes=p.notes,
                conversation_count=p.conversation_count + 1,
                last_contact=time.time(),
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
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
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
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
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
            conversation_count=p.conversation_count,
            last_contact=p.last_contact,
        ))
    return result


# ── REACH-OUT SELECTION ──────────────────────────────────────

def choose_reach_out_target(persons: list[Person], mood: str) -> Optional[Person]:
    """Pick who Chloe should reach out to based on warmth, distance, and mood.

    Logic:
    - Base score = warmth * 0.5 + distance * 0.5  (distant people who are warm score high)
    - Lonely mood → bonus to everyone (wants connection)
    - Serene mood → strong preference for the warmest person
    - Melancholic → slight boost for warmest (seeks comfort)
    - Irritable   → slight penalty for everyone (less likely to reach out)
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
    return [Person.from_dict(d) for d in data]


def get_person(persons: list[Person], person_id: str) -> Optional[Person]:
    return next((p for p in persons if p.id == person_id), None)
