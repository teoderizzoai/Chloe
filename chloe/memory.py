# chloe/memory.py
# ─────────────────────────────────────────────────────────────
# Chloe's memory system.
#
# Memories are fragments — impressions, not transcripts.
# They are distilled, partial, sometimes emotionally coloured.
# Older memories fade. Recent ones are vivid.
# Interests emerge from what she remembers most.
# ─────────────────────────────────────────────────────────────

import time
import math
import uuid
import random
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional, Union

MemoryType = Literal["observation", "conversation", "idea", "feeling", "interest", "dream", "creative"]


# ── IDEA ─────────────────────────────────────────────────────

@dataclass
class Idea:
    text:      str
    timestamp: float     = field(default_factory=time.time)
    tags:      list[str] = field(default_factory=list)
    id:        str       = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Union[str, dict]) -> "Idea":
        if isinstance(d, str):          # migrate old plain-string ideas
            return cls(text=d)
        return cls(
            text=d["text"],
            timestamp=float(d.get("timestamp", time.time())),
            tags=d.get("tags", []),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


MAX_IDEAS = 20  # kept for reference; cap no longer applied (SQLite is unbounded)

def ideas_to_dicts(ideas: list["Idea"]) -> list[dict]:
    return [i.to_dict() for i in ideas]

def ideas_from_dicts(data: list) -> list["Idea"]:
    return [Idea.from_dict(d) for d in data]


@dataclass
class Memory:
    text:       str
    type:       MemoryType       = "observation"
    tags:       list[str]        = field(default_factory=list)
    weight:     float            = 1.0       # 0.0–1.0, decays over time
    confidence: float            = 1.0       # item 69: how sure she is of this memory
    timestamp:  float            = field(default_factory=time.time)
    id:         str              = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Memory":
        return cls(
            text=d["text"], type=d["type"], tags=d.get("tags", []),
            weight=float(d.get("weight", 1.0)),
            confidence=float(d.get("confidence", 1.0)),  # default 1.0 for old records
            timestamp=float(d.get("timestamp", time.time())),
            id=d.get("id", str(uuid.uuid4())[:8]),
        )


# ── SEED MEMORIES ────────────────────────────────────────────

def seed_memories() -> list[Memory]:
    return []


# ── STORE OPERATIONS ─────────────────────────────────────────

MAX_MEMORIES = 200

def add(store: list[Memory], text: str,
        type: MemoryType = "observation",
        tags: list[str] | None = None) -> list[Memory]:
    """Prepend a new memory. No cap — SQLite is unbounded."""
    m = Memory(text=text, type=type, tags=tags or [], weight=1.0)
    return [m, *store]


def age(store: list[Memory]) -> list[Memory]:
    """Decay every memory's weight and confidence slightly.
    Call this periodically (e.g. every few minutes or on sleep)."""
    return [
        Memory(**{**m.to_dict(),
                  "weight":     max(0.05, m.weight     * 0.997),
                  "confidence": max(0.10, m.confidence * 0.998)})
        for m in store
    ]


def get_vivid(store: list[Memory], n: int = 5) -> list[Memory]:
    """Return the N most vivid memories — weighted by strength × recency."""
    scored = sorted(store, key=lambda m: m.weight * _recency(m.timestamp), reverse=True)
    return scored[:n]



def derive_interests(store: list[Memory], top_n: int = 10) -> list[str]:
    """Return a balanced interest list — dominant interests plus emerging ones.

    The top half of slots go to the strongest tags (deepening).
    The remaining slots are sampled randomly from the mid-tier (exploration),
    so that LLM prompts don't become an echo chamber of the same few concepts.
    """
    tally: dict[str, float] = {}
    for m in store:
        for tag in m.tags:
            tally[tag] = tally.get(tag, 0.0) + m.weight
    ranked = sorted(tally.items(), key=lambda x: x[1], reverse=True)

    if len(ranked) <= top_n:
        return [tag for tag, _ in ranked]

    # Dominant interests — the top half of requested slots
    deep_n  = max(1, top_n // 2)
    deep    = [tag for tag, _ in ranked[:deep_n]]

    # Emerging interests — randomly sampled from the mid-tier (positions deep_n … top_n*4)
    # Wide window so genuinely novel tags have a chance to surface
    fringe_pool = [tag for tag, _ in ranked[deep_n : top_n * 4]]
    fringe = random.sample(fringe_pool, min(top_n - deep_n, len(fringe_pool)))

    return deep + fringe


def derive_fringe_interests(store: list[Memory], n: int = 6) -> list[str]:
    """Return only lower-weight tags — used during exploration reads to send
    Chloe toward topics she has barely touched rather than her dominant ones."""
    tally: dict[str, float] = {}
    for m in store:
        for tag in m.tags:
            tally[tag] = tally.get(tag, 0.0) + m.weight
    ranked = sorted(tally.items(), key=lambda x: x[1], reverse=True)

    # Skip the dominant top third, sample from the rest
    skip = max(1, len(ranked) // 3)
    pool = [tag for tag, _ in ranked[skip:]]
    if not pool:
        pool = [tag for tag, _ in ranked]
    return random.sample(pool, min(n, len(pool)))


_UNCERTAIN_PREFIXES = ["I think ", "I'm not sure but ", "Something like, ", "Maybe, "]

def format_for_prompt(memories: list[Memory]) -> str:
    """Compact string for injecting memories into an LLM prompt.
    Item 69: low-confidence memories are prefixed with uncertainty phrasing."""
    lines = []
    for m in memories:
        if m.confidence < 0.5:
            prefix = random.choice(_UNCERTAIN_PREFIXES)
            lines.append(f"[{m.type}] {prefix}{m.text}")
        else:
            lines.append(f"[{m.type}] {m.text}")
    return "\n".join(lines)


def to_dicts(store: list[Memory]) -> list[dict]:
    return [m.to_dict() for m in store]


def from_dicts(data: list[dict]) -> list[Memory]:
    return [Memory.from_dict(d) for d in data]


# ── helper ───────────────────────────────────────────────────

def _recency(timestamp: float) -> float:
    """Score between 0–1 based on how recent a memory is. Decays over ~3 days."""
    age_days = (time.time() - timestamp) / 86400
    return math.exp(-age_days * 0.3)


# ── SEMANTIC INDEX ────────────────────────────────────────────

class MemoryIndex:
    """ChromaDB-backed semantic index over the memory store.
    Degrades gracefully to get_vivid if chromadb is not installed."""

    def __init__(self, persist_dir: str):
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._col    = self._client.get_or_create_collection("memories")
            self._ok     = True
        except Exception as e:
            print(f"[memory_index] chromadb unavailable, falling back to get_vivid: {e}")
            self._ok = False

    def add(self, memory: Memory) -> None:
        if not self._ok:
            return
        try:
            self._col.upsert(
                ids=[memory.id],
                documents=[memory.text],
                metadatas=[{"type": memory.type, "tags": ",".join(memory.tags)}],
            )
        except Exception:
            pass

    def sync(self, store: list[Memory]) -> None:
        """Index any memories not already present (idempotent, called after load)."""
        if not self._ok or not store:
            return
        try:
            existing = set(self._col.get(include=[])["ids"])
            for m in store:
                if m.id not in existing:
                    self.add(m)
        except Exception:
            pass

    def query(self, text: str, store: list[Memory], n: int = 5) -> list[Memory]:
        """Return the n memories most semantically relevant to text,
        reranked by similarity × freshness so old/faded memories don't
        crowd out more recent ones on the same topic."""
        if not self._ok or not store:
            return get_vivid(store, n)
        try:
            k       = min(n * 3, len(store))   # fetch 3× candidates, then rerank
            results = self._col.query(query_texts=[text], n_results=k,
                                      include=["distances"])
            by_id   = {m.id: m for m in store}
            ids     = results["ids"][0]
            dists   = results["distances"][0]   # 0.0 = identical, 2.0 = opposite

            scored = []
            for id_, dist in zip(ids, dists):
                m = by_id.get(id_)
                if not m:
                    continue
                similarity = 1.0 - (dist / 2.0)
                freshness  = m.weight * _recency(m.timestamp) * m.confidence
                # similarity dominates; freshness can suppress but not eliminate
                score = similarity * (0.5 + 0.5 * freshness)
                scored.append((score, m))

            scored.sort(key=lambda x: x[0], reverse=True)
            found = [m for _, m in scored[:n]]
            return found if found else get_vivid(store, n)
        except Exception:
            return get_vivid(store, n)
