"""
Experiment 40: FTS5 + HRR Hybrid Retrieval Pipeline (End-to-End)

THE test: query "agent behavior instructions" -> FTS5 finds D188 -> HRR walks
AGENT_CONSTRAINT edge -> D157 recovered. If this works, the hybrid architecture
is validated. If not, it's theoretical.

Phase 1: Manual edges. AGENT_CONSTRAINT edges hand-assigned to known behavioral
beliefs. Tests whether the pipeline mechanism works.

Ground truth: 6 topics, 13 critical decisions (from Exp 9/39).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

# ============================================================
# Config
# ============================================================

project-a_DB = Path(
    "/home/user/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/project-a.db"
)

DIM = 2048
HRR_THRESHOLD = 0.08  # Exp 34: worst behavior node 0.149, best distractor 0.013
RNG = np.random.default_rng(42)

# Ground truth from Exp 9/39
TOPICS: dict[str, dict[str, Any]] = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol",
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "query": "calls puts equal citizens",
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "query": "starting capital bankroll",
        "needed": ["D099"],
    },
    "agent_behavior": {
        "query": "agent behavior instructions",
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "query": "typing pyright strict",
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "query": "GCP primary compute platform",
        "needed": ["D078", "D120"],
    },
}

# Known behavioral beliefs (manual classification for Phase 1)
BEHAVIORAL_BELIEFS = ["D157", "D188", "D100", "D073"]


# ============================================================
# Data loading
# ============================================================


def load_nodes() -> dict[str, str]:
    """Load all active belief nodes from project-a DB."""
    db = sqlite3.connect(str(project-a_DB))
    nodes: dict[str, str] = {}
    for row in db.execute(
        "SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes[str(row[0])] = str(row[1])
    db.close()
    return nodes


# ============================================================
# FTS5
# ============================================================


def build_fts(nodes: dict[str, str]) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for nid, content in nodes.items():
        db.execute("INSERT INTO fts VALUES (?, ?)", (nid, content))
    db.commit()
    return db


def search_fts(
    query: str, fts_db: sqlite3.Connection, top_k: int = 30
) -> list[tuple[str, float]]:
    """FTS5 search returning (node_id, bm25_score) pairs."""
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    try:
        results = fts_db.execute(
            "SELECT id, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
        return [(str(r[0]), float(r[1])) for r in results]
    except Exception:
        return []


# ============================================================
# Graph construction
# ============================================================


def extract_cites_edges(nodes: dict[str, str]) -> list[tuple[str, str]]:
    """Extract CITES edges from D### references in belief content."""
    d_pattern = re.compile(r"\bD(\d{3})\b")
    edges: list[tuple[str, str]] = []

    for nid, content in nodes.items():
        # Get the decision ID of this node
        src_match = re.match(r"(D\d{3})", nid)
        if not src_match:
            continue
        src_decision = src_match.group(1)

        # Find D### references in the content
        for m in d_pattern.finditer(content):
            target_decision = f"D{m.group(1)}"
            if target_decision != src_decision:
                # Find any node belonging to target decision
                for target_nid in nodes:
                    if target_nid.startswith(target_decision):
                        edges.append((nid, target_nid))
                        break  # One edge per decision reference

    return edges


def build_agent_constraint_edges(
    nodes: dict[str, str], behavioral_ids: list[str]
) -> list[tuple[str, str]]:
    """Connect all behavioral beliefs to each other via AGENT_CONSTRAINT.

    Every pair of behavioral belief nodes gets an edge. This means querying
    any one of them with AGENT_CONSTRAINT retrieves all the others.
    """
    # Find all node IDs that belong to behavioral decisions
    behavioral_nodes: list[str] = []
    for nid in nodes:
        for bid in behavioral_ids:
            if nid.startswith(bid):
                behavioral_nodes.append(nid)
                break

    # Fully connect behavioral nodes
    edges: list[tuple[str, str]] = []
    for i, a in enumerate(behavioral_nodes):
        for b in behavioral_nodes[i + 1 :]:
            edges.append((a, b))
            edges.append((b, a))  # Bidirectional

    return edges


