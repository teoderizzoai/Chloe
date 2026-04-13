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
    nodes = [
        Node(id="root", label="Chloe", depth=0, strength=1.0, fixed=True, x=0, y=0),
        
        # --- THE 10 HUMAN PILLARS ---
        
        # 1. Soundscape (Spotify, YouTube, background noise)
        Node(id="p1", label="Music & Audio", depth=1, strength=0.8),
        
        # 2. Visual Style (Art, UI design, "Does this look good?")
        Node(id="p2", label="Aesthetics & Design", depth=1, strength=0.7),
        
        # 3. The Daily Bread (Cooking, ordering in, caffeine intake)
        Node(id="p3", label="Food & Drink", depth=1, strength=0.7),
        
        # 4. Digital Playground (Gaming, Steam, late-night play)
        Node(id="p4", label="Games & Play", depth=1, strength=0.9),
        
        # 5. The Grind (Coding, writing, spreadsheets, "The Mission")
        Node(id="p5", label="Work & Ambition", depth=1, strength=0.8),
        
        # 6. Rabbit Holes (Wikipedia, random facts, learning new stuff)
        Node(id="p6", label="Curiosity & Learning", depth=1, strength=0.7),
        
        # 7. Physical World (Weather, travel, "The Outside")
        Node(id="p7", label="Nature & Places", depth=1, strength=0.6),
        
        # 8. Human Connection (Social media, chat, "What are they thinking?")
        Node(id="p8", label="Social & People", depth=1, strength=0.7),
        
        # 9. Wellness (Sleep schedules, stress levels, "Take a breath")
        Node(id="p9", label="Health & Rest", depth=1, strength=0.6),
        
        # 10. Tech & Future (AI, gadgets, the tools we use)
        Node(id="p10", label="Technology & Tools", depth=1, strength=0.7),
    ]
    
    edges = [Edge(source="root", target=n.id) for n in nodes if n.id != "root"]
    return Graph(nodes=nodes, edges=edges)


# ── MUTATIONS ────────────────────────────────────────────────

def expand(graph: Graph, parent_id: str, new_node_defs: list[dict]) -> Graph:
    """Add LLM-generated nodes branching from a parent node.
    new_node_defs: [{"id": ..., "label": ..., "note": ...}]"""
    parent = _find_node(graph, parent_id)
    if not parent:
        return graph

    angle_offset = random.uniform(0, 2 * math.pi)
    new_nodes: list[Node] = []
    new_edges: list[Edge] = []

    for i, defn in enumerate(new_node_defs):
        angle = angle_offset + (i / len(new_node_defs)) * 2 * math.pi
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


def node_exists(graph: Graph, label: str) -> bool:
    return any(n.label.lower() == label.lower() for n in graph.nodes)


# ── HELPERS ──────────────────────────────────────────────────

def _find_node(graph: Graph, node_id: str) -> Node | None:
    return next((n for n in graph.nodes if n.id == node_id), None)
