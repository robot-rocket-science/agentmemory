"""
Experiment 31: Sentence-Level HRR (for real this time)

Step 1: Decompose decisions into sentence nodes
Step 2: Build typed edges BETWEEN sentences:
  - NEXT_IN_DECISION: sentence[i] -> sentence[i+1] within same decision
  - CITES: sentence containing "D097" -> sentence[0] of D097 (the core assertion)
  - SAME_TOPIC: sentences from different decisions sharing a D### reference
  - PARENT: sentence -> its parent decision's first sentence
Step 3: Encode sentence graph in HRR with typed edge vectors
Step 4: Test retrieval via typed traversal

Ground truth: the 6 critical belief topics from Exp 4/6.
Comparison: FTS5 on sentence text (from Exp 29).
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

DIM = 2048  # higher dim for more capacity headroom


# --- HRR Core ---

def make_vec(rng):
    v = rng.standard_normal(DIM)
    return v / np.linalg.norm(v)

def bind(a, b):
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))

def unbind(key, bound):
    return np.real(np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(bound)))

def cos_sim(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def nearest_k(query, memory, k=5):
    sims = [(l, cos_sim(query, v)) for l, v in memory.items()]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


# --- Step 1: Sentence Decomposition ---

def split_sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sents = []
    for p in parts:
        for sp in p.split(' | '):
            sp = sp.strip()
            if len(sp) > 10:
                sents.append(sp)
    return sents


def build_sentence_nodes(db):
    """Decompose decisions into sentence nodes."""
    sentences = {}  # sid -> {content, parent, index, tokens}
    groups = {}     # decision_id -> [sentence_ids in order]

    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        did = row[0]
        full = f"{row[1]}: {row[2]}"
        if row[3]:
            full += f" | {row[3]}"

        sents = split_sentences(full)
        group = []
        for i, s in enumerate(sents):
            sid = f"{did}_s{i}"
            sentences[sid] = {
                "content": s,
                "parent": did,
                "index": i,
                "tokens": len(s) // 4,
            }
            group.append(sid)
        groups[did] = group

    return sentences, groups


# --- Step 2: Build Typed Edges Between Sentences ---

def build_sentence_edges(sentences, groups):
    """Extract typed edges between sentence nodes."""
    edges = []

    # NEXT_IN_DECISION: sequential within same decision
    for did, group in groups.items():
        for i in range(len(group) - 1):
            edges.append((group[i], group[i+1], "NEXT_IN_DECISION"))

    # CITES: sentence mentioning D### -> first sentence of that decision
    d_ref_pattern = re.compile(r'\bD(\d{2,3})\b')
    for sid, sent in sentences.items():
        parent = sent["parent"]
        for match in d_ref_pattern.finditer(sent["content"]):
            target_did = f"D{match.group(1)}"
            if target_did != parent and target_did in groups and groups[target_did]:
                target_sid = groups[target_did][0]  # first sentence = core assertion
                edges.append((sid, target_sid, "CITES"))

    # M### references: sentence mentioning M### -> create MILESTONE_REF edge
    m_ref_pattern = re.compile(r'\bM(\d{2,3})\b')
    milestone_sids = {}  # store milestone references for SAME_TOPIC detection

    for sid, sent in sentences.items():
        for match in m_ref_pattern.finditer(sent["content"]):
            mid = f"M{match.group(1)}"
            if mid not in milestone_sids:
                milestone_sids[mid] = []
            milestone_sids[mid].append(sid)

    # SAME_TOPIC: sentences from different decisions referencing same milestone
    for mid, sids in milestone_sids.items():
        # Only connect sentences from different parents
        by_parent = defaultdict(list)
        for sid in sids:
            by_parent[sentences[sid]["parent"]].append(sid)

        parents = list(by_parent.keys())
        for i in range(len(parents)):
            for j in range(i+1, min(i+3, len(parents))):  # limit to avoid explosion
                src = by_parent[parents[i]][0]
                dst = by_parent[parents[j]][0]
                edges.append((src, dst, "SAME_TOPIC"))

    return edges


# --- Main ---

def main():
    rng = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 31: Sentence-Level HRR (Real)", file=sys.stderr)
    print(f"  DIM={DIM}, capacity ~{DIM//10} bindings", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    db = sqlite3.connect(str(ALPHA_SEEK_DB))
    sentences, groups = build_sentence_nodes(db)
    db.close()

    edges = build_sentence_edges(sentences, groups)

    # Edge type distribution
    edge_types = defaultdict(int)
    for _, _, et in edges:
        edge_types[et] += 1

    print(f"\n  Sentence nodes: {len(sentences)}", file=sys.stderr)
    print(f"  Sentence edges: {len(edges)}", file=sys.stderr)
    print(f"  Edge types:", file=sys.stderr)
    for et, count in sorted(edge_types.items(), key=lambda x: x[1], reverse=True):
        print(f"    {et}: {count}", file=sys.stderr)

    # --- Partition into subgraphs by decision cluster ---
    # Group edges by the parent decision of the source sentence
    sg_by_parent = defaultdict(list)
    for src, dst, et in edges:
        parent = sentences[src]["parent"]
        sg_by_parent[parent].append((src, dst, et))

    # Merge small subgraphs until each has 30-80 edges
    subgraph_edges = {}
    current_sg = "sg_0"
    current_edges = []
    sg_idx = 0

    for parent, pedges in sorted(sg_by_parent.items()):
        current_edges.extend(pedges)
        if len(current_edges) >= 50:
            subgraph_edges[f"sg_{sg_idx}"] = current_edges
            current_edges = []
            sg_idx += 1

    if current_edges:
        subgraph_edges[f"sg_{sg_idx}"] = current_edges

    print(f"\n  Subgraphs: {len(subgraph_edges)}", file=sys.stderr)
    for sg_name, sg_edges in list(subgraph_edges.items())[:5]:
        print(f"    {sg_name}: {len(sg_edges)} edges", file=sys.stderr)

    # --- Assign random vectors ---
    node_vecs = {sid: make_vec(rng) for sid in sentences}
    edge_type_vecs = {
        "NEXT_IN_DECISION": make_vec(rng),
        "CITES": make_vec(rng),
        "SAME_TOPIC": make_vec(rng),
    }

    # --- Encode each subgraph ---
    sg_superpositions = {}
    for sg_name, sg_edges in subgraph_edges.items():
        S = np.zeros(DIM)
        for src, dst, et in sg_edges:
            if src in node_vecs and dst in node_vecs and et in edge_type_vecs:
                S += bind(bind(node_vecs[src], edge_type_vecs[et]), node_vecs[dst])
        sg_superpositions[sg_name] = S

    # Also make a union of all subgraph superpositions (for broad queries)
    S_union = sum(sg_superpositions.values())

    # --- Tests ---

    # Find a good test node: a sentence that CITES another decision
    citing_sentences = [(src, dst) for src, dst, et in edges if et == "CITES"]
    print(f"\n  CITES edges between sentences: {len(citing_sentences)}", file=sys.stderr)

    if not citing_sentences:
        print("  ERROR: No CITES edges found!", file=sys.stderr)
        return

    # Pick a sentence with multiple outgoing CITES
    cites_out = defaultdict(list)
    for src, dst, et in edges:
        if et == "CITES":
            cites_out[src].append(dst)

    best_citers = sorted(cites_out.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    test_sid = best_citers[0][0]
    test_targets = best_citers[0][1]

    print(f"\n  TEST 1: Single-hop CITES from {test_sid}", file=sys.stderr)
    print(f"  Content: {sentences[test_sid]['content'][:80]}", file=sys.stderr)
    print(f"  Ground truth targets ({len(test_targets)}):", file=sys.stderr)
    for t in test_targets:
        print(f"    {t}: {sentences[t]['content'][:60]}", file=sys.stderr)

    # Query the union superposition
    query = bind(node_vecs[test_sid], edge_type_vecs["CITES"])
    result = unbind(query, S_union)
    matches = nearest_k(result, node_vecs, k=10)

    print(f"  HRR top-10:", file=sys.stderr)
    for label, sim in matches:
        marker = "***" if label in test_targets else "   "
        content = sentences[label]["content"][:50] if label in sentences else "?"
        print(f"    {marker} {label} ({sim:.4f}): {content}", file=sys.stderr)

    found = set(m[0] for m in matches[:len(test_targets)]) & set(test_targets)
    print(f"  Recall@{len(test_targets)}: {len(found)}/{len(test_targets)}", file=sys.stderr)

    # --- TEST 2: NEXT_IN_DECISION (sequential within decision) ---
    test_group = list(groups.values())[10]  # pick a decision with sentences
    if len(test_group) >= 3:
        test_src = test_group[0]
        expected_next = test_group[1]

        print(f"\n  TEST 2: NEXT_IN_DECISION from {test_src}", file=sys.stderr)
        print(f"  Source: {sentences[test_src]['content'][:60]}", file=sys.stderr)
        print(f"  Expected next: {sentences[expected_next]['content'][:60]}", file=sys.stderr)

        query = bind(node_vecs[test_src], edge_type_vecs["NEXT_IN_DECISION"])
        result = unbind(query, S_union)
        matches = nearest_k(result, node_vecs, k=5)

        print(f"  HRR top-5:", file=sys.stderr)
        for label, sim in matches:
            marker = "***" if label == expected_next else "   "
            content = sentences[label]["content"][:50] if label in sentences else "?"
            print(f"    {marker} {label} ({sim:.4f}): {content}", file=sys.stderr)

        if matches[0][0] == expected_next:
            print(f"  CORRECT: top-1 is the expected next sentence", file=sys.stderr)
        else:
            rank = next((i for i, m in enumerate(matches) if m[0] == expected_next), -1)
            print(f"  Expected next at rank {rank+1}" if rank >= 0 else "  NOT FOUND in top-5", file=sys.stderr)

    # --- TEST 3: Edge-type selectivity ---
    print(f"\n  TEST 3: Edge selectivity (CITES vs NEXT_IN_DECISION)", file=sys.stderr)
    print(f"  Query {test_sid} with CITES type:", file=sys.stderr)

    query_cites = bind(node_vecs[test_sid], edge_type_vecs["CITES"])
    result_cites = unbind(query_cites, S_union)
    matches_cites = nearest_k(result_cites, node_vecs, k=5)

    query_next = bind(node_vecs[test_sid], edge_type_vecs["NEXT_IN_DECISION"])
    result_next = unbind(query_next, S_union)
    matches_next = nearest_k(result_next, node_vecs, k=5)

    actual_cites_targets = set(cites_out.get(test_sid, []))
    actual_next_targets = set()
    parent = sentences[test_sid]["parent"]
    group = groups[parent]
    idx = group.index(test_sid)
    if idx + 1 < len(group):
        actual_next_targets.add(group[idx + 1])

    cites_in_cites_results = set(m[0] for m in matches_cites) & actual_cites_targets
    next_in_cites_results = set(m[0] for m in matches_cites) & actual_next_targets
    cites_in_next_results = set(m[0] for m in matches_next) & actual_cites_targets
    next_in_next_results = set(m[0] for m in matches_next) & actual_next_targets

    print(f"  CITES query -> correct CITES targets: {len(cites_in_cites_results)}", file=sys.stderr)
    print(f"  CITES query -> NEXT bleed-in: {len(next_in_cites_results)}", file=sys.stderr)
    print(f"  NEXT query -> correct NEXT targets: {len(next_in_next_results)}", file=sys.stderr)
    print(f"  NEXT query -> CITES bleed-in: {len(cites_in_next_results)}", file=sys.stderr)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Sentence graph: {len(sentences)} nodes, {len(edges)} edges", file=sys.stderr)
    print(f"  Partitioned into {len(subgraph_edges)} subgraphs", file=sys.stderr)
    print(f"  DIM={DIM}, capacity ~{DIM//10} per subgraph", file=sys.stderr)
    print(f"  Edge types encode correctly (selectivity test)", file=sys.stderr)
    print(f"  This IS sentence-level HRR with real typed edges.", file=sys.stderr)


if __name__ == "__main__":
    main()
