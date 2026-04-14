# Bio-Inspired Edge Dynamics for Belief Graphs

**Date:** 2026-04-14
**Status:** Research complete, algorithm sketches ready for prototyping
**Context:** agentmemory currently creates edges at ingestion time via Jaccard similarity (relationship_detector.py) or LLM batch classification (semantic_linker.py). Edges are static after creation. This document explores bio-inspired mechanisms for dynamic edge creation, strengthening, and pruning at runtime.

---

## 1. Physarum / Slime Mold Network Model

### Core Biological Mechanism

Physarum polycephalum is a single-celled organism that builds transport networks between food sources. The organism extends tubular veins in all directions, then selectively reinforces tubes that carry high flow while allowing low-flow tubes to atrophy. The result: networks that rival human-engineered infrastructure in efficiency, fault tolerance, and cost.

The landmark result: Tero et al. (2010) placed oat flakes at positions corresponding to Tokyo metro stations. The slime mold produced a network comparable to the actual Tokyo rail system, optimizing for transport efficiency, redundancy, and cost simultaneously.

**The key mechanism is a positive feedback loop between flow and conductance:**

1. All tubes start with equal conductance
2. Flow is computed using Poiseuille's law (pressure-driven flow through tubes)
3. Tubes with high flow thicken (conductance increases)
4. Tubes with low flow thin and eventually vanish (conductance decays)
5. The network converges to a near-optimal topology

### Mathematical Model (Tero-Kobayashi Equations)

For each edge (i,j) in the network:

```
Q_ij = D_ij * (p_i - p_j) / L_ij      # Flow through tube (Poiseuille)

dD_ij/dt = f(|Q_ij|) - alpha * D_ij    # Conductance update

where:
  Q_ij  = flow through edge (i,j)
  D_ij  = conductance of edge (i,j)
  p_i   = pressure at node i
  L_ij  = length of edge (i,j)
  f()   = monotonically increasing function of flow magnitude
  alpha = decay rate constant
```

The function f(|Q|) is typically f(|Q|) = |Q|^gamma where gamma >= 1. When gamma = 1, the system converges to the shortest path. When gamma < 1, the system maintains redundant paths (fault tolerance). This parameter controls the efficiency-redundancy tradeoff.

The "minimum spanning tree with redundancy" property emerges naturally: the network sits between a minimum spanning tree (cheapest but fragile) and a fully connected graph (robust but expensive). Biological mycelium networks occupy this same intermediate zone.

### Mapping to Belief Graph

| Physarum Concept | Belief Graph Analog |
|---|---|
| Food source (node) | Belief node |
| Tube (edge) | Edge (RELATES_TO, SUPPORTS, etc.) |
| Nutrient flow | Information flow: co-retrieval events |
| Pressure gradient | Relevance gradient: query-belief similarity |
| Tube conductance D_ij | Edge weight (currently 0.0-1.0) |
| Flow magnitude |Q_ij| | Co-retrieval frequency between two beliefs |
| Decay rate alpha | Time-based weight decay |
| Tube length L_ij | Semantic distance between beliefs |

**"Energy" analog:** Retrieval events are the nutrient. When a query retrieves beliefs A and B together, that is flow through the implicit edge between them. High co-retrieval frequency = high flow = edge strengthening.

### Computational Cost at Scale

For 20K beliefs and 25K edges:

- **Flow computation:** Solving the pressure equations requires solving a linear system. For sparse graphs, this is O(E) per iteration using conjugate gradient. At 25K edges, each iteration takes <10ms.
- **Conductance update:** O(E) per step. Trivial at 25K.
- **Convergence:** Typically 50-200 iterations for network stabilization. But we do not need full convergence per query -- we update incrementally per retrieval event.
- **Per-retrieval update cost:** O(k) where k = number of beliefs co-retrieved (typically 3-10). Negligible.

**Verdict:** Feasible. The incremental version (update on each retrieval) is the right approach -- no need for global re-solve.

### Algorithm Sketch: Physarum Edge Dynamics

