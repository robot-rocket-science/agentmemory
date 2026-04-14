# Bayesian Edge Dynamics for Knowledge Graph Memory

**Date:** 2026-04-14
**Status:** Research complete -- ready for design decisions
**Purpose:** Extend belief-level Bayesian scoring to edges, enabling dynamic edge confidence that updates based on traversal outcomes.

---

## Current State

The agentmemory system has:
- **Beliefs** with `alpha`/`beta_param` (Beta distribution), updated via feedback ("used", "ignored", "harmful")
- **Edges** with static `weight` (REAL), no feedback mechanism
- **Edge types**: CITES, RELATES_TO, SUPERSEDES, CONTRADICTS, SUPPORTS, TESTS, IMPLEMENTS, TEMPORAL_NEXT
- **Credal gap metric**: counts beliefs still at type prior (untested)
- **Thompson sampling** for belief ranking: `random.betavariate(alpha, beta_param)`

The gap: edges are born with a fixed weight and never learn. A RELATES_TO edge created by LLM semantic linking gets weight=0.8 forever, regardless of whether traversing it leads to useful retrievals.

---

## 1. Bayesian Edge Scoring

### 1.1 Beta-Binomial Model for Edges

The same Beta-Bernoulli conjugate pair used for beliefs applies to edges. Each edge gets its own `alpha_e` and `beta_e` parameters:

```
Prior:     Beta(alpha_e, beta_e)
Posterior: Beta(alpha_e + traversal_successes, beta_e + traversal_failures)

Edge confidence = alpha_e / (alpha_e + beta_e)
```

**What counts as success/failure for an edge:**

| Event | Update | Rationale |
|---|---|---|
| Traverse edge, destination belief is USED | alpha_e += 1.0 | Edge led to useful content |
| Traverse edge, destination belief is HARMFUL | beta_e += 1.0 | Edge led to bad content |
| Traverse edge, destination belief is IGNORED | No update | Same rationale as beliefs: absence of use != evidence of badness |
| Destination belief is superseded | beta_e += 0.5 | Mild penalty -- the path is now stale |
| Edge participates in contradiction detection | alpha_e += 0.5 | CONTRADICTS edges that correctly flag conflicts are valuable |

**Why IGNORED gets no edge update (matching belief policy):** An edge from a database config belief to a schema belief is irrelevant during CSS work. Penalizing it for being irrelevant would kill niche-but-correct structural knowledge.

