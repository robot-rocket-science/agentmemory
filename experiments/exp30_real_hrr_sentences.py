"""
Experiment 30: Real HRR with Sentence-Level Nodes and Typed Edges

Previous HRR experiment (Exp 24) was BoW cosine -- not real HRR. It matched
FTS5 because it was doing the same thing in different spaces (HRR_RESEARCH.md
section 8).

This experiment uses REAL HRR:
- Each sentence node gets a RANDOM vector (not BoW sum)
- Typed edges encoded via circular convolution (binding)
- Compositional multi-hop queries via successive binding
- Cleanup memory for nearest-neighbor recovery

Tests whether HRR's unique capabilities (compositional queries, multi-hop
traversal, edge-type selectivity) provide retrieval quality that FTS5 cannot.

Hypothesis: HRR should find nodes reachable via multi-hop graph traversal
WITHOUT doing BFS, and should be able to answer compositional queries like
"what does D097 cite that also relates to sizing?" in a single vector operation.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

DIM = 1024  # higher dim for better SNR with real graph edges


# --- HRR Core ---

def make_vec(rng):
    v = rng.standard_normal(DIM)
    v /= np.linalg.norm(v)
    return v

def bind(a, b):
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))

def unbind(key, bound):
    return np.real(np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(bound)))

def cos_sim(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def nearest_k(query, memory, k=5):
    sims = [(label, cos_sim(query, vec)) for label, vec in memory.items()]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


# --- Load and Build Graph ---

def load_graph():
    db = sqlite3.connect(str(ALPHA_SEEK_DB))

    nodes = {}
    for row in db.execute("SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes[row[0]] = row[1]

    edges = []
    for row in db.execute("SELECT from_id, to_id, edge_type FROM mem_edges"):
        if row[0] in nodes and row[1] in nodes:
            edges.append((row[0], row[1], row[2]))

    db.close()
    return nodes, edges


def split_sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sents = []
    for p in parts:
        for sp in p.split(' | '):
            sp = sp.strip()
            if len(sp) > 10:
                sents.append(sp)
    return sents


def main():
    rng = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 30: Real HRR with Sentence Nodes", file=sys.stderr)
    print(f"  Dimensionality: {DIM}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    nodes, edges = load_graph()
    print(f"  {len(nodes)} nodes, {len(edges)} edges", file=sys.stderr)

    # --- Step 1: Assign random vectors to each node ---
    node_vecs = {nid: make_vec(rng) for nid in nodes}

    # --- Step 2: Create edge type vectors ---
    edge_types = set(e[2] for e in edges)
    edge_type_vecs = {et: make_vec(rng) for et in edge_types}
    print(f"  Edge types: {sorted(edge_types)}", file=sys.stderr)

    # --- Step 3: Encode graph as superposition of bound triples ---
    # Partition into subgraphs to stay within capacity (~100 bindings per superposition)
    # Group edges by source node's first letter (rough partitioning)
    subgraphs = defaultdict(list)
    for src, dst, etype in edges:
        # Group by source node prefix for manageable superposition size
        prefix = src[0] if src[0] != '_' else src[:2]
        subgraphs[prefix].append((src, dst, etype))

    # Encode each subgraph as a superposition
    sg_vecs = {}
    for prefix, sg_edges in subgraphs.items():
        S = np.zeros(DIM)
        for src, dst, etype in sg_edges:
            triple = bind(bind(node_vecs[src], edge_type_vecs[etype]), node_vecs[dst])
            S += triple
        sg_vecs[prefix] = S
        if len(sg_edges) > 50:
            print(f"  Subgraph '{prefix}': {len(sg_edges)} edges (near capacity)", file=sys.stderr)

    # Global superposition (all edges -- will be noisy for large graphs)
    S_global = sum(sg_vecs.values())
    print(f"  Global superposition: {len(edges)} bindings in {DIM}D "
          f"(capacity ~{DIM//10})", file=sys.stderr)

    # --- Test 1: Single-hop forward traversal ---
    print(f"\n  TEST 1: Single-hop forward traversal", file=sys.stderr)
    print(f"  'What does D097 cite?'", file=sys.stderr)

    query = bind(node_vecs["D097"], edge_type_vecs["CITES"])
    result = unbind(query, S_global)
    matches = nearest_k(result, node_vecs, k=5)

    # Ground truth: what does D097 actually cite?
    actual_cites = [dst for src, dst, et in edges if src == "D097" and et == "CITES"]
    print(f"  Ground truth (D097 CITES): {actual_cites[:10]}", file=sys.stderr)
    print(f"  HRR top-5: {[(m[0], round(m[1], 3)) for m in matches]}", file=sys.stderr)
    hrr_found = set(m[0] for m in matches) & set(actual_cites)
    print(f"  Overlap: {len(hrr_found)}/{min(5, len(actual_cites))} "
          f"({hrr_found})", file=sys.stderr)

    # --- Test 2: Reverse traversal ---
    print(f"\n  TEST 2: Reverse traversal", file=sys.stderr)
    print(f"  'What cites D097?'", file=sys.stderr)

    # For reverse: unbind D097 from bound triples where D097 is the target
    query = bind(edge_type_vecs["CITES"], node_vecs["D097"])
    result = unbind(query, S_global)
    matches = nearest_k(result, node_vecs, k=5)

    actual_cited_by = [src for src, dst, et in edges if dst == "D097" and et == "CITES"]
    print(f"  Ground truth (X CITES D097): {actual_cited_by[:10]}", file=sys.stderr)
    print(f"  HRR top-5: {[(m[0], round(m[1], 3)) for m in matches]}", file=sys.stderr)
    hrr_found = set(m[0] for m in matches) & set(actual_cited_by)
    print(f"  Overlap: {len(hrr_found)}/{min(5, len(actual_cited_by))} "
          f"({hrr_found})", file=sys.stderr)

    # --- Test 3: Edge-type selectivity ---
    print(f"\n  TEST 3: Edge-type selectivity", file=sys.stderr)
    print(f"  'What does D097 RELATE_TO (not CITE)?'", file=sys.stderr)

    query = bind(node_vecs["D097"], edge_type_vecs["RELATES_TO"])
    result = unbind(query, S_global)
    matches = nearest_k(result, node_vecs, k=5)

    actual_relates = [dst for src, dst, et in edges if src == "D097" and et == "RELATES_TO"]
    actual_cites_only = [dst for src, dst, et in edges if src == "D097" and et == "CITES"]
    print(f"  Ground truth (D097 RELATES_TO): {actual_relates[:10]}", file=sys.stderr)
    print(f"  HRR top-5: {[(m[0], round(m[1], 3)) for m in matches]}", file=sys.stderr)

    # Check selectivity: did CITES bleed in?
    cites_bleed = set(m[0] for m in matches) & set(actual_cites_only)
    relates_found = set(m[0] for m in matches) & set(actual_relates)
    print(f"  Correct (RELATES_TO): {relates_found}", file=sys.stderr)
    print(f"  Bleed-in (CITES): {cites_bleed}", file=sys.stderr)

    # --- Test 4: Multi-hop (2-hop) traversal ---
    print(f"\n  TEST 4: Two-hop traversal", file=sys.stderr)
    print(f"  'What does D097 CITE that also has DECIDED_IN edges?'", file=sys.stderr)
    print(f"  D097 -[CITES]-> X -[DECIDED_IN]-> ?", file=sys.stderr)

    query_2hop = bind(bind(node_vecs["D097"], edge_type_vecs["CITES"]),
                      edge_type_vecs["DECIDED_IN"])
    result = unbind(query_2hop, S_global)
    matches = nearest_k(result, node_vecs, k=5)

    # Ground truth: find actual 2-hop targets
    hop1 = [dst for src, dst, et in edges if src == "D097" and et == "CITES"]
    hop2 = []
    for h1 in hop1:
        for src, dst, et in edges:
            if src == h1 and et == "DECIDED_IN":
                hop2.append((h1, dst))
    print(f"  Ground truth 2-hop: {hop2[:10]}", file=sys.stderr)
    print(f"  HRR top-5: {[(m[0], round(m[1], 3)) for m in matches]}", file=sys.stderr)
    hop2_targets = set(dst for _, dst in hop2)
    hrr_found = set(m[0] for m in matches) & hop2_targets
    print(f"  Overlap with 2-hop targets: {len(hrr_found)} ({hrr_found})", file=sys.stderr)

    # --- Test 5: Compare to BFS ---
    print(f"\n  TEST 5: HRR vs BFS for 'what does D097 cite?'", file=sys.stderr)

    # BFS 1-hop
    bfs_results = [dst for src, dst, et in edges if src == "D097" and et == "CITES"]

    # HRR 1-hop (from Test 1)
    query = bind(node_vecs["D097"], edge_type_vecs["CITES"])
    result = unbind(query, S_global)
    hrr_results = nearest_k(result, node_vecs, k=len(bfs_results))
    hrr_ids = [m[0] for m in hrr_results]

    overlap = set(bfs_results) & set(hrr_ids)
    print(f"  BFS finds: {len(bfs_results)} nodes", file=sys.stderr)
    print(f"  HRR finds: {len(hrr_ids)} nodes", file=sys.stderr)
    print(f"  Overlap: {len(overlap)}/{len(bfs_results)} "
          f"({len(overlap)/len(bfs_results):.0%})", file=sys.stderr)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  This is REAL HRR: random node vectors, bound typed edges,", file=sys.stderr)
    print(f"  compositional multi-hop queries in vector space.", file=sys.stderr)
    print(f"  NOT bag-of-words cosine similarity (which matched FTS5).", file=sys.stderr)
    print(f"\n  Graph encoding: {len(edges)} edges in {DIM}D superposition", file=sys.stderr)
    print(f"  Capacity: ~{DIM//10} reliable bindings (we have {len(edges)} -- OVER CAPACITY)", file=sys.stderr)
    print(f"  This means noise is high. Subgraph partitioning would help.", file=sys.stderr)


if __name__ == "__main__":
    main()
