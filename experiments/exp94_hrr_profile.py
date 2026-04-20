"""Exp 94: Profile HRR hot path to identify optimization targets.

Measures wall-clock time for each HRR phase:
  1. Graph construction (encode)
  2. Single query_forward
  3. Single query_reverse
  4. Cleanup memory query (cosine similarity search)
  5. FFT bind/unbind operations

Goal: determine whether Rust/numba compilation would meaningfully
reduce the ~117ms per-call latency that blocks hook-path usage.

Usage:
    uv run python experiments/exp94_hrr_profile.py
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np

from agentmemory.hrr import (
    DEFAULT_DIM,
    CleanupMemory,
    HRRGraph,
    bind,
    cosine_similarity,
    random_vector,
    superpose,
    unbind,
)


def profile_primitives(dim: int, n_trials: int = 1000) -> dict[str, float]:
    """Profile individual HRR operations."""
    rng: np.random.Generator = np.random.default_rng(42)
    a: np.ndarray[tuple[int], np.dtype[np.float64]] = random_vector(dim, rng)
    b: np.ndarray[tuple[int], np.dtype[np.float64]] = random_vector(dim, rng)

    # bind
    t0: float = time.perf_counter()
    for _ in range(n_trials):
        bind(a, b)
    bind_us: float = (time.perf_counter() - t0) / n_trials * 1e6

    # unbind
    t0 = time.perf_counter()
    for _ in range(n_trials):
        unbind(a, b)
    unbind_us: float = (time.perf_counter() - t0) / n_trials * 1e6

    # cosine_similarity
    t0 = time.perf_counter()
    for _ in range(n_trials):
        cosine_similarity(a, b)
    cosine_us: float = (time.perf_counter() - t0) / n_trials * 1e6

    # superpose (10 vectors)
    vecs: list[np.ndarray[tuple[int], np.dtype[np.float64]]] = [
        random_vector(dim, rng) for _ in range(10)
    ]
    t0 = time.perf_counter()
    for _ in range(n_trials):
        superpose(vecs)
    superpose_us: float = (time.perf_counter() - t0) / n_trials * 1e6

    # FFT alone
    t0 = time.perf_counter()
    for _ in range(n_trials):
        np.fft.fft(a)
    fft_us: float = (time.perf_counter() - t0) / n_trials * 1e6

    return {
        "bind": bind_us,
        "unbind": unbind_us,
        "cosine": cosine_us,
        "superpose_10": superpose_us,
        "fft_alone": fft_us,
    }


def profile_cleanup_query(n_vectors: int, dim: int, n_queries: int = 100) -> float:
    """Profile cleanup memory with n_vectors stored."""
    rng: np.random.Generator = np.random.default_rng(42)
    mem: CleanupMemory = CleanupMemory()
    for i in range(n_vectors):
        mem.add(f"node_{i}", random_vector(dim, rng))

    probe: np.ndarray[tuple[int], np.dtype[np.float64]] = random_vector(dim, rng)
    # Warm up matrix cache
    mem.query(probe, top_k=10)

    t0: float = time.perf_counter()
    for _ in range(n_queries):
        mem.query(probe, top_k=10)
    return (time.perf_counter() - t0) / n_queries * 1e6


def profile_full_pipeline(db_path: str) -> dict[str, float]:
    """Profile encode + query on real graph data."""
    conn: sqlite3.Connection = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    edge_rows: list[sqlite3.Row] = conn.execute(
        "SELECT from_id, to_id, edge_type FROM edges"
    ).fetchall()
    conn.close()

    triples: list[tuple[str, str, str]] = [
        (str(r["from_id"]), str(r["to_id"]), str(r["edge_type"])) for r in edge_rows
    ]

    print(f"  Total edges in DB: {len(triples)}")

    # Filter to semantic types (same as retrieval.py)
    semantic_types: frozenset[str] = frozenset({
        "RELATES_TO", "SUPPORTS", "CONTRADICTS", "CITES",
    })
    semantic_triples: list[tuple[str, str, str]] = [
        t for t in triples if t[2] in semantic_types
    ]
    print(f"  Semantic edges: {len(semantic_triples)}")

    # Encode
    graph: HRRGraph = HRRGraph()
    t0: float = time.perf_counter()
    graph.encode(semantic_triples)
    encode_ms: float = (time.perf_counter() - t0) * 1000

    summary: dict[str, object] = graph.summary()
    print(f"  Nodes: {summary['nodes']}")
    print(f"  Partitions: {summary['partitions']}")
    print(f"  Total encoded edges: {summary['total_edges']}")

    # Get some real node IDs for queries
    node_ids: list[str] = list(graph._node_vecs.keys())[:50]
    edge_types: list[str] = graph.edge_types()

    # Query forward
    n_queries: int = min(50, len(node_ids))
    t0 = time.perf_counter()
    for i in range(n_queries):
        for et in edge_types:
            graph.query_forward(node_ids[i], et, top_k=5)
    total_queries: int = n_queries * len(edge_types)
    query_fwd_us: float = (time.perf_counter() - t0) / total_queries * 1e6

    # Query reverse
    t0 = time.perf_counter()
    for i in range(n_queries):
        for et in edge_types:
            graph.query_reverse(node_ids[i], et, top_k=5)
    query_rev_us: float = (time.perf_counter() - t0) / total_queries * 1e6

    return {
        "encode_ms": encode_ms,
        "query_forward_us": query_fwd_us,
        "query_reverse_us": query_rev_us,
        "n_edges": len(semantic_triples),
        "n_nodes": int(str(summary["nodes"])),
        "n_partitions": int(str(summary["partitions"])),
    }


def main() -> None:
    db_path: str = str(
        Path.home() / ".agentmemory" / "projects" / "2e7ed55e017a" / "memory.db"
    )

    print("=" * 70)
    print("Exp 94: HRR Performance Profile")
    print("=" * 70)
    print()

    # --- Primitive operations ---
    print("## PRIMITIVE OPERATIONS (dim=2048, 1000 trials)")
    prims: dict[str, float] = profile_primitives(DEFAULT_DIM)
    for op, us in prims.items():
        print(f"  {op:>15s}: {us:>8.1f} us")
    print()

    # bind is 2x FFT + 1x IFFT + multiply
    # theoretical: 3 * fft_alone + multiply
    print(f"  Theoretical bind = 3*FFT + mul = {3 * prims['fft_alone']:.1f} us")
    print(f"  Actual bind = {prims['bind']:.1f} us")
    print(f"  Overhead: {prims['bind'] - 3 * prims['fft_alone']:.1f} us")
    print()

    # --- Cleanup memory scaling ---
    print("## CLEANUP MEMORY SCALING (cosine search)")
    for n in [100, 500, 1000, 5000, 10000, 20000]:
        us: float = profile_cleanup_query(n, DEFAULT_DIM, n_queries=50)
        print(f"  n={n:>6d}: {us:>8.1f} us ({us/1000:.2f} ms)")
    print()

    # --- Full pipeline on real data ---
    print("## FULL PIPELINE (real graph data)")
    pipeline: dict[str, float] = profile_full_pipeline(db_path)
    print()
    print(f"  Encode time:      {pipeline['encode_ms']:>8.1f} ms")
    print(f"  Query forward:    {pipeline['query_forward_us']:>8.1f} us ({pipeline['query_forward_us']/1000:.2f} ms)")
    print(f"  Query reverse:    {pipeline['query_reverse_us']:>8.1f} us ({pipeline['query_reverse_us']/1000:.2f} ms)")
    print()

    # --- Hook path budget ---
    print("## HOOK PATH BUDGET ANALYSIS")
    print("  Target: <20ms total for HRR contribution to hook search")
    print("  Current hook search budget: ~200ms (6 layers)")
    print()

    # Typical hook query: 5 seed beliefs -> 5 forward + 5 reverse queries per edge type
    n_seeds: int = 5
    n_edge_types: int = max(1, len(HRRGraph().edge_types()) if False else 4)  # estimate
    n_edge_types = int(pipeline.get("n_partitions", 4))
    queries_per_search: int = n_seeds * n_edge_types * 2  # forward + reverse
    total_query_ms: float = queries_per_search * max(pipeline["query_forward_us"], pipeline["query_reverse_us"]) / 1000
    total_with_encode: float = pipeline["encode_ms"] + total_query_ms

    print(f"  Queries per search: {queries_per_search}")
    print(f"  Query time: {total_query_ms:.1f} ms")
    print(f"  Encode time (cached after first call): {pipeline['encode_ms']:.1f} ms")
    print(f"  Total (first call): {total_with_encode:.1f} ms")
    print(f"  Total (cached): {total_query_ms:.1f} ms")
    print()

    if total_query_ms < 20:
        print("  VERDICT: Query time fits in hook budget.")
        print(f"  The 117ms figure was likely encode time, not query time.")
        print(f"  Solution: pre-build HRR graph at server start, cache it.")
        print(f"  No Rust/numba needed -- just move encode out of the hot path.")
    elif total_query_ms < 50:
        print("  VERDICT: Query time is borderline.")
        print("  Consider: reduce dim from 2048 to 1024 (2x speedup on FFT).")
        print("  Or: use numba to JIT the bind/unbind FFT operations.")
    else:
        print("  VERDICT: Query time exceeds budget.")
        print("  Rust or numba compilation of core FFT+bind would help.")
        print("  Alternative: pre-compute query results for common seed patterns.")

    # --- Dimensionality reduction test ---
    print()
    print("## DIMENSIONALITY SENSITIVITY")
    for dim in [512, 1024, 2048, 4096]:
        p: dict[str, float] = profile_primitives(dim, n_trials=500)
        cm_us: float = profile_cleanup_query(int(pipeline["n_nodes"]), dim, n_queries=20)
        print(f"  dim={dim:>5d}: bind={p['bind']:>6.1f}us  cleanup={cm_us/1000:>6.2f}ms  "
              f"capacity={dim//9}")


if __name__ == "__main__":
    main()