def scan_for_additional_behavioral(
    nodes: dict[str, str], known: list[str]
) -> list[str]:
    """Scan for additional behavioral beliefs using directive patterns.

    Returns decision IDs not already in the known list.
    """
    directive_patterns = [
        re.compile(r"\bBANNED\b"),
        re.compile(r"\bNever\s+use\b", re.IGNORECASE),
        re.compile(r"\bNever\s+\w+\b"),
        re.compile(r"\balways\s+\w+\b", re.IGNORECASE),
        re.compile(r"\bmust\s+not\b", re.IGNORECASE),
        re.compile(r"\bdo\s+not\b", re.IGNORECASE),
        re.compile(r"\bdon't\b", re.IGNORECASE),
    ]

    found: set[str] = set()
    for nid, content in nodes.items():
        decision_match = re.match(r"(D\d{3})", nid)
        if not decision_match:
            continue
        did = decision_match.group(1)
        if did in known:
            continue

        for pattern in directive_patterns:
            if pattern.search(content):
                found.add(did)
                break

    return sorted(found)


# ============================================================
# HRR encoding
# ============================================================


def make_vector(dim: int) -> np.ndarray:
    """Random unit vector in R^dim."""
    v = RNG.standard_normal(dim)
    v /= np.linalg.norm(v)
    return v


