"""
Experiment 26: Hierarchical Confidence on Real Alpha-Seek Topology

Exp 22 used artificial subgraphs (every 50th node). This tests on real
graph topology where anchors have uneven degree (D097=70, most nodes=1-3).

Questions:
- Does real topology help or hurt vs artificial?
- Does D097 (70 edges) over-propagate?
- What propagation weight works for power-law topology?
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from experiments.exp2_bayesian_calibration import Belief, compute_calibration


ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

DOMAINS = ["strategy", "methodology", "knowledge", "architecture",
           "data-source", "backtesting", "agent behavior", "milestone"]
N_SESSIONS = 50
N_TRIALS = 10


def load_real_graph():
    """Load alpha-seek nodes and build real subgraphs from anchors."""
    db = sqlite3.connect(str(ALPHA_SEEK_DB))

    nodes = {}
    for row in db.execute("SELECT id, content, category, confidence FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes[row[0]] = {
            "content": row[1],
            "category": row[2] or "unknown",
            "confidence": row[3] or 0.5,
        }

    adj = defaultdict(list)
    for row in db.execute("SELECT from_id, to_id, edge_type, weight FROM mem_edges"):
        adj[row[0]].append((row[1], row[2], row[3] or 1.0))
        adj[row[1]].append((row[0], row[2], row[3] or 1.0))

    db.close()

    # Find natural anchors (degree >= 10)
    degrees = {nid: len(adj.get(nid, [])) for nid in nodes}
    anchors = {nid: deg for nid, deg in degrees.items() if deg >= 10}

    # Build subgraphs via BFS from each anchor (1-hop)
    subgraphs = {}
    for anchor_id in anchors:
        members = set()
        for neighbor, etype, weight in adj.get(anchor_id, []):
            if neighbor in nodes and neighbor not in anchors:
                members.add(neighbor)
        subgraphs[anchor_id] = members

    return nodes, adj, anchors, subgraphs, degrees


def create_beliefs_from_graph(nodes, rng):
    """Create belief objects from real graph nodes with semi-realistic true rates."""
    beliefs = {}
    # Assign true rates based on category (domain proxy)
    category_rates = {
        "strategy": 0.75, "methodology": 0.80, "knowledge": 0.60,
        "architecture": 0.65, "data-source": 0.55, "backtesting": 0.70,
        "agent behavior": 0.85, "milestone": 0.50, "unknown": 0.50,
    }

    for nid, node in nodes.items():
        cat = node["category"]
        base_rate = category_rates.get(cat, 0.55)
        # Add noise to true rate
        true_rate = np.clip(base_rate + rng.normal(0, 0.1), 0.1, 0.95)

        beliefs[nid] = Belief(
            id=hash(nid) % 100000,
            source_type=cat,
            true_usefulness_rate=true_rate,
            alpha=0.5,
            beta_param=0.5,
        )
        beliefs[nid]._nid = nid  # keep track of node ID

    return beliefs


def run_flat(beliefs_dict, rng):
    """Flat Thompson sampling (baseline)."""
    beliefs = list(beliefs_dict.values())
    n = len(beliefs)

    for _ in range(N_SESSIONS):
        for _ in range(10):
            samples = np.array([rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)) for b in beliefs])
            top_k = np.argpartition(samples, -5)[-5:]
            for idx in top_k:
                beliefs[idx].retrieval_count += 1
                if rng.random() < 0.30:
                    beliefs[idx].update("ignored")
                elif rng.random() < beliefs[idx].true_usefulness_rate:
                    beliefs[idx].update("used")
                else:
                    beliefs[idx].update("harmful")

    cal = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    return {"ece": cal["ece"], "coverage": round(tested / n, 4)}


def run_hierarchical(beliefs_dict, subgraphs, anchors, prop_weight, rng):
    """Hierarchical with real subgraphs and configurable propagation weight."""
    beliefs = list(beliefs_dict.values())
    nid_to_idx = {b._nid: i for i, b in enumerate(beliefs)}
    n = len(beliefs)

    # Map anchor indices to member indices
    anchor_members = {}
    for anchor_nid, members in subgraphs.items():
        if anchor_nid in nid_to_idx:
            anchor_idx = nid_to_idx[anchor_nid]
            member_idxs = [nid_to_idx[m] for m in members if m in nid_to_idx]
            anchor_members[anchor_idx] = member_idxs

    for _ in range(N_SESSIONS):
        for _ in range(10):
            samples = np.array([rng.beta(max(b.alpha, 0.01), max(b.beta_param, 0.01)) for b in beliefs])
            top_k = np.argpartition(samples, -5)[-5:]

            for idx in top_k:
                b = beliefs[idx]
                b.retrieval_count += 1

                if rng.random() < 0.30:
                    outcome = "ignored"
                elif rng.random() < b.true_usefulness_rate:
                    outcome = "used"
                else:
                    outcome = "harmful"
                b.update(outcome)

                # Propagate if this is an anchor
                if idx in anchor_members and outcome != "ignored":
                    members = anchor_members[idx]
                    # Scale propagation by 1/sqrt(subgraph_size) to prevent over-propagation
                    scaled_weight = prop_weight / max(1, np.sqrt(len(members)))
                    for midx in members:
                        if outcome == "used":
                            beliefs[midx].alpha += scaled_weight
                        else:
                            beliefs[midx].beta_param += scaled_weight
                        beliefs[midx].retrieval_count += 1

    cal = compute_calibration(beliefs)
    tested = sum(1 for b in beliefs if b.retrieval_count > 0)
    return {"ece": cal["ece"], "coverage": round(tested / n, 4)}


def main():
    rng_base = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 26: Real Topology Hierarchical Confidence", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    nodes, adj, anchors, subgraphs, degrees = load_real_graph()
    print(f"  Nodes: {len(nodes)}", file=sys.stderr)
    print(f"  Anchors (degree >= 10): {len(anchors)}", file=sys.stderr)
    for aid, deg in sorted(anchors.items(), key=lambda x: x[1], reverse=True)[:5]:
        sg_size = len(subgraphs.get(aid, set()))
        print(f"    {aid}: degree={deg}, subgraph={sg_size} members", file=sys.stderr)

    results = {}

    # Flat baseline
    print(f"\n  Running flat Thompson...", file=sys.stderr)
    flat_eces = []
    flat_covs = []
    for _ in range(N_TRIALS):
        seed = rng_base.integers(0, 2**32)
        beliefs = create_beliefs_from_graph(nodes, np.random.default_rng(seed))
        r = run_flat(beliefs, np.random.default_rng(seed))
        flat_eces.append(r["ece"])
        flat_covs.append(r["coverage"])

    results["flat"] = {
        "ece": round(float(np.mean(flat_eces)), 4),
        "coverage": round(float(np.mean(flat_covs)), 4),
    }
    print(f"    ECE={np.mean(flat_eces):.4f}, coverage={np.mean(flat_covs):.0%}", file=sys.stderr)

    # Hierarchical with different propagation weights
    for pw in [0.1, 0.3, 0.5, 1.0]:
        print(f"\n  Running hierarchical (prop_weight={pw})...", file=sys.stderr)
        h_eces = []
        h_covs = []
        for _ in range(N_TRIALS):
            seed = rng_base.integers(0, 2**32)
            beliefs = create_beliefs_from_graph(nodes, np.random.default_rng(seed))
            r = run_hierarchical(beliefs, subgraphs, anchors, pw, np.random.default_rng(seed))
            h_eces.append(r["ece"])
            h_covs.append(r["coverage"])

        results[f"hierarchical_pw{pw}"] = {
            "ece": round(float(np.mean(h_eces)), 4),
            "coverage": round(float(np.mean(h_covs)), 4),
        }
        print(f"    ECE={np.mean(h_eces):.4f}, coverage={np.mean(h_covs):.0%}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"{'Method':<25} {'ECE':>8} {'Coverage':>10}", file=sys.stderr)
    print("-" * 45, file=sys.stderr)
    for method, r in results.items():
        print(f"{method:<25} {r['ece']:>8.4f} {r['coverage']:>10.0%}", file=sys.stderr)

    Path("experiments/exp26_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nOutput: experiments/exp26_results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
