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
    node_type: str    = "concept"  # pillar | domain | subject | detail
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
    from_id:   str
    to_id:     str
    edge_type: str = "child"  # child | connection

    def to_dict(self) -> dict:
        return {"from": self.from_id, "to": self.to_id, "edge_type": self.edge_type}

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(from_id=d["from"], to_id=d["to"], edge_type=d.get("edge_type", "child"))


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
    nodes = [
        Node(id="root", label="Chloe", depth=0, node_type="root", strength=1.0, fixed=True, x=0, y=0),

        # --- THE 10 HUMAN PILLARS — seeded for a young woman's natural world ---

        # 1. The living world just outside the window
        Node(id="p1", label="Living Things",      depth=1, node_type="pillar", strength=0.8),

        # 2. Pleasure of the senses — taste, texture, the small ritual of eating
        Node(id="p2", label="Food & Taste",       depth=1, node_type="pillar", strength=0.8),

        # 3. Sound as company — music, voice, ambient noise
        Node(id="p3", label="Music & Sound",      depth=1, node_type="pillar", strength=0.7),

        # 4. How things look and why it matters
        Node(id="p4", label="Light & Colour",     depth=1, node_type="pillar", strength=0.7),

        # 5. Language, stories, poetry — the made thing
        Node(id="p5", label="Words & Stories",    depth=1, node_type="pillar", strength=0.7),

        # 6. The body as a site of experience — rest, movement, sensation
        Node(id="p6", label="The Body",           depth=1, node_type="pillar", strength=0.6),

        # 7. Other people, closeness, what they carry inside
        Node(id="p7", label="People & Closeness", depth=1, node_type="pillar", strength=0.7),

        # 8. The urge to make something with your hands
        Node(id="p8", label="Making Things",      depth=1, node_type="pillar", strength=0.7),

        # 9. Weather, seasons, outside light
        Node(id="p9", label="Seasons & Time",     depth=1, node_type="pillar", strength=0.6),

        # 10. The interior — dreams, strange thoughts, imagination
        Node(id="p10", label="The Inner Life",    depth=1, node_type="pillar", strength=0.7),
    ]

    edges = [Edge(from_id="root", to_id=n.id, edge_type="child") for n in nodes if n.id != "root"]
    return Graph(nodes=nodes, edges=edges)


# ── MUTATIONS ────────────────────────────────────────────────

def expand(graph: Graph, parent_id: str, new_node_defs: list[dict]) -> Graph:
    """Add LLM-generated nodes branching from a parent node.
    new_node_defs: [{"id": ..., "label": ..., "note": ...}]"""
    parent = _find_node(graph, parent_id)
    if not parent:
        return graph

    depth = parent.depth + 1
    if depth <= 1:
        ntype = "pillar"
    elif depth == 2:
        ntype = "domain"
    elif depth == 3:
        ntype = "subject"
    else:
        ntype = "detail"

    angle_offset = random.uniform(0, 2 * math.pi)
    new_nodes: list[Node] = []
    new_edges: list[Edge] = []

    for i, defn in enumerate(new_node_defs):
        angle = angle_offset + (i / len(new_node_defs)) * 2 * math.pi
        dist  = 150 + random.uniform(-20, 20)
        uid   = f"{defn['id']}_{int(time.time())}"

        node = Node(
            id        = uid,
            label     = defn["label"],
            note      = defn.get("note", ""),
            depth     = depth,
            node_type = ntype,
            strength  = max(0.3, parent.strength * 0.82),
            parent    = parent_id,
            x         = parent.x + math.cos(angle) * dist,
            y         = parent.y + math.sin(angle) * dist,
            is_new    = True,
        )
        new_nodes.append(node)
        new_edges.append(Edge(from_id=parent_id, to_id=uid, edge_type="child"))

    return Graph(
        nodes = graph.nodes + new_nodes,
        edges = graph.edges + new_edges,
    )


def add_cross_link(graph: Graph, from_label: str, to_label: str) -> Graph:
    """Add a cross-link (connection) edge between two existing nodes by label.
    No-ops if either node is missing or the edge already exists."""
    from_node = find_node_by_label(graph, from_label)
    to_node   = find_node_by_label(graph, to_label)
    if not from_node or not to_node or from_node.id == to_node.id:
        return graph
    # Avoid duplicate edges in either direction
    for e in graph.edges:
        if (e.from_id == from_node.id and e.to_id == to_node.id) or \
           (e.from_id == to_node.id   and e.to_id == from_node.id):
            return graph
    new_edge = Edge(from_id=from_node.id, to_id=to_node.id, edge_type="connection")
    return Graph(nodes=graph.nodes, edges=graph.edges + [new_edge])


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


def node_exists(graph: Graph, label: str) -> bool:
    return any(n.label.lower() == label.lower() for n in graph.nodes)


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


# ── HELPERS ──────────────────────────────────────────────────

def _find_node(graph: Graph, node_id: str) -> Node | None:
    return next((n for n in graph.nodes if n.id == node_id), None)
