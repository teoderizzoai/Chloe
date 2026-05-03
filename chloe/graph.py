# chloe/graph.py
# ─────────────────────────────────────────────────────────────
# Chloe's interest graph.
#
# Nodes are concepts. Edges are connections between them.
# The graph expands when Chloe reads, thinks, or creates.
# Physics (force-directed layout) is handled in the frontend;
# this module manages the data structures and mutations only.
# ─────────────────────────────────────────────────────────────

import math
import random
import time
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class Node:
    id:       str
    label:    str
    depth:    int     = 0
    strength: float   = 1.0     # 0–1, decays with each generation
    parent:   str     = ""      # id of parent node, empty for root
    note:     str     = ""      # why Chloe cares about this
    x:        float   = 0.0     # layout position (set by frontend physics)
    y:        float   = 0.0
    fixed:    bool    = False   # root node is fixed at centre
    is_new:   bool    = False   # briefly True after insertion, for animation
    # Graph Intelligence (G1/G2) — organic growth tracking
    hit_count:          int   = 0    # times a memory tag matched this node
    last_auto_expanded: float = 0.0  # unix timestamp of last auto-expand
    last_reinforced:    float = 0.0  # item 72: unix timestamp of last hit_count increment

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Edge:
    from_id: str
    to_id:   str

    def to_dict(self) -> dict:
        return {"from": self.from_id, "to": self.to_id}

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(from_id=d["from"], to_id=d["to"])


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Graph":
        return cls(
            nodes=[Node.from_dict(n) for n in d.get("nodes", [])],
            edges=[Edge.from_dict(e) for e in d.get("edges", [])],
        )


# ── SEED GRAPH ───────────────────────────────────────────────

def seed_graph() -> Graph:
    """Start with just the root node. Interests emerge organically via G3/G4."""
    return Graph(
        nodes=[Node(id="root", label="Chloe", depth=0, strength=1.0, fixed=True, x=0, y=0)],
        edges=[],
    )


# ── MUTATIONS ────────────────────────────────────────────────

_ABSTRACT_WORDS = {
    "shadow", "dissolution", "surrender", "paradox", "threshold", "liminal",
    "archetype", "integration", "fragmentation", "suppression", "repression",
    "projection", "sublimation", "disintegration", "vulnerability", "visceral",
    "embodied", "somatic", "deconstruction", "infrastructure", "paradigm",
    "self-judgment", "consciousness", "mortality", "erasure", "dissolution",
    "bifurcation", "crystallisation", "crystallization", "stereotopic", "parallax",
}

MAX_NODE_DEPTH = 4  # hard cap on how deep the graph can grow


def _is_acceptable_label(label: str) -> bool:
    """Return False if a label contains abstract/psychological keywords or is too deep."""
    words = {w.strip("().,") for w in label.lower().split()}
    return not (words & _ABSTRACT_WORDS)


def expand(graph: Graph, parent_id: str, new_node_defs: list[dict]) -> Graph:
    """Add LLM-generated nodes branching from a parent node.
    new_node_defs: [{"id": ..., "label": ..., "note": ...}]
    Silently drops nodes with abstract/psychological labels or past MAX_NODE_DEPTH."""
    parent = _find_node(graph, parent_id)
    if not parent:
        return graph

    if parent.depth >= MAX_NODE_DEPTH:
        return graph

    angle_offset = random.uniform(0, 2 * math.pi)
    new_nodes: list[Node] = []
    new_edges: list[Edge] = []
    accepted = [d for d in new_node_defs if _is_acceptable_label(d.get("label", ""))]

    for i, defn in enumerate(accepted):
        angle = angle_offset + (i / max(len(accepted), 1)) * 2 * math.pi
        dist  = 150 + random.uniform(-20, 20)
        uid   = f"{defn['id']}_{int(time.time())}"

        node = Node(
            id       = uid,
            label    = defn["label"],
            note     = defn.get("note", ""),
            depth    = parent.depth + 1,
            strength = max(0.3, parent.strength * 0.82),
            parent   = parent_id,
            x        = parent.x + math.cos(angle) * dist,
            y        = parent.y + math.sin(angle) * dist,
            is_new   = True,
        )
        new_nodes.append(node)
        new_edges.append(Edge(from_id=parent_id, to_id=uid))

    return Graph(
        nodes = graph.nodes + new_nodes,
        edges = graph.edges + new_edges,
    )


