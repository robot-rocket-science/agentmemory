"""
Experiment 34: Three closing HRR tests

Test A: Vocabulary bridge (D157/D188 via shared AGENT_CONSTRAINT edge)
Test B: Multi-hop within capacity (D195 neighborhood, 2-hop)
Test C: Combined HRR + FTS5 pipeline (real HRR, not BoW)

All tests use sentence-level nodes, real HRR binding, DIM=2048.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
          "260406-1-associative-memory-for-gsd-please-explor/"
          "sandbox/alpha-seek.db")

DIM = 2048
rng = np.random.default_rng(42)


def make_vec():
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

def split_sents(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sents = []
    for p in parts:
        for sp in p.split(' | '):
            sp = sp.strip()
            if len(sp) > 10: sents.append(sp)
    return sents


def load_sentences():
    db = sqlite3.connect(str(DB))
    sentences = {}
    groups = {}
    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        did = row[0]
        full = f"{row[1]}: {row[2]}"
        if row[3]: full += f" | {row[3]}"
        sents = split_sents(full)
        g = []
        for i, s in enumerate(sents):
            sid = f"{did}_s{i}"
            sentences[sid] = {"content": s, "parent": did, "index": i}
            g.append(sid)
        groups[did] = g

    # Also load known edges
    known_edges = []
    d_ref = re.compile(r'\bD(\d{2,3})\b')
    for sid, sent in sentences.items():
        parent = sent["parent"]
        for m in d_ref.finditer(sent["content"]):
            target_did = f"D{m.group(1)}"
            if target_did != parent and target_did in groups and groups[target_did]:
                known_edges.append((sid, groups[target_did][0], "CITES"))

    db.close()
    return sentences, groups, known_edges


# =========================================================================
# TEST A: Vocabulary Bridge
# =========================================================================

def test_vocabulary_bridge(sentences, groups):
    print("=" * 60, file=sys.stderr)
    print("TEST A: Vocabulary Bridge (D157/D188 via AGENT_CONSTRAINT)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # The problem: D157 ("ban async_bash") and D188 ("don't elaborate")
    # share ZERO vocabulary but are both agent behavior constraints.
    # Can HRR connect them via a shared edge type?

    # Gather agent behavior decisions
    behavior_decisions = ["D157", "D188", "D100", "D073"]
    behavior_sids = []
    for did in behavior_decisions:
        if did in groups and groups[did]:
            behavior_sids.append(groups[did][0])  # first sentence = core assertion

    # Also add some non-behavior decisions as distractors
    distractor_decisions = ["D097", "D099", "D005", "D137", "D174"]
    distractor_sids = []
    for did in distractor_decisions:
        if did in groups and groups[did]:
            distractor_sids.append(groups[did][0])

    all_sids = behavior_sids + distractor_sids
    print(f"\n  Behavior nodes: {behavior_sids}", file=sys.stderr)
    print(f"  Distractor nodes: {distractor_sids}", file=sys.stderr)

    for sid in behavior_sids:
        print(f"    {sid}: {sentences[sid]['content'][:60]}", file=sys.stderr)

    # Assign random vectors
    node_vecs = {sid: make_vec() for sid in all_sids}
    AGENT_CONSTRAINT = make_vec()
    DOMAIN_RULE = make_vec()

    # Build subgraph: connect all behavior nodes with AGENT_CONSTRAINT edges
    # This simulates the onboarding process classifying these as behavioral
    edges = []
    for i in range(len(behavior_sids)):
        for j in range(i+1, len(behavior_sids)):
            edges.append((behavior_sids[i], behavior_sids[j], "AGENT_CONSTRAINT"))

    # Add some DOMAIN_RULE edges between distractor nodes
    for i in range(len(distractor_sids)):
        for j in range(i+1, min(i+2, len(distractor_sids))):
            edges.append((distractor_sids[i], distractor_sids[j], "DOMAIN_RULE"))

    print(f"  Edges: {len(edges)} ({sum(1 for _,_,e in edges if e=='AGENT_CONSTRAINT')} AGENT_CONSTRAINT, "
          f"{sum(1 for _,_,e in edges if e=='DOMAIN_RULE')} DOMAIN_RULE)", file=sys.stderr)

    edge_type_vecs = {"AGENT_CONSTRAINT": AGENT_CONSTRAINT, "DOMAIN_RULE": DOMAIN_RULE}

    # Encode
    S = np.zeros(DIM)
    for src, dst, et in edges:
        S += bind(bind(node_vecs[src], edge_type_vecs[et]), node_vecs[dst])

    # THE TEST: Query from D157_s0 with AGENT_CONSTRAINT. Does it find D188_s0?
    test_sid = behavior_sids[0]  # D157_s0
    print(f"\n  Query: what is {test_sid} connected to via AGENT_CONSTRAINT?", file=sys.stderr)
    print(f"  ({sentences[test_sid]['content'][:60]})", file=sys.stderr)

    query = bind(node_vecs[test_sid], edge_type_vecs["AGENT_CONSTRAINT"])
    result = unbind(query, S)
    matches = nearest_k(result, node_vecs, k=len(all_sids))

    print(f"\n  Results:", file=sys.stderr)
    for label, sim in matches:
        is_behavior = label in behavior_sids
        is_self = label == test_sid
        marker = "SELF" if is_self else ("BEHAVIOR" if is_behavior else "distractor")
        print(f"    {label} ({sim:.4f}) [{marker}]: {sentences[label]['content'][:50]}", file=sys.stderr)

    # Did behavior nodes rank above distractor nodes?
    behavior_ranks = [i for i, (l, _) in enumerate(matches) if l in behavior_sids and l != test_sid]
    distractor_ranks = [i for i, (l, _) in enumerate(matches) if l in distractor_sids]

    behavior_sims = [s for l, s in matches if l in behavior_sids and l != test_sid]
    distractor_sims = [s for l, s in matches if l in distractor_sids]

    print(f"\n  Behavior node ranks: {behavior_ranks}", file=sys.stderr)
    print(f"  Distractor node ranks: {distractor_ranks}", file=sys.stderr)
    print(f"  Behavior mean sim: {np.mean(behavior_sims):.4f}", file=sys.stderr)
    print(f"  Distractor mean sim: {np.mean(distractor_sims):.4f}", file=sys.stderr)
    separation = np.mean(behavior_sims) / max(np.mean(distractor_sims), 0.001)
    print(f"  Separation ratio: {separation:.1f}x", file=sys.stderr)

    # Verdict
    all_behavior_above_all_distractor = all(br < dr for br in behavior_ranks for dr in distractor_ranks)
    print(f"\n  VERDICT: All behavior nodes ranked above all distractors: "
          f"{'YES' if all_behavior_above_all_distractor else 'NO'}", file=sys.stderr)

    return {
        "behavior_ranks": behavior_ranks,
        "distractor_ranks": distractor_ranks,
        "separation_ratio": round(separation, 2),
        "all_above": all_behavior_above_all_distractor,
    }


# =========================================================================
# TEST B: Multi-hop within capacity
# =========================================================================

def test_multihop(sentences, groups, known_edges):
    print(f"\n{'='*60}", file=sys.stderr)
    print("TEST B: Multi-hop within high-capacity subgraph", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # D195 neighborhood: 18 nodes, 25 edges. DIM=2048, capacity=204.
    # Single-hop: 5/5 (proven in Exp 31).
    # Test: 2-hop traversal D195_s1 -[CITES]-> X -[CITES]-> ?

    # Build D195 neighborhood with 2-hop edges
    d195_sids = [s for s in sentences if s.startswith("D195")]
    neighborhood_edges = []
    neighborhood_nodes = set()

    # D195's CITES targets
    for src, dst, et in known_edges:
        if src in d195_sids:
            neighborhood_edges.append((src, dst, et))
            neighborhood_nodes.add(src)
            neighborhood_nodes.add(dst)

    # Targets' CITES targets (hop 2)
    hop1_targets = set(dst for _, dst, _ in neighborhood_edges)
    for src, dst, et in known_edges:
        src_parent = sentences[src]["parent"]
        for h1 in hop1_targets:
            h1_parent = sentences[h1]["parent"]
            if src_parent == h1_parent:
                neighborhood_edges.append((src, dst, et))
                neighborhood_nodes.add(src)
                neighborhood_nodes.add(dst)

    neighborhood_edges = list(set(neighborhood_edges))
    print(f"  D195 2-hop neighborhood: {len(neighborhood_nodes)} nodes, "
          f"{len(neighborhood_edges)} edges", file=sys.stderr)
    print(f"  Capacity: ~{DIM//10}. Headroom: {DIM//10 - len(neighborhood_edges)}", file=sys.stderr)

    # Vectors
    node_vecs = {sid: make_vec() for sid in neighborhood_nodes}
    CITES = make_vec()

    # Encode
    S = np.zeros(DIM)
    for src, dst, et in neighborhood_edges:
        S += bind(bind(node_vecs[src], CITES), node_vecs[dst])

    # Single-hop validation
    test_sid = "D195_s1"
    if test_sid not in node_vecs:
        print("  D195_s1 not in neighborhood, skipping", file=sys.stderr)
        return {}

    print(f"\n  Single-hop validation: {test_sid} -[CITES]-> ?", file=sys.stderr)
    query_1hop = bind(node_vecs[test_sid], CITES)
    result_1hop = unbind(query_1hop, S)
    matches_1hop = nearest_k(result_1hop, node_vecs, k=5)

    actual_1hop = set(dst for src, dst, _ in neighborhood_edges if src == test_sid)
    found_1hop = set(m[0] for m in matches_1hop[:len(actual_1hop)]) & actual_1hop
    print(f"  Ground truth: {actual_1hop}", file=sys.stderr)
    print(f"  HRR top-{len(actual_1hop)}: {[m[0] for m in matches_1hop[:len(actual_1hop)]]}", file=sys.stderr)
    print(f"  Recall: {len(found_1hop)}/{len(actual_1hop)}", file=sys.stderr)

    # 2-hop test
    print(f"\n  2-hop: {test_sid} -[CITES]-> X -[CITES]-> ?", file=sys.stderr)

    # Ground truth 2-hop targets
    hop2_targets = set()
    for h1 in actual_1hop:
        h1_parent = sentences[h1]["parent"]
        for src, dst, _ in neighborhood_edges:
            if sentences[src]["parent"] == h1_parent and dst not in actual_1hop and dst != test_sid:
                hop2_targets.add(dst)

    print(f"  Ground truth 2-hop targets: {hop2_targets}", file=sys.stderr)

    if not hop2_targets:
        print("  No 2-hop targets found in neighborhood", file=sys.stderr)
        return {"single_hop_recall": f"{len(found_1hop)}/{len(actual_1hop)}", "two_hop": "no targets"}

    query_2hop = bind(bind(node_vecs[test_sid], CITES), CITES)
    result_2hop = unbind(query_2hop, S)
    matches_2hop = nearest_k(result_2hop, node_vecs, k=10)

    print(f"  HRR top-10:", file=sys.stderr)
    for label, sim in matches_2hop:
        marker = "***" if label in hop2_targets else ("h1" if label in actual_1hop else "   ")
        c = sentences.get(label, {}).get("content", "?")[:50]
        print(f"    {marker} {label} ({sim:.4f}): {c}", file=sys.stderr)

    found_2hop = set(m[0] for m in matches_2hop[:len(hop2_targets)]) & hop2_targets
    print(f"  Recall@{len(hop2_targets)}: {len(found_2hop)}/{len(hop2_targets)}", file=sys.stderr)

    return {
        "single_hop_recall": f"{len(found_1hop)}/{len(actual_1hop)}",
        "two_hop_targets": len(hop2_targets),
        "two_hop_found": len(found_2hop),
    }


# =========================================================================
# TEST C: Combined HRR + FTS5
# =========================================================================

def test_combined_pipeline(sentences, groups, known_edges):
    print(f"\n{'='*60}", file=sys.stderr)
    print("TEST C: Combined HRR + FTS5 Pipeline", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    CRITICAL = {
        "dispatch_gate": {
            "query": "dispatch gate deploy protocol",
            "needed": {"D089", "D106", "D137"},
        },
        "agent_behavior": {
            "query": "agent behavior instructions",
            "needed": {"D157", "D188"},
            "note": "D157 is the vocabulary mismatch case"
        },
    }

    # Build FTS5 on sentence content
    fts = sqlite3.connect(":memory:")
    fts.execute("CREATE VIRTUAL TABLE ft USING fts5(id, content, tokenize='porter')")
    for sid, s in sentences.items():
        fts.execute("INSERT INTO ft VALUES (?, ?)", (sid, s["content"]))
    fts.commit()

    # Build HRR graph for agent behavior decisions
    # Connect known agent behavior decisions via AGENT_CONSTRAINT
    behavior_dids = ["D157", "D188", "D100", "D073"]
    behavior_sids = [groups[d][0] for d in behavior_dids if d in groups and groups[d]]

    # Also include their CITES targets
    behavior_neighborhood = set(behavior_sids)
    for src, dst, et in known_edges:
        if any(src.startswith(d) for d in behavior_dids):
            behavior_neighborhood.add(src)
            behavior_neighborhood.add(dst)

    node_vecs = {sid: make_vec() for sid in behavior_neighborhood}
    AGENT_CONSTRAINT = make_vec()
    CITES = make_vec()

    edges_hrr = []
    # AGENT_CONSTRAINT between behavior core sentences
    for i in range(len(behavior_sids)):
        for j in range(i+1, len(behavior_sids)):
            edges_hrr.append((behavior_sids[i], behavior_sids[j], AGENT_CONSTRAINT))
    # CITES from known edges
    for src, dst, _ in known_edges:
        if src in behavior_neighborhood and dst in behavior_neighborhood:
            edges_hrr.append((src, dst, CITES))

    S = np.zeros(DIM)
    for src, dst, et_vec in edges_hrr:
        S += bind(bind(node_vecs[src], et_vec), node_vecs[dst])

    print(f"  HRR subgraph: {len(behavior_neighborhood)} nodes, {len(edges_hrr)} edges", file=sys.stderr)

    for topic_id, topic in CRITICAL.items():
        query_text = topic["query"]
        needed = topic["needed"]

        # FTS5 retrieval
        terms = " OR ".join(t for t in query_text.split() if len(t) > 2)
        try:
            fts_results = [r[0] for r in fts.execute(
                "SELECT id FROM ft WHERE ft MATCH ? ORDER BY rank LIMIT 15", (terms,)
            ).fetchall()]
        except:
            fts_results = []

        fts_parents = set(sentences[s]["parent"] for s in fts_results)
        fts_found = needed & fts_parents

        # HRR retrieval: for any FTS hit that's in the HRR subgraph,
        # traverse via AGENT_CONSTRAINT to find connected nodes
        hrr_found_sids = set()
        for fts_sid in fts_results:
            if fts_sid in node_vecs:
                # Traverse AGENT_CONSTRAINT from this hit
                q = bind(node_vecs[fts_sid], AGENT_CONSTRAINT)
                r = unbind(q, S)
                hrr_matches = nearest_k(r, node_vecs, k=5)
                for label, sim in hrr_matches:
                    if sim > 0.05:  # above noise
                        hrr_found_sids.add(label)

        hrr_parents = set(sentences[s]["parent"] for s in hrr_found_sids if s in sentences)
        combined_parents = fts_parents | hrr_parents
        combined_found = needed & combined_parents

        print(f"\n  {topic_id}: query='{query_text}'", file=sys.stderr)
        print(f"    FTS5 only:  found {fts_found} ({len(fts_found)}/{len(needed)})", file=sys.stderr)
        print(f"    HRR added:  {hrr_parents - fts_parents}", file=sys.stderr)
        print(f"    Combined:   found {combined_found} ({len(combined_found)}/{len(needed)})", file=sys.stderr)

        if topic_id == "agent_behavior":
            d157_in_fts = "D157" in fts_parents
            d157_in_combined = "D157" in combined_parents
            print(f"    D157 (vocab mismatch): FTS5={'found' if d157_in_fts else 'MISSED'}, "
                  f"Combined={'found' if d157_in_combined else 'MISSED'}", file=sys.stderr)

    return {}


# =========================================================================
# MAIN
# =========================================================================

def main():
    sentences, groups, known_edges = load_sentences()
    print(f"Loaded {len(sentences)} sentences, {len(groups)} decisions, "
          f"{len(known_edges)} known edges\n", file=sys.stderr)

    results = {}
    results["test_a"] = test_vocabulary_bridge(sentences, groups)
    results["test_b"] = test_multihop(sentences, groups, known_edges)
    results["test_c"] = test_combined_pipeline(sentences, groups, known_edges)

    print(f"\n{'='*60}", file=sys.stderr)
    print("ALL TESTS COMPLETE", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    import json
    Path("experiments/exp34_results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
