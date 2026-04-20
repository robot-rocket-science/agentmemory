# Energy-Balance and Thermodynamic Models for Knowledge Graph Edge Dynamics

**Date:** 2026-04-14
**Status:** Research complete -- design proposal included
**Context:** agentmemory graph (~20K beliefs, ~25K edges). The intuition: information into the system is energy, and the algorithm binds things together based on an energy balance metric.

---

## 1. Thermodynamic Models of Information

### 1.1 Landauer's Principle

Landauer's principle (1961) establishes the minimum energy cost of irreversible information processing: erasing one bit of information dissipates at least `kT ln 2` joules of heat, where `k` is Boltzmann's constant and `T` is temperature.

**Mathematical formulation:**

```
Q >= kT ln 2  (per bit erased)
```

This sets a hard floor: destroying information is never free. For a knowledge graph, the analog is that pruning an edge (erasing the relationship) has a minimum cost -- the system must expend computational effort to determine the edge is safe to remove, and doing so irreversibly loses the encoded relationship.

**Implication for agentmemory:** Edge pruning should not be treated as zero-cost garbage collection. Each pruned edge represents lost structure. The system should only prune when the energy cost of maintaining the edge (storage, traversal noise, retrieval pollution) exceeds the Landauer-analog cost of erasing it.

Recent experimental work (2025) has confirmed Landauer's bound in quantum many-body regimes, and a comprehensive review notes that real systems operating far from equilibrium may break the classical bound -- relevant because agentmemory is an open, far-from-equilibrium system receiving continuous input.