def clear_new_flags(graph: Graph) -> Graph:
    """Strip is_new from all nodes (called after animation completes)."""
    return Graph(
        nodes=[Node(**{**n.to_dict(), "is_new": False}) for n in graph.nodes],
        edges=graph.edges,
    )


def remove_node(graph: Graph, node_id: str) -> Graph:
    """Remove a node and all its connected edges."""
    return Graph(
        nodes=[n for n in graph.nodes if n.id != node_id],
        edges=[e for e in graph.edges if e.from_id != node_id and e.to_id != node_id],
    )


def get_labels(graph: Graph) -> list[str]:
    """All current node labels — used to prevent duplicates when expanding."""
    return [n.label for n in graph.nodes]


# ── GRAPH INTELLIGENCE HELPERS ───────────────────────────────

def reinforce_node(graph: Graph, node_id: str) -> Graph:
    """G1: A memory tag matched this node — increment hit count, boost strength.
    Item 72: record when this reinforcement happened for attention bias."""
    new_nodes = []
    for n in graph.nodes:
        if n.id == node_id:
            n = Node(**{**n.to_dict(),
                        "hit_count":      n.hit_count + 1,
                        "strength":       min(1.0, n.strength + 0.02),
                        "last_reinforced": time.time()})
        new_nodes.append(n)
    return Graph(nodes=new_nodes, edges=graph.edges)


def match_nodes_by_tags(graph: Graph, tags: list[str]) -> list[Node]:
    """G1: Return nodes whose label appears (case-insensitive substring) in any tag,
    or any tag appears in the node label. Skips root."""
    matches: list[Node] = []
    tags_lower = [t.lower() for t in tags]
    for node in graph.nodes:
        if node.id == "root":
            continue
        label_lower = node.label.lower()
        if any(label_lower in t or t in label_lower for t in tags_lower):
            matches.append(node)
    return matches


def match_deep_nodes_for_message(graph: Graph, message: str, min_depth: int = 2) -> list[Node]:
    """Return depth >= min_depth nodes with notes whose label matches words in the message.
    Used to surface specific knowledge Chloe has genuinely traced during chat."""
    msg_lower = message.lower()
    matches = []
    for node in graph.nodes:
        if node.id == "root" or node.depth < min_depth or not node.note:
            continue
        label_lower = node.label.lower()
        if label_lower in msg_lower or any(w in label_lower for w in msg_lower.split() if len(w) > 3):
            matches.append(node)
    matches.sort(key=lambda n: n.hit_count, reverse=True)
    return matches[:3]


def get_leaf_nodes(graph: Graph) -> list[Node]:
    """G2: Nodes that have no outgoing edges (no children)."""
    parents = {e.from_id for e in graph.edges}
    return [n for n in graph.nodes if n.id not in parents]


def mark_auto_expanded(graph: Graph, node_id: str) -> Graph:
    """G2: Reset hit_count and record timestamp after auto-expansion."""
    new_nodes = []
    for n in graph.nodes:
        if n.id == node_id:
            n = Node(**{**n.to_dict(),
                        "hit_count": 0,
                        "last_auto_expanded": time.time()})
        new_nodes.append(n)
    return Graph(nodes=new_nodes, edges=graph.edges)


def find_node_by_label(graph: Graph, label: str) -> Node | None:
    """Find a node by exact or case-insensitive label match."""
    label_lower = label.lower()
    return next((n for n in graph.nodes if n.label.lower() == label_lower), None)


