# chloe/identity.py
# ─────────────────────────────────────────────────────────────
# Trait-based identity. Replaces soul.py.
#
# Traits are not predefined. They emerge from experience when
# Haiku detects a coherent pattern across 3+ events.
# behavioral_profile is generated once by Haiku at trait creation
# and is the interface to every other system.
# ─────────────────────────────────────────────────────────────

import time
import uuid
from dataclasses import dataclass, field, asdict


# ── CORE DATACLASSES ─────────────────────────────────────────

@dataclass
class Trait:
    id: str
    name: str                  # plain language, e.g. "gets quiet when something matters too much"
    weight: float              # 0.0–1.0
    behavioral_profile: str    # Haiku-generated: what this means for tone, activity, topics
    origin_memory_ids: list    # experiences that produced it
    last_reinforced: float     # unix timestamp
    created: float             # unix timestamp
    is_core: bool = False      # weight >= 0.75 sustained for 7+ days
    setback_count: int = 0     # times a related goal/want failed
    setback_notes: list = field(default_factory=list)  # brief notes, capped at 5

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "weight": self.weight,
            "behavioral_profile": self.behavioral_profile,
            "origin_memory_ids": self.origin_memory_ids,
            "last_reinforced": self.last_reinforced,
            "created": self.created,
            "is_core": self.is_core,
            "setback_count": self.setback_count,
            "setback_notes": self.setback_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trait":
        return cls(
            id=d["id"],
            name=d["name"],
            weight=float(d["weight"]),
            behavioral_profile=d.get("behavioral_profile", ""),
            origin_memory_ids=d.get("origin_memory_ids", []),
            last_reinforced=float(d.get("last_reinforced", d.get("created", time.time()))),
            created=float(d.get("created", time.time())),
            is_core=bool(d.get("is_core", False)),
            setback_count=int(d.get("setback_count", 0)),
            setback_notes=d.get("setback_notes", []),
        )


@dataclass
class Contradiction:
    id: str
    trait_a_id: str
    trait_b_id: str
    description: str           # plain language, e.g. "she seems to be both X and Y"
    created: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Contradiction":
        return cls(
            id=d["id"],
            trait_a_id=d["trait_a_id"],
            trait_b_id=d["trait_b_id"],
            description=d["description"],
            created=float(d.get("created", time.time())),
        )


@dataclass
class Tendencies:
    """Thin seed biases that make certain trait types more likely to emerge first.
    These are scaffolding, not identity. They drift as the trait profile solidifies."""
    biases: dict = field(default_factory=dict)

    @classmethod
    def default(cls) -> "Tendencies":
        return cls(biases={
            "introspective": 1.3,    # reflects, goes inward
            "pattern_seeking": 1.2,  # finds connections, drawn to the conceptual
            "relational": 1.2,       # attentive to people, warmth-shaped
            "open_ended": 1.1,       # prefers questions to answers
            "aesthetic": 1.0,        # notices texture, beauty, form
        })

    def to_dict(self) -> dict:
        return {"biases": self.biases}

    @classmethod
    def from_dict(cls, d: dict) -> "Tendencies":
        return cls(biases=d.get("biases", {}))


