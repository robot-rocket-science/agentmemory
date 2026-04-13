"""Experiment 80: Consistency Graph Analysis.

Analyzes the CONTRADICTS and SUPPORTS edge network to:
  1. Count contradicting statement pairs
  2. Find connected components in the edge graph
  3. Identify which components contain contradictions (inconsistent clusters)
  4. Measure cluster sizes and topology
  5. Prototype "maximal consistent subgraph" extraction

Success criteria:
  - Contradicting pairs identified and quantified
  - Connected components computed
  - At least one example of a consistent vs inconsistent cluster shown
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = str(
    Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class EdgeStats:
    total_edges: int
    by_type: dict[str, int]
    contradicting_pairs: list[tuple[str, str, str, str]]  # (from_id, to_id, from_content, to_content)
    supporting_pairs: int
    superseding_pairs: int


@dataclass
class Component:
    nodes: set[str]
    edges: list[tuple[str, str, str]]  # (from, to, type)
    has_contradiction: bool
    size: int

    @property
    def contradiction_count(self) -> int:
        return sum(1 for _, _, t in self.edges if t == "CONTRADICTS")


@dataclass
class GraphAnalysis:
    edge_stats: EdgeStats
    components: list[Component]
    total_nodes_in_graph: int
    total_beliefs_in_db: int
    orphan_count: int  # beliefs with no edges
    consistent_components: int
    inconsistent_components: int
    largest_component_size: int
    largest_inconsistent_size: int


# ---------------------------------------------------------------------------
# Union-Find for connected components
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for node in self.parent:
            groups[self.find(node)].append(node)
        return dict(groups)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_graph() -> GraphAnalysis:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    # Get edge stats
    cursor = conn.cursor()
    cursor.execute("SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type")
    by_type: dict[str, int] = {row["edge_type"]: row["COUNT(*)"] for row in cursor.fetchall()}
    total_edges: int = sum(by_type.values())

    # Get all edges
    cursor.execute("SELECT from_id, to_id, edge_type FROM edges")
    all_edges: list[tuple[str, str, str]] = [
        (row["from_id"], row["to_id"], row["edge_type"]) for row in cursor.fetchall()
    ]

    # Get contradicting pairs with content
    cursor.execute("""
        SELECT e.from_id, e.to_id, b1.content as from_content, b2.content as to_content
        FROM edges e
        JOIN beliefs b1 ON e.from_id = b1.id
        JOIN beliefs b2 ON e.to_id = b2.id
        WHERE e.edge_type = 'CONTRADICTS'
        AND b1.valid_to IS NULL AND b2.valid_to IS NULL
    """)
    contradicting_pairs: list[tuple[str, str, str, str]] = [
        (row["from_id"], row["to_id"], row["from_content"], row["to_content"])
        for row in cursor.fetchall()
    ]

    # Total beliefs
    cursor.execute("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL")
    total_beliefs: int = cursor.fetchone()[0]

    conn.close()

    edge_stats = EdgeStats(
        total_edges=total_edges,
        by_type=by_type,
        contradicting_pairs=contradicting_pairs,
        supporting_pairs=by_type.get("SUPPORTS", 0),
        superseding_pairs=by_type.get("SUPERSEDES", 0),
    )

    # Build connected components using union-find
    uf = UnionFind()
    edge_lookup: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for from_id, to_id, edge_type in all_edges:
        uf.union(from_id, to_id)
        edge_lookup[from_id].append((from_id, to_id, edge_type))
        edge_lookup[to_id].append((from_id, to_id, edge_type))

    raw_components = uf.components()
    nodes_in_graph: set[str] = set()
    for node_list in raw_components.values():
        nodes_in_graph.update(node_list)

    # Build Component objects
    components: list[Component] = []
    for _root, node_list in raw_components.items():
        node_set = set(node_list)
        component_edges: list[tuple[str, str, str]] = []
        seen_edges: set[tuple[str, str]] = set()
        for node in node_list:
            for edge in edge_lookup[node]:
                edge_key = (edge[0], edge[1])
                if edge_key not in seen_edges:
                    if edge[0] in node_set and edge[1] in node_set:
                        component_edges.append(edge)
                        seen_edges.add(edge_key)

        has_contradiction = any(t == "CONTRADICTS" for _, _, t in component_edges)
        components.append(Component(
            nodes=node_set,
            edges=component_edges,
            has_contradiction=has_contradiction,
            size=len(node_set),
        ))

    components.sort(key=lambda c: c.size, reverse=True)

    consistent = [c for c in components if not c.has_contradiction]
    inconsistent = [c for c in components if c.has_contradiction]

    return GraphAnalysis(
        edge_stats=edge_stats,
        components=components,
        total_nodes_in_graph=len(nodes_in_graph),
        total_beliefs_in_db=total_beliefs,
        orphan_count=total_beliefs - len(nodes_in_graph),
        consistent_components=len(consistent),
        inconsistent_components=len(inconsistent),
        largest_component_size=components[0].size if components else 0,
        largest_inconsistent_size=inconsistent[0].size if inconsistent else 0,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    results = analyze_graph()

    print("=" * 70)
    print("EXPERIMENT 80: CONSISTENCY GRAPH ANALYSIS")
    print("=" * 70)

    print(f"\n--- Edge Statistics ---")
    print(f"Total edges: {results.edge_stats.total_edges}")
    for etype, count in sorted(results.edge_stats.by_type.items(), key=lambda x: -x[1]):
        print(f"  {etype:>15}: {count}")

    print(f"\n--- Graph Coverage ---")
    coverage: float = results.total_nodes_in_graph / results.total_beliefs_in_db * 100
    print(f"Total active beliefs: {results.total_beliefs_in_db}")
    print(f"Nodes in edge graph:  {results.total_nodes_in_graph} ({coverage:.1f}%)")
    print(f"Orphans (no edges):   {results.orphan_count} ({100-coverage:.1f}%)")

    print(f"\n--- Connected Components ---")
    print(f"Total components:       {len(results.components)}")
    print(f"  Consistent (no contradictions): {results.consistent_components}")
    print(f"  Inconsistent (has contradictions): {results.inconsistent_components}")
    print(f"Largest component:      {results.largest_component_size} nodes")
    if results.largest_inconsistent_size > 0:
        print(f"Largest inconsistent:   {results.largest_inconsistent_size} nodes")

    # Size distribution
    sizes: list[int] = [c.size for c in results.components]
    if sizes:
        print(f"\nComponent size distribution:")
        buckets: dict[str, int] = {"1": 0, "2-5": 0, "6-20": 0, "21-100": 0, "100+": 0}
        for s in sizes:
            if s == 1:
                buckets["1"] += 1
            elif s <= 5:
                buckets["2-5"] += 1
            elif s <= 20:
                buckets["6-20"] += 1
            elif s <= 100:
                buckets["21-100"] += 1
            else:
                buckets["100+"] += 1
        for bucket, count in buckets.items():
            print(f"  {bucket:>8} nodes: {count} components")

    # Show contradicting pairs
    pairs = results.edge_stats.contradicting_pairs
    print(f"\n--- Contradicting Pairs ({len(pairs)} total) ---")
    for from_id, to_id, from_c, to_c in pairs[:10]:
        from_snippet: str = from_c[:80].replace("\n", " ")
        to_snippet: str = to_c[:80].replace("\n", " ")
        print(f"  [{from_id}] {from_snippet}")
        print(f"    vs")
        print(f"  [{to_id}] {to_snippet}")
        print()

    # Show top 5 components
    print(f"\n--- Largest Components (top 5) ---")
    for i, comp in enumerate(results.components[:5]):
        edge_types = defaultdict(int)
        for _, _, t in comp.edges:
            edge_types[t] += 1
        edge_summary = ", ".join(f"{t}={c}" for t, c in sorted(edge_types.items()))
        status = "INCONSISTENT" if comp.has_contradiction else "consistent"
        print(f"  #{i+1}: {comp.size} nodes, {len(comp.edges)} edges ({edge_summary}) [{status}]")


if __name__ == "__main__":
    main()
