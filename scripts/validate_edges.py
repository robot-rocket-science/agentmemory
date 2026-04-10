"""
validate_edges.py -- V1: Validate edge precision without human labeling.

Three validation approaches:
  1. Triangulation: stratify edges by multi-method agreement
  2. Negative sampling: do co-change edges predict structure better than random?
  3. Self-consistency: transitivity and degree distribution checks

Usage:
    python scripts/validate_edges.py /path/to/repo /path/to/extracted_dir

Reads: extracted/{git_edges,import_edges,structural_edges}/<repo>.json
Writes: extracted/validation/<repo>.json
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


SKIP_DIRS: set[str] = {
    ".git", "node_modules", "target", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".tox", "vendor",
    "third_party", "3rdparty",
}


def load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON file if it exists."""
    if path.exists():
        result: dict[str, Any] = json.loads(path.read_text())
        return result
    return None


def file_pairs_undirected(edges: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Extract undirected (source, target) file pairs from edge list."""
    pairs: set[tuple[str, str]] = set()
    for e in edges:
        s: str = e.get("source", "")
        t: str = e.get("target", "")
        if ":" in s or ":" in t:
            continue
        pairs.add((min(s, t), max(s, t)))
    return pairs


def share_directory(a: str, b: str) -> bool:
    """Check if two file paths share a parent directory."""
    return os.path.dirname(a) == os.path.dirname(b)


def path_depth_distance(a: str, b: str) -> int:
    """Count the number of directory levels separating two paths."""
    parts_a: tuple[str, ...] = Path(a).parts
    parts_b: tuple[str, ...] = Path(b).parts
    # Find common prefix length
    common: int = 0
    for pa, pb in zip(parts_a, parts_b):
        if pa == pb:
            common += 1
        else:
            break
    return (len(parts_a) - common) + (len(parts_b) - common)


# --- Approach 2: Triangulation ---

def triangulation_analysis(
    extracted_dir: Path,
    repo_name: str,
    min_cochange_weight: int = 3,
) -> dict[str, Any]:
    """Stratify edges by number of independent methods that found them."""

    # Load edges per method as undirected pairs
    method_pairs: dict[str, set[tuple[str, str]]] = {}

    git_data: dict[str, Any] | None = load_json(extracted_dir / "git_edges" / f"{repo_name}.json")
    if git_data:
        co_pairs: set[tuple[str, str]] = set()
        for e in git_data.get("co_changed_edges", []):
            w: int = e.get("weight", 1)
            if w >= min_cochange_weight:
                co_pairs.add((min(e["source"], e["target"]), max(e["source"], e["target"])))
        if co_pairs:
            method_pairs["CO_CHANGED"] = co_pairs

    imp_data: dict[str, Any] | None = load_json(extracted_dir / "import_edges" / f"{repo_name}.json")
    if imp_data:
        imp_pairs: set[tuple[str, str]] = file_pairs_undirected(imp_data.get("edges", []))
        if imp_pairs:
            method_pairs["IMPORTS"] = imp_pairs

    str_data: dict[str, Any] | None = load_json(extracted_dir / "structural_edges" / f"{repo_name}.json")
    if str_data:
        struct_pairs: set[tuple[str, str]] = file_pairs_undirected(str_data.get("edges", []))
        if struct_pairs:
            method_pairs["STRUCTURAL"] = struct_pairs

    if not method_pairs:
        return {"error": "no methods produced edges"}

    # Count how many methods found each edge
    edge_method_count: Counter[tuple[str, str]] = Counter()
    edge_methods: dict[tuple[str, str], list[str]] = defaultdict(list)
    for method, pairs in method_pairs.items():
        for pair in pairs:
            edge_method_count[pair] += 1
            edge_methods[pair].append(method)

    # Stratify
    by_count: dict[int, int] = Counter(edge_method_count.values())
    total_edges: int = len(edge_method_count)

    # Sample edges at each tier
    tier_samples: dict[str, list[dict[str, Any]]] = {}
    for n_methods in sorted(by_count.keys()):
        tier_edges: list[tuple[str, str]] = [p for p, c in edge_method_count.items() if c == n_methods]
        sample_size: int = min(10, len(tier_edges))
        rng: np.random.Generator = np.random.default_rng(42)
        sample_indices: NDArray[np.intp] = rng.choice(len(tier_edges), size=sample_size, replace=False)
        samples: list[dict[str, Any]] = []
        for idx in sample_indices:
            pair: tuple[str, str] = tier_edges[int(idx)]
            samples.append({
                "source": pair[0],
                "target": pair[1],
                "methods": edge_methods[pair],
                "same_dir": share_directory(pair[0], pair[1]),
            })
        tier_samples[f"{n_methods}_methods"] = samples

    return {
        "total_edges": total_edges,
        "methods_available": list(method_pairs.keys()),
        "edges_per_method": {m: len(p) for m, p in method_pairs.items()},
        "stratification": {f"{k}_methods": v for k, v in sorted(by_count.items())},
        "pct_multi_method": round(sum(v for k, v in by_count.items() if k >= 2) / max(total_edges, 1) * 100, 1),
        "tier_samples": tier_samples,
    }


# --- Approach 3: Negative Sampling ---

def negative_sampling_analysis(
    repo_path: Path,
    extracted_dir: Path,
    repo_name: str,
    n_samples: int = 100,
    min_cochange_weight: int = 3,
) -> dict[str, Any]:
    """Test whether co-change edges predict structure better than random pairs."""

    # Load co-change edges
    git_data: dict[str, Any] | None = load_json(extracted_dir / "git_edges" / f"{repo_name}.json")
    if not git_data:
        return {"error": "no git edges"}

    # Get weighted co-change pairs
    weighted_pairs: list[tuple[str, str, int]] = []
    for e in git_data.get("co_changed_edges", []):
        w: int = e.get("weight", 1)
        if w >= min_cochange_weight:
            weighted_pairs.append((e["source"], e["target"], w))

    if len(weighted_pairs) < 20:
        return {"error": f"too few co-change edges ({len(weighted_pairs)})"}

    # Sort by weight descending, take top n_samples
    weighted_pairs.sort(key=lambda x: x[2], reverse=True)
    positive_pairs: list[tuple[str, str]] = [(a, b) for a, b, _ in weighted_pairs[:n_samples]]

    # Load import edges for cross-check
    imp_data: dict[str, Any] | None = load_json(extracted_dir / "import_edges" / f"{repo_name}.json")
    import_pairs: set[tuple[str, str]] = set()
    if imp_data:
        import_pairs = file_pairs_undirected(imp_data.get("edges", []))

    # Get all files in repo
    all_files: list[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            rel: str = str(Path(root, f).relative_to(repo_path))
            all_files.append(rel)

    # Generate random negative pairs (files that never co-changed)
    positive_set: set[tuple[str, str]] = set()
    for a, b in positive_pairs:
        positive_set.add((min(a, b), max(a, b)))

    all_cochange_set: set[tuple[str, str]] = set()
    for e in git_data.get("co_changed_edges", []):
        all_cochange_set.add((min(e["source"], e["target"]), max(e["source"], e["target"])))

    rng: np.random.Generator = np.random.default_rng(42)
    negative_pairs: list[tuple[str, str]] = []
    attempts: int = 0
    max_attempts: int = n_samples * 20
    while len(negative_pairs) < n_samples and attempts < max_attempts:
        i: int = int(rng.integers(0, len(all_files)))
        j: int = int(rng.integers(0, len(all_files)))
        if i == j:
            attempts += 1
            continue
        pair: tuple[str, str] = (min(all_files[i], all_files[j]), max(all_files[i], all_files[j]))
        if pair not in all_cochange_set:
            negative_pairs.append(pair)
        attempts += 1

    # Measure structural properties for positive vs negative
    def measure_properties(pairs: list[tuple[str, str]]) -> dict[str, float]:
        n: int = len(pairs)
        if n == 0:
            return {"same_dir": 0.0, "has_import": 0.0, "avg_path_dist": 0.0}
        same_dir_count: int = sum(1 for a, b in pairs if share_directory(a, b))
        import_count: int = sum(1 for a, b in pairs if (min(a, b), max(a, b)) in import_pairs)
        path_dists: list[int] = [path_depth_distance(a, b) for a, b in pairs]
        return {
            "same_dir": round(same_dir_count / n, 4),
            "has_import": round(import_count / n, 4),
            "avg_path_dist": round(sum(path_dists) / n, 2),
        }

    pos_props: dict[str, float] = measure_properties(positive_pairs)
    neg_props: dict[str, float] = measure_properties(negative_pairs)

    # Lift: how much better are positive edges than random?
    lifts: dict[str, float] = {}
    for key in pos_props:
        neg_val: float = neg_props[key]
        pos_val: float = pos_props[key]
        if key == "avg_path_dist":
            # Lower is better for path distance
            lifts[key] = round(neg_val / max(pos_val, 0.01), 2)
        else:
            # Higher is better for same_dir, has_import
            lifts[key] = round(pos_val / max(neg_val, 0.001), 2)

    return {
        "n_positive": len(positive_pairs),
        "n_negative": len(negative_pairs),
        "positive_properties": pos_props,
        "negative_properties": neg_props,
        "lift": lifts,
        "verdict": (
            "SIGNAL" if lifts.get("same_dir", 0) > 2.0 or lifts.get("has_import", 0) > 2.0
            else "WEAK" if lifts.get("same_dir", 0) > 1.5 or lifts.get("has_import", 0) > 1.5
            else "NOISE"
        ),
    }


# --- Approach 5: Self-Consistency ---

def self_consistency_analysis(
    extracted_dir: Path,
    repo_name: str,
    min_cochange_weight: int = 3,
) -> dict[str, Any]:
    """Check transitivity and degree distribution of co-change graph."""

    git_data: dict[str, Any] | None = load_json(extracted_dir / "git_edges" / f"{repo_name}.json")
    if not git_data:
        return {"error": "no git edges"}

    # Build adjacency from co-change
    adj: dict[str, set[str]] = defaultdict(set)
    edge_count: int = 0
    for e in git_data.get("co_changed_edges", []):
        w: int = e.get("weight", 1)
        if w >= min_cochange_weight:
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])
            edge_count += 1

    if edge_count < 10:
        return {"error": f"too few edges ({edge_count})"}

    nodes: list[str] = list(adj.keys())
    n_nodes: int = len(nodes)

    # Degree distribution
    degrees: list[int] = [len(neighbors) for neighbors in adj.values()]
    mean_degree: float = sum(degrees) / max(len(degrees), 1)
    max_degree: int = max(degrees) if degrees else 0
    median_degree: float = float(sorted(degrees)[len(degrees) // 2]) if degrees else 0.0

    # Check if degree distribution is heavy-tailed (power-law-like)
    # Simple test: ratio of max to median. Power-law: high ratio. Uniform: low ratio.
    tail_ratio: float = max_degree / max(median_degree, 1.0)

    # Transitivity (clustering coefficient)
    # Sample nodes for efficiency
    rng: np.random.Generator = np.random.default_rng(42)
    sample_size: int = min(200, n_nodes)
    sample_indices: NDArray[np.intp] = rng.choice(n_nodes, size=sample_size, replace=False)
    sample_nodes: list[str] = [nodes[int(i)] for i in sample_indices]

    transitive_triples: int = 0
    total_triples: int = 0
    for node in sample_nodes:
        neighbors: list[str] = list(adj[node])
        if len(neighbors) < 2:
            continue
        # Sample pairs of neighbors
        max_pairs: int = min(50, len(neighbors) * (len(neighbors) - 1) // 2)
        for _ in range(max_pairs):
            i: int = int(rng.integers(0, len(neighbors)))
            j: int = int(rng.integers(0, len(neighbors)))
            if i == j:
                continue
            total_triples += 1
            if neighbors[j] in adj[neighbors[i]]:
                transitive_triples += 1

    clustering_coeff: float = transitive_triples / max(total_triples, 1)

    # Compare against random graph expectation
    # For Erdos-Renyi with same density: expected clustering = density = 2*edges / (n*(n-1))
    max_possible_edges: float = n_nodes * (n_nodes - 1) / 2
    density: float = edge_count / max(max_possible_edges, 1)
    clustering_vs_random: float = clustering_coeff / max(density, 1e-6)

    return {
        "n_nodes": n_nodes,
        "n_edges": edge_count,
        "density": round(density, 6),
        "degree_stats": {
            "mean": round(mean_degree, 1),
            "median": median_degree,
            "max": max_degree,
            "tail_ratio": round(tail_ratio, 1),
        },
        "transitivity": {
            "clustering_coefficient": round(clustering_coeff, 4),
            "random_graph_expected": round(density, 6),
            "ratio_vs_random": round(clustering_vs_random, 1),
            "triples_sampled": total_triples,
        },
        "verdict": {
            "degree_distribution": (
                "HEAVY_TAILED" if tail_ratio > 10
                else "MODERATE_TAIL" if tail_ratio > 5
                else "NEAR_UNIFORM"
            ),
            "transitivity": (
                "STRONG_CLUSTERING" if clustering_vs_random > 50
                else "MODERATE_CLUSTERING" if clustering_vs_random > 10
                else "WEAK_CLUSTERING" if clustering_vs_random > 2
                else "RANDOM_LIKE"
            ),
        },
    }


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /path/to/repo /path/to/extracted_dir")
        sys.exit(1)

    repo_path: Path = Path(sys.argv[1]).resolve()
    extracted_dir: Path = Path(sys.argv[2])
    repo_name: str = repo_path.name

    print(f"[validate] {repo_name}", file=sys.stderr)

    # Approach 2: Triangulation
    print(f"\n  === Triangulation ===", file=sys.stderr)
    tri: dict[str, Any] = triangulation_analysis(extracted_dir, repo_name)
    if "error" not in tri:
        print(f"  total edges: {tri['total_edges']}", file=sys.stderr)
        print(f"  methods: {tri['methods_available']}", file=sys.stderr)
        for tier, count in sorted(tri["stratification"].items()):
            print(f"    {tier}: {count} edges", file=sys.stderr)
        print(f"  multi-method: {tri['pct_multi_method']}%", file=sys.stderr)
    else:
        print(f"  {tri['error']}", file=sys.stderr)

    # Approach 3: Negative Sampling
    print(f"\n  === Negative Sampling (co-change vs random) ===", file=sys.stderr)
    neg: dict[str, Any] = negative_sampling_analysis(repo_path, extracted_dir, repo_name)
    if "error" not in neg:
        print(f"  positive (top co-change): {neg['positive_properties']}", file=sys.stderr)
        print(f"  negative (random pairs):  {neg['negative_properties']}", file=sys.stderr)
        print(f"  lift: {neg['lift']}", file=sys.stderr)
        print(f"  verdict: {neg['verdict']}", file=sys.stderr)
    else:
        print(f"  {neg['error']}", file=sys.stderr)

    # Approach 5: Self-Consistency
    print(f"\n  === Self-Consistency ===", file=sys.stderr)
    sc: dict[str, Any] = self_consistency_analysis(extracted_dir, repo_name)
    if "error" not in sc:
        print(f"  nodes: {sc['n_nodes']}, edges: {sc['n_edges']}", file=sys.stderr)
        print(f"  degree: mean={sc['degree_stats']['mean']}, median={sc['degree_stats']['median']}, max={sc['degree_stats']['max']}, tail_ratio={sc['degree_stats']['tail_ratio']}", file=sys.stderr)
        print(f"  clustering: {sc['transitivity']['clustering_coefficient']} (vs random: {sc['transitivity']['random_graph_expected']}, ratio: {sc['transitivity']['ratio_vs_random']}x)", file=sys.stderr)
        print(f"  verdict: degree={sc['verdict']['degree_distribution']}, transitivity={sc['verdict']['transitivity']}", file=sys.stderr)
    else:
        print(f"  {sc['error']}", file=sys.stderr)

    # Write results
    output_dir: Path = extracted_dir / "validation"
    output_dir.mkdir(exist_ok=True)
    output_path: Path = output_dir / f"{repo_name}.json"

    result: dict[str, Any] = {
        "repo": repo_name,
        "triangulation": tri,
        "negative_sampling": neg,
        "self_consistency": sc,
    }

    output_path.write_text(json.dumps(result, indent=2))
    print(f"\n  written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