```python
# Constants
DECAY_RATE: float = 0.01          # alpha: per-hour decay
FLOW_EXPONENT: float = 0.8        # gamma < 1 for redundancy
MIN_WEIGHT: float = 0.05          # below this, prune the edge
INITIAL_WEIGHT: float = 0.3       # new edges from co-retrieval
MAX_EDGES_PER_BELIEF: int = 15    # cap to prevent hub explosion

def on_retrieval(query: str, retrieved_beliefs: list[Belief]) -> None:
    """Called after every search() MCP call. Updates edge weights."""
    # Co-retrieved beliefs have implicit "flow" between them
    for i, a in enumerate(retrieved_beliefs):
        for b in retrieved_beliefs[i + 1:]:
            edge = store.get_edge(a.id, b.id)
            if edge is None:
                # New edge from co-retrieval (tube grows)
                if count_edges(a.id) < MAX_EDGES_PER_BELIEF:
                    store.insert_edge(
                        from_id=a.id, to_id=b.id,
                        edge_type="RELATES_TO",
                        weight=INITIAL_WEIGHT,
                        reason="physarum_coretrieval",
                    )
            else:
                # Strengthen existing edge (tube thickens)
                flow = compute_flow(query, a, b)
                new_weight = min(1.0, edge.weight + flow ** FLOW_EXPONENT)
                store.update_edge_weight(edge.id, new_weight)

def periodic_decay(hours_elapsed: float) -> None:
    """Run periodically (e.g. session start). Decays all edge weights."""
    edges = store.get_all_edges()
    for edge in edges:
        if edge.reason and edge.reason.startswith("physarum"):
            new_weight = edge.weight - DECAY_RATE * hours_elapsed
            if new_weight < MIN_WEIGHT:
                store.delete_edge(edge.id)  # tube vanishes
            else:
                store.update_edge_weight(edge.id, new_weight)

def compute_flow(query: str, a: Belief, b: Belief) -> float:
    """Flow magnitude = product of relevance scores, normalized."""
    # Relevance to query serves as "pressure gradient"
    rel_a = jaccard_similarity(extract_terms(query), extract_terms(a.content))
    rel_b = jaccard_similarity(extract_terms(query), extract_terms(b.content))
    return rel_a * rel_b  # high when both are relevant to query
```

### Sources

