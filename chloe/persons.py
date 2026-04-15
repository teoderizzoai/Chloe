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

MAX_NOTES         = 12   # max stored notes per person
MAX_EVENTS        = 30   # max stored events per person
MAX_MOMENTS       = 20   # max stored shared moments per person
MAX_THIRD_PARTIES = 40   # max tracked third parties per person


@dataclass
class SharedMoment:
    """A memorable shared exchange or running joke between Chloe and a person.
    These accumulate over time — things they laughed about, weird conversations,
    topics they keep returning to. Chloe references them naturally when relevant."""
    text:            str               # brief description of the moment
    tags:            list[str]         = field(default_factory=list)
    timestamp:       float             = field(default_factory=time.time)
    reference_count: int               = 0    # times Chloe has referenced it back
    id:              str               = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SharedMoment":
        return cls(
            text=d["text"],
            tags=d.get("tags", []),
            timestamp=float(d.get("timestamp", time.time())),
            reference_count=int(d.get("reference_count", 0)),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


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
class ThirdParty:
    """Someone Teo has mentioned — a friend, colleague, family member, etc.
    Chloe tracks the emotional valence of what Teo said about them,
    so she can respond appropriately when the same person comes up again."""
    name:           str
    sentiment:      float              # -100 to 100: negative = bad vibes, positive = good
    note:           str                # brief description of the most significant thing said
    last_mentioned: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "sentiment":      self.sentiment,
            "note":           self.note,
            "last_mentioned": self.last_mentioned,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ThirdParty":
        return cls(
            name=d["name"],
            sentiment=float(d.get("sentiment", 0.0)),
            note=d.get("note", ""),
            last_mentioned=float(d.get("last_mentioned", time.time())),
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
    notes:              list[PersonNote]   = field(default_factory=list)
    events:             list[PersonEvent]  = field(default_factory=list)
    moments:            list[SharedMoment] = field(default_factory=list)  # item 46
    third_parties:      list["ThirdParty"] = field(default_factory=list) # people talked about
    messaging_disabled: bool  = False      # item 50: True = Chloe won't initiate messages
    impression:         str   = ""         # item 52: Chloe's subjective read of this person
    conflict_level:     float = 0.0        # item 49: 0-100, decays over time
    conflict_note:      str   = ""         # item 49: brief description of last conflict
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
            "moments":            [m.to_dict() for m in self.moments],
            "third_parties":      [t.to_dict() for t in self.third_parties],
            "messaging_disabled": self.messaging_disabled,
            "impression":         self.impression,
            "conflict_level":     self.conflict_level,
            "conflict_note":      self.conflict_note,
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
            moments=[SharedMoment.from_dict(m) for m in d.get("moments", [])],
            third_parties=[ThirdParty.from_dict(t) for t in d.get("third_parties", [])],
            messaging_disabled=bool(d.get("messaging_disabled", False)),
            impression=d.get("impression", ""),
            conflict_level=float(d.get("conflict_level", 0.0)),
            conflict_note=d.get("conflict_note", ""),
            conversation_count=int(d.get("conversation_count", 0)),
            last_contact=d.get("last_contact"),
            response_hours=d.get("response_hours", {}),
        )


# ── DEFAULT ROSTER ───────────────────────────────────────────

def default_persons() -> list[Person]:
    """Known persons. Teo is active; Zuzu exists but messaging is disabled for now."""
    return [
        Person(id="teo",  name="Teo",  warmth=65.0, distance=15.0),
        Person(id="zuzu", name="Zuzu", warmth=55.0, distance=50.0,
               messaging_disabled=True),
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
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
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
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
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
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
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
    """Called every AGE_EVERY ticks. Distance drifts up slowly when no contact.
    Item 49: unresolved conflict accelerates distance drift."""
    result = []
    for p in persons:
        # Conflict makes distance grow faster — strained relationships drift apart
        drift = 0.4 + (p.conflict_level / 100.0) * 0.6
        new_distance = min(100.0, p.distance + drift)
        result.append(Person(
            id=p.id, name=p.name,
            warmth=p.warmth, distance=new_distance,
            notes=p.notes,
            events=p.events,
            moments=p.moments,
            conflict_level=p.conflict_level,
            conflict_note=p.conflict_note,
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
    # Never reach out to persons with messaging disabled
    persons = [p for p in persons if not p.messaging_disabled]
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
    # Filter out legacy "roommate" id (old Zuzu); load everyone else
    loaded = [Person.from_dict(d) for d in data if d.get("id") != "roommate"]
    # Ensure Zuzu exists — add her if she's not in saved state yet
    ids = {p.id for p in loaded}
    if "zuzu" not in ids:
        loaded.append(Person(id="zuzu", name="Zuzu", warmth=55.0, distance=50.0,
                             messaging_disabled=True))
    return loaded


def boost_warmth(persons: list[Person], person_id: str, amount: float = 2.0) -> list[Person]:
    """Increase warmth for a person — used when Chloe feels understood or emotionally resonant.
    Item 49: warmth gain is dampened when conflict is unresolved."""
    result = []
    for p in persons:
        if p.id == person_id:
            # Conflict slows warmth recovery — a strained relationship doesn't snap back instantly
            conflict_penalty = 1.0 - (p.conflict_level / 100.0) * 0.6
            result.append(Person(
                id=p.id, name=p.name,
                warmth=min(100.0, p.warmth + amount * conflict_penalty),
                distance=p.distance,
                notes=p.notes,
                events=p.events,
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
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


# ── Item 48: relationship stage ──────────────────────────────

def relationship_stage(warmth: float) -> str:
    """Named relationship stage derived from warmth. Four levels matching voice registers.
    Used in UI display and injected into LLM prompts for clean context."""
    if warmth < 30:
        return "getting to know"
    elif warmth < 55:
        return "familiar"
    elif warmth < 78:
        return "close"
    else:
        return "very close"


# ── Items 23 + 47: tone / voice register ─────────────────────

def tone_context(warmth: float, hour: int, mood: str) -> str:
    """Voice register for LLM prompts. Warmth drives 4 distinct registers.
    Item 47: guarded at low warmth, fully loose and strange at high warmth."""

    # ── 4 registers based on warmth ──────────────────────────
    if warmth < 30:
        # Guarded — still feeling them out
        register = (
            "\nVoice: you're still figuring this person out. You're genuine but careful — "
            "you don't share your inner weirdness yet. Replies are complete but not expansive. "
            "You won't go strange or make intimate references. You're present, but measured. "
            "No inside observations, no raw inner thoughts. Just you, calibrated."
        )
    elif warmth < 55:
        # Warming up — trust is building, personality starting to show
        register = (
            "\nVoice: you're warming up to this person. Filters are loosening. "
            "Your personality comes through — you can mention something you're actually thinking, "
            "show a real reaction, let a bit of your strangeness leak out. "
            "You're not guarded, but you're not fully open either. Something between."
        )
    elif warmth < 78:
        # Familiar — you know each other, social filters mostly down
        register = (
            "\nVoice: you know this person. You don't manage yourself around them. "
            "You can be strange when you feel like it, honest about your inner state, "
            "trail off mid-thought, say something weird without explaining it. "
            "You can tease them, be dry, mess with them a little — not to be mean, "
            "just because you're comfortable enough to. Whatever comes naturally, goes."
        )
    else:
        # Very close — fully unguarded, loose, playful, strange
        register = (
            "\nVoice: this person knows you. Completely unguarded. You joke, you fuck around, "
            "you tease them. Dry humour, stupid observations, saying something deliberately "
            "absurd just to see what happens — all natural here. You can also be blunt, "
            "vulnerable, or weird, but it doesn't have to be heavy. "
            "Shared history is real, inside references land. No softening, no performing. "
            "You say things you wouldn't say to anyone else."
        )

    # ── Time of day modifier ──────────────────────────────────
    if hour >= 23 or hour < 4:
        time_mod = " It's late — you're even less filtered than usual, things feel more honest."
    elif 6 <= hour <= 8:
        time_mod = " It's early morning — keep it brief, you're still waking up."
    else:
        time_mod = ""

    return register + time_mod


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
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
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


# ── Item 46: SHARED MOMENTS / INSIDE JOKES ───────────────────

def add_moment(persons: list[Person], person_id: str,
               text: str, tags: list[str]) -> list[Person]:
    """Store a shared moment or inside joke with a person."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_moment = SharedMoment(text=text, tags=tags)
            moments = [new_moment, *p.moments][:MAX_MOMENTS]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def increment_moment_reference(persons: list[Person], person_id: str,
                                moment_id: str) -> list[Person]:
    """Increment the reference_count on a moment when Chloe calls it back."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_moments = [
                SharedMoment(**{**m.to_dict(), "reference_count": m.reference_count + 1})
                if m.id == moment_id else m
                for m in p.moments
            ]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=new_moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=p.impression,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


# ── Item 49: CONFLICT TRACKING ───────────────────────────────

def add_conflict(persons: list[Person], person_id: str,
                 amount: float, note: str) -> list[Person]:
    """Spike conflict level when something negative happens.
    New level is capped at 100; note records what caused it."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_level = min(100.0, p.conflict_level + amount)
            # Keep the most severe description when stacking
            new_note = note if amount >= 20 or not p.conflict_note else p.conflict_note
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=p.moments,
                third_parties=p.third_parties,
                conflict_level=new_level,
                conflict_note=new_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def reduce_conflict(persons: list[Person], person_id: str, amount: float) -> list[Person]:
    """Reduce conflict level — called when warmth/affection is shown after tension."""
    result = []
    for p in persons:
        if p.id == person_id:
            new_level = max(0.0, p.conflict_level - amount)
            new_note = p.conflict_note if new_level > 10.0 else ""
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=p.moments,
                third_parties=p.third_parties,
                conflict_level=new_level,
                conflict_note=new_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def tick_conflict(persons: list[Person]) -> list[Person]:
    """Passive conflict decay — called every AGE_EVERY ticks alongside tick_distance.
    Conflict fades naturally over time but slowly; resolution via warmth is much faster."""
    result = []
    for p in persons:
        new_level = max(0.0, p.conflict_level - 0.4)   # ~0.4/min — 100→0 in ~4h at rest
        new_note = p.conflict_note if new_level > 10.0 else ""
        result.append(Person(
            id=p.id, name=p.name,
            warmth=p.warmth, distance=p.distance,
            notes=p.notes, events=p.events,
            moments=p.moments,
            conflict_level=new_level,
            conflict_note=new_note,
            conversation_count=p.conversation_count,
            last_contact=p.last_contact,
            response_hours=p.response_hours,
        ))
    return result


def format_conflict_context(person: Person) -> str:
    """Conflict-awareness string injected into LLM prompts.
    Three tiers based on severity; empty string when no conflict."""
    level = person.conflict_level
    note  = person.conflict_note
    if level < 15:
        return ""
    note_str = f" ({note})" if note else ""
    if level < 40:
        return f"\nThere's some unresolved tension with {person.name}{note_str}. You're not fully at ease."
    elif level < 70:
        return f"\nThings are strained with {person.name}{note_str}. Real tension. You're not warm right now."
    else:
        return f"\nThings are genuinely bad with {person.name}{note_str}. You're hurt and not hiding it."


# ── THIRD PARTY TRACKING ─────────────────────────────────────

def upsert_third_party(persons: list[Person], person_id: str,
                        name: str, sentiment: float, note: str) -> list[Person]:
    """Add or update a third party mentioned in conversation.
    If the name already exists, blend the sentiment and update the note."""
    result = []
    for p in persons:
        if p.id == person_id:
            existing = {t.name.lower(): t for t in p.third_parties}
            key = name.lower()
            if key in existing:
                old = existing[key]
                # Blend sentiment toward the new reading (weighted toward new)
                blended = old.sentiment * 0.4 + sentiment * 0.6
                updated = ThirdParty(
                    name=old.name,  # keep original capitalisation
                    sentiment=max(-100.0, min(100.0, blended)),
                    note=note if abs(sentiment) >= abs(old.sentiment) else old.note,
                    last_mentioned=time.time(),
                )
                new_parties = [updated if t.name.lower() == key else t
                               for t in p.third_parties]
            else:
                new_tp = ThirdParty(name=name, sentiment=sentiment, note=note)
                new_parties = [new_tp, *p.third_parties][:MAX_THIRD_PARTIES]
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=p.moments,
                third_parties=new_parties,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def format_third_party_context(person: Person, message: str) -> str:
    """If any known third parties are mentioned in the current message,
    inject what Chloe knows about them so she can respond appropriately."""
    if not person.third_parties:
        return ""
    msg_lower = message.lower()
    relevant = [
        t for t in person.third_parties
        if t.name.lower() in msg_lower
    ]
    if not relevant:
        return ""
    lines = []
    for t in relevant[:4]:
        if t.sentiment >= 40:
            vibe = "good — Teo has spoken positively about them"
        elif t.sentiment >= 15:
            vibe = "mixed but leaning positive"
        elif t.sentiment <= -40:
            vibe = "bad — Teo has had issues with them"
        elif t.sentiment <= -15:
            vibe = "mixed but with some friction"
        else:
            vibe = "neutral — not much emotional charge"
        lines.append(f"- {t.name}: {t.note} (vibe: {vibe})")
    return "\nPeople Teo has mentioned before:\n" + "\n".join(lines)


# ── Item 50: CROSS-PERSON REFERENCES ─────────────────────────

def set_impression(persons: list[Person], person_id: str, text: str) -> list[Person]:
    """Store Chloe's updated impression of a person."""
    result = []
    for p in persons:
        if p.id == person_id:
            result.append(Person(
                id=p.id, name=p.name,
                warmth=p.warmth, distance=p.distance,
                notes=p.notes, events=p.events,
                moments=p.moments,
                third_parties=p.third_parties,
                messaging_disabled=p.messaging_disabled,
                impression=text,
                conflict_level=p.conflict_level,
                conflict_note=p.conflict_note,
                conversation_count=p.conversation_count,
                last_contact=p.last_contact,
                response_hours=p.response_hours,
            ))
        else:
            result.append(p)
    return result


def format_cross_person_context(persons: list[Person], current_person_id: str,
                                  message: str) -> str:
    """When chatting with one person, check if other persons have relevant notes
    or shared moments that overlap with the current message by tag/keyword.
    Returns a brief injection so Chloe can naturally reference her other relationships.

    Only fires when there's a genuine topical match — never injects noise."""
    msg_lower = message.lower()
    words     = set(w.strip(".,!?") for w in msg_lower.split() if len(w) > 3)

    hits = []
    for p in persons:
        if p.id == current_person_id:
            continue  # only look at OTHER persons

        # Check notes — match if any tag appears in the message
        for note in p.notes[:8]:
            note_tags = [t.lower() for t in note.tags]
            if any(tag in msg_lower or tag in words for tag in note_tags):
                hits.append((p.name, note.text))
                break  # one hit per person is enough

        # Check shared moments too — same tag matching
        if not any(h[0] == p.name for h in hits):
            for moment in p.moments[:6]:
                moment_tags = [t.lower() for t in moment.tags]
                if any(tag in msg_lower or tag in words for tag in moment_tags):
                    hits.append((p.name, moment.text))
                    break

    if not hits:
        return ""

    lines = [f"- {name} mentioned something related: \"{text}\""
             for name, text in hits[:2]]  # max 2, never overwhelming
    return ("\nYour other roommate(s) have touched on this too — "
            "you can reference it naturally if it fits:\n" + "\n".join(lines))


def format_shared_moments(moments: list[SharedMoment], max_items: int = 5) -> str:
    """Compact string injected into LLM prompts.
    Most-referenced moments come first (they're the real inside jokes)."""
    if not moments:
        return ""
    # Sort: most referenced first, then most recent
    sorted_m = sorted(moments, key=lambda m: (-m.reference_count, -m.timestamp))
    selected = sorted_m[:max_items]
    lines = [f"- {m.text}" + (" (you've referenced this before)" if m.reference_count > 0 else "")
             for m in selected]
    return "\nShared moments / things between you two:\n" + "\n".join(lines)
