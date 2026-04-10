from __future__ import annotations

"""
Experiment 35: Weighted Edges + Beam Search for Multi-Hop HRR

Baseline: iterative with cleanup = 1/3 recall (D097 found, D175/D167 missed)
Test: weighted encoding + beam search
Goal: >= 2/3 recall on hop-2 targets

Same D195 neighborhood: 18 nodes, 25 edges, DIM=2048.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
          "260406-1-associative-memory-for-gsd-please-explor/"
          "sandbox/alpha-seek.db")

DIM = 2048
rng = np.random.default_rng(42)

NDArr = npt.NDArray[np.floating[Any]]


def make_vec() -> NDArr:
    v: NDArr = rng.standard_normal(DIM)
    return v / np.linalg.norm(v)

def bind(a: NDArr, b: NDArr) -> NDArr:
    result: NDArr = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))
    return result

def unbind(key: NDArr, bound: NDArr) -> NDArr:
    result: NDArr = np.real(np.fft.ifft(np.conj(np.fft.fft(key)) * np.fft.fft(bound)))
    return result

def cos_sim(a: NDArr, b: NDArr) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

def nearest_k(query: NDArr, memory: dict[str, NDArr], k: int = 5) -> list[tuple[str, float]]:
    sims: list[tuple[str, float]] = [(l, cos_sim(query, v)) for l, v in memory.items()]
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:k]


def split_sents(text: str) -> list[str]:
    parts: list[str | Any] = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    sents: list[str] = []
    for p in parts:
        for sp in str(p).split(' | '):
            sp = sp.strip()
            if len(sp) > 10: sents.append(sp)
    return sents


SentDict = dict[str, dict[str, Any]]
GroupDict = dict[str, list[str]]
EdgeList = list[tuple[str, str, str]]


def build_neighborhood() -> tuple[SentDict, GroupDict, set[str], EdgeList]:
    db = sqlite3.connect(str(DB))
    sentences: SentDict = {}
    groups: GroupDict = {}
    for row in db.execute("SELECT id, decision, choice, rationale FROM decisions"):
        did: str = str(row[0])
        full = f"{row[1]}: {row[2]}"
        if row[3]: full += f" | {row[3]}"
        sents = split_sents(full)
        g: list[str] = []
        for i, s in enumerate(sents):
            sid = f"{did}_s{i}"
            sentences[sid] = {"content": s, "parent": did, "index": i}
            g.append(sid)
        groups[did] = g

    known_edges: EdgeList = []
    d_ref = re.compile(r'\bD(\d{2,3})\b')
    for sid, sent in sentences.items():
        parent: str = sent["parent"]
        for m in d_ref.finditer(str(sent["content"])):
            target_did = f"D{m.group(1)}"
            if target_did != parent and target_did in groups and groups[target_did]:
                known_edges.append((sid, groups[target_did][0], "CITES"))
    db.close()

    # Build D195 2-hop neighborhood
    d195_sids: list[str] = [s for s in sentences if s.startswith("D195")]
    edges: EdgeList = []
    nodes: set[str] = set()
    for src, dst, et in known_edges:
        if src in d195_sids:
            edges.append((src, dst, et))
            nodes.add(src)
            nodes.add(dst)
    hop1_targets: set[str] = set(dst for _, dst, _ in edges)
    for src, dst, et in known_edges:
        if str(sentences[src]["parent"]) in [str(sentences[h]["parent"]) for h in hop1_targets]:
            edges.append((src, dst, et))
            nodes.add(src)
            nodes.add(dst)
    edges = list(set(edges))

    return sentences, groups, nodes, edges


def main() -> None:
    sentences, _groups, nodes, edges = build_neighborhood()

    test_sid = "D195_s1"
    actual_1hop: set[str] = set(dst for src, dst, _ in edges if src == test_sid)
    hop2_targets: set[str] = set()
    for h1 in actual_1hop:
        h1_parent: str = str(sentences[h1]["parent"])
        for src, dst, _ in edges:
            if str(sentences[src]["parent"]) == h1_parent and dst not in actual_1hop and dst != test_sid:
                hop2_targets.add(dst)

    print(f"Neighborhood: {len(nodes)} nodes, {len(edges)} edges", file=sys.stderr)
    print(f"Hop-1 targets: {actual_1hop}", file=sys.stderr)
    print(f"Hop-2 targets: {hop2_targets}", file=sys.stderr)
    for t in hop2_targets:
        print(f"  {t}: {str(sentences[t]['content'])[:60]}", file=sys.stderr)

    node_vecs: dict[str, NDArr] = {sid: make_vec() for sid in nodes}
    CITES: NDArr = make_vec()

    # --- Assign edge weights ---
    # Simulate confidence-based weights: count how many edges a node has
    # (proxy for importance/citation count)
    node_degree: defaultdict[str, int] = defaultdict(int)
    for src, dst, _ in edges:
        node_degree[src] += 1
        node_degree[dst] += 1

    max_degree = max(node_degree.values()) if node_degree else 1
    edge_weights: dict[tuple[str, str], float] = {}
    for src, dst, _et in edges:
        # Weight = geometric mean of normalized degrees
        w_src = node_degree[src] / max_degree
        w_dst = node_degree[dst] / max_degree
        weight = float(np.sqrt(w_src * w_dst))
        weight = max(weight, 0.1)  # floor
        edge_weights[(src, dst)] = weight

    # =================================================================
    # METHOD A: Baseline iterative (from Exp 34, no weights, no beam)
    # =================================================================
    print(f"\n{'='*60}", file=sys.stderr)
    print("METHOD A: Iterative with cleanup (baseline)", file=sys.stderr)

    S_unweighted: NDArr = np.zeros(DIM)
    for src, dst, _et in edges:
        S_unweighted += bind(bind(node_vecs[src], CITES), node_vecs[dst])

    hop1_result: NDArr = unbind(bind(node_vecs[test_sid], CITES), S_unweighted)
    hop1_clean: list[tuple[str, float]] = nearest_k(hop1_result, node_vecs, k=5)

    all_hop2_a: defaultdict[str, float] = defaultdict(float)
    for h1_label, _ in hop1_clean:
        if h1_label not in actual_1hop:
            continue
        hop2_result: NDArr = unbind(bind(node_vecs[h1_label], CITES), S_unweighted)
        for label, sim in nearest_k(hop2_result, node_vecs, k=5):
            all_hop2_a[label] = max(all_hop2_a[label], sim)

    ranked_a: list[tuple[str, float]] = sorted(all_hop2_a.items(), key=lambda x: x[1], reverse=True)
    found_a: set[str] = set(l for l, _ in ranked_a[:len(hop2_targets)]) & hop2_targets
    print(f"  Top-{len(hop2_targets)}:", file=sys.stderr)
    for _i, (l, s) in enumerate(ranked_a[:6]):
        mk = "***" if l in hop2_targets else "   "
        print(f"    {mk} {l} ({s:.4f}): {str(sentences.get(l,{}).get('content','?'))[:45]}", file=sys.stderr)
    print(f"  Recall@{len(hop2_targets)}: {len(found_a)}/{len(hop2_targets)}", file=sys.stderr)

    # =================================================================
    # METHOD B: Weighted encoding + iterative
    # =================================================================
    print(f"\n{'='*60}", file=sys.stderr)
    print("METHOD B: Weighted edges + iterative cleanup", file=sys.stderr)

    S_weighted: NDArr = np.zeros(DIM)
    for src, dst, _et in edges:
        w = edge_weights[(src, dst)]
        S_weighted += w * bind(bind(node_vecs[src], CITES), node_vecs[dst])

    hop1_result = unbind(bind(node_vecs[test_sid], CITES), S_weighted)
    hop1_clean = nearest_k(hop1_result, node_vecs, k=5)

    all_hop2_b: defaultdict[str, float] = defaultdict(float)
    for h1_label, _ in hop1_clean:
        if h1_label not in actual_1hop:
            continue
        hop2_result = unbind(bind(node_vecs[h1_label], CITES), S_weighted)
        for label, sim in nearest_k(hop2_result, node_vecs, k=5):
            all_hop2_b[label] = max(all_hop2_b[label], sim)

    ranked_b: list[tuple[str, float]] = sorted(all_hop2_b.items(), key=lambda x: x[1], reverse=True)
    found_b: set[str] = set(l for l, _ in ranked_b[:len(hop2_targets)]) & hop2_targets
    print(f"  Top-{len(hop2_targets)}:", file=sys.stderr)
    for _i, (l, s) in enumerate(ranked_b[:6]):
        mk = "***" if l in hop2_targets else "   "
        print(f"    {mk} {l} ({s:.4f}): {str(sentences.get(l,{}).get('content','?'))[:45]}", file=sys.stderr)
    print(f"  Recall@{len(hop2_targets)}: {len(found_b)}/{len(hop2_targets)}", file=sys.stderr)

    # =================================================================
    # METHOD C: Beam search (top-k at each hop, aggregate)
    # =================================================================
    print(f"\n{'='*60}", file=sys.stderr)
    print("METHOD C: Beam search (k=5) + iterative cleanup", file=sys.stderr)

    BEAM_K = 5

    # Hop 1: top-k
    hop1_result = unbind(bind(node_vecs[test_sid], CITES), S_unweighted)
    hop1_beam: list[tuple[str, float]] = nearest_k(hop1_result, node_vecs, k=BEAM_K)

    # Hop 2: from EACH hop-1 node (even if not in ground truth), top-k
    all_hop2_c: defaultdict[str, float] = defaultdict(float)
    for h1_label, h1_sim in hop1_beam:
        if h1_label == test_sid:
            continue
        hop2_result = unbind(bind(node_vecs[h1_label], CITES), S_unweighted)
        for label, sim in nearest_k(hop2_result, node_vecs, k=BEAM_K):
            if label != test_sid and label != h1_label:
                all_hop2_c[label] = max(all_hop2_c[label], sim)

    ranked_c: list[tuple[str, float]] = sorted(all_hop2_c.items(), key=lambda x: x[1], reverse=True)
    found_c: set[str] = set(l for l, _ in ranked_c[:len(hop2_targets)]) & hop2_targets
    print(f"  Top-{len(hop2_targets)}:", file=sys.stderr)
    for _i, (l, s) in enumerate(ranked_c[:6]):
        mk = "***" if l in hop2_targets else "   "
        print(f"    {mk} {l} ({s:.4f}): {str(sentences.get(l,{}).get('content','?'))[:45]}", file=sys.stderr)
    print(f"  Recall@{len(hop2_targets)}: {len(found_c)}/{len(hop2_targets)}", file=sys.stderr)

    # =================================================================
    # METHOD D: Weighted + Beam search combined
    # =================================================================
    print(f"\n{'='*60}", file=sys.stderr)
    print("METHOD D: Weighted edges + beam search (k=5)", file=sys.stderr)

    hop1_result = unbind(bind(node_vecs[test_sid], CITES), S_weighted)
    hop1_beam = nearest_k(hop1_result, node_vecs, k=BEAM_K)

    all_hop2_d: defaultdict[str, float] = defaultdict(float)
    for h1_label, h1_sim in hop1_beam:
        if h1_label == test_sid:
            continue
        hop2_result = unbind(bind(node_vecs[h1_label], CITES), S_weighted)
        for label, sim in nearest_k(hop2_result, node_vecs, k=BEAM_K):
            if label != test_sid and label != h1_label:
                # Weight by hop-1 similarity (path score)
                path_score = h1_sim * sim
                all_hop2_d[label] = max(all_hop2_d[label], path_score)

    ranked_d: list[tuple[str, float]] = sorted(all_hop2_d.items(), key=lambda x: x[1], reverse=True)
    found_d: set[str] = set(l for l, _ in ranked_d[:len(hop2_targets)]) & hop2_targets
    print(f"  Top-{len(hop2_targets)}:", file=sys.stderr)
    for _i, (l, s) in enumerate(ranked_d[:6]):
        mk = "***" if l in hop2_targets else "   "
        print(f"    {mk} {l} ({s:.4f}): {str(sentences.get(l,{}).get('content','?'))[:45]}", file=sys.stderr)
    print(f"  Recall@{len(hop2_targets)}: {len(found_d)}/{len(hop2_targets)}", file=sys.stderr)

    # =================================================================
    # SUMMARY
    # =================================================================
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY: Hop-2 recall for {hop2_targets}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  A. Baseline iterative:        {len(found_a)}/{len(hop2_targets)}", file=sys.stderr)
    print(f"  B. Weighted + iterative:      {len(found_b)}/{len(hop2_targets)}", file=sys.stderr)
    print(f"  C. Beam search + iterative:   {len(found_c)}/{len(hop2_targets)}", file=sys.stderr)
    print(f"  D. Weighted + beam (combined): {len(found_d)}/{len(hop2_targets)}", file=sys.stderr)

    import json
    Path("experiments/exp35_results.json").write_text(json.dumps({
        "baseline": {"recall": len(found_a), "total": len(hop2_targets), "found": list(found_a)},
        "weighted": {"recall": len(found_b), "total": len(hop2_targets), "found": list(found_b)},
        "beam": {"recall": len(found_c), "total": len(hop2_targets), "found": list(found_c)},
        "combined": {"recall": len(found_d), "total": len(hop2_targets), "found": list(found_d)},
    }, indent=2))


if __name__ == "__main__":
    main()