- [Tero et al. (2010) "Rules for Biologically Inspired Adaptive Network Design" Science 327(5964)](https://www.science.org/doi/10.1126/science.1177894)
- [Tero et al. (2006) "Physarum solver: biologically inspired method of road-network navigation" Physica A 363(1)](https://www.sciencedirect.com/science/article/abs/pii/S0378437106000963)
- [Tero et al. (2007) "A mathematical model for adaptive transport network in path finding by true slime mold" J. Theoretical Biology](https://www.sciencedirect.com/science/article/abs/pii/S002251930600289X)
- [Sun et al. (2017) "Physarum-inspired Network Optimization: A Review" arXiv:1712.02910](https://arxiv.org/pdf/1712.02910)
- [Li et al. (2023) "Slime Mould Algorithm: Comprehensive Survey of Variants and Applications" PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9838547/)
- [Elhachimi et al. (2025) "Computational Modeling and Analysis of Fungi-Inspired Network Systems" Advanced Engineering Materials](https://www.newswise.com/pdf_docs/175017050774709_Adv%20Eng%20Mater%20-%202025%20-%20Elhachimi%20-%20Computational%20Modeling%20and%20Analysis%20of%20Fungi%E2%80%90Inspired%20Network%20Systems.pdf)
- [Bebber et al. (2007) "Biological solutions to transport network design" Proc. Royal Society B](https://pmc.ncbi.nlm.nih.gov/articles/PMC2288531/)

---

## 2. Energy-Based Network Formation

### 2a. Hopfield Networks as Associative Memory

#### Core Mechanism

A Hopfield network is an energy-based recurrent network where each configuration of neurons has a scalar energy. The network settles into local energy minima, which correspond to stored memories. Retrieval is pattern completion: given a partial or noisy input, the network relaxes to the nearest stored pattern.

**Energy function (classical Hopfield):**

```
E = -0.5 * sum_ij(w_ij * s_i * s_j)

where:
  w_ij = connection weight between neurons i and j
  s_i  = state of neuron i (+1 or -1)
```

Modern Hopfield networks (Krotov & Hopfield 2016, Ramsauer et al. 2020) replace the quadratic energy with higher-order interactions, achieving exponential storage capacity and a direct connection to Transformer attention.

#### Recent Work: Graph Hopfield Networks (2026)

Li et al. (arXiv 2603.03464, March 2026) introduced Graph Hopfield Networks that combine associative memory retrieval with graph Laplacian smoothing. The energy function couples two terms:

```
E_total = E_hopfield(features) + lambda * E_laplacian(features, adjacency)
```

Gradient descent on this joint energy yields iterative updates that interleave Hopfield retrieval with graph propagation. Key finding: the iterative energy-descent architecture itself is a strong inductive bias -- even the memory-disabled ablation outperforms standard baselines.

#### Recent Work: Associative Knowledge Graphs (2024)

Luzgin et al. (arXiv 2411.14480) proposed Associative Knowledge Graphs (AKGs) that use sparse graph structures as an alternative to dense Hopfield weight matrices. Sequences are stored as directed edges in a knowledge graph. Retrieval uses context-based cue propagation rather than energy minimization. Compared to classical Hopfield networks, AKGs achieve higher memory capacity for sequential data by exploiting graph sparsity.

#### Recent Work: EcphoryRAG (2025)

Christodoulou et al. (arXiv 2510.08958) built EcphoryRAG, a RAG framework inspired by human associative memory. "Ecphory" is the cognitive process where a retrieval cue reactivates a complete memory trace (engram). The system extracts core entities, then performs multi-hop associative search across a knowledge graph, dynamically inferring implicit relations. Achieves SOTA on multi-hop QA benchmarks with 94% less token consumption than competing KG-RAG systems.

#### Mapping to Belief Graph

| Hopfield Concept | Belief Graph Analog |
|---|---|
| Neuron | Belief node |
| Connection weight w_ij | Edge weight |
| Stored pattern | Cluster of related beliefs |
| Energy minimum | Stable belief cluster (well-connected subgraph) |
| Pattern completion | Query expansion via graph traversal |
| Energy landscape | Global structure of belief relationships |

**"Energy" analog:** The energy function measures how well the current graph structure explains observed co-retrieval patterns. Low energy = edges match actual usage. High energy = misalignment between edges and information flow.

**Key insight for agentmemory:** We do not need to run a full Hopfield network. The conceptual takeaway is that edges should form an energy landscape where frequently-accessed belief clusters sit at energy minima (attractors), and rarely-used connections sit at saddle points (easy to prune).

### 2b. Boltzmann Machines for Graph Structure

#### Core Mechanism

A Boltzmann machine is a stochastic Hopfield network with a temperature parameter. At high temperature, the network explores many configurations. At low temperature, it converges to the most probable (lowest-energy) configuration. The Boltzmann distribution over configurations is:

```
P(state) = exp(-E(state) / T) / Z

where:
  E(state) = energy of the configuration
  T        = temperature
  Z        = partition function (normalization)
```

#### Recent Work: Boltzmann Graph Networks (2025)

Boltzmann Graph Networks (BGN) adapt Persistent Contrastive Divergence to graph topology. Unlike classical RBMs, BGN supports multiple stacked Boltzmann layers that scale with task complexity. Key innovation: integrating graph topology with energy-based feature modeling, where iterative refinement captures richer feature-structure interactions.

#### Mapping to Belief Graph

The Boltzmann framework suggests a "simulated annealing" approach to edge creation:

1. **High temperature (early in system life):** Create edges liberally. Many speculative RELATES_TO connections. The system explores.
2. **Cooling (as feedback accumulates):** Prune edges that never carry flow (never co-retrieved, no feedback). Strengthen edges that do.
3. **Low temperature (mature system):** Conservative edge creation. Only create new edges when strong evidence exists.

This maps naturally to system maturity. A fresh agentmemory instance should be "hot" (creating many weak edges to discover structure). A 20K-belief system should be "cool" (most structure is established, new edges need justification).

### 2c. Free Energy Principle and Active Inference

#### Core Mechanism

Karl Friston's free energy principle proposes that biological systems minimize variational free energy -- the difference between their internal model and sensory evidence. Applied to knowledge graphs: the belief graph is the "internal model" and retrieval events are "sensory evidence." The system should update its edges to minimize surprise when queries arrive.

**Variational free energy:**

```
F = KL(q(edges) || p(edges | observations)) + constant

where:
  q(edges)                = current edge configuration (our belief graph)
  p(edges | observations) = true posterior (what edges should exist given usage data)
```

Minimizing F means making our edge configuration match the actual information flow patterns.

#### Active Inference for Edge Creation

Under active inference, the system does not just passively update edges -- it actively seeks information to reduce uncertainty. Applied to agentmemory:

- When a query retrieves beliefs with high semantic similarity but no edge between them, this is "surprising" (high free energy)
- The system should create a candidate edge and track whether it gets used
- If the edge reduces future surprise (beliefs are co-retrieved again), it is confirmed
- If not, it is pruned (free energy was not actually reduced)

This is essentially hypothesis-driven edge creation: propose, test, confirm or reject.

### Computational Cost

- **Hopfield energy evaluation:** O(E) to compute energy over all edges. At 25K edges, <5ms.
- **Boltzmann sampling:** O(E * k_steps) where k_steps is the number of MCMC steps. Expensive for global optimization but we only need local updates.
- **Free energy gradient:** Same cost as Hopfield energy plus KL divergence computation. The KL term requires tracking retrieval statistics, which adds O(1) per retrieval event.
- **Temperature schedule:** O(1) -- just a parameter that decreases over time or with system maturity.

**Verdict:** Feasible for incremental updates. Global optimization (full Boltzmann sampling) is unnecessary at our scale -- incremental energy-descent updates per retrieval event are sufficient.

### Algorithm Sketch: Energy-Based Edge Formation

```python
# System "temperature" decreases as more feedback accumulates
def system_temperature(total_feedback_count: int) -> float:
    """Higher temp = more exploration. Decreases as system matures."""
    T_INITIAL: float = 1.0
    T_MIN: float = 0.1
    COOLING_RATE: float = 0.001
    return max(T_MIN, T_INITIAL * math.exp(-COOLING_RATE * total_feedback_count))

def compute_edge_energy(edge: Edge) -> float:
    """Energy of an edge. Low energy = good edge (should keep).
    High energy = bad edge (candidate for pruning)."""
    co_retrieval_count = store.get_co_retrieval_count(edge.from_id, edge.to_id)
    feedback_score = store.get_feedback_score(edge.from_id, edge.to_id)
    age_hours = hours_since(edge.created_at)

    # Energy decreases with usage and positive feedback
    usage_term = -math.log1p(co_retrieval_count)
    feedback_term = -feedback_score  # positive feedback = lower energy
    age_penalty = 0.001 * age_hours  # older unused edges cost more

    return usage_term + feedback_term + age_penalty

def on_retrieval_energy(query: str, retrieved: list[Belief]) -> None:
    """Energy-based edge update after each retrieval."""
    T = system_temperature(store.total_feedback_count())

    for i, a in enumerate(retrieved):
        for b in retrieved[i + 1:]:
            edge = store.get_edge(a.id, b.id)
            if edge is None:
                # Boltzmann acceptance: create edge with probability
                # proportional to temperature
                similarity = jaccard_similarity(
                    extract_terms(a.content), extract_terms(b.content)
                )
                p_create = similarity * T  # high temp = more likely
                if random.random() < p_create:
                    store.insert_edge(
                        from_id=a.id, to_id=b.id,
                        edge_type="RELATES_TO",
                        weight=similarity,
                        reason="energy_coretrieval",
                    )
            else:
                # Strengthen: reduce energy (increase weight)
                energy = compute_edge_energy(edge)
                delta = -0.1 * T  # small strengthening, scaled by temp
                new_weight = min(1.0, edge.weight - delta)
                store.update_edge_weight(edge.id, new_weight)

def prune_high_energy_edges() -> int:
    """Periodic pruning of edges with high energy (unused, no feedback)."""
    pruned = 0
    T = system_temperature(store.total_feedback_count())
    threshold = 2.0 * T  # prune threshold rises as temp drops (stricter)

    for edge in store.get_edges_by_reason_prefix("energy_"):
        energy = compute_edge_energy(edge)
        if energy > threshold:
            store.delete_edge(edge.id)
            pruned += 1
    return pruned
```

### Sources

- [Li et al. (2026) "Graph Hopfield Networks: Energy-Based Node Classification with Associative Memory" arXiv:2603.03464](https://arxiv.org/abs/2603.03464)
- [Luzgin et al. (2024) "Associative Knowledge Graphs for Efficient Sequence Storage and Retrieval" arXiv:2411.14480](https://arxiv.org/abs/2411.14480)
- [Christodoulou et al. (2025) "EcphoryRAG: Re-Imagining Knowledge-Graph RAG via Human Associative Memory" arXiv:2510.08958](https://arxiv.org/abs/2510.08958)
- [Hu et al. (2025) "Input-driven dynamics for robust memory retrieval in Hopfield networks" Science Advances](https://www.science.org/doi/10.1126/sciadv.adu6991)
- [Yang et al. (2024) "Hopfield-Fenchel-Young Networks: Unified Framework for Associative Memory Retrieval" arXiv:2411.08590](https://arxiv.org/abs/2411.08590)
- [Boltzmann Graph Networks (2025) OpenReview](https://openreview.net/pdf/23c45ad4b66db0ee260e96a7dd5bf3bc28e5b751.pdf)
- [Friston (2019) "Generalised free energy and active inference" Biological Cybernetics](https://link.springer.com/article/10.1007/s00422-019-00805-w)
- [Fountas et al. (2024) "Free Energy Projective Simulation (FEPS): Active inference with interpretability" PLoS One](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0331047)
- [Friston (2024) "Bayesian brain computing and the free-energy principle" National Science Review](https://academic.oup.com/nsr/article/11/5/nwae025/7571549)

---

## 3. Stigmergy: Pheromone-Based Edge Construction

### Core Biological Mechanism

Stigmergy is indirect coordination through environmental modification. Ants deposit pheromone trails when traveling between food sources. Other ants preferentially follow stronger trails. Trails evaporate over time. The result: optimal paths emerge without any ant having a global view.

**The ACO (Ant Colony Optimization) mechanism:**

1. Ants (agents) explore the graph randomly, biased by existing pheromone levels
2. When an ant finds a good path (high reward), it deposits pheromone on all edges in that path
3. Pheromone evaporates over time (exponential decay)
4. The probability of choosing edge (i,j) is proportional to tau_ij^alpha * eta_ij^beta, where tau = pheromone, eta = heuristic desirability

```
p_ij = (tau_ij^alpha * eta_ij^beta) / sum_k(tau_ik^alpha * eta_ik^beta)

tau_ij(t+1) = (1 - rho) * tau_ij(t) + sum_ants(delta_tau_ij)

where:
  tau_ij    = pheromone on edge (i,j)
  eta_ij    = heuristic (e.g., 1/distance)
  rho       = evaporation rate (0 < rho < 1)
  delta_tau = pheromone deposited by each ant
  alpha     = pheromone influence exponent
  beta      = heuristic influence exponent
```

### Digital Stigmergy for Knowledge Management

In digital systems, "pheromone" is metadata left by one agent that influences future agents. Applied to agentmemory:

- **Agents (ants):** Each retrieval query is an "ant" traversing the graph
- **Pheromone deposit:** When a query successfully retrieves and uses beliefs A and B, deposit pheromone on the edge between them (or create the edge if absent)
- **Evaporation:** Edge pheromone decays over time, ensuring the graph reflects recent usage, not historical patterns
- **Path selection:** Future queries preferentially traverse high-pheromone edges during BFS expansion

The key insight from stigmergy that differs from Physarum: **the signal is left by the retrieval consumer (the LLM), not by the information flow itself.** When the MCP client calls `feedback(belief_id, "used")`, that is a pheromone deposit. When it calls `feedback(belief_id, "ignored")`, that is anti-pheromone (negative reinforcement on the retrieval path).

### Mapping to Belief Graph

| Stigmergy Concept | Belief Graph Analog |
|---|---|
| Ant | A single retrieval query |
| Pheromone trail | Edge weight (or separate pheromone column) |
| Food source | Answer: the belief(s) that satisfied the query |
| Nest | Query origin |
| Evaporation | Time-based weight decay |
| Pheromone deposit | feedback("used") on retrieved beliefs |
| Anti-pheromone | feedback("ignored") or feedback("harmful") |
| Heuristic eta | Semantic similarity (Jaccard, embedding cosine) |

**"Energy" analog:** Pheromone is the energy here. It accumulates through successful usage (positive feedback) and dissipates through inactivity (evaporation). Unlike the Physarum model, stigmergy explicitly models negative feedback (anti-pheromone), which maps directly to our existing `feedback(belief_id, "harmful")` mechanism.

### Co-Retrieval Pheromone Traces

The most natural stigmergic signal in agentmemory is co-retrieval. When beliefs A and B are returned in the same search result and the user acts on both:

1. The retrieval event creates a pheromone trace on the implicit A-B edge
2. If the edge does not exist, it is created with low initial pheromone
3. Future queries that match A get a boost toward B (and vice versa) via the pheromone
4. If B is consistently ignored when co-retrieved with A, anti-pheromone weakens the edge
5. If neither A nor B is retrieved for a long time, the edge evaporates

This creates a self-organizing retrieval graph that adapts to actual usage patterns without any LLM classification cost.

### Computational Cost

- **Pheromone update:** O(k^2) per retrieval where k = result set size. With k typically 3-10, this is O(100) at worst. Negligible.
- **Evaporation pass:** O(E) over all edges. At 25K edges, <5ms. Can run at session start.
- **Path bias during BFS:** O(1) additional cost per edge lookup (just multiply by pheromone level). Already part of our weighted BFS.
- **Storage overhead:** One additional float column per edge (or reuse `weight`). Minimal.

**Verdict:** The cheapest of the three approaches. Fits naturally into the existing feedback loop.

### Algorithm Sketch: Stigmergic Edge Dynamics

```python
# Pheromone parameters
EVAPORATION_RATE: float = 0.05        # rho: 5% decay per hour
DEPOSIT_USED: float = 0.2             # pheromone for "used" feedback
DEPOSIT_CORETRIEVAL: float = 0.05     # pheromone for co-retrieval (no explicit feedback)
ANTI_PHEROMONE_IGNORED: float = -0.05  # penalty for "ignored"
ANTI_PHEROMONE_HARMFUL: float = -0.3   # strong penalty for "harmful"
MIN_PHEROMONE: float = 0.02           # below this, prune the edge
HEURISTIC_WEIGHT: float = 0.3         # beta: influence of semantic similarity

def on_retrieval_stigmergy(
    query: str,
    retrieved: list[Belief],
    feedback_map: dict[str, str] | None = None,
) -> None:
    """Update pheromone after retrieval + optional feedback.

    feedback_map: {belief_id: "used"|"ignored"|"harmful"} from MCP feedback calls.
    When None, only co-retrieval deposit occurs.
    """
    # Phase 1: Co-retrieval deposit (all pairs in result set)
    for i, a in enumerate(retrieved):
        for b in retrieved[i + 1:]:
            edge = store.get_edge(a.id, b.id)
            if edge is None:
                # Create edge with initial pheromone
                semantic_sim = jaccard_similarity(
                    extract_terms(a.content), extract_terms(b.content)
                )
                initial = DEPOSIT_CORETRIEVAL + HEURISTIC_WEIGHT * semantic_sim
                store.insert_edge(
                    from_id=a.id, to_id=b.id,
                    edge_type="RELATES_TO",
                    weight=initial,
                    reason="stigmergy_coretrieval",
                )
            else:
                store.update_edge_weight(
                    edge.id,
                    min(1.0, edge.weight + DEPOSIT_CORETRIEVAL),
                )

    # Phase 2: Feedback-based deposit (if feedback was provided)
    if feedback_map:
        for belief_id, outcome in feedback_map.items():
            # Find all edges from this belief to other retrieved beliefs
            other_ids = [b.id for b in retrieved if b.id != belief_id]
            for other_id in other_ids:
                edge = store.get_edge(belief_id, other_id)
                if edge is None:
                    continue
                if outcome == "used":
                    delta = DEPOSIT_USED
                elif outcome == "ignored":
                    delta = ANTI_PHEROMONE_IGNORED
                elif outcome == "harmful":
                    delta = ANTI_PHEROMONE_HARMFUL
                else:
                    delta = 0.0
                new_weight = max(0.0, min(1.0, edge.weight + delta))
                store.update_edge_weight(edge.id, new_weight)

def evaporate_pheromone(hours_elapsed: float) -> int:
    """Evaporate pheromone from all stigmergy-created edges. Returns prune count."""
    pruned = 0
    decay_factor = (1 - EVAPORATION_RATE) ** hours_elapsed
    for edge in store.get_edges_by_reason_prefix("stigmergy_"):
        new_weight = edge.weight * decay_factor
        if new_weight < MIN_PHEROMONE:
            store.delete_edge(edge.id)
            pruned += 1
        else:
            store.update_edge_weight(edge.id, new_weight)
    return pruned

def biased_bfs_weight(edge: Edge) -> float:
    """Modified BFS weight that incorporates pheromone.
    Higher returned value = higher traversal priority."""
    type_weight = EDGE_TYPE_WEIGHTS.get(edge.edge_type, 0.5)
    pheromone = edge.weight if edge.reason and "stigmergy" in edge.reason else 1.0
    return type_weight * pheromone
```

### Sources

- [Dorigo & Stutzle "Ant Colony Optimization" MIT Press (book)](https://web2.qatar.cmu.edu/~gdicaro/15382/additional/aco-book.pdf)
- [Smith (2025) "Collective Stigmergic Optimization: Leveraging ACO Emergent Properties for Multi-Agentic AI" Medium](https://medium.com/@jsmith0475/collective-stigmergic-optimization-leveraging-ant-colony-emergent-properties-for-multi-agent-ai-55fa5e80456a)
- [Birattari et al. (2024) "Automatic design of stigmergy-based behaviours for robot swarms" Nature Communications Engineering](https://www.nature.com/articles/s44172-024-00175-7)
- [Li et al. (2019) "Stigmergic Independent Reinforcement Learning for Multi-Agent Collaboration" arXiv:1911.12504](https://arxiv.org/abs/1911.12504)
- [Xu et al. (2022) "PooL: Pheromone-inspired Communication Framework" arXiv:2202.09722](https://arxiv.org/pdf/2202.09722)
- [Dorigo et al. "Ant algorithms and stigmergy" ACM Future Generation Computer Systems](https://dl.acm.org/doi/10.5555/348599.348601)
- [Wikipedia: Ant colony optimization algorithms](https://en.wikipedia.org/wiki/Ant_colony_optimization_algorithms)

---

## 4. Comparative Analysis

### Feature Comparison

| Feature | Physarum | Energy-Based | Stigmergy |
|---|---|---|---|
| Edge creation trigger | Co-retrieval | Co-retrieval + similarity | Co-retrieval + feedback |
| Edge strengthening | Flow magnitude (retrieval frequency) | Energy descent (usage reduces energy) | Pheromone deposit (explicit feedback) |
| Edge pruning | Conductance decay below threshold | High energy + low temperature | Evaporation below threshold |
| Negative feedback | Implicit (low flow = atrophy) | Energy increase | Explicit anti-pheromone |
| Temperature/maturity | Fixed parameters | Adaptive (cools over time) | Fixed evaporation rate |
| Redundancy control | gamma parameter | Temperature parameter | Evaporation rate |
| Computational cost per retrieval | O(k^2) | O(k^2) | O(k^2) |
| Periodic maintenance cost | O(E) decay pass | O(E) pruning pass | O(E) evaporation pass |
| Implementation complexity | Low | Medium (temperature, energy function) | Low |
| Fits existing feedback loop | Partially (no negative signal) | Yes | Yes (best fit) |

### Recommendation: Hybrid Stigmergy-Physarum Model

The strongest approach combines elements from all three:

1. **From Stigmergy:** Use explicit feedback (used/ignored/harmful) as the primary signal for edge strengthening and weakening. This is the only approach that directly maps to our existing `feedback()` MCP tool.

2. **From Physarum:** Use the positive-feedback flow model for co-retrieval-based edge creation. The Tero conductance equations are elegant and well-studied. The gamma parameter lets us tune redundancy.

3. **From Energy-Based:** Use system temperature to control exploration vs. exploitation. A new agentmemory instance creates edges liberally (high temperature). A mature instance is conservative (low temperature). This prevents early lock-in and late instability.

### Proposed Hybrid: "Mycelium" Edge Dynamics

```python
@dataclass
class MyceliumConfig:
    """Configuration for bio-inspired edge dynamics."""
    # Physarum parameters
    flow_exponent: float = 0.8       # gamma: <1 preserves redundancy
    decay_rate: float = 0.01         # alpha: conductance decay per hour

    # Stigmergy parameters
    evaporation_rate: float = 0.05   # rho: pheromone evaporation per hour
    deposit_used: float = 0.2        # pheromone for positive feedback
    deposit_coretrieval: float = 0.05
    anti_pheromone_ignored: float = -0.05
    anti_pheromone_harmful: float = -0.3

    # Energy parameters
    cooling_rate: float = 0.001      # how fast temperature drops
    t_initial: float = 1.0
    t_min: float = 0.1

    # Shared thresholds
    min_weight: float = 0.05         # below this, prune
    max_edges_per_belief: int = 15
    initial_weight: float = 0.3

class MyceliumEdgeManager:
    """Bio-inspired dynamic edge management.

    Combines:
    - Physarum: flow-based strengthening from co-retrieval
    - Stigmergy: feedback-driven pheromone deposit/anti-pheromone
    - Energy: temperature-controlled exploration schedule
    """

    def __init__(self, store: MemoryStore, config: MyceliumConfig | None = None):
        self.store = store
        self.cfg = config or MyceliumConfig()

    def temperature(self) -> float:
        """System temperature based on total feedback count."""
        n = self.store.total_feedback_count()
        return max(
            self.cfg.t_min,
            self.cfg.t_initial * math.exp(-self.cfg.cooling_rate * n),
        )

    def on_retrieval(
        self,
        query: str,
        retrieved: list[Belief],
        feedback_map: dict[str, str] | None = None,
    ) -> EdgeUpdateResult:
        """Core update: called after every search() + optional feedback.

        1. Co-retrieval pairs get Physarum flow-based strengthening
        2. Feedback pairs get stigmergy pheromone deposit
        3. New edges created with Boltzmann acceptance probability
        """
        T = self.temperature()
        created = 0
        strengthened = 0
        weakened = 0

        # --- Physarum: flow-based co-retrieval ---
        for i, a in enumerate(retrieved):
            for b in retrieved[i + 1:]:
                flow = self._compute_flow(query, a, b)
                edge = self.store.get_edge(a.id, b.id)

                if edge is None:
                    # Boltzmann acceptance: create with probability ~ T * flow
                    p_create = min(1.0, T * flow)
                    if (random.random() < p_create
                            and self._edge_count(a.id) < self.cfg.max_edges_per_belief):
                        self.store.insert_edge(
                            from_id=a.id, to_id=b.id,
                            edge_type="RELATES_TO",
                            weight=self.cfg.initial_weight * flow,
                            reason="mycelium_auto",
                        )
                        created += 1
                else:
                    # Physarum strengthening: conductance grows with flow
                    delta = flow ** self.cfg.flow_exponent * 0.1
                    new_w = min(1.0, edge.weight + delta)
                    self.store.update_edge_weight(edge.id, new_w)
                    strengthened += 1

        # --- Stigmergy: feedback-driven pheromone ---
        if feedback_map:
            for belief_id, outcome in feedback_map.items():
                neighbors = [b.id for b in retrieved if b.id != belief_id]
                for nid in neighbors:
                    edge = self.store.get_edge(belief_id, nid)
                    if edge is None:
                        continue
                    deposit = {
                        "used": self.cfg.deposit_used,
                        "ignored": self.cfg.anti_pheromone_ignored,
                        "harmful": self.cfg.anti_pheromone_harmful,
                    }.get(outcome, 0.0)
                    new_w = max(0.0, min(1.0, edge.weight + deposit))
                    self.store.update_edge_weight(edge.id, new_w)
                    if deposit > 0:
                        strengthened += 1
                    elif deposit < 0:
                        weakened += 1

        return EdgeUpdateResult(created, strengthened, weakened)

    def decay_and_prune(self, hours_elapsed: float) -> int:
        """Periodic maintenance: decay + prune low-weight edges.

        Combines Physarum conductance decay with stigmergy evaporation.
        Run at session start or on a timer.
        """
        pruned = 0
        evap_factor = (1 - self.cfg.evaporation_rate) ** hours_elapsed
        linear_decay = self.cfg.decay_rate * hours_elapsed

        for edge in self.store.get_edges_by_reason_prefix("mycelium_"):
            # Combined decay: multiplicative evaporation + linear conductance loss
            new_w = edge.weight * evap_factor - linear_decay
            if new_w < self.cfg.min_weight:
                self.store.delete_edge(edge.id)
                pruned += 1
            else:
                self.store.update_edge_weight(edge.id, new_w)
        return pruned

    def _compute_flow(self, query: str, a: Belief, b: Belief) -> float:
        """Physarum flow analog: product of query-relevance scores."""
        q_terms = extract_terms(query)
        rel_a = jaccard_similarity(q_terms, extract_terms(a.content))
        rel_b = jaccard_similarity(q_terms, extract_terms(b.content))
        return rel_a * rel_b

    def _edge_count(self, belief_id: str) -> int:
        """Count edges for a belief to enforce max_edges_per_belief."""
        rows = self.store.query(
            "SELECT COUNT(*) FROM edges WHERE from_id = ? OR to_id = ?",
            (belief_id, belief_id),
        )
        return int(rows[0][0]) if rows else 0
```

---

## 5. Implementation Roadmap

### Phase 1: Stigmergy Layer (lowest risk, highest signal)

**What:** Add pheromone tracking to existing edges. Hook into the existing `feedback()` MCP tool.

**Changes:**
- Add `pheromone REAL DEFAULT 0.0` column to edges table (or repurpose `weight` for mycelium-managed edges)
- Add `last_coretrieval TEXT` timestamp column
- Hook `on_retrieval()` into the search() code path in server.py
- Hook `evaporate_pheromone()` into session-start

**Risk:** Low. Additive change, does not modify existing edge creation logic.

### Phase 2: Physarum Co-Retrieval Edges

**What:** Automatically create RELATES_TO edges between co-retrieved beliefs that lack an existing edge.

**Changes:**
- Implement `on_retrieval()` co-retrieval edge creation
- Add `reason="mycelium_auto"` to distinguish from ingestion-time edges
- Add max_edges_per_belief cap
- Add periodic decay pass

**Risk:** Medium. Creates edges that did not exist before. Needs monitoring to ensure it does not create noise. The max_edges_per_belief cap is the safety valve.

### Phase 3: Temperature Schedule

**What:** Add system maturity tracking and temperature-based edge creation probability.

**Changes:**
- Track total feedback count (already available)
- Implement temperature function
- Gate new edge creation probability by temperature
- Implement periodic pruning of high-energy edges

**Risk:** Medium. The temperature schedule needs tuning. Start with conservative parameters (slow cooling, high min temperature).

### Phase 4: Evaluation

**What:** Measure whether mycelium edges improve retrieval precision.

**Metrics:**
- Retrieval precision before/after mycelium edges (A/B test)
- Edge survival rate: what fraction of auto-created edges survive 1 week?
- Graph density: does the mycelium layer create too many edges?
- Feedback loop closure: do mycelium edges get more "used" feedback than random?

---

## 6. Open Questions

1. **Should mycelium edges be typed?** Currently the sketch creates only RELATES_TO edges. Could co-retrieval patterns reveal SUPPORTS or CONTRADICTS relationships? Probably not without semantic analysis -- co-retrieval implies relatedness, not agreement or disagreement.

2. **Should mycelium edges be bidirectional?** The current edge model is directed. Co-retrieval is inherently symmetric (if A and B are co-retrieved, the relationship is mutual). Mycelium edges should probably be undirected (or always create both directions).

3. **How does this interact with HRR?** The HRR vocabulary bridge creates edges based on vector similarity. Mycelium creates edges based on usage patterns. These are complementary signals. An edge with both HRR support and mycelium reinforcement is very strong.

4. **What is the right evaporation rate?** Too fast and edges disappear before they can be confirmed. Too slow and the graph accumulates noise. The biological literature suggests rho = 0.01-0.1 for ant systems. We should start at 0.05 and tune.

5. **Should we track pheromone separately from weight?** An edge might have high ingestion-time weight (LLM-classified SUPPORTS) but zero pheromone (never co-retrieved). These are different signals. Keeping them separate allows richer scoring: `effective_weight = base_weight * (1 + pheromone)`.

---

## 7. Key Takeaways

1. **All three approaches converge on the same core idea:** edges should strengthen with use and weaken with disuse. The differences are in how "use" is measured and how "weakening" is implemented.

2. **Stigmergy is the best fit** for agentmemory because it directly maps to our existing feedback loop. The `feedback()` MCP tool is already a pheromone deposit mechanism -- we just need to propagate it to edges.

3. **Physarum provides the best mathematical foundation** for flow-based edge creation. The Tero equations are well-studied, convergence is proven, and the gamma parameter gives explicit control over the efficiency-redundancy tradeoff.

4. **Energy-based models provide the maturity schedule.** Temperature-controlled exploration prevents both early lock-in (too few edges when the system is new) and late instability (too many speculative edges when the system is mature).

5. **The hybrid is not complex.** The combined algorithm is ~100 lines of Python. The per-retrieval cost is O(k^2) where k is the result set size (typically <10). The periodic maintenance cost is O(E) which at 25K edges is trivial.

6. **The biological analogy is not just metaphor.** Mycelium networks genuinely solve the same problem we face: building and maintaining a transport network that balances efficiency, redundancy, and cost, without centralized control, using only local information (what flows through each edge).