Source: This follows the same logic validated in our BAYESIAN_RESEARCH.md for beliefs. The Beta-Bernoulli conjugate pair is the standard approach for binary outcome learning with sequential updates. See [Bayes Rules! Ch. 3](https://www.bayesrulesbook.com/chapter-3) and [Think Bayes Ch. 18](https://allendowney.github.io/ThinkBayes2/chap18.html).

### 1.2 Edge-Type-Informed Priors

Different edge types should start with different priors. A SUPERSEDES edge created by the correction system deserves higher initial confidence than a RELATES_TO edge created by LLM semantic linking.

**Recommended edge type priors:**

| Edge Type | alpha_e | beta_e | Initial Confidence | Prior Strength | Rationale |
|---|---|---|---|---|---|
| SUPERSEDES | 8.0 | 1.0 | 0.89 | 9 (moderate) | Correction system creates these; high reliability |
| CONTRADICTS | 6.0 | 2.0 | 0.75 | 8 (moderate) | Important for safety; slightly uncertain |
| SUPPORTS | 5.0 | 2.0 | 0.71 | 7 (moderate) | Evidence relationship; usually correct |
| CITES | 7.0 | 1.0 | 0.88 | 8 (moderate) | Explicit reference; structurally reliable |
| IMPLEMENTS | 6.0 | 1.5 | 0.80 | 7.5 (moderate) | Code-to-requirement link; usually correct |
| TESTS | 5.0 | 2.0 | 0.71 | 7 (moderate) | Test-to-belief link; reasonably reliable |
| RELATES_TO | 3.0 | 2.0 | 0.60 | 5 (weak) | LLM-inferred; genuinely uncertain |
| TEMPORAL_NEXT | 4.0 | 1.0 | 0.80 | 5 (weak) | Temporal ordering; structurally correct but low semantic value |

**Design choice: prior strength controls learning rate.** RELATES_TO edges have low prior strength (5), meaning ~5 observations can significantly shift them. SUPERSEDES edges have moderate strength (9), requiring more contradicting evidence to overcome.

### 1.3 Hierarchical Bayesian Model for Edge Types

Rather than hand-coding priors per edge type, a hierarchical model lets the data inform the priors:

```
Level 2 (population): mu_k ~ Beta(a0, b0)    for each edge type k
Level 1 (individual): theta_ij ~ Beta(mu_k * kappa_k, (1 - mu_k) * kappa_k)
```

Where:
- `mu_k` is the population mean reliability for edge type k
- `kappa_k` is the concentration (how tightly individual edges cluster around the mean)
- `theta_ij` is the individual edge's true reliability

**Empirical Bayes approximation** (practical for SQLite): estimate `mu_k` and `kappa_k` from observed edge outcomes per type, then use those as the prior for new edges of that type. This avoids full MCMC while capturing the key benefit: data-rich edge types (RELATES_TO, which are abundant) inform priors for data-poor types.

```python
def estimate_type_prior(edge_type: str, store: MemoryStore) -> tuple[float, float]:
    """Empirical Bayes: estimate alpha_e, beta_e prior from observed outcomes."""
    rows = store.query(
        """SELECT e.alpha_e, e.beta_e FROM edges e
           WHERE e.edge_type = ? AND (e.alpha_e + e.beta_e) > 5.0""",
        (edge_type,),
    )
    if len(rows) < 10:
        # Not enough data; fall back to hand-coded priors
        return DEFAULT_EDGE_PRIORS[edge_type]

    alphas = [r["alpha_e"] for r in rows]
    betas = [r["beta_e"] for r in rows]
    mean_conf = sum(a / (a + b) for a, b in zip(alphas, betas)) / len(rows)
    # Method of moments for Beta distribution
    var_conf = sum((a / (a + b) - mean_conf) ** 2
                   for a, b in zip(alphas, betas)) / len(rows)
    if var_conf < 1e-10:
        var_conf = 0.01  # Floor to avoid division by zero

    # Method of moments: kappa = mu(1-mu)/var - 1
    kappa = mean_conf * (1.0 - mean_conf) / var_conf - 1.0
    kappa = max(2.0, min(kappa, 100.0))  # Clamp to reasonable range

    alpha_prior = mean_conf * kappa
    beta_prior = (1.0 - mean_conf) * kappa
    return (alpha_prior, beta_prior)
```

Source: Hierarchical Beta-Binomial models are standard in empirical Bayes. See [Bayesian Hierarchical Modeling](https://bayesball.github.io/BOOK/bayesian-hierarchical-modeling.html) and the UBC lecture on [Conjugate Priors and Hierarchical Bayes](https://www.cs.ubc.ca/~schmidtm/Courses/540-W19/L33.pdf). Method of moments estimation for Beta parameters is covered in the Georgia Tech [Hierarchical Bayes and Empirical Bayes handout](https://www2.isye.gatech.edu/isyebayes/bank/handout8.pdf).

### 1.4 Thompson Sampling for Edge Selection

When multiple edges lead from a seed belief, use Thompson sampling to decide which to traverse:

```python
def select_edges_thompson(
    edges: list[Edge],
    top_k: int = 3,
) -> list[Edge]:
    """Thompson sampling over edges: sample from each edge's Beta posterior."""
    scored: list[tuple[float, Edge]] = []
    for edge in edges:
        sample = random.betavariate(edge.alpha_e, edge.beta_e)
        scored.append((sample, edge))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [edge for _, edge in scored[:top_k]]
```

This naturally balances exploration (trying uncertain edges) with exploitation (preferring edges with good track records), exactly as it does for beliefs. The existing `_exploration_count`/`_exploitation_count` instrumentation in scoring.py can be extended to track edge exploration.

---

## 2. Bayesian Structure Learning

### 2.1 Should This Edge Exist?

Structure learning asks: given the data, which edges are justified? This is relevant when the graph accumulates many RELATES_TO edges from LLM linking passes and some turn out to be noise.

**BDeu Score for Edge Justification:**

The Bayesian Dirichlet equivalent uniform (BDeu) score evaluates whether adding an edge improves the model's ability to explain the data:

```
BDeu(Xi, Pa_i) = Product over j of [
    Gamma(N'_ij) / Gamma(N'_ij + N_ij) *
    Product over k of [Gamma(N'_ijk + N_ijk) / Gamma(N'_ijk)]
]
```

Where:
- `Pa_i` is the parent set of node i
- `N_ijk` is the count of data instances where Xi=k and parents are in state j
- `N'_ijk = equivalent_sample_size / (q_i * r_i)` is the prior pseudo-count

For our system, the "data" is co-retrieval patterns: if belief A and belief B are frequently retrieved together and both used, an edge between them is justified. If they're co-retrieved but one is always ignored, the edge is noise.

Source: Heckerman et al. (1995) introduced BDeu. See [Scutari (2017)](https://proceedings.mlr.press/v73/scutari17a.html) for the connection between BDeu and the maximum entropy principle. The [pgmpy documentation](https://pgmpy.org/examples/Structure%20Learning%20in%20Bayesian%20Networks.html) provides practical implementations.

### 2.2 Practical Structure Learning: Co-Retrieval Scoring

Full BDeu computation is expensive. A practical approximation for agentmemory:

```python
def edge_justification_score(
    from_id: str,
    to_id: str,
    store: MemoryStore,
) -> float:
    """Score whether an edge between two beliefs is justified by co-retrieval data.

    Returns a log-odds score: positive = edge justified, negative = edge is noise.
    """
    # Count sessions where both were retrieved
    co_retrieved = store.query(
        """SELECT COUNT(DISTINCT t1.session_id) FROM tests t1
           JOIN tests t2 ON t1.session_id = t2.session_id
           WHERE t1.belief_id = ? AND t2.belief_id = ?""",
        (from_id, to_id),
    )
    n_co = co_retrieved[0][0]

    # Count sessions where both were retrieved AND both used
    co_used = store.query(
        """SELECT COUNT(DISTINCT t1.session_id) FROM tests t1
           JOIN tests t2 ON t1.session_id = t2.session_id
           WHERE t1.belief_id = ? AND t2.belief_id = ?
           AND t1.outcome = 'used' AND t2.outcome = 'used'""",
        (from_id, to_id),
    )
    n_used = co_used[0][0]

    if n_co < 3:
        return 0.0  # Not enough data to judge

    use_rate = n_used / n_co
    # Log-odds relative to base rate (assume 0.3 base co-use rate)
    base_rate = 0.3
    if use_rate < 0.01:
        use_rate = 0.01
    return math.log(use_rate / base_rate)
```

### 2.3 Gaussian Graphical Models for Conditional Dependencies

GGMs discover which beliefs are conditionally independent given all others. The precision matrix (inverse covariance) has zeros where beliefs are conditionally independent -- those zeros mean "no edge needed."

For agentmemory, this would work on **embedding vectors**:
1. Collect embedding vectors for all active beliefs
2. Estimate the sparse precision matrix via graphical lasso
3. Non-zero entries in the precision matrix suggest edges

The graphical lasso (Friedman et al., 2008) solves:

```
minimize  -log det(Theta) + trace(S * Theta) + lambda * ||Theta||_1
```

Where S is the sample covariance and lambda controls sparsity.

**Practical concern:** This requires belief embeddings, which we'd need to store or compute on-the-fly. It's computationally heavier than co-retrieval scoring. Best used as a periodic offline pass (e.g., during compaction) rather than real-time.

Source: See [Accelerating Bayesian Structure Learning in Sparse GGMs](https://www.tandfonline.com/doi/full/10.1080/01621459.2021.1996377) for the Bayesian treatment. The G-Wishart conjugate prior for precision matrices under graphical constraints is the standard Bayesian approach.

### 2.4 Bayesian Nonparametric: Indian Buffet Process

The Indian Buffet Process (IBP) is a Bayesian nonparametric prior over binary feature matrices. Applied to edges: each belief can possess a latent set of "features," and edges exist between beliefs that share features.

```
Z ~ IBP(alpha)
P(edge A->B) = sigma(z_A^T * z_B)
```

Where `z_A` and `z_B` are binary feature vectors drawn from the IBP, and `sigma` is the sigmoid function.

**Why this matters:** The IBP automatically determines how many latent features (edge-generating concepts) exist. You don't need to specify the number of edge types in advance -- the model discovers them.

**Practical assessment:** Too computationally expensive for real-time use in agentmemory. The IBP requires MCMC inference, which is orders of magnitude slower than our current SQLite-based approach. However, the *concept* is useful: edge types are not fixed, and the system should be able to discover new types of relationships. This can be approximated by the LLM semantic linker, which already discovers relationships without pre-specifying types.

Source: [Griffiths & Ghahramani, "The Indian Buffet Process"](https://cocosci.princeton.edu/tom/papers/indianbuffet.pdf) is the foundational paper. [Thibaux & Jordan (2007)](https://www.researchgate.net/publication/220321011_Hierarchical_Beta_Processes_and_the_Indian_Buffet_Process) extend it to hierarchical settings. For graph applications, see [Bayesian Models of Graphs, Arrays and Other Exchangeable Structures](https://arxiv.org/pdf/1312.7857).

---

## 3. Credal Networks and Imprecise Probability

### 3.1 Credal Sets for Edge Uncertainty

A credal set is a closed, convex set of probability distributions. Instead of saying "this edge has confidence 0.7," we say "the confidence lies in [0.55, 0.85]."

For a Beta(alpha, beta) distribution, the credal set can be expressed as a credible interval:

```python
def edge_credal_interval(
    alpha_e: float,
    beta_e: float,
    credal_level: float = 0.90,
) -> tuple[float, float]:
    """90% credible interval for edge reliability."""
    from scipy.stats import beta as beta_dist
    tail = (1.0 - credal_level) / 2.0
    lower = beta_dist.ppf(tail, alpha_e, beta_e)
    upper = beta_dist.ppf(1.0 - tail, alpha_e, beta_e)
    return (lower, upper)
```

**The credal gap for edges** mirrors the existing belief credal gap: it counts edges still at their type prior (no traversal feedback yet). This is a system health metric -- a high edge credal gap means the graph structure is untested.

```python
def edge_credal_gap(store: MemoryStore) -> dict[str, float]:
    """Percentage of edges with no traversal feedback (still at type prior)."""
    total = store.query("SELECT COUNT(*) FROM edges")[0][0]
    # Edges at prior have alpha_e + beta_e == initial prior strength
    at_prior = store.query(
        """SELECT COUNT(*) FROM edges
           WHERE (alpha_e + beta_e) <= (
               CASE edge_type
                   WHEN 'SUPERSEDES' THEN 9.5
                   WHEN 'RELATES_TO' THEN 5.5
                   ELSE 8.5
               END
           )""",
    )[0][0]
    pct = (at_prior / total * 100) if total > 0 else 0.0
    return {"total": total, "at_prior": at_prior, "pct": round(pct, 1)}
```

### 3.2 Interval-Valued Edge Weights

Instead of a point-estimate weight, each edge carries an interval [w_lower, w_upper]:

```
w_lower = alpha_e / (alpha_e + beta_e) - credal_width / 2
w_upper = alpha_e / (alpha_e + beta_e) + credal_width / 2
```

Where `credal_width` comes from the Beta distribution's variance:
```
credal_width = k * sqrt(alpha_e * beta_e / ((alpha_e + beta_e)^2 * (alpha_e + beta_e + 1)))
```

**When to use the lower bound vs. upper bound:**
- **Conservative retrieval** (safety-critical queries): use `w_lower`. Only traverse edges you're confident about.
- **Exploratory retrieval** (broad search): use `w_upper`. Traverse edges that *might* be useful.
- **Thompson sampling**: sample from Beta(alpha_e, beta_e) directly -- this naturally produces values distributed across the interval.

### 3.3 Uncertainty Propagation Through Traversals

When traversing a path A -> B -> C, the uncertainty compounds:

```
P(C useful | traversed A->B->C) = P(edge_AB useful) * P(edge_BC useful) * P(C useful)
```

Using credal intervals, this becomes interval multiplication:

```python
def path_credal_interval(
    edges: list[Edge],
    destination_belief: Belief,
) -> tuple[float, float]:
    """Credal interval for a multi-hop path."""
    lower = 1.0
    upper = 1.0
    for edge in edges:
        e_lower, e_upper = edge_credal_interval(edge.alpha_e, edge.beta_e)
        lower *= e_lower
        upper *= e_upper
    # Multiply by destination belief's confidence interval
    b_lower, b_upper = edge_credal_interval(
        destination_belief.alpha, destination_belief.beta_param,
    )
    lower *= b_lower
    upper *= b_upper
    return (lower, upper)
```

**Practical implication:** Multi-hop traversals accumulate uncertainty rapidly. A 3-hop path through moderately uncertain edges (each [0.5, 0.9]) yields a path interval of [0.125, 0.729] -- very wide. This naturally limits useful traversal depth, which is desirable: the system should prefer direct connections over long chains.

### 3.4 Connection to Existing credal_gap Metric

The existing `credal_gap` in store.py counts beliefs at type prior. Extending to edges:

```python
def system_credal_health(store: MemoryStore) -> dict[str, Any]:
    """Combined belief + edge credal gap."""
    belief_health = store.health_metrics()
    edge_health = edge_credal_gap(store)
    return {
        "belief_credal_gap_pct": belief_health["credal_gap_pct"],
        "edge_credal_gap_pct": edge_health["pct"],
        "combined_credal_gap_pct": (
            belief_health["credal_gap_pct"] + edge_health["pct"]
        ) / 2.0,
    }
```

Source: For credal networks, see the [SIPTA 30 Years of Credal Networks survey](https://sipta.org/blog/credal-network-history/). For the 2U propagation algorithm, see Cano et al. and Tessem's interval propagation. The connection between Beta posteriors and credible intervals is standard; see [Understanding Credible Intervals](http://varianceexplained.org/r/credible_intervals_baseball/).

---

## 4. Information-Theoretic Edge Evaluation

### 4.1 Mutual Information Between Beliefs as Edge Weight

Mutual information I(A; B) measures how much knowing belief A reduces uncertainty about belief B. For edges, this provides an alternative to Bayesian confidence: edges with high MI are informationally dense.

```
I(A; B) = H(A) + H(B) - H(A, B)
```

For binary retrieval outcomes (used/not-used):

```python
def edge_mutual_information(
    from_id: str,
    to_id: str,
    store: MemoryStore,
) -> float:
    """Mutual information between two beliefs' retrieval outcomes.

    Based on co-occurrence in test results within the same session.
    Returns bits of mutual information.
    """
    # Get session-level outcome vectors for both beliefs
    sessions_a = _get_session_outcomes(from_id, store)  # {session_id: used/not}
    sessions_b = _get_session_outcomes(to_id, store)
    common = set(sessions_a.keys()) & set(sessions_b.keys())

    if len(common) < 5:
        return 0.0  # Insufficient data

    # Build 2x2 contingency table
    n11 = sum(1 for s in common if sessions_a[s] and sessions_b[s])      # both used
    n10 = sum(1 for s in common if sessions_a[s] and not sessions_b[s])  # A used, B not
    n01 = sum(1 for s in common if not sessions_a[s] and sessions_b[s])  # A not, B used
    n00 = sum(1 for s in common if not sessions_a[s] and not sessions_b[s])
    n = len(common)

    mi = 0.0
    for nij, ni, nj in [
        (n11, n11 + n10, n11 + n01),
        (n10, n11 + n10, n10 + n00),
        (n01, n01 + n00, n11 + n01),
        (n00, n01 + n00, n10 + n00),
    ]:
        if nij > 0 and ni > 0 and nj > 0:
            mi += (nij / n) * math.log2((nij * n) / (ni * nj))

    return mi
```

Source: Mutual information for knowledge graph evaluation is an active research area. See [A Mutual Information Perspective on Knowledge Graph Embedding (ACL 2025)](https://aclanthology.org/2025.acl-long.1077/) for MI applied to KG embeddings. The [Graph Embeddings, Mutual Information, KL Divergence](https://geelon.github.io/assets/writing/graph-embeddings.pdf) paper covers the theoretical foundations.

### 4.2 KL Divergence for Stale Edge Detection

An edge becomes stale when the beliefs it connects have drifted apart in meaning or relevance. KL divergence measures how much one distribution has diverged from another.

For edges, track the edge's Beta distribution over time windows:

```python
def edge_staleness_kl(
    edge: Edge,
    window_days: int = 30,
    store: MemoryStore,
) -> float:
    """KL divergence between recent and historical edge outcomes.

    High KL divergence = the edge's reliability has changed significantly.
    Returns KL(recent || historical) in nats.
    """
    # Historical: the edge's current alpha_e, beta_e
    p_alpha = edge.alpha_e
    p_beta = edge.beta_e

    # Recent: outcomes in the last window_days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    recent = store.query(
        """SELECT outcome FROM edge_traversals
           WHERE edge_id = ? AND created_at > ?""",
        (edge.id, cutoff),
    )

    if len(recent) < 3:
        return 0.0  # Not enough recent data

    recent_successes = sum(1 for r in recent if r["outcome"] == "used")
    recent_failures = len(recent) - recent_successes
    q_alpha = recent_successes + 0.5  # Jeffreys prior
    q_beta = recent_failures + 0.5

    # KL divergence between two Beta distributions (closed form):
    # KL(q || p) = ln(B(p_a, p_b) / B(q_a, q_b))
    #            + (q_a - p_a) * digamma(q_a) + (q_b - p_b) * digamma(q_b)
    #            + (p_a - q_a + p_b - q_b) * digamma(q_a + q_b)
    from math import lgamma
    from scipy.special import digamma

    def ln_beta(a: float, b: float) -> float:
        return lgamma(a) + lgamma(b) - lgamma(a + b)

    kl = (ln_beta(p_alpha, p_beta) - ln_beta(q_alpha, q_beta)
          + (q_alpha - p_alpha) * digamma(q_alpha)
          + (q_beta - p_beta) * digamma(q_beta)
          + (p_alpha - q_alpha + p_beta - q_beta) * digamma(q_alpha + q_beta))

    return max(0.0, kl)
```

**When to act on staleness:** If `edge_staleness_kl > 1.0` (1 nat, roughly 1.44 bits), the edge's recent performance is significantly different from its historical average. Options:
- **Reset the edge** to its type prior (aggressive)
- **Blend** recent and historical via exponential decay (conservative)
- **Flag for review** in the compaction pass

Source: KL divergence between Beta distributions has a closed-form solution. The Bayesian changepoint detection literature provides the framework for detecting distributional shifts; see [Online Bayesian Changepoint Detection for Network Poisson Processes](https://link.springer.com/article/10.1007/s11222-025-10606-w) and [A Survey of Change Point Detection in Dynamic Graphs](https://www.computer.org/csdl/journal/tk/2025/03/10817616/231oUDkTj8s).

### 4.3 Information Gain from Traversing an Edge

Before traversing an edge, estimate how much information we'd gain:

```python
def expected_information_gain(edge: Edge) -> float:
    """Expected bits of information from traversing this edge.

    High uncertainty edges have high information gain -- traversing them
    teaches us a lot about their reliability. Low uncertainty edges
    provide predictable results but no new information.

    This is the entropy of the Beta distribution.
    """
    from scipy.stats import beta as beta_dist
    return beta_dist.entropy(edge.alpha_e, edge.beta_e)
```

**Use case: active learning.** When the system has bandwidth for exploration, prefer edges with high information gain. This is the information-theoretic justification for Thompson sampling's exploration behavior.

### 4.4 MDL for Optimal Edge Sets

The Minimum Description Length principle says: the best edge set is the one that most compresses the observed data. Peixoto (2025) formalized this for network reconstruction.

Applied to agentmemory: the description length of the graph is:

```
DL(G, D) = DL(G) + DL(D | G)
```

Where:
- `DL(G)` = cost of encoding the graph structure (number of edges, edge types, weights)
- `DL(D | G)` = cost of encoding the retrieval outcome data given the graph

Adding an edge is justified only if it reduces `DL(D | G)` by more than it increases `DL(G)`.

**Practical approximation:**

```python
def mdl_edge_score(edge: Edge, store: MemoryStore) -> float:
    """MDL score for whether this edge is worth keeping.

    Positive = edge compresses the data (keep it).
    Negative = edge adds more description cost than it saves (prune it).
    """
    # Cost of encoding this edge (structure cost)
    # Each edge costs: log2(N^2) bits for endpoints + log2(T) for type + bits for weight
    n_beliefs = store.query("SELECT COUNT(*) FROM beliefs WHERE valid_to IS NULL")[0][0]
    structure_cost = 2 * math.log2(max(n_beliefs, 2)) + math.log2(8)  # 8 edge types

    # Data compression: how much does this edge help predict retrieval outcomes?
    # Use the edge's traversal success rate vs. base rate
    traversals = edge.alpha_e + edge.beta_e - _initial_prior_strength(edge.edge_type)
    if traversals < 1:
        return -structure_cost  # No data yet; edge is pure cost

    success_rate = edge.alpha_e / (edge.alpha_e + edge.beta_e)
    base_rate = 0.5  # Assume 50% base usage rate without the edge

    # Bits saved per traversal by knowing this edge's reliability
    if success_rate > 0.01 and success_rate < 0.99:
        bits_saved = traversals * (
            success_rate * math.log2(success_rate / base_rate)
            + (1 - success_rate) * math.log2((1 - success_rate) / (1 - base_rate))
        )
    else:
        bits_saved = traversals  # Near-certain edges save ~1 bit per traversal

    return bits_saved - structure_cost
```

**Edge pruning policy:** During compaction, remove edges where `mdl_edge_score < -2.0` (cost exceeds benefit by more than 2 bits). This is the information-theoretic equivalent of the belief supersession policy.

Source: [Peixoto (2025), "Network Reconstruction via the Minimum Description Length Principle"](https://arxiv.org/abs/2405.01015), Physical Review X. The MDL principle for pattern mining is surveyed in [Galbrun (2022)](https://link.springer.com/article/10.1007/s10618-022-00846-z).

---

## 5. Practical Integration

### 5.1 Schema Changes

**Minimal addition to the edges table -- 2 columns:**

```sql
ALTER TABLE edges ADD COLUMN alpha_e REAL NOT NULL DEFAULT 3.0;
ALTER TABLE edges ADD COLUMN beta_e REAL NOT NULL DEFAULT 2.0;
```

The defaults (3.0, 2.0) give a RELATES_TO-level prior. The `insert_edge` function should set type-appropriate priors at creation time.

**New table for traversal tracking (parallel to tests table for beliefs):**

```sql
CREATE TABLE IF NOT EXISTS edge_traversals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    outcome TEXT NOT NULL,          -- 'used', 'ignored', 'harmful'
    created_at TEXT NOT NULL,
    FOREIGN KEY (edge_id) REFERENCES edges(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_edge_trav_edge ON edge_traversals(edge_id);
CREATE INDEX IF NOT EXISTS idx_edge_trav_session ON edge_traversals(session_id);
```

**Storage impact:** 2 REAL columns on edges adds ~16 bytes per edge. The edge_traversals table is append-only and can be compacted (aggregate into alpha_e/beta_e and delete old rows). With ~1000 edges and ~10 traversals each, that's ~10K rows -- negligible for SQLite.

### 5.2 Edge Model Extension

```python
@dataclass
class Edge:
    id: int
    from_id: str
    to_id: str
    edge_type: str
    weight: float               # Legacy; kept for backward compat
    reason: str
    created_at: str
    alpha_e: float = 3.0        # Beta distribution success parameter
    beta_e: float = 2.0         # Beta distribution failure parameter

    @property
    def confidence(self) -> float:
        """Point estimate of edge reliability."""
        return self.alpha_e / (self.alpha_e + self.beta_e)

    @property
    def uncertainty(self) -> float:
        """Normalized variance of the Beta distribution."""
        total = self.alpha_e + self.beta_e
        if total <= 0.0:
            return 1.0
        variance = (self.alpha_e * self.beta_e) / (total * total * (total + 1.0))
        return min(1.0, variance / 0.125)
```

### 5.3 insert_edge Update

```python
# Edge type -> (default_alpha, default_beta) priors
EDGE_TYPE_PRIORS: dict[str, tuple[float, float]] = {
    "SUPERSEDES":    (8.0, 1.0),
    "CONTRADICTS":   (6.0, 2.0),
    "SUPPORTS":      (5.0, 2.0),
    "CITES":         (7.0, 1.0),
    "IMPLEMENTS":    (6.0, 1.5),
    "TESTS":         (5.0, 2.0),
    "RELATES_TO":    (3.0, 2.0),
    "TEMPORAL_NEXT": (4.0, 1.0),
}

def insert_edge(
    self,
    from_id: str,
    to_id: str,
    edge_type: str,
    weight: float = 1.0,
    reason: str = "",
) -> int:
    ts = _now()
    alpha_e, beta_e = EDGE_TYPE_PRIORS.get(edge_type, (3.0, 2.0))
    cursor = self._conn.execute(
        """INSERT INTO edges (from_id, to_id, edge_type, weight, reason,
                             alpha_e, beta_e, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_id, to_id, edge_type, weight, reason, alpha_e, beta_e, ts),
    )
    self._conn.commit()
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("Edge insert did not return a rowid")
    return row_id
```

### 5.4 Feedback Loop: Retrieval -> Traversal -> Use/Ignore -> Update

The key integration point is in `retrieval.py`, where HRR graph traversal happens. The flow:

```
1. User queries via search()
2. FTS5 returns seed beliefs
3. HRR traversal follows edges to find vocabulary-bridged beliefs
4. All results returned to agent
5. Agent uses some, ignores others
6. feedback() called with belief_id and outcome
7. NEW: propagate feedback to the edges that led to each belief
```

```python
def propagate_edge_feedback(
    belief_id: str,
    outcome: str,
    session_id: str,
    store: MemoryStore,
) -> int:
    """After belief feedback, update the edges that led to this belief.

    Finds edges where to_id == belief_id that were traversed in this session's
    retrieval. Updates their alpha_e/beta_e accordingly.

    Returns number of edges updated.
    """
    # Find edges that point to this belief (it was the destination)
    edges = store.query(
        """SELECT id, alpha_e, beta_e, edge_type FROM edges
           WHERE to_id = ?""",
        (belief_id,),
    )

    updated = 0
    for edge_row in edges:
        edge_id = edge_row["id"]

        if outcome == "used":
            new_alpha = edge_row["alpha_e"] + 1.0
            new_beta = edge_row["beta_e"]
        elif outcome == "harmful":
            new_alpha = edge_row["alpha_e"]
            new_beta = edge_row["beta_e"] + 1.0
        else:
            # "ignored" -- no update, matching belief policy
            continue

        store.execute(
            """UPDATE edges SET alpha_e = ?, beta_e = ? WHERE id = ?""",
            (new_alpha, new_beta, edge_id),
        )

        # Record the traversal for history/staleness detection
        store.execute(
            """INSERT INTO edge_traversals (edge_id, session_id, outcome, created_at)
               VALUES (?, ?, ?, ?)""",
            (edge_id, session_id, outcome, _now()),
        )

        updated += 1

    store.commit()
    return updated
```

**Important refinement:** Not all edges pointing to a belief were actually traversed. The HRR retrieval path should record which edges were traversed in a given query, so feedback is attributed only to the edges that actually participated. This requires a small addition to the retrieval function:

```python
# In retrieval.py, track traversed edges during HRR expansion
_session_traversed_edges: set[int] = set()

def record_traversal(edge_id: int) -> None:
    _session_traversed_edges.add(edge_id)

def get_traversed_edges() -> set[int]:
    return _session_traversed_edges.copy()

def clear_traversed_edges() -> None:
    _session_traversed_edges.clear()
```

Then `propagate_edge_feedback` filters to only edges in `_session_traversed_edges`.

### 5.5 Migration Strategy

1. **Add columns with defaults** -- zero downtime, backward compatible
2. **Existing edges get type-appropriate priors** via a migration script
3. **Start collecting traversal data** -- edges begin learning immediately
4. **Empirical Bayes update** runs weekly during compaction to adjust type-level priors
5. **MDL pruning** added to compaction after 30 days of traversal data

```python
def migrate_edge_priors(store: MemoryStore) -> int:
    """One-time migration: set type-appropriate priors on existing edges."""
    updated = 0
    for edge_type, (alpha, beta) in EDGE_TYPE_PRIORS.items():
        cursor = store.execute(
            """UPDATE edges SET alpha_e = ?, beta_e = ?
               WHERE edge_type = ? AND alpha_e = 3.0 AND beta_e = 2.0""",
            (alpha, beta, edge_type),
        )
        updated += cursor.rowcount
    store.commit()
    return updated
```

---

## 6. Algorithm Summary: Edge Lifecycle

```
CREATE:
  1. Detect relationship (LLM semantic linker, correction system, onboarding)
  2. Set type-appropriate Beta prior: (alpha_e, beta_e) from EDGE_TYPE_PRIORS
  3. Insert edge with prior

TRAVERSE:
  1. HRR graph query selects candidate edges
  2. Thompson sampling ranks edges: sample ~ Beta(alpha_e, beta_e)
  3. Top-k edges traversed; record edge IDs in session traversal set
  4. Destination beliefs added to retrieval results

UPDATE:
  1. Agent feedback on destination belief: "used" / "ignored" / "harmful"
  2. Propagate to traversed edges only
  3. alpha_e += 1 (used) or beta_e += 1 (harmful) or no-op (ignored)
  4. Record in edge_traversals table

EVALUATE (periodic, during compaction):
  1. Compute edge_staleness_kl for each edge with sufficient data
  2. Flag edges with KL > 1.0 nat for review
  3. Compute mdl_edge_score for each edge
  4. Prune edges with MDL score < -2.0
  5. Run empirical Bayes to update type-level priors
  6. Report edge credal gap as system health metric

PRUNE:
  1. MDL score negative and persistent -> soft-delete edge
  2. Destination belief superseded -> decay edge beta_e += 0.5
  3. No traversals in 90 days + low prior -> candidate for removal
```

---

## 7. Open Questions for Design Decision

1. **Should edge alpha/beta replace weight, or coexist?** The `weight` column currently serves a different purpose (LLM-assessed semantic similarity) than alpha/beta (traversal-validated reliability). Recommendation: keep both. `weight` is the prior assessment of semantic relevance; `alpha_e/beta_e` is the posterior learned from usage. Composite score = `weight * confidence_e`.

2. **How aggressively to propagate feedback?** Option A: update all edges pointing to the belief. Option B: update only edges actually traversed in the query. Option B is more correct but requires traversal tracking. Recommendation: implement Option B (traversal tracking is cheap).

3. **Should edge Thompson sampling replace or supplement HRR similarity?** Currently HRR returns edges by vector similarity. Thompson sampling could re-rank HRR results, or replace HRR entirely. Recommendation: use Thompson sampling as a re-ranker on top of HRR. HRR handles the "which edges are semantically relevant" question; Thompson sampling handles "which of those are reliable."

4. **Compaction of edge_traversals:** Like the tests table, edge_traversals will grow. Compact by aggregating into alpha_e/beta_e and deleting rows older than 90 days. Keep last 10 traversals per edge for staleness detection.

5. **Graph_edges table:** The schema has both `edges` and `graph_edges` tables. Should Bayesian scoring apply to both? Recommendation: only `edges` (the belief-to-belief graph). `graph_edges` appears to be for a different purpose (possibly onboarding-stage file-level graph).

---

## References

- [Bayes Rules! Chapter 3: The Beta-Binomial Model](https://www.bayesrulesbook.com/chapter-3)
- [Think Bayes Chapter 18: Conjugate Priors](https://allendowney.github.io/ThinkBayes2/chap18.html)
- [Bayesian Hierarchical Modeling](https://bayesball.github.io/BOOK/bayesian-hierarchical-modeling.html)
- [UBC CPSC 540: Conjugate Priors, Hierarchical Bayes](https://www.cs.ubc.ca/~schmidtm/Courses/540-W19/L33.pdf)
- [Georgia Tech: Hierarchical Bayes and Empirical Bayes](https://www2.isye.gatech.edu/isyebayes/bank/handout8.pdf)
- [Scutari (2017): Dirichlet Bayesian Network Scores and the Maximum Entropy Principle](https://proceedings.mlr.press/v73/scutari17a.html)
- [pgmpy: Structure Learning in Bayesian Networks](https://pgmpy.org/examples/Structure%20Learning%20in%20Bayesian%20Networks.html)
- [Peixoto (2025): Network Reconstruction via MDL](https://arxiv.org/abs/2405.01015)
- [Galbrun (2022): MDL Principle for Pattern Mining Survey](https://link.springer.com/article/10.1007/s10618-022-00846-z)
- [SIPTA: 30 Years of Credal Networks](https://sipta.org/blog/credal-network-history/)
- [Credal Sets: Modeling Epistemic Uncertainty](https://www.emergentmind.com/topics/credal-sets)
- [ACL 2025: A Mutual Information Perspective on Knowledge Graph Embedding](https://aclanthology.org/2025.acl-long.1077/)
- [Graph Embeddings, Mutual Information, KL Divergence](https://geelon.github.io/assets/writing/graph-embeddings.pdf)
- [Griffiths & Ghahramani: The Indian Buffet Process](https://cocosci.princeton.edu/tom/papers/indianbuffet.pdf)
- [Thibaux & Jordan (2007): Hierarchical Beta Processes and the IBP](https://www.researchgate.net/publication/220321011_Hierarchical_Beta_Processes_and_the_Indian_Buffet_Process)
- [Accelerating Bayesian Structure Learning in Sparse GGMs](https://www.tandfonline.com/doi/full/10.1080/01621459.2021.1996377)
- [Online Bayesian Changepoint Detection for Network Processes](https://link.springer.com/article/10.1007/s11222-025-10606-w)
- [Change Point Detection in Dynamic Graphs Survey](https://www.computer.org/csdl/journal/tk/2025/03/10817616/231oUDkTj8s)
- [Understanding Credible Intervals](http://varianceexplained.org/r/credible_intervals_baseball/)
- [Stanford: A Tutorial on Thompson Sampling](https://web.stanford.edu/~bvr/pubs/TS_Tutorial.pdf)
- [Bayesian Models of Graphs and Exchangeable Structures](https://arxiv.org/pdf/1312.7857)