def graph_interests(graph: Graph, top_n: int = 6) -> list[str]:
    """Labels of the most reinforced/strongest non-root nodes.
    Used to bias reading, conversation, and prompts toward things
    Chloe has genuinely built up interest in, not just recently tagged."""
    candidates = sorted(
        [n for n in graph.nodes if n.id != "root"],
        key=lambda n: n.hit_count * 0.6 + n.strength * 0.4,
        reverse=True,
    )
    return [n.label for n in candidates[:top_n]]


# ── THINK EXPANSION ──────────────────────────────────────────

def pick_think_expansion_target(graph: Graph) -> "Node | None":
    """Return the best leaf node for deliberate think-time expansion.
    Scores by hit_count × recency of last reinforcement.
    Skips nodes expanded in the last 6 hours."""
    now = time.time()
    SIX_HOURS = 21600

    candidates = [
        n for n in get_leaf_nodes(graph)
        if n.id != "root"
        and n.hit_count >= 1
        and n.last_reinforced > 0
        and (now - n.last_auto_expanded) > SIX_HOURS
    ]

    if not candidates:
        return None

    def score(n: Node) -> float:
        recency = math.exp(-(now - n.last_reinforced) / 86400)  # decays over ~3 days
        return n.hit_count * recency

    return max(candidates, key=score)


# ── PROMPT CONTEXT ───────────────────────────────────────────

def graph_knowledge_context(graph: Graph, max_nodes: int = 6) -> str:
    """Return a compact string describing nodes at depth ≥ 3 with notes.
    These represent concepts Chloe has genuinely traced rather than just heard of."""
    deep = [
        n for n in graph.nodes
        if n.depth >= 3 and n.note and n.id != "root"
    ]
    if not deep:
        return ""
    deep.sort(key=lambda n: n.hit_count, reverse=True)
    lines = [f"{n.label} — {n.note}" for n in deep[:max_nodes]]
    return "Things she's genuinely traced:\n" + "\n".join(lines)


# ── DECAY ────────────────────────────────────────────────────

# At TICK_SECONDS=300, this rate means:
#   ~7.5% strength lost per day → node at 1.0 fades below 0.08 in ~30 days
#   node at 0.3 fades below 0.08 in ~16 days
# reinforce_node (+0.02 per hit) offsets ~1 hit every 3-4 days.
_DECAY_RATE_PER_TICK = 0.000266
_MIN_STRENGTH        = 0.08  # below this the node is pruned


def decay_graph(graph: Graph) -> Graph:
    """Per-tick strength decay for all non-root nodes.
    Nodes not reinforced will shrink and eventually be pruned.
    Pruning cascades: children of a pruned node are also removed."""

    # 1. Apply multiplicative decay; collect survivors
    decayed: list[Node] = []
    for n in graph.nodes:
        if n.id == "root":
            decayed.append(n)
            continue
        new_strength = n.strength * (1.0 - _DECAY_RATE_PER_TICK)
        if new_strength > _MIN_STRENGTH:
            decayed.append(Node(**{**n.to_dict(), "strength": new_strength}))

    # 2. BFS from root to prune disconnected subtrees
    surviving_ids = {n.id for n in decayed}
    edges_by_parent: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.from_id in surviving_ids and e.to_id in surviving_ids:
            edges_by_parent.setdefault(e.from_id, []).append(e.to_id)

    reachable: set[str] = set()
    queue = ["root"]
    while queue:
        nid = queue.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        queue.extend(edges_by_parent.get(nid, []))

    surviving_ids &= reachable
    return Graph(
        nodes=[n for n in decayed if n.id in surviving_ids],
        edges=[e for e in graph.edges
               if e.from_id in surviving_ids and e.to_id in surviving_ids],
    )


# ── HELPERS ──────────────────────────────────────────────────

def _find_node(graph: Graph, node_id: str) -> Node | None:
    return next((n for n in graph.nodes if n.id == node_id), None)