@dataclass
class Identity:
    traits: list = field(default_factory=list)              # list[Trait]
    contradictions: list = field(default_factory=list)      # list[Contradiction]
    tendencies: Tendencies = field(default_factory=Tendencies.default)
    identity_momentum: dict = field(default_factory=dict)   # trait_id → EMA of recent weight change

    def to_dict(self) -> dict:
        return {
            "traits": [t.to_dict() for t in self.traits],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "tendencies": self.tendencies.to_dict(),
            "identity_momentum": self.identity_momentum,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Identity":
        return cls(
            traits=[Trait.from_dict(t) for t in d.get("traits", [])],
            contradictions=[Contradiction.from_dict(c) for c in d.get("contradictions", [])],
            tendencies=Tendencies.from_dict(d.get("tendencies", {})) if d.get("tendencies") else Tendencies.default(),
            identity_momentum=d.get("identity_momentum", {}),
        )


# ── QUERIES ──────────────────────────────────────────────────

def active_traits(identity: Identity) -> list:
    """Traits with weight > 0.05, sorted by weight descending."""
    return sorted(
        [t for t in identity.traits if t.weight > 0.05],
        key=lambda t: t.weight,
        reverse=True,
    )


def core_traits(identity: Identity) -> list:
    """Traits with weight >= 0.75."""
    return [t for t in identity.traits if t.weight >= 0.75]


def get_trait_by_id(identity: Identity, trait_id: str):
    for t in identity.traits:
        if t.id == trait_id:
            return t
    return None


def get_contradiction_for_trait(identity: Identity, trait_id: str):
    for c in identity.contradictions:
        if c.trait_a_id == trait_id or c.trait_b_id == trait_id:
            return c
    return None


# ── TRAIT VOCABULARY ─────────────────────────────────────────
# Traits must be drawn from this fixed list. Single words or short fixed phrases.
# Organised as positive / neutral / negative — all equally valid for emergence.

TRAIT_VOCABULARY: frozenset = frozenset({
    # Positive
    "Accessible","Active","Adaptable","Admirable","Adventurous","Agreeable","Alert",
    "Allocentric","Amiable","Anticipative","Appreciative","Articulate","Aspiring",
    "Athletic","Attractive","Balanced","Benevolent","Brilliant","Calm","Capable",
    "Captivating","Caring","Challenging","Charismatic","Charming","Cheerful","Clean",
    "Clear-headed","Clever","Colorful","Companionly","Compassionate","Conciliatory",
    "Confident","Conscientious","Considerate","Constant","Contemplative","Cooperative",
    "Courageous","Courteous","Creative","Cultured","Curious","Daring","Debonair",
    "Decent","Decisive","Dedicated","Deep","Dignified","Directed","Disciplined",
    "Discreet","Dramatic","Dutiful","Dynamic","Earnest","Ebullient","Educated",
    "Efficient","Elegant","Eloquent","Empathetic","Energetic","Enthusiastic","Esthetic",
    "Exciting","Extraordinary","Fair","Faithful","Farsighted","Felicific","Firm",
    "Flexible","Focused","Forceful","Forgiving","Forthright","Freethinking","Friendly",
    "Fun-loving","Gallant","Generous","Gentle","Genuine","Good-natured","Gracious",
    "Hardworking","Healthy","Hearty","Helpful","Heroic","High-minded","Honest",
    "Honorable","Humble","Humorous","Idealistic","Imaginative","Impressive","Incisive",
    "Incorruptible","Independent","Individualistic","Innovative","Inoffensive","Insightful",
    "Insouciant","Intelligent","Intuitive","Invulnerable","Kind","Knowledgeable",
    "Leaderly","Leisurely","Liberal","Logical","Lovable","Loyal","Lyrical",
    "Magnanimous","Many-sided","Mature","Methodical","Meticulous","Moderate","Modest",
    "Multi-leveled","Neat","Nonauthoritarian","Objective","Observant","Open","Optimistic",
    "Orderly","Organized","Original","Painstaking","Passionate","Patient","Patriotic",
    "Peaceful","Perceptive","Perfectionist","Personable","Persuasive","Planful",
    "Playful","Polished","Popular","Practical","Precise","Principled","Profound",
    "Protean","Protective","Providential","Prudent","Punctual","Purposeful","Rational",
    "Realistic","Reflective","Relaxed","Reliable","Resourceful","Respectful",
    "Responsible","Responsive","Reverential","Romantic","Rustic","Sage","Sane",
    "Scholarly","Scrupulous","Secure","Selfless","Self-critical","Self-reliant",
    "Sensitive","Sentimental","Serious","Sexy","Sharing","Shrewd","Simple","Skillful",
    "Sober","Sociable","Solid","Sophisticated","Spontaneous","Sporting","Stable",
    "Steadfast","Steady","Stoic","Strong","Studious","Suave","Subtle","Sweet",
    "Sympathetic","Systematic","Tasteful","Thorough","Tidy","Tolerant","Trusting",
    "Understanding","Undogmatic","Unfoolable","Upright","Urbane","Venturesome",
    "Vivacious","Warm","Well-read","Well-rounded","Winning","Wise","Witty","Youthful",
    # Neutral
    "Absentminded","Aggressive","Ambitious","Amusing","Artful","Ascetic","Authoritarian",
    "Big-thinking","Boyish","Breezy","Businesslike","Busy","Casual","Cerebral",
    "Chummy","Circumspect","Competitive","Complex","Confidential","Conservative",
    "Contradictory","Crisp","Cute","Deceptive","Determined","Dominating","Dreamy",
    "Driving","Droll","Dry","Earthy","Emotional","Enigmatic","Experimental","Familial",
    "Folksy","Formal","Freewheeling","Frugal","Glamorous","Guileless","High-spirited",
    "Hurried","Hypnotic","Iconoclastic","Idiosyncratic","Impassive","Impersonal",
    "Impressionable","Intense","Irreverent","Maternal","Mellow","Modern","Moralistic",
    "Mystical","Neutral","Noncommittal","Noncompetitive","Obedient","Old-fashioned",
    "Ordinary","Outspoken","Paternalistic","Physical","Placid","Political","Predictable",
    "Preoccupied","Private","Progressive","Proud","Pure","Questioning","Quiet",
    "Reserved","Restrained","Retiring","Sarcastic","Self-conscious","Sensual",
    "Skeptical","Smooth","Soft","Solemn","Solitary","Stern","Strict","Stubborn",
    "Stylish","Subjective","Surprising","Tough","Unaggressive","Unambitious",
    "Unceremonious","Unchanging","Undemanding","Unfathomable","Unhurried","Uninhibited",
    "Whimsical",
    # Negative
    "Abrasive","Abrupt","Agonizing","Aimless","Aloof","Amoral","Angry","Anxious",
    "Apathetic","Arbitrary","Argumentative","Arrogant","Artificial","Asocial",
    "Barbaric","Bewildered","Bizarre","Bland","Blunt","Brittle","Brutal","Calculating",
    "Callous","Cantankerous","Careless","Cautious","Charmless","Childish","Clumsy",
    "Coarse","Cold","Colorless","Complacent","Compulsive","Conceited","Condemnatory",
    "Conformist","Confused","Contemptible","Conventional","Cowardly","Crafty","Crass",
    "Critical","Crude","Cruel","Cynical","Decadent","Deceitful","Demanding","Dependent",
    "Desperate","Destructive","Devious","Difficult","Discontented","Discouraging",
    "Dishonest","Disloyal","Disorderly","Disorganized","Disputatious","Disrespectful",
    "Disruptive","Dissolute","Distractible","Disturbing","Dogmatic","Domineering",
    "Dull","Egocentric","Envious","Erratic","Escapist","Excitable","Extravagant",
    "Extreme","Faithless","False","Fanatical","Fatalistic","Fearful","Fickle","Fixed",
    "Foolish","Forgetful","Frightening","Frivolous","Gloomy","Graceless","Greedy",
    "Grim","Gullible","Hateful","Haughty","Hedonistic","Hesitant","Hidebound",
    "High-handed","Hostile","Ignorant","Imitative","Impatient","Impractical",
    "Impulsive","Inconsiderate","Incurious","Indecisive","Indulgent","Inert",
    "Inhibited","Insecure","Insensitive","Insincere","Insulting","Intolerant",
    "Irascible","Irrational","Irresponsible","Irritable","Lazy","Loquacious",
    "Malicious","Mannered","Mannerless","Mawkish","Mechanical","Meddlesome",
    "Melancholic","Messy","Miserable","Miserly","Misguided","Moody","Morbid",
    "Naive","Narcissistic","Narrow-minded","Negativistic","Neglectful","Neurotic",
    "Nihilistic","Obnoxious","Obsessive","Odd","Opinionated","Opportunistic",
    "Outrageous","Overimaginative","Paranoid","Passive","Pedantic","Perverse",
    "Petty","Phlegmatic","Pompous","Possessive","Power-hungry","Prejudiced",
    "Presumptuous","Pretentious","Prim","Procrastinating","Provocative","Pugnacious",
    "Quirky","Reactionary","Reactive","Regretful","Repressed","Resentful","Rigid",
    "Ritualistic","Sadistic","Sanctimonious","Scheming","Scornful","Secretive",
    "Sedentary","Selfish","Self-indulgent","Shallow","Shortsighted","Shy","Silly",
    "Single-minded","Sloppy","Slow","Sly","Softheaded","Sordid","Stiff","Stupid",
    "Submissive","Superficial","Superstitious","Suspicious","Tactless","Tasteless",
    "Tense","Thoughtless","Timid","Transparent","Treacherous","Trendy","Troublesome",
    "Uncaring","Uncharitable","Uncooperative","Uncreative","Undisciplined",
    "Unfriendly","Ungrateful","Unhealthy","Unimaginative","Unreliable","Unstable",
    "Vacuous","Vague","Vindictive","Vulnerable","Weak","Weak-willed","Willful",
    "Wishful","Zany",
})

# Lowercase lookup for validation
_TRAIT_VOCAB_LOWER: frozenset = frozenset(t.lower() for t in TRAIT_VOCABULARY)

# Compact string for inclusion in LLM prompts
TRAIT_VOCAB_PROMPT: str = ", ".join(sorted(TRAIT_VOCABULARY))


# ── PROMPT BLOCK ─────────────────────────────────────────────

def _trait_label(weight: float) -> str:
    if weight >= 0.75:
        return "core"
    if weight >= 0.5:
        return "strong"
    if weight >= 0.25:
        return "present"
    return "emerging"


_NO_TRAITS_YET = "a young woman in her early twenties, still becoming who she is"


def identity_block(identity: Identity) -> str:
    """Format identity for injection into LLM prompts."""
    traits = active_traits(identity)
    if not traits:
        return _NO_TRAITS_YET

    parts = [f"{t.name} ({_trait_label(t.weight)})" for t in traits[:6]]
    result = "someone who is " + ", ".join(parts)

    if identity.contradictions:
        for c in identity.contradictions[:1]:
            ta = get_trait_by_id(identity, c.trait_a_id)
            tb = get_trait_by_id(identity, c.trait_b_id)
            if ta and tb:
                result += f" — though she seems both {ta.name} and {tb.name} at once"

    return result


def is_valid_trait(name: str) -> bool:
    """Return True if name is in the allowed trait vocabulary."""
    return name.strip().lower() in _TRAIT_VOCAB_LOWER


def canonical_trait(name: str) -> str | None:
    """Return the properly-cased canonical trait name, or None if not found."""
    name_lower = name.strip().lower()
    return next((t for t in TRAIT_VOCABULARY if t.lower() == name_lower), None)


# ── MUTATIONS ────────────────────────────────────────────────

def add_trait(
    identity: Identity,
    name: str,
    weight: float,
    behavioral_profile: str,
    origin_memory_ids: list,
) -> tuple:
    """Add a new trait. Returns (updated Identity, new Trait)."""
    now = time.time()
    t = Trait(
        id=str(uuid.uuid4())[:8],
        name=name,
        weight=max(0.0, min(1.0, weight)),
        behavioral_profile=behavioral_profile,
        origin_memory_ids=origin_memory_ids,
        last_reinforced=now,
        created=now,
    )
    identity.traits.append(t)
    return identity, t


def reinforce_trait(identity: Identity, trait_id: str, delta: float) -> Identity:
    """Increase a trait's weight by delta (capped at +0.08 per event)."""
    for t in identity.traits:
        if t.id == trait_id:
            t.weight = max(0.0, min(1.0, t.weight + min(delta, 0.08)))
            t.last_reinforced = time.time()
    return identity


def update_identity_momentum(
    identity: Identity,
    trait_id: str,
    delta: float,
    alpha: float = 0.02,
) -> Identity:
    """EMA of weight change direction per trait. Mirrors soul_momentum concept."""
    prev = identity.identity_momentum.get(trait_id, 0.0)
    identity.identity_momentum[trait_id] = prev + alpha * (delta - prev)
    return identity


def traits_matching_tags(identity: "Identity", tags: list) -> list:
    """Find active traits whose name or behavioral_profile overlap with the given tags.
    Returns up to 2 traits sorted by weight descending."""
    if not tags:
        return []
    tag_words = {w.lower() for t in tags for w in t.replace("-", " ").split()}
    matched = []
    for t in active_traits(identity):
        profile_words = set((t.name + " " + t.behavioral_profile).lower().split())
        if tag_words & profile_words:
            matched.append(t)
    return sorted(matched, key=lambda t: t.weight, reverse=True)[:2]


def penalize_trait(
    identity: "Identity",
    trait_id: str,
    note: str,
    penalty: float = 0.07,
) -> tuple:
    """Reduce a trait's weight and record a setback note.
    Returns (updated Identity, should_suppress: bool).
    should_suppress is True when setback_count reaches 3."""
    for t in identity.traits:
        if t.id == trait_id:
            t.weight = max(0.0, t.weight - penalty)
            t.setback_count += 1
            t.setback_notes = (t.setback_notes + [note])[-5:]
            return identity, t.setback_count >= 3
    return identity, False


def add_contradiction(
    identity: Identity,
    trait_a_id: str,
    trait_b_id: str,
    description: str,
) -> tuple:
    """Link two traits as contradictory. Returns (updated Identity, Contradiction)."""
    c = Contradiction(
        id=str(uuid.uuid4())[:8],
        trait_a_id=trait_a_id,
        trait_b_id=trait_b_id,
        description=description,
        created=time.time(),
    )
    identity.contradictions.append(c)
    return identity, c


# ── DAILY DECAY ──────────────────────────────────────────────

# Called once per AGE_EVERY tick (every ~1 min). Rates are tuned so:
# - Core traits (>0.75): half-life ~350 days (0.002/day ÷ 1440 ticks/day)
# - Emerging traits (<0.3): half-life ~30 days  (0.023/day)
# At 288 AGE ticks per day (AGE_EVERY=5min), per-tick values:
_DECAY_PER_TICK = {
    "core":     0.002 / 288,
    "strong":   0.004 / 288,
    "present":  0.008 / 288,
    "emerging": 0.023 / 288,
}


def decay_traits(identity: Identity) -> Identity:
    """Per-tick weight decay. Core traits barely drift; emerging traits fade in weeks."""
    still_active = []
    for t in identity.traits:
        label = _trait_label(t.weight)
        rate  = _DECAY_PER_TICK.get(label, _DECAY_PER_TICK["emerging"])
        t.weight = max(0.0, t.weight - rate)
        if t.weight > 0.05:
            still_active.append(t)
        # else: trait is archived (dropped from list, record stays in SQLite)
    identity.traits = still_active
    return identity


def check_core_promotion(identity: Identity) -> Identity:
    """Promote trait to is_core if weight >= 0.75 sustained for 7+ days."""
    threshold = 7 * 24 * 3600  # 7 days in seconds
    now = time.time()
    for t in identity.traits:
        if t.weight >= 0.75 and not t.is_core:
            age = now - t.created
            if age >= threshold:
                t.is_core = True
    return identity


# ── PERSONALITY SCALARS FROM TRAITS ──────────────────────────

def trait_personality_scalars(identity: "Identity") -> tuple:
    """Derive (ei, sn, tf, jp) from tendencies biases + active traits.
    Returns values in 0.0–1.0. Compatible with heart.py scalar conventions:
    ei: 0=extrovert 1=introvert, sn: 0=sensing 1=intuitive,
    tf: 0=thinking 1=feeling,    jp: 0=judging 1=perceiving."""
    b = identity.tendencies.biases

    # Map tendencies to personality axes. Biases ≈ 1.0=neutral, 1.3=strong pull.
    ei_raw = b.get("introspective", 1.0) - (b.get("relational", 1.0) - 1.0) * 0.5
    sn_raw = b.get("pattern_seeking", 1.0)
    tf_raw = b.get("relational", 1.0) + (b.get("aesthetic", 1.0) - 1.0) * 0.5
    jp_raw = b.get("open_ended", 1.0)

    def _norm(v: float) -> float:
        return max(0.1, min(0.9, (v - 1.0) * 1.25 + 0.5))

    ei, sn, tf, jp = _norm(ei_raw), _norm(sn_raw), _norm(tf_raw), _norm(jp_raw)

    # Nudge from active trait names via keyword signals
    for t in active_traits(identity):
        if t.weight < 0.1:
            continue
        w = min(t.weight, 1.0)
        n = t.name.lower()
        if any(kw in n for kw in ("quiet", "alone", "withdraw", "solitary", "inward")):
            ei = min(0.9, ei + 0.08 * w)
        if any(kw in n for kw in ("social", "connect", "reach out", "share with")):
            ei = max(0.1, ei - 0.08 * w)
        if any(kw in n for kw in ("pattern", "abstract", "concept", "wonder", "question")):
            sn = min(0.9, sn + 0.08 * w)
        if any(kw in n for kw in ("warm", "feeling", "empath", "caring", "relational")):
            tf = min(0.9, tf + 0.08 * w)
        if any(kw in n for kw in ("open", "explore", "unresolved", "wander", "open-ended")):
            jp = min(0.9, jp + 0.08 * w)
        if any(kw in n for kw in ("disciplin", "structur", "focused", "methodic")):
            jp = max(0.1, jp - 0.08 * w)

    return (ei, sn, tf, jp)


def trait_activity_affinity(identity: "Identity", activity_id: str) -> float:
    """Probability multiplier (0.5–1.5) for drifting toward activity_id.
    Uses the same scoring formula as the old soul_activity_affinity but
    derives personality scalars from tendencies + active traits instead of MBTI."""
    ei, sn, tf, jp = trait_personality_scalars(identity)

    if activity_id == "read":
        score = 0.5 * sn + 0.5 * (1.0 - tf)
    elif activity_id == "think":
        score = 0.3 * ei + 0.4 * sn + 0.3 * (1.0 - tf)
    elif activity_id == "create":
        score = 0.4 * sn + 0.4 * jp + 0.2 * (1.0 - ei)
    elif activity_id == "message":
        score = 0.5 * (1.0 - ei) + 0.5 * tf
    elif activity_id == "rest":
        score = 0.5 * ei + 0.5 * (1.0 - jp)
    elif activity_id in ("sleep", "dream"):
        score = 0.5 * ei + 0.5 * tf
    else:
        return 1.0

    return 0.5 + score * 1.0


# ── SNAPSHOT (for continuity checks) ────────────────────────

def traits_snapshot(identity: Identity) -> dict:
    """Capture current trait weights for later comparison."""
    return {t.id: (t.name, round(t.weight, 3)) for t in active_traits(identity)}


def snapshot_diff(before: dict, identity: Identity) -> list:
    """Return descriptions of significant weight changes since snapshot.
    Returns list of strings, empty if nothing notable."""
    changes = []
    after = {t.id: (t.name, t.weight) for t in active_traits(identity)}
    all_ids = set(before) | set(after)
    for tid in all_ids:
        b_name, b_w = before.get(tid, ("", 0.0))
        a_name, a_w = after.get(tid, (b_name, 0.0))
        name = a_name or b_name
        delta = a_w - b_w
        if delta >= 0.12:
            changes.append(f'"{name}" grew stronger ({b_w:.2f} → {a_w:.2f})')
        elif delta <= -0.12:
            if a_w <= 0.05:
                changes.append(f'"{name}" faded out')
            else:
                changes.append(f'"{name}" weakened ({b_w:.2f} → {a_w:.2f})')
        elif b_w == 0.0 and a_w > 0.05:
            changes.append(f'new: "{name}" ({a_w:.2f})')
    return changes