def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Circular convolution (binding) via FFT."""
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))


def unbind(bound: np.ndarray, key: np.ndarray) -> np.ndarray:
    """Circular correlation (approximate unbinding) via FFT."""
    return np.real(np.fft.ifft(np.fft.fft(bound) * np.conj(np.fft.fft(key))))


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity."""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class HRRGraph:
    """HRR-encoded graph with typed edges and partition routing."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.node_vecs: dict[str, np.ndarray] = {}
        self.edge_type_vecs: dict[str, np.ndarray] = {}
        self.partitions: dict[str, np.ndarray] = {}  # partition_id -> superposition
        self.node_to_partition: dict[str, str] = {}  # node_id -> partition_id

    def add_node(self, nid: str) -> None:
        if nid not in self.node_vecs:
            self.node_vecs[nid] = make_vector(self.dim)

    def add_edge_type(self, etype: str) -> None:
        if etype not in self.edge_type_vecs:
            self.edge_type_vecs[etype] = make_vector(self.dim)

    def encode_partition(
        self, partition_id: str, edges: list[tuple[str, str, str]]
    ) -> None:
        """Encode a set of (source, target, edge_type) edges into a superposition."""
        superpos = np.zeros(self.dim)
        for src, tgt, etype in edges:
            self.add_node(src)
            self.add_node(tgt)
            self.add_edge_type(etype)
            # Encode: from src's perspective, tgt is reachable via etype
            superpos += bind(self.node_vecs[tgt], self.edge_type_vecs[etype])
            self.node_to_partition[src] = partition_id
            self.node_to_partition[tgt] = partition_id

        self.partitions[partition_id] = superpos

    def query_neighbors(
        self, node_id: str, edge_type: str, threshold: float = HRR_THRESHOLD
    ) -> list[tuple[str, float]]:
        """Find neighbors of node_id via edge_type in its partition."""
        if node_id not in self.node_to_partition:
            return []
        if edge_type not in self.edge_type_vecs:
            return []

        partition_id = self.node_to_partition[node_id]
        S = self.partitions[partition_id]

        # Unbind with edge type to get approximate superposition of neighbors
        result = unbind(S, self.edge_type_vecs[edge_type])

        # Score all nodes in this partition against the result
        scores: list[tuple[str, float]] = []
        for nid, vec in self.node_vecs.items():
            if self.node_to_partition.get(nid) != partition_id:
                continue
            if nid == node_id:
                continue  # Don't return the query node itself
            sim = cos_sim(result, vec)
            if sim >= threshold:
                scores.append((nid, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


# ============================================================
# Hybrid pipeline
# ============================================================


def run_hybrid_pipeline(
    query: str,
    fts_db: sqlite3.Connection,
    hrr_graph: HRRGraph,
    edge_types: list[str],
) -> dict[str, Any]:
    """The full FTS5 -> HRR walk -> union pipeline."""

    # Step 1: FTS5 search
    fts_results = search_fts(query, fts_db, top_k=30)
    fts_ids = {nid for nid, _ in fts_results}

    # Step 2: HRR walk from each FTS5 hit
    hrr_results: dict[
        str, list[tuple[str, float, str]]
    ] = {}  # seed -> [(neighbor, sim, edge_type)]

    for seed_id, _bm25 in fts_results:
        for etype in edge_types:
            neighbors = hrr_graph.query_neighbors(seed_id, etype)
            for neighbor_id, sim in neighbors:
                if neighbor_id not in hrr_results:
                    hrr_results[neighbor_id] = []
                hrr_results[neighbor_id].append((seed_id, sim, etype))

    # Step 3: Union
    hrr_only_ids = set(hrr_results.keys()) - fts_ids
    both_ids = set(hrr_results.keys()) & fts_ids
    all_ids = fts_ids | set(hrr_results.keys())

    return {
        "fts_results": fts_results,
        "fts_ids": sorted(fts_ids),
        "hrr_neighbors": {k: v for k, v in hrr_results.items()},
        "hrr_only_ids": sorted(hrr_only_ids),
        "both_ids": sorted(both_ids),
        "all_ids": sorted(all_ids),
        "fts_count": len(fts_ids),
        "hrr_only_count": len(hrr_only_ids),
        "combined_count": len(all_ids),
    }


# ============================================================
# Evaluation
# ============================================================


def extract_decision_id(node_id: str) -> str | None:
    m = re.match(r"(D\d{3})", node_id)
    return m.group(1) if m else None


def evaluate_topic(
    topic_name: str,
    topic_data: dict[str, Any],
    pipeline_result: dict[str, Any],
) -> dict[str, Any]:
    needed: set[str] = set(topic_data["needed"])

    # Decisions found by FTS5 only
    fts_decisions: set[str | None] = {
        extract_decision_id(str(nid)) for nid in pipeline_result["fts_ids"]
    }
    fts_found: set[str] = needed & (fts_decisions - {None})  # type: ignore[arg-type]

    # Decisions found by combined pipeline
    all_decisions: set[str | None] = {
        extract_decision_id(str(nid)) for nid in pipeline_result["all_ids"]
    }
    combined_found: set[str] = needed & (all_decisions - {None})  # type: ignore[arg-type]

    # Decisions found ONLY via HRR (not by FTS5)
    hrr_only_decisions: set[str | None] = {
        extract_decision_id(str(nid)) for nid in pipeline_result["hrr_only_ids"]
    }
    hrr_rescued: set[str] = needed & (hrr_only_decisions - {None})  # type: ignore[arg-type]

    return {
        "topic": topic_name,
        "needed": sorted(needed),
        "fts_found": sorted(fts_found),
        "fts_missed": sorted(needed - fts_found),
        "fts_coverage": round(len(fts_found) / len(needed), 3),
        "combined_found": sorted(combined_found),
        "combined_missed": sorted(needed - combined_found),
        "combined_coverage": round(len(combined_found) / len(needed), 3),
        "hrr_rescued": sorted(hrr_rescued),
        "fts_result_count": pipeline_result["fts_count"],
        "hrr_only_count": pipeline_result["hrr_only_count"],
        "combined_result_count": pipeline_result["combined_count"],
    }


# ============================================================
# Main
# ============================================================


def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 40: FTS5 + HRR Hybrid Retrieval Pipeline", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Load data
    print("\n[1] Loading belief nodes...", file=sys.stderr)
    nodes = load_nodes()
    print(f"    {len(nodes)} nodes loaded", file=sys.stderr)

    # Build FTS5 index
    print("[2] Building FTS5 index...", file=sys.stderr)
    fts_db = build_fts(nodes)

    # Scan for additional behavioral beliefs
    print("[3] Scanning for behavioral beliefs...", file=sys.stderr)
    additional = scan_for_additional_behavioral(nodes, BEHAVIORAL_BELIEFS)
    all_behavioral = BEHAVIORAL_BELIEFS + additional
    print(f"    Known: {BEHAVIORAL_BELIEFS}", file=sys.stderr)
    print(f"    Scan found {len(additional)} additional: {additional}", file=sys.stderr)

    # Show what the additional ones contain
    for did in additional[:10]:
        for nid, content in nodes.items():
            if nid.startswith(did):
                print(f"      {did}: {content[:100]}...", file=sys.stderr)
                break

    # Extract edges
    print("\n[4] Extracting edges...", file=sys.stderr)
    cites_edges = extract_cites_edges(nodes)
    print(f"    CITES edges: {len(cites_edges)}", file=sys.stderr)

    agent_constraint_edges = build_agent_constraint_edges(nodes, all_behavioral)
    behavioral_node_ids = [
        nid for nid in nodes if any(nid.startswith(bid) for bid in all_behavioral)
    ]
    print(
        f"    AGENT_CONSTRAINT edges: {len(agent_constraint_edges)} "
        f"(connecting {len(behavioral_node_ids)} behavioral nodes)",
        file=sys.stderr,
    )

    # Build HRR graph
    print("\n[5] Encoding HRR graph...", file=sys.stderr)

    hrr = HRRGraph(dim=DIM)

    # Partition strategy: put ALL behavioral beliefs in one partition ("behavioral")
    # Put CITES edges in subgraph-based partitions (group by source decision neighborhood)
    behavioral_edge_triples = [
        (s, t, "AGENT_CONSTRAINT") for s, t in agent_constraint_edges
    ]

    # Also add CITES edges that touch behavioral nodes into the behavioral partition
    behavioral_cites: list[tuple[str, str, str]] = []
    other_cites: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for src, tgt in cites_edges:
        src_is_behavioral = any(src.startswith(bid) for bid in all_behavioral)
        tgt_is_behavioral = any(tgt.startswith(bid) for bid in all_behavioral)
        if src_is_behavioral or tgt_is_behavioral:
            behavioral_cites.append((src, tgt, "CITES"))
        else:
            # Group by source decision for partitioning
            src_d = extract_decision_id(src) or "unknown"
            other_cites[src_d].append((src, tgt, "CITES"))

    # Encode behavioral partition (AGENT_CONSTRAINT + any CITES touching behavioral nodes)
    behavioral_all_edges = behavioral_edge_triples + behavioral_cites
    print(
        f"    Behavioral partition: {len(behavioral_all_edges)} edges "
        f"({len(behavioral_edge_triples)} AGENT_CONSTRAINT + {len(behavioral_cites)} CITES)",
        file=sys.stderr,
    )

    if len(behavioral_all_edges) > 200:
        print(
            f"    WARNING: {len(behavioral_all_edges)} edges exceeds DIM=2048 comfortable capacity (~200)",
            file=sys.stderr,
        )

    hrr.encode_partition("behavioral", behavioral_all_edges)

    # Encode other CITES partitions (group into chunks of <= 150 edges)
    cites_chunk: list[tuple[str, str, str]] = []
    chunk_id = 0
    for _decision_id, decision_edges in other_cites.items():
        cites_chunk.extend(decision_edges)
        if len(cites_chunk) >= 150:
            hrr.encode_partition(f"cites_{chunk_id}", cites_chunk)
            chunk_id += 1
            cites_chunk = []
    if cites_chunk:
        hrr.encode_partition(f"cites_{chunk_id}", cites_chunk)
        chunk_id += 1

    total_partitions = 1 + chunk_id  # behavioral + cites chunks
    print(
        f"    Total partitions: {total_partitions} (1 behavioral + {chunk_id} CITES chunks)",
        file=sys.stderr,
    )

    # Verify: are D157 and D188 in the same partition?
    d157_nodes = [nid for nid in hrr.node_to_partition if nid.startswith("D157")]
    d188_nodes = [nid for nid in hrr.node_to_partition if nid.startswith("D188")]
    print(f"\n    D157 nodes in graph: {d157_nodes}", file=sys.stderr)
    print(f"    D188 nodes in graph: {d188_nodes}", file=sys.stderr)
    for nid in d157_nodes:
        print(
            f"    D157 partition: {hrr.node_to_partition.get(nid, 'NOT FOUND')}",
            file=sys.stderr,
        )
    for nid in d188_nodes:
        print(
            f"    D188 partition: {hrr.node_to_partition.get(nid, 'NOT FOUND')}",
            file=sys.stderr,
        )

    # Sanity check: HRR single-hop from D188 via AGENT_CONSTRAINT
    print(
        "\n[6] Sanity check: HRR walk from D188 via AGENT_CONSTRAINT...",
        file=sys.stderr,
    )
    for d188_nid in d188_nodes:
        neighbors = hrr.query_neighbors(d188_nid, "AGENT_CONSTRAINT", threshold=0.0)
        print(f"    From {d188_nid}:", file=sys.stderr)
        for nid, sim in neighbors[:10]:
            is_behavioral = any(nid.startswith(bid) for bid in all_behavioral)
            marker = " <-- BEHAVIORAL" if is_behavioral else ""
            d157_marker = " *** D157 FOUND ***" if nid.startswith("D157") else ""
            print(
                f"      {nid:>12} sim={sim:.4f}{marker}{d157_marker}", file=sys.stderr
            )

    # Run the hybrid pipeline on all 6 topics
    print("\n[7] Running hybrid pipeline on all topics...", file=sys.stderr)
    edge_types_to_walk = ["AGENT_CONSTRAINT", "CITES"]

    all_results: dict[str, Any] = {}
    total_fts_found = 0
    total_combined_found = 0
    total_needed = 0

    for topic_name, topic_data in TOPICS.items():
        pipeline_result = run_hybrid_pipeline(
            topic_data["query"], fts_db, hrr, edge_types_to_walk
        )
        eval_result = evaluate_topic(topic_name, topic_data, pipeline_result)
        all_results[topic_name] = eval_result

        total_needed += len(topic_data["needed"])
        total_fts_found += len(eval_result["fts_found"])
        total_combined_found += len(eval_result["combined_found"])

        # Print per-topic results
        fts_status = (
            "OK"
            if not eval_result["fts_missed"]
            else f"MISSED: {eval_result['fts_missed']}"
        )
        combined_status = (
            "OK"
            if not eval_result["combined_missed"]
            else f"MISSED: {eval_result['combined_missed']}"
        )
        rescued = (
            f" [HRR rescued: {eval_result['hrr_rescued']}]"
            if eval_result["hrr_rescued"]
            else ""
        )

        print(f"\n    {topic_name}:", file=sys.stderr)
        print(
            f"      FTS5:     {eval_result['fts_coverage']:.0%} ({eval_result['fts_result_count']} results)  {fts_status}",
            file=sys.stderr,
        )
        print(
            f"      Combined: {eval_result['combined_coverage']:.0%} ({eval_result['combined_result_count']} results)  {combined_status}{rescued}",
            file=sys.stderr,
        )

        # For agent_behavior, show detailed diagnostics
        if topic_name == "agent_behavior":
            print(
                "\n      --- DETAILED DIAGNOSTICS (agent_behavior) ---", file=sys.stderr
            )
            print(
                f"      FTS5 hits containing D157: {[nid for nid in pipeline_result['fts_ids'] if 'D157' in nid]}",
                file=sys.stderr,
            )
            print(
                f"      FTS5 hits containing D188: {[nid for nid in pipeline_result['fts_ids'] if 'D188' in nid]}",
                file=sys.stderr,
            )
            print(
                f"      HRR-only hits containing D157: {[nid for nid in pipeline_result['hrr_only_ids'] if 'D157' in nid]}",
                file=sys.stderr,
            )

            if pipeline_result["hrr_neighbors"]:
                print("      HRR neighbor details:", file=sys.stderr)
                for nid, sources in pipeline_result["hrr_neighbors"].items():
                    if any("D157" in nid or "D188" in nid for _ in [0]):
                        pass
                    # Show all HRR-discovered neighbors
                    for seed, sim, etype in sources:
                        print(
                            f"        {nid} <- {seed} via {etype} (sim={sim:.4f})",
                            file=sys.stderr,
                        )

    # Summary
    print(f"\n{'=' * 70}", file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(
        f"\n{'Topic':<20} {'FTS5':>8} {'Combined':>10} {'HRR Rescued':>15} {'Precision':>12}",
        file=sys.stderr,
    )
    print("-" * 67, file=sys.stderr)
    for topic_name, r in all_results.items():
        rescued_str = ", ".join(r["hrr_rescued"]) if r["hrr_rescued"] else "--"
        precision = f"{r['fts_result_count']}->{r['combined_result_count']}"
        print(
            f"{topic_name:<20} {r['fts_coverage']:>8.0%} {r['combined_coverage']:>10.0%} "
            f"{rescued_str:>15} {precision:>12}",
            file=sys.stderr,
        )

    fts_overall = round(total_fts_found / total_needed, 3)
    combined_overall = round(total_combined_found / total_needed, 3)
    print(
        f"\n{'OVERALL':<20} {fts_overall:>8.0%} {combined_overall:>10.0%}",
        file=sys.stderr,
    )
    print("\nExp 9 hand-crafted:                 100%", file=sys.stderr)

    # THE QUESTION
    d157_found = any(
        "D157" in d for r in all_results.values() for d in r["combined_found"]
    )
    print(
        f"\n*** D157 found by combined pipeline: {'YES' if d157_found else 'NO'} ***",
        file=sys.stderr,
    )

    # H2: precision check
    max_inflation = max(
        r["combined_result_count"] / max(1, r["fts_result_count"])
        for r in all_results.values()
    )
    print(
        f"*** Max result inflation (combined/fts): {max_inflation:.1f}x "
        f"(threshold: < 3x) ***",
        file=sys.stderr,
    )

    # Save results
    out = Path("experiments/exp40_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
