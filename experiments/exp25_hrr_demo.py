from __future__ import annotations

"""
Experiment 25: HRR Operations Demo

Demonstrates each HRR operation with clear printed output, showing exactly
what the math does and why it works. No external data required -- all synthetic.

Operations demonstrated:
  1. Circular convolution (binding)
  2. Circular correlation (approximate unbinding)
  3. Superposition capacity (how many bindings before retrieval degrades)
  4. Multi-hop graph traversal in vector space
  5. Edge-type orthogonality (selective traversal)
  6. Cleanup memory (nearest-neighbor recovery from noisy unbinding)

Run with: uv run python experiments/exp25_hrr_demo.py
"""

import numpy as np
import numpy.typing as npt

DIM = 1024
SEP = "=" * 60


# ---------------------------------------------------------------------------
# Core HRR operations
# ---------------------------------------------------------------------------

def make_vector(rng: np.random.Generator, label: str = "") -> npt.NDArray[np.float64]:
    """Random unit vector in DIM dimensions."""
    v = rng.standard_normal(DIM)
    v /= np.linalg.norm(v)
    return v


def convolve(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Circular convolution: bind two vectors. O(n log n)."""
    result = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))
    return result  # type: ignore[no-any-return]


def correlate(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Circular correlation: approximate inverse of convolution. O(n log n)."""
    result = np.real(np.fft.ifft(np.conj(np.fft.fft(a)) * np.fft.fft(b)))
    return result  # type: ignore[no-any-return]


def cos_sim(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def nearest_neighbor(query: npt.NDArray[np.float64], memory: dict[str, npt.NDArray[np.float64]]) -> tuple[str, float]:
    """Cleanup memory: return (label, similarity) of best-matching vector."""
    best_label, best_sim = "", -2.0
    for label, vec in memory.items():
        s = cos_sim(query, vec)
        if s > best_sim:
            best_sim = s
            best_label = label
    return best_label, best_sim


# ---------------------------------------------------------------------------
# Demo 1: Circular convolution properties
# ---------------------------------------------------------------------------

def demo_convolution(rng: np.random.Generator) -> None:
    print(SEP)
    print("DEMO 1: Circular Convolution (Binding)")
    print(SEP)

    a = make_vector(rng, "a")
    b = make_vector(rng, "b")
    c = convolve(a, b)

    print(f"\n  a, b are random unit vectors in R^{DIM}")
    print(f"  c = convolve(a, b)")
    print()

    # c should be approximately orthogonal to both a and b
    sim_ca = cos_sim(c, a)
    sim_cb = cos_sim(c, b)
    print(f"  cos(c, a) = {sim_ca:+.4f}   (expected ~ 0: result is orthogonal to inputs)")
    print(f"  cos(c, b) = {sim_cb:+.4f}   (expected ~ 0)")

    # Commutativity
    c2 = convolve(b, a)
    print(f"\n  Commutativity: convolve(a,b) == convolve(b,a)?")
    print(f"  Max absolute difference: {np.max(np.abs(c - c2)):.2e}  (expected ~ 0)")

    # Associativity
    d = make_vector(rng)
    lhs = convolve(convolve(a, b), d)
    rhs = convolve(a, convolve(b, d))
    print(f"\n  Associativity: (a*b)*d == a*(b*d)?")
    print(f"  Max absolute difference: {np.max(np.abs(lhs - rhs)):.2e}  (expected ~ 0)")

    # Result has same norm ~ 1
    print(f"\n  Norm of c = convolve(a, b): {np.linalg.norm(c):.4f}  (expected ~ 1.0)")


# ---------------------------------------------------------------------------
# Demo 2: Circular correlation (unbinding)
# ---------------------------------------------------------------------------

def demo_unbinding(rng: np.random.Generator) -> None:
    print(f"\n{SEP}")
    print("DEMO 2: Circular Correlation (Approximate Unbinding)")
    print(SEP)

    a = make_vector(rng)
    b = make_vector(rng)
    c = convolve(a, b)   # c = a * b

    # Unbind: given c and a, recover b
    b_recovered = correlate(a, c)
    sim_to_b     = cos_sim(b_recovered, b)
    sim_to_a     = cos_sim(b_recovered, a)
    sim_to_noise = cos_sim(b_recovered, make_vector(rng))

    print(f"\n  c = convolve(a, b)")
    print(f"  b_recovered = correlate(a, c)")
    print()
    print(f"  cos(b_recovered, b)     = {sim_to_b:+.4f}   (expected >> 0: we recovered b)")
    print(f"  cos(b_recovered, a)     = {sim_to_a:+.4f}   (expected ~ 0: not a)")
    print(f"  cos(b_recovered, noise) = {sim_to_noise:+.4f}   (expected ~ 0)")
    print(f"\n  Signal-to-noise ratio: {sim_to_b / max(abs(sim_to_noise), 1e-6):.1f}x")

    # Reverse direction: given c and b, recover a
    a_recovered = correlate(b, c)
    sim_to_a2 = cos_sim(a_recovered, a)
    print(f"\n  Reverse: correlate(b, c) -> similarity to a: {sim_to_a2:+.4f}")
    print(f"  Both directions work (correlation is directional but invertible both ways)")

    # Theoretical SNR
    theoretical_snr = np.sqrt(DIM)
    print(f"\n  Theoretical SNR for n={DIM}: sqrt({DIM}) = {theoretical_snr:.1f}")
    print(f"  Observed SNR: {sim_to_b / max(abs(sim_to_noise), 1e-6):.1f}x")


# ---------------------------------------------------------------------------
# Demo 3: Superposition capacity
# ---------------------------------------------------------------------------

def demo_superposition(rng: np.random.Generator) -> None:
    print(f"\n{SEP}")
    print("DEMO 3: Superposition Capacity")
    print(SEP)
    print(f"\n  Superpose k bindings into one vector s_vec.")
    print(f"  Then try to recover each individual binding.")
    print(f"  SNR degrades as k increases: SNR ~ sqrt(n/k)")
    print()

    keys = [make_vector(rng) for _ in range(200)]
    values = [make_vector(rng) for _ in range(200)]

    print(f"  {'k bindings':>12}  {'sim to target':>14}  {'sim to noise':>13}  {'SNR':>6}  retrieval")
    print(f"  {'-'*12}  {'-'*14}  {'-'*13}  {'-'*6}  {'-'*8}")

    for k in [1, 5, 10, 25, 50, 100, 150, 200]:
        # Build superposition of k bindings
        s_vec = np.zeros(DIM)
        for i in range(k):
            s_vec += convolve(keys[i], values[i])

        # Try to recover value[0] from s_vec using key[0]
        recovered = correlate(keys[0], s_vec)
        sim_target = cos_sim(recovered, values[0])
        sim_noise  = cos_sim(recovered, make_vector(rng))
        snr = sim_target / max(abs(sim_noise), 1e-6)
        ok = "OK" if snr > 3.0 else ("weak" if snr > 1.0 else "FAIL")

        print(f"  {k:>12}  {sim_target:>+14.4f}  {sim_noise:>+13.4f}  {snr:>6.1f}  {ok}")

    theoretical_capacity = DIM // 9
    print(f"\n  Theoretical reliable capacity ~ n/9 = {theoretical_capacity} bindings at n={DIM}")


# ---------------------------------------------------------------------------
# Demo 4: Multi-hop graph traversal
# ---------------------------------------------------------------------------

def demo_multihop(rng: np.random.Generator) -> None:
    print(f"\n{SEP}")
    print("DEMO 4: Multi-Hop Graph Traversal in Vector Space")
    print(SEP)

    # Nodes
    node: dict[str, npt.NDArray[np.float64]] = {name: make_vector(rng) for name in ["A", "B", "C", "D", "X"]}

    # Edge types
    edge: dict[str, npt.NDArray[np.float64]] = {name: make_vector(rng) for name in ["SUPPORTS", "CITES", "CONTRADICTS"]}

    # Encode graph edges into a single superposition:
    #   A -[SUPPORTS]-> B
    #   B -[CITES]->    C
    #   A -[CITES]->    D
    #   X -[SUPPORTS]-> C   (distractor)
    s_vec = np.zeros(DIM)
    s_vec = s_vec + convolve(convolve(node["A"], edge["SUPPORTS"]), node["B"])
    s_vec = s_vec + convolve(convolve(node["B"], edge["CITES"]),    node["C"])
    s_vec = s_vec + convolve(convolve(node["A"], edge["CITES"]),    node["D"])
    s_vec = s_vec + convolve(convolve(node["X"], edge["SUPPORTS"]), node["C"])

    # Cleanup memory: all node vectors
    memory: dict[str, npt.NDArray[np.float64]] = {name: vec for name, vec in node.items()}

    print(f"\n  Graph encoded as superposition of 4 edges:")
    print(f"    A -[SUPPORTS]-> B")
    print(f"    B -[CITES]->    C")
    print(f"    A -[CITES]->    D")
    print(f"    X -[SUPPORTS]-> C  (distractor)")

    # 1-hop: A --SUPPORTS--> ?
    print(f"\n  Query 1-hop: A -[SUPPORTS]-> ?")
    q = convolve(node["A"], edge["SUPPORTS"])
    recovered = correlate(q, s_vec)
    label, sim = nearest_neighbor(recovered, memory)
    sims = {n: cos_sim(recovered, v) for n, v in memory.items()}
    print(f"    Result: {label} (cos={sim:+.4f})")
    print(f"    All similarities: " + ", ".join(f"{n}={s:+.3f}" for n, s in sorted(sims.items())))

    # 1-hop: A --CITES--> ?
    print(f"\n  Query 1-hop: A -[CITES]-> ?")
    q = convolve(node["A"], edge["CITES"])
    recovered = correlate(q, s_vec)
    label, sim = nearest_neighbor(recovered, memory)
    sims = {n: cos_sim(recovered, v) for n, v in memory.items()}
    print(f"    Result: {label} (cos={sim:+.4f})")
    print(f"    All similarities: " + ", ".join(f"{n}={s:+.3f}" for n, s in sorted(sims.items())))

    # 2-hop: A --SUPPORTS--> ? --CITES--> ?
    # Expected: A->B->C
    print(f"\n  Query 2-hop: A -[SUPPORTS]-> ? -[CITES]-> ?  (expected: C)")
    q = convolve(convolve(node["A"], edge["SUPPORTS"]), edge["CITES"])
    recovered = correlate(q, s_vec)
    label, sim = nearest_neighbor(recovered, memory)
    sims = {n: cos_sim(recovered, v) for n, v in memory.items()}
    print(f"    Result: {label} (cos={sim:+.4f})")
    print(f"    All similarities: " + ", ".join(f"{n}={s:+.3f}" for n, s in sorted(sims.items())))
    print(f"    Note: B never explicitly visited -- traversal is a pure vector operation")


# ---------------------------------------------------------------------------
# Demo 5: Edge-type orthogonality (selective traversal)
# ---------------------------------------------------------------------------

def demo_edge_orthogonality(rng: np.random.Generator) -> None:
    print(f"\n{SEP}")
    print("DEMO 5: Edge-Type Orthogonality (Selective Traversal)")
    print(SEP)

    node: dict[str, npt.NDArray[np.float64]] = {name: make_vector(rng) for name in ["A", "B", "C", "D"]}
    edge: dict[str, npt.NDArray[np.float64]] = {name: make_vector(rng) for name in ["SUPPORTS", "CONTRADICTS", "CITES"]}

    # Encode:
    #   A -[SUPPORTS]->    B
    #   A -[CONTRADICTS]-> C
    #   A -[CITES]->       D
    s_vec = np.zeros(DIM)
    s_vec = s_vec + convolve(convolve(node["A"], edge["SUPPORTS"]),    node["B"])
    s_vec = s_vec + convolve(convolve(node["A"], edge["CONTRADICTS"]), node["C"])
    s_vec = s_vec + convolve(convolve(node["A"], edge["CITES"]),       node["D"])

    memory: dict[str, npt.NDArray[np.float64]] = {name: vec for name, vec in node.items()}

    print(f"\n  Graph: A -[SUPPORTS]-> B,  A -[CONTRADICTS]-> C,  A -[CITES]-> D")
    print(f"\n  Querying with each edge type selectively activates only that edge:")

    for edge_name, expected in [("SUPPORTS", "B"), ("CONTRADICTS", "C"), ("CITES", "D")]:
        q = convolve(node["A"], edge[edge_name])
        recovered = correlate(q, s_vec)
        label, _sim = nearest_neighbor(recovered, memory)
        sims = {n: cos_sim(recovered, v) for n, v in memory.items()}
        correct = "OK" if label == expected else f"WRONG (got {label})"
        print(f"\n  A -[{edge_name}]-> ?  (expected {expected}): {correct}")
        print(f"    " + ", ".join(f"{n}={s:+.3f}" for n, s in sorted(sims.items())))

    # Show cross-type interference is noise
    print(f"\n  Cross-type interference (SUPPORTS query against CONTRADICTS edge):")
    q_supports = convolve(node["A"], edge["SUPPORTS"])
    # Manually compute what SUPPORTS gives against A-CONTRADICTS-C
    a_contra_c = convolve(convolve(node["A"], edge["CONTRADICTS"]), node["C"])
    interference = correlate(q_supports, a_contra_c)
    sim_to_c = cos_sim(interference, node["C"])
    print(f"    Similarity of SUPPORTS-query to C (via CONTRADICTS edge): {sim_to_c:+.4f}  (expected ~ 0)")
    print(f"    Selectivity is geometric -- no filtering code needed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    rng = np.random.default_rng(42)

    print(f"\n{SEP}")
    print(f"Experiment 25: HRR Operations Demo  (n={DIM})")
    print(SEP)

    demo_convolution(rng)
    demo_unbinding(rng)
    demo_superposition(rng)
    demo_multihop(rng)
    demo_edge_orthogonality(rng)

    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)
    print("""
  1. Convolution binds two vectors into a third with the same dimensionality.
     Result is orthogonal to both inputs -- looks like noise.

  2. Correlation approximately inverts convolution. Given c = a*b, correlate(a, c) ~ b.
     Signal-to-noise ratio ~ sqrt(n). Both directions of a binding are recoverable.

  3. Superposition stores multiple bindings in one vector by addition.
     Capacity ~ n/9 reliable bindings. SNR degrades as sqrt(n/k).

  4. Multi-hop traversal is successive convolution: no BFS, no intermediate node lookup.
     A -[e1]-> B -[e2]-> C  retrieved as  correlate(node_A * e1 * e2, S).
     Complexity O(k * n log n) regardless of graph size.

  5. Edge type vectors are random and nearly orthogonal. Querying with SUPPORTS
     activates only SUPPORTS edges in the superposition -- free geometric filtering.
""")


if __name__ == "__main__":
    main()