**Sources:**
- [Landauer's Principle: Past, Present and Future (MDPI Entropy, 2025)](https://www.mdpi.com/1099-4300/27/4/437)
- [Experimentally probing Landauer's principle in quantum many-body regime (Nature Physics, 2025)](https://www.nature.com/articles/s41567-025-02930-9)
- [Fundamental energy cost of finite-time computing (Nature Communications, 2023)](https://www.nature.com/articles/s41467-023-36020-2)

### 1.2 Maxwell's Demon and Information-Theoretic Work

Maxwell's demon (1867) appears to violate the second law of thermodynamics by sorting fast and slow molecules using information. The resolution: the demon must erase its memory to complete the cycle, and that erasure dissipates at least `kT ln 2` per bit (Landauer's principle). The demon converts information into work, but accounting for memory erasure restores the second law.

**The information engine cycle:**

```
1. Measure system state (acquire information)
2. Apply feedback control (extract work using information)
3. Erase measurement record (pay Landauer cost)
```

**Direct analog for agentmemory:**

| Demon Operation | agentmemory Operation |
|---|---|
| Measure molecule velocity | Classify incoming belief (Haiku pipeline) |
| Sort molecule into chamber | Route belief to correct category + create edges |
| Extract work from temperature difference | Retrieve relevant beliefs (useful work) |
| Erase demon's memory | Prune stale edges + compact beliefs |

The system acts as an information engine: it acquires information (ingestion), sorts it (classification + edge creation), extracts work (retrieval), and must periodically pay the erasure cost (pruning). The key insight is that the sorting step is where energy is spent -- edge creation IS the work being done.

Recent quantum Maxwell's demon experiments show that work can be extracted directly from the measurement process itself, without a thermal bath. This maps to the idea that the act of classifying a belief (the "measurement") directly produces useful structure (edges) as a byproduct.

**Sources:**
- [Information-to-work conversion by Maxwell's demon (Nature Communications, 2018)](https://www.nature.com/articles/s41467-018-03686-y)
- [Extracting work from quantum measurement in Maxwell demon engines (PRL, 2017)](https://arxiv.org/abs/1702.01917)

### 1.3 Free Energy Principle (Friston)

Karl Friston's Free Energy Principle (FEP) states that self-organizing systems minimize variational free energy -- a tractable upper bound on surprise (negative log-evidence). The system maintains an internal generative model and updates it to minimize the divergence between predicted and observed states.

**Mathematical formulation:**

```
F = E_q[ln q(z) - ln p(o, z)]
  = D_KL[q(z) || p(z|o)] - ln p(o)
  >= -ln p(o)

Where:
  F = variational free energy
  q(z) = approximate posterior (recognition density)
  p(o, z) = generative model (joint over observations and hidden causes)
  D_KL = Kullback-Leibler divergence
  p(o) = model evidence (marginal likelihood)
```

Minimizing F simultaneously:
1. Makes the approximate posterior closer to the true posterior (accuracy)
2. Maximizes model evidence (the generative model explains observations well)

**Application to agentmemory:** The belief graph IS the generative model. Edges encode the system's model of how beliefs relate. When a new observation arrives, the system should update edges (minimize free energy) to make the graph better predict future retrievals. Edges that reduce prediction error (improve retrieval relevance) lower free energy and should be strengthened. Edges that increase prediction error (lead to irrelevant retrievals) raise free energy and should be weakened.

The variational free energy decomposition maps directly:

```
F_edge = Complexity - Accuracy

Complexity = cost of maintaining the edge (storage, traversal time, noise)
Accuracy  = improvement in retrieval relevance attributable to this edge
```

An edge is justified when its accuracy contribution exceeds its complexity cost.

**Sources:**
- [Free Energy Principle (Wikipedia)](https://en.wikipedia.org/wiki/Free_energy_principle)
- [Bayesian brain computing and the free-energy principle (NSR, 2024)](https://academic.oup.com/nsr/article/11/5/nwae025/7571549)
- [Generalised free energy and active inference (Biological Cybernetics, 2019)](https://link.springer.com/article/10.1007/s00422-019-00805-w)

### 1.4 Active Inference for Knowledge Graph Maintenance

Active inference extends FEP: the system not only updates beliefs passively but actively seeks observations that reduce expected free energy. This has two components:

```
G = E_q[ln q(z) - ln p(o, z)]  (expected free energy)
  = Epistemic Value + Pragmatic Value
  = Information Gain + Expected Utility
```

For agentmemory, active inference means the system should:
- **Epistemic actions:** Seek observations that resolve uncertainty about edge validity (e.g., test whether two co-retrieved beliefs are actually related)
- **Pragmatic actions:** Seek observations that improve retrieval quality (e.g., reinforce edges that led to successful retrievals)

This maps to the existing feedback loop: `feedback(belief_id, "used")` is a pragmatic signal that the edge structure works; `feedback(belief_id, "harmful")` is an epistemic signal that the model is wrong.

**Sources:**
- [Active Inference and Epistemic Value in Graphical Models (Frontiers, 2022)](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2022.794464/full)
- [Reframing the Expected Free Energy (arXiv, 2024)](https://arxiv.org/pdf/2402.14460)

### 1.5 Two Kinds of Free Energy

An important distinction: thermodynamic free energy (Helmholtz: `F = U - TS`) and variational free energy (Friston: `F = D_KL + surprise`) are formally analogous but not identical. The Helmholtz machine (Dayan, Hinton, Neal, Zemel) bridges them -- it uses variational methods inspired by statistical mechanics to perform approximate Bayesian inference.

For agentmemory, we want to use the variational formulation (it is computationally tractable) but borrow intuitions from the thermodynamic formulation (it gives physical meaning to "temperature", "entropy", "equilibrium").

**Sources:**
- [The two kinds of free energy and the Bayesian revolution (PLOS Comp Bio, 2020)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7714236/)

---

## 2. Energy-Based Models for Graphs

### 2.1 Graph Energy

The energy of a graph `G` is defined as the sum of absolute values of eigenvalues of its adjacency matrix:

```
E(G) = sum(|lambda_i|)  for i = 1..n

Where A * v_i = lambda_i * v_i  (eigendecomposition of adjacency matrix)
```

For a weighted graph (like agentmemory's edge structure), this generalizes to the singular values of the weighted adjacency matrix. Graph energy correlates with structural complexity -- a graph with more and stronger edges has higher energy.

**Implications:**
- Adding an edge increases graph energy (energy input)
- Removing an edge decreases graph energy (energy dissipation)
- The graph energy gives a single scalar measuring "how connected" the belief network is
- Tracking graph energy over time shows whether the system is accumulating or dissipating structure

**Computational cost:** For agentmemory's 25K edges, computing full eigendecomposition of the adjacency matrix at every step is prohibitive. But we can track approximate graph energy using:
- Trace of A^2 (sum of squared eigenvalues, O(|E|) to compute)
- Spectral radius (largest eigenvalue, computable via power iteration)
- Local energy contributions (sum of edge weights per node)

**Sources:**
- [Graph Energy (Wolfram MathWorld)](https://mathworld.wolfram.com/GraphEnergy.html)
- [Graph Eigenvalue (Wolfram MathWorld)](https://mathworld.wolfram.com/GraphEigenvalue.html)

### 2.2 Ising Model on Graphs

The Ising model assigns binary spins (+1 or -1) to nodes, with an energy function:

```
H = -sum_{(i,j) in E} J_ij * s_i * s_j - sum_i h_i * s_i

Where:
  s_i in {-1, +1}  (spin of node i)
  J_ij              (coupling strength between nodes i and j)
  h_i               (external field on node i)
```

The system evolves toward configurations that minimize H. Aligned spins (s_i = s_j) on positive-coupling edges (J_ij > 0) lower energy. The partition function `Z = sum_s exp(-beta * H(s))` governs the probability of each configuration at inverse temperature beta.

**Mapping to agentmemory:**

| Ising Concept | agentmemory Analog |
|---|---|
| Spin s_i = +1/-1 | Belief is active/inactive (above/below confidence threshold) |
| Coupling J_ij | Edge weight between beliefs |
| External field h_i | Direct evidence for belief i (retrieval feedback) |
| Temperature T = 1/beta | System activity level (retrievals per session) |
| Ground state | Optimal edge configuration for retrieval quality |

At low temperature (low activity), the system freezes into a fixed configuration. At high temperature (many retrievals and updates), the system explores many configurations. The phase transition between ordered and disordered states corresponds to the point where edge structure either crystallizes or melts.

**Sources:**
- [Ising model (Wikipedia)](https://en.wikipedia.org/wiki/Ising_model)
- [Ising's roots and the transfer-matrix eigenvalues (arXiv, 2024)](https://arxiv.org/pdf/2405.05703)

### 2.3 Potts Model for Community Structure

The Potts model generalizes Ising from binary spins to q-state spins, making it natural for community detection. The Hamiltonian for community detection is:

```
H_Potts = -sum_{(i,j) in E} [A_ij - gamma * (k_i * k_j) / (2m)] * delta(sigma_i, sigma_j)

Where:
  A_ij = adjacency matrix
  gamma = resolution parameter
  k_i = degree of node i
  m = total edges
  sigma_i = community assignment of node i
  delta = Kronecker delta (1 if same community, 0 otherwise)
```

Minimizing this Hamiltonian finds community structure. The resolution parameter gamma controls granularity -- higher gamma finds smaller communities. The Constant Potts Model (CPM) variant avoids the resolution-limit problem in modularity-based methods.

**Application to agentmemory:** Beliefs naturally cluster into topic communities. The Potts model gives a principled way to:
- Detect belief clusters (potential for edge densification within clusters)
- Identify inter-cluster bridges (high-value edges connecting different topics)
- Set resolution parameters for multi-scale community structure

**Sources:**
- [Local resolution-limit-free Potts model for community detection (ResearchGate)](https://www.researchgate.net/publication/44610654_Local_resolution-limit-free_Potts_model_for_community_detection)
- [Unsupervised community detection with a Potts Model Hamiltonian (arXiv, 2020)](https://arxiv.org/abs/2002.01599)
- [From Leiden to Pleasure Island: CPM as a hedonic game (ScienceDirect, 2025)](https://www.sciencedirect.com/science/article/abs/pii/S0378437125006417)

### 2.4 Restricted Boltzmann Machines for Graph Generation

RBMs define an energy function over visible and hidden units:

```
E(v, h) = -sum_i a_i * v_i - sum_j b_j * h_j - sum_{i,j} v_i * W_ij * h_j

P(v, h) = exp(-E(v, h)) / Z
```

The bipartite structure (no intra-layer connections) makes inference tractable. Training via contrastive divergence learns the weight matrix W that captures the data distribution.

**Application to agentmemory:** An RBM-like model could learn the latent structure of edge patterns. Visible units = observed edge presence/absence. Hidden units = latent topic/relationship factors. The learned energy landscape would predict which edges "should" exist based on the overall pattern, enabling:
- Link prediction (suggest missing edges)
- Anomaly detection (flag edges that are energetically unfavorable)
- Edge generation (propose new edges based on learned distribution)

**Practical concern:** Full RBM training on 25K edges is tractable but adds ML infrastructure. A lighter approach: use the energy function concept without full RBM training -- define energy directly from observable features.

**Sources:**
- [Restricted Boltzmann machine (Wikipedia)](https://en.wikipedia.org/wiki/Restricted_Boltzmann_machine)
- [Multiview Graph Restricted Boltzmann Machines (PubMed, 2021)](https://pubmed.ncbi.nlm.nih.gov/34166216/)

### 2.5 Hopfield Networks and Associative Memory

Hopfield networks (1982, Nobel Prize 2024) define an energy function for associative memory:

```
E = -0.5 * sum_{i,j} w_ij * s_i * s_j

Where:
  w_ij = connection weight between units i and j (symmetric)
  s_i = state of unit i
```

The network evolves by flipping units to lower energy, converging to local minima that correspond to stored patterns. Modern Hopfield networks (Ramsauer et al., 2020) replace the quadratic energy with exponential interactions, dramatically increasing storage capacity.

**Graph Hopfield Networks (2025):** Recent work introduces Graph Hopfield Networks that couple associative memory retrieval with graph Laplacian smoothing:

```
E_GraphHopfield = E_associative + lambda * x^T * L * x

Where:
  L = graph Laplacian
  x = node features
  lambda = coupling strength
```

This is directly relevant: it combines content-based memory retrieval (Hopfield) with graph-structure-based smoothing (Laplacian), which is exactly what agentmemory does when it retrieves beliefs and then walks graph edges.

**Sources:**
- [Graph Hopfield Networks: Energy-Based Node Classification with Associative Memory (arXiv, 2025)](https://arxiv.org/abs/2603.03464)
- [Sparse Quantized Hopfield Network for online-continual memory (Nature Communications, 2024)](https://www.nature.com/articles/s41467-024-46976-4)
- [Modern Hopfield Networks (Wikipedia)](https://en.wikipedia.org/wiki/Modern_Hopfield_network)

### 2.6 Energy-Based Contrastive Learning for Link Prediction

Recent work on knowledge graph completion uses energy-based contrastive learning:

```
L = E_pos[E(h, r, t)] - E_neg[E(h', r, t')]

Where:
  E(h, r, t) = energy of a triple (head, relation, tail)
  Positive triples should have LOW energy
  Negative (corrupted) triples should have HIGH energy
```

The EIFCL model (2024) uses explicit and implicit feature contrastive learning for knowledge graph link prediction, capturing semantic associations through both visible and latent features.

**Application:** This gives a training signal for edge weights. Edges that connect genuinely related beliefs (confirmed by retrieval feedback) should have low energy. Edges connecting unrelated beliefs should have high energy. The contrastive setup naturally handles the feedback loop: "used" feedback = positive sample, "harmful" feedback = negative sample.

**Sources:**
- [Explicit and Implicit Feature Contrastive Learning for KG Link Prediction (PMC, 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11598061/)
- [Improving KG Embeddings through Contrastive Learning with Negative Statements (ACM, 2025)](https://dl.acm.org/doi/10.1145/3731443.3771343)

---

## 3. Dissipative Structures (Prigogine)

### 3.1 Order from Energy Flow in Open Systems

Ilya Prigogine's dissipative structure theory (Nobel Prize, 1977) explains how order emerges in open systems far from thermodynamic equilibrium. The key conditions:

1. **Open system:** Continuous inflow and outflow of energy/matter
2. **Far from equilibrium:** The system is driven away from thermal equilibrium by external gradients
3. **Nonlinear dynamics:** Feedback loops amplify fluctuations
4. **Symmetry breaking:** Small fluctuations can push the system into qualitatively new ordered states

The entropy production rate has two components:

```
dS/dt = dS_internal/dt + dS_exchange/dt

dS_internal/dt >= 0  (always, by second law)
dS_exchange/dt < 0   (possible, via energy inflow from environment)

Net order increases when |dS_exchange/dt| > dS_internal/dt
```

**Application to agentmemory:** The belief graph is a dissipative structure:

| Prigogine Concept | agentmemory Analog |
|---|---|
| Energy inflow | New beliefs arriving (ingestion, user corrections) |
| Matter inflow | Raw text being classified into structured beliefs |
| Entropy production | Edge disorder -- wrong edges, stale edges, redundant edges |
| Entropy export | Edge pruning, belief compaction (removes disorder) |
| Dissipative structure | The emergent edge topology -- clusters, hierarchies, temporal chains |
| Far-from-equilibrium | Continuous sessions with active retrieval and feedback |

The system maintains its ordered edge structure ONLY because energy (new information) continuously flows through it. If ingestion stops, the graph gradually decays toward maximum entropy (all edges equally likely, no useful structure). This is exactly the "stale edge" problem.

**Sources:**
- [Self-Organization in Nonequilibrium Systems (Nicolis & Prigogine, 1977)](https://www.amazon.com/Self-Organization-Nonequilibrium-Systems-Dissipative-Fluctuations/dp/0471024015)
- [Self-organizing systems: what, how, and why? (npj Complexity, 2025)](https://www.nature.com/articles/s44260-025-00031-5)
- [Dissipative structures in biological systems (Phil Trans A, 2017)](https://royalsocietypublishing.org/doi/10.1098/rsta.2017.0376)

### 3.2 Edge of Criticality and Self-Organized Criticality

Self-organized criticality (SOC) describes systems that naturally project-j toward a critical state -- the boundary between order and chaos -- without external tuning. Classic examples: sandpiles (Bak, Tang, Wiesenfeld 1987), earthquakes, neural avalanches.

At criticality, the system exhibits:
- **Power-law distributions** in event sizes (many small events, rare large events)
- **Long-range correlations** (local changes propagate globally)
- **Maximum information transfer** (the system is most responsive to inputs)

**Application to agentmemory:** A knowledge graph at criticality would have:
- Power-law degree distribution (many low-degree beliefs, few hubs)
- Avalanche-like updates (one correction cascades through related beliefs)
- Maximum retrieval sensitivity (small query changes lead to meaningfully different results)

The practical question is whether agentmemory's graph naturally evolves toward criticality, or whether we need to tune parameters (edge creation threshold, pruning aggressiveness) to push it there. SOC suggests that with the right dynamics (add edges when information arrives, prune edges that are not reinforced), the system will self-tune to the critical point.

**Sources:**
- [Self-organized criticality (Wikipedia)](https://en.wikipedia.org/wiki/Self-organized_criticality)

---

## 4. Metabolic Network Analogy

### 4.1 Beliefs as Metabolites, Edges as Reactions

In metabolic networks, metabolites are transformed by enzyme-catalyzed reactions. The stoichiometric matrix S encodes which metabolites are consumed and produced by each reaction:

```
S * v = 0  (steady-state constraint)

Where:
  S = stoichiometric matrix (m metabolites x n reactions)
  v = flux vector (rate of each reaction)
```

**Mapping:**

| Metabolic Concept | agentmemory Analog |
|---|---|
| Metabolite | Belief |
| Reaction | Edge traversal (retrieving one belief leads to another) |
| Enzyme | Edge type (SUPPORTS, CONTRADICTS, CITES...) |
| Flux | Traversal frequency (how often an edge is actually used) |
| Stoichiometric matrix | Adjacency matrix with edge type annotations |
| Steady state (Sv = 0) | Balanced information flow (no belief accumulates unreachable) |

### 4.2 Flux Balance Analysis for Information Flow

FBA finds the flux distribution that optimizes an objective function subject to stoichiometric and capacity constraints:

```
Maximize: c^T * v           (objective: e.g., maximize retrieval quality)
Subject to: S * v = 0       (mass balance at each node)
            v_min <= v <= v_max  (capacity constraints)
```

**Adapted for agentmemory:**

```
Maximize: sum(retrieval_quality_i * v_i)   (maximize useful retrievals)
Subject to:
  For each belief b: sum(inflow edges) >= sum(outflow edges)  (reachability)
  v_i >= 0                                                     (directed flow)
  v_i <= capacity_i                                            (edge bandwidth)
```

This gives a principled way to identify:
- **Bottleneck edges:** Edges at maximum capacity (heavily used, high value)
- **Dead-end paths:** Beliefs with inflow but no outflow (unreachable sinks)
- **Redundant edges:** Edges carrying zero flux (could be pruned without loss)

The Normalised Flow Graph (NFG) representation is particularly relevant: it converts FBA results into a directed graph where edge weights represent the probability that a randomly chosen metabolite flows along that edge. For agentmemory, this translates to: given a random retrieval, what is the probability that edge (i,j) is traversed?

**Sources:**
- [What is Flux Balance Analysis? (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3108565/)
- [Flux-dependent graphs for metabolic networks (npj Systems Biology, 2018)](https://www.nature.com/articles/s41540-018-0067-y)
- [A Graph-Based Approach to Analyze Flux-Balanced Pathways (ResearchGate)](https://www.researchgate.net/publication/315454682_A_Graph-Based_Approach_to_Analyze_Flux-Balanced_Pathways_in_Metabolic_Networks)

### 4.3 Pathway Optimization as Edge Selection

Metabolic pathway analysis identifies essential pathways (elementary flux modes) -- minimal sets of reactions that can operate at steady state. The analog for agentmemory: identify the minimal edge sets that sustain retrieval quality.

If a set of edges forms an "elementary retrieval mode" -- a minimal subgraph that supports a class of queries -- then those edges are essential and should never be pruned. Edges not part of any elementary mode are candidates for pruning.

---

## 5. Temporal Edge Dynamics: Decay, Pruning, and Maintenance

### 5.1 Temporal Pruning in Dynamic Graphs

Recent work on dynamic graph maintenance is directly applicable:

**Time-decay Hawkes process (DynTKG, 2025):** Uses a Hawkes process to weight historical events, with recent interactions weighted more heavily:

```
lambda(t) = mu + sum_{t_i < t} alpha * exp(-beta * (t - t_i))

Where:
  mu = base rate
  alpha = excitation from past events
  beta = decay rate
```

**STEP framework:** Self-supervised temporal pruning removes edges based on temporal relevance rather than uniform random sampling. Edges are scored by a combination of recency, frequency, and structural importance.

**Application to agentmemory:** Edge energy should decay with a Hawkes-like process -- each traversal "excites" the edge (increases energy), and energy decays exponentially between traversals. Edges whose energy falls below a threshold are pruned.

**Sources:**
- [Dynamic subgraph pruning and causal-aware knowledge distillation for temporal KGs (Springer, 2025)](https://link.springer.com/article/10.1007/s44443-025-00105-3)
- [Less Can Be More: Unsupervised Graph Pruning for Large-scale Dynamic Graphs (arXiv, 2023)](https://arxiv.org/pdf/2305.10673)
- [Temporal decay algorithms for retention in real-time knowledge graphs (Graphiti/Zep, 2025)](https://github.com/getzep/graphiti/issues/1300)

---

## 6. Concrete Energy Model for agentmemory

### 6.1 Definitions

**Energy (E_edge):** A scalar value associated with each edge, representing its "vitality" -- how alive and useful the connection is. Measured in dimensionless units. Ranges from 0 (dead) to unbounded positive (highly active).

```python
E_edge = w_retrieval * R + w_feedback * F + w_cooccurrence * C + w_recency * D(t)

Where:
  R = retrieval count (times this edge was traversed during search)
  F = net feedback score (sum of +1 for "used", -1 for "harmful", 0 for "ignored")
  C = co-occurrence count (times both endpoints appeared in the same retrieval set)
  D(t) = temporal decay factor = exp(-lambda * (t_now - t_last_traversal))
  w_* = tunable weights (start with w_retrieval=1.0, w_feedback=2.0, w_cooccurrence=0.5, w_recency=1.0)
```

**Temperature (T):** System activity level. Measured as retrievals per unit time (e.g., per session or per hour).

```python
T = searches_performed / session_duration

# Or more precisely, an exponential moving average:
T_new = alpha * T_measured + (1 - alpha) * T_old
```

At high temperature (many searches), the system is "hot" -- edges form and break rapidly. At low temperature (few searches), the system is "cold" -- the edge structure is frozen.

**Entropy (S):** Disorder in the edge structure. Measured as the Shannon entropy of the edge weight distribution, normalized:

```python
S = -sum(p_i * ln(p_i))

Where p_i = E_i / sum(E_j)  (normalized edge energies as a probability distribution)
```

High entropy = all edges have similar energy (no differentiation, maximum disorder). Low entropy = a few edges dominate (clear structure, low disorder).

**Free Energy (F):** The useful work the edge structure enables, minus the cost of maintaining it:

```python
F = U - T * S

Where:
  U = internal energy = sum of all edge energies (total "vitality")
  T = temperature (activity level)
  S = entropy (disorder)
```

Minimizing F (as in thermodynamics) means: at low temperature, minimize U (prune weak edges, strengthen strong ones). At high temperature, maximize S (keep many edges to handle diverse queries). This naturally adapts behavior to usage patterns.

### 6.2 Edge Lifecycle

**Formation (crystallization):**

```
Two beliefs co-retrieved in search result
  -> Potential energy stored (co-occurrence count incremented)
  -> If co-occurrence >= threshold (e.g., 3 times):
     -> Edge crystallizes (inserted into edges table)
     -> Initial energy = w_cooccurrence * C
     -> Edge type inferred from content similarity + belief types
```

This mirrors nucleation in physical systems -- random co-occurrences don't immediately create structure, but repeated co-occurrences indicate a real relationship and trigger edge formation.

**Strengthening (energy injection):**

```
Edge traversed during retrieval:
  -> R += 1
  -> E_edge recalculated
  -> D(t) reset (t_last_traversal = now)

Positive feedback received:
  -> F += 1
  -> E_edge recalculated
```

Each use injects energy into the edge, counteracting decay.

**Decay (energy dissipation):**

```
Every session (or every N hours):
  For each edge:
    D(t) = exp(-lambda * (t_now - t_last_traversal))
    E_edge recalculated with new D(t)

    If E_edge < E_prune_threshold:
      Mark edge for pruning review
```

The decay rate lambda controls how quickly unused edges lose energy. A reasonable starting point: lambda = ln(2) / half_life, where half_life = 30 sessions (an edge unused for 30 sessions loses half its recency energy).

**Pruning (Landauer cost):**

```
Edge marked for pruning:
  1. Check if edge is part of an "elementary retrieval mode" (essential for some query class)
  2. If essential: boost energy by E_essential_bonus, skip pruning
  3. If not essential:
     a. Record edge in pruning log (Landauer cost -- we spend computation to decide)
     b. Soft-delete edge (retain in archive for potential recovery)
     c. After archive_ttl: hard-delete
```

### 6.3 Equilibrium Dynamics

The system reaches equilibrium when edge creation rate equals edge decay rate:

```
dE_total/dt = E_input - E_dissipation = 0

E_input = sum of energy from new edges + energy from traversals + energy from feedback
E_dissipation = sum of energy lost to temporal decay + energy removed by pruning
```

At equilibrium:
- The edge count stabilizes (not growing unboundedly, not shrinking to zero)
- The edge energy distribution stabilizes (same entropy level)
- Retrieval quality stabilizes (same precision/recall)

If the system is out of equilibrium:
- **E_input > E_dissipation:** Edge count grows, graph becomes denser, retrieval may become noisier (too many edges dilute signal). Response: increase lambda (faster decay) or raise pruning threshold.
- **E_dissipation > E_input:** Edge count shrinks, graph becomes sparser, retrieval may miss connections. Response: decrease lambda (slower decay) or lower co-occurrence threshold for new edges.

### 6.4 Phase Transitions

The system exhibits phase-transition-like behavior at critical temperatures:

**Low temperature (idle system):**
- Few retrievals, minimal feedback
- Temporal decay dominates
- Edges freeze in place (no energy to reorganize)
- Graph reflects historical state, not current utility

**High temperature (active use):**
- Many retrievals, frequent feedback
- Edge creation and decay both high
- Graph reorganizes rapidly
- Edge structure reflects current usage patterns

**Critical temperature (edge of criticality):**
- Balance between creation and decay
- Power-law degree distribution emerges
- Maximum retrieval sensitivity
- System adapts quickly but retains long-term structure

### 6.5 Implementation Plan

**Phase 1: Instrumentation (low cost, high information)**

Add columns to the edges table:

```sql
ALTER TABLE edges ADD COLUMN traversal_count INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN feedback_score INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN cooccurrence_count INTEGER DEFAULT 0;
ALTER TABLE edges ADD COLUMN last_traversed_at TEXT;
ALTER TABLE edges ADD COLUMN energy REAL DEFAULT 1.0;
```

Instrument the retrieval path to increment `traversal_count` and update `last_traversed_at` whenever an edge is used. Instrument the feedback path to update `feedback_score`.

**Phase 2: Energy computation (batch job)**

```python
def compute_edge_energy(edge: Edge, now: datetime, params: EnergyParams) -> float:
    """Compute current energy for an edge."""
    dt = (now - edge.last_traversed_at).total_seconds()
    decay = math.exp(-params.lambda_decay * dt / params.session_duration)

    return (
        params.w_retrieval * edge.traversal_count
        + params.w_feedback * edge.feedback_score
        + params.w_cooccurrence * edge.cooccurrence_count
        + params.w_recency * decay
    )
```

Run as a periodic batch job (every session start, or every N minutes during active use). Store computed energy in the `energy` column.

**Phase 3: Edge formation from co-occurrence**

Track co-retrieval events. When two beliefs appear in the same search result set N times, create a candidate edge. Score the candidate using content similarity (existing HRR infrastructure) and create the edge if the score exceeds a threshold.

**Phase 4: Pruning loop**

After energy computation, identify edges below the pruning threshold. Apply the Landauer check (is this edge essential?). Soft-delete non-essential low-energy edges. Log all pruning decisions for analysis.

**Phase 5: Temperature-adaptive parameters**

Compute system temperature from session activity. Adjust lambda and pruning thresholds based on temperature. At high temperature, be more aggressive about both creation and pruning (high flux). At low temperature, be conservative (preserve structure).

### 6.6 Thermodynamic Bookkeeping

Track these aggregate metrics per session:

```python
@dataclass
class ThermodynamicState:
    total_energy: float        # sum of all edge energies
    entropy: float             # Shannon entropy of energy distribution
    temperature: float         # retrievals per unit time
    free_energy: float         # total_energy - temperature * entropy
    edge_creation_rate: float  # new edges per unit time
    edge_pruning_rate: float   # pruned edges per unit time
    equilibrium_gap: float     # |creation_rate - pruning_rate| / max(creation_rate, pruning_rate)
```

When `equilibrium_gap` approaches zero, the system is at equilibrium. When it is large, the system is undergoing a phase transition (rapid growth or rapid pruning).

### 6.7 Connection to Existing Infrastructure

This model integrates with agentmemory's existing components:

| Existing Component | Energy Model Role |
|---|---|
| `store.insert_edge()` | Edge crystallization (set initial energy) |
| `store.get_neighbors()` | Edge traversal (increment traversal_count) |
| `server.feedback()` | Energy injection/extraction (update feedback_score) |
| `store.get_all_edge_triples()` | Bulk energy computation |
| HRR encode/decode | Content-based co-occurrence detection |
| Haiku classification pipeline | "Maxwell's demon" sorting incoming information |
| Bayesian confidence scores | Prior for edge energy (high-confidence beliefs = higher initial edge energy) |
| `models.Edge.weight` | Current weight field becomes the energy field (or energy is computed from weight + new columns) |

---

## 7. Summary of Theoretical Foundations

| Framework | Key Insight for agentmemory | Mathematical Tool |
|---|---|---|
| Landauer's Principle | Edge pruning has a minimum cost; don't prune carelessly | `Q >= kT ln 2` per erased bit |
| Maxwell's Demon | Classification + edge creation is work extracted from information | Information engine cycle |
| Free Energy Principle | Minimize prediction error = strengthen useful edges, weaken useless ones | `F = D_KL + surprise` |
| Active Inference | System should actively test uncertain edges | Expected free energy decomposition |
| Graph Energy | Track total "vitality" of the edge structure as a scalar | `E(G) = sum(abs(eigenvalues))` |
| Ising Model | Beliefs align/anti-align through edge interactions | `H = -sum J_ij s_i s_j` |
| Potts Model | Community structure emerges from energy minimization | Resolution-parameterized Hamiltonian |
| Hopfield Networks | Associative memory retrieval via energy minimization on graphs | Graph Hopfield energy function |
| Dissipative Structures | Order maintained only through continuous energy flow | `dS/dt = dS_internal + dS_exchange` |
| Self-Organized Criticality | System should self-tune to critical point for maximum sensitivity | Power-law degree distribution |
| Flux Balance Analysis | Identify essential vs redundant edges via flow analysis | `Sv = 0`, linear programming |
| Temporal Decay | Unused edges lose energy exponentially | Hawkes process / exponential decay |

---

## 8. Recommended Next Steps

1. **Instrument first, model second.** Add traversal counting and timestamp tracking to edges before building the energy model. Without usage data, any energy model is guesswork.

2. **Start with the simplest energy function.** The four-term model (retrieval + feedback + co-occurrence + recency decay) is sufficient for initial experiments. Do not add Ising/Potts/FBA complexity until the simple model proves insufficient.

3. **Measure the equilibrium gap.** Track edge creation and pruning rates. If the system naturally reaches equilibrium, the basic model works. If it oscillates or diverges, add temperature-adaptive parameters.

4. **Validate against retrieval quality.** The energy model is only useful if it improves retrieval. Run A/B tests: energy-weighted traversal vs. current weight-only traversal. Measure precision@k and mean reciprocal rank.

5. **Consider Graph Hopfield Networks** as the next-generation retrieval mechanism. The 2025 paper combining associative memory with graph Laplacian smoothing is architecturally close to what agentmemory already does.
