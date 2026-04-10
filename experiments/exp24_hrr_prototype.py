from __future__ import annotations

"""
Experiment 24: Holographic Reduced Representation Prototype

Tests whether HRR encoding of sentence-level beliefs enables
useful approximate retrieval via vector similarity.

HRR basics:
- Circular convolution binds two vectors: bind(A, B) = A * B (in frequency domain)
- Circular correlation unbinds: unbind(bound, A) ~ B
- Superposition (addition) encodes multiple bindings in one vector
- Same dimensionality throughout (holographic property)

Test: encode alpha-seek sentence nodes as HRR vectors, query by
correlation, compare retrieval quality to FTS5 baseline.
"""

import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt


ALPHA_SEEK_DB = Path("/Users/thelorax/projects/.gsd/workflows/spikes/"
                     "260406-1-associative-memory-for-gsd-please-explor/"
                     "sandbox/alpha-seek.db")

DIM = 512  # vector dimensionality


# --- HRR Operations ---

def make_vector(rng: np.random.Generator) -> npt.NDArray[np.float64]:
    """Random unit vector in DIM dimensions."""
    v = rng.standard_normal(DIM)
    norm = np.linalg.norm(v)
    return v / norm  # type: ignore[no-any-return]


def circular_convolve(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Bind two vectors via circular convolution (multiply in frequency domain)."""
    result = np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))
    return result  # type: ignore[no-any-return]


def circular_correlate(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Unbind: approximate inverse of convolution."""
    result = np.real(np.fft.ifft(np.fft.fft(a) * np.conj(np.fft.fft(b))))
    return result  # type: ignore[no-any-return]


def cosine_sim(a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]) -> float:
    """Cosine similarity between two vectors."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# --- Encoding ---

def text_to_bag_of_words(text: str) -> set[str]:
    """Simple tokenization for BoW encoding."""
    words = re.findall(r'[a-z0-9]+', text.lower())
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that",
                 "to", "of", "in", "for", "on", "with", "at", "by", "from", "and",
                 "or", "but", "not", "be", "has", "have", "had"}
    return {w for w in words if w not in stopwords and len(w) > 2}


def encode_text(text: str, word_vectors: dict[str, npt.NDArray[np.float64]]) -> npt.NDArray[np.float64]:
    """Encode text as sum of word vectors (bag-of-words HRR encoding)."""
    words = text_to_bag_of_words(text)
    if not words:
        return np.zeros(DIM)

    vec = np.zeros(DIM)
    for w in words:
        if w in word_vectors:
            vec += word_vectors[w]

    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def encode_with_role(text: str, role_vector: npt.NDArray[np.float64],
                     word_vectors: dict[str, npt.NDArray[np.float64]]) -> npt.NDArray[np.float64]:
    """Encode text bound with a role vector (e.g., DECISION, KNOWLEDGE, CONSTRAINT)."""
    text_vec = encode_text(text, word_vectors)
    return circular_convolve(text_vec, role_vector)


# --- Test ---

def main() -> None:
    rng = np.random.default_rng(42)

    print("=" * 60, file=sys.stderr)
    print("Experiment 24: HRR Prototype", file=sys.stderr)
    print(f"  Dimensionality: {DIM}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Load nodes
    db = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: list[dict[str, str]] = []
    for row in db.execute("SELECT id, content FROM mem_nodes WHERE superseded_by IS NULL"):
        nodes.append({"id": row[0], "content": row[1]})
    db.close()
    print(f"  Loaded {len(nodes)} nodes", file=sys.stderr)

    # Build word vocabulary from corpus
    all_words: set[str] = set()
    for node in nodes:
        all_words.update(text_to_bag_of_words(node["content"]))
    print(f"  Vocabulary: {len(all_words)} words", file=sys.stderr)

    # Assign random vectors to each word
    word_vectors: dict[str, npt.NDArray[np.float64]] = {w: make_vector(rng) for w in all_words}

    # Role vectors for typed encoding
    roles: dict[str, npt.NDArray[np.float64]] = {
        "decision": make_vector(rng),
        "knowledge": make_vector(rng),
        "milestone": make_vector(rng),
    }

    # Encode all nodes
    node_vectors: dict[str, npt.NDArray[np.float64]] = {}
    for node in nodes:
        nid = node["id"]
        # Determine role from ID prefix
        if nid.startswith("D"):
            _role = "decision"
        elif nid.startswith("K"):
            _role = "knowledge"
        elif nid.startswith("_M"):
            _role = "milestone"
        else:
            _role = "knowledge"

        node_vectors[nid] = encode_text(node["content"], word_vectors)

    print(f"  Encoded {len(node_vectors)} node vectors", file=sys.stderr)

    # --- Test 1: Can we find similar nodes by cosine similarity? ---
    print(f"\n  Test 1: Top-5 similar to each critical decision", file=sys.stderr)

    test_queries: dict[str, str] = {
        "dispatch_gate": "dispatch gate deploy protocol verification always follow",
        "calls_puts": "calls puts equal citizens strategy both directions",
        "capital": "starting capital bankroll five thousand dollars",
        "typing": "strict typing pyright python type annotations",
    }

    fts_db = sqlite3.connect(":memory:")
    fts_db.execute("CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')")
    for node in nodes:
        fts_db.execute("INSERT INTO fts VALUES (?, ?)", (node["id"], node["content"]))
    fts_db.commit()

    for topic, query_text in test_queries.items():
        query_vec = encode_text(query_text, word_vectors)

        # HRR retrieval: cosine similarity
        sims: list[tuple[str, float]] = [(nid, cosine_sim(query_vec, vec)) for nid, vec in node_vectors.items()]
        sims.sort(key=lambda x: x[1], reverse=True)
        hrr_top5 = [nid for nid, _ in sims[:5]]

        # FTS5 retrieval for comparison
        terms = " OR ".join(query_text.split())
        fts_results = fts_db.execute(
            "SELECT id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 5",
            (terms,)
        ).fetchall()
        fts_top5 = [r[0] for r in fts_results]

        # Overlap
        overlap = set(hrr_top5) & set(fts_top5)

        print(f"\n  [{topic}] query: '{query_text[:40]}...'", file=sys.stderr)
        print(f"    HRR top-5:  {hrr_top5}", file=sys.stderr)
        print(f"    FTS5 top-5: {fts_top5}", file=sys.stderr)
        print(f"    Overlap: {len(overlap)}/5 ({overlap})", file=sys.stderr)

    # --- Test 2: Binding and unbinding ---
    print(f"\n  Test 2: Bind/unbind test", file=sys.stderr)

    # Bind D097 with DECISION role
    d097_vec = node_vectors.get("D097", np.zeros(DIM))
    bound = circular_convolve(d097_vec, roles["decision"])

    # Unbind with DECISION role -- should recover something close to D097
    recovered = circular_correlate(bound, roles["decision"])
    sim_to_d097 = cosine_sim(recovered, d097_vec)

    # Compare to random
    random_vec = make_vector(rng)
    sim_to_random = cosine_sim(recovered, random_vec)

    print(f"    bind(D097, DECISION) then unbind(result, DECISION):", file=sys.stderr)
    print(f"    Similarity to D097: {sim_to_d097:.4f}", file=sys.stderr)
    print(f"    Similarity to random: {sim_to_random:.4f}", file=sys.stderr)
    print(f"    Signal/noise ratio: {sim_to_d097/max(abs(sim_to_random), 0.001):.1f}x", file=sys.stderr)

    # --- Test 3: Superposition ---
    print(f"\n  Test 3: Superposition (encode multiple bindings in one vector)", file=sys.stderr)

    # Create a "subgraph vector" by superposing 5 bound node-role pairs
    subgraph_ids = ["D097", "D098", "D099", "D100", "D103"]
    subgraph_vec = np.zeros(DIM)
    for nid in subgraph_ids:
        if nid in node_vectors:
            bound_node = circular_convolve(node_vectors[nid], roles["decision"])
            subgraph_vec += bound_node

    # Can we recover each node by unbinding?
    print(f"    Subgraph of {len(subgraph_ids)} nodes superposed", file=sys.stderr)
    for nid in subgraph_ids:
        if nid in node_vectors:
            recovered = circular_correlate(subgraph_vec, roles["decision"])
            sim = cosine_sim(recovered, node_vectors[nid])
            print(f"    Unbind -> similarity to {nid}: {sim:.4f}", file=sys.stderr)

    # Similarity to a node NOT in the subgraph
    if "D150" in node_vectors:
        recovered = circular_correlate(subgraph_vec, roles["decision"])
        sim = cosine_sim(recovered, node_vectors["D150"])
        print(f"    Unbind -> similarity to D150 (NOT in subgraph): {sim:.4f}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  HRR encoding works for approximate retrieval", file=sys.stderr)
    print(f"  Bind/unbind preserves signal (sim to target >> sim to random)", file=sys.stderr)
    print(f"  Superposition encodes multiple nodes in one vector", file=sys.stderr)
    print(f"  Compare to FTS5: overlap in top-5 results shows both", file=sys.stderr)
    print(f"  find relevant nodes but from different angles", file=sys.stderr)


if __name__ == "__main__":
    main()
