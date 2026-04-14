# Edge Dynamics: Evolutionary and Optimization Algorithms for Dynamic Graph Edge Management

**Date:** 2026-04-14
**Status:** Research complete -- design decisions pending
**Context:** agentmemory belief graph (~20K nodes, ~25K edges, 5 edge types). Edges are currently static after creation. This research surveys algorithms for making edges dynamic: created, strengthened, weakened, and pruned based on usage patterns.

---

## 1. Evolutionary Algorithms for Graph Structure

### 1.1 Genetic Algorithms for Graph Topology Optimization

**Core mechanism:** A population of candidate edge sets (genomes) evolves via selection, crossover, and mutation. Each genome encodes which edges exist and their weights. A fitness function evaluates graph quality. Over generations, the population converges toward high-fitness topologies.

**How it maps to belief graphs:** Each individual in the population represents a variant of the belief graph's edge set. Crossover swaps edge subsets between two parent graphs. Mutation adds, removes, or re-weights individual edges. Fitness measures retrieval quality, graph connectivity, or information-theoretic coherence.

**Genome encoding for 25K edges:**
```
Genome = bitstring of length |E_candidate|
  bit_i = 1 means edge_i is present
  Optional: append float per edge for weight
```

For a graph with N=20K nodes, the candidate edge set (all possible typed edges) is enormous. Practical approach: restrict candidates to edges between nodes sharing at least one token overlap or co-occurring in the same session. This reduces candidate set to ~100K-500K.

**Fitness function candidates (what makes a "good" edge set):**

| Fitness component | Formula sketch | What it measures |
|---|---|---|
| Retrieval precision | mean(relevant_in_top_k / k) over query log | Do edges help retrieve useful beliefs? |
| Graph coherence | mean edge weight * (1 - contradiction_ratio) | Are connected beliefs consistent? |
| Navigability | mean(shortest_path_length for sampled pairs) | Can you reach related beliefs quickly? |
| Parsimony penalty | -lambda * |E| | Prefer fewer, better edges |
| Community structure | modularity Q score | Are there meaningful clusters? |
| Temporal consistency | fraction of edges where newer belief supersedes older | Does time flow correctly? |

A multi-objective approach (NSGA-II) optimizing retrieval precision and parsimony simultaneously is recommended over single-objective. This avoids collapsing to either "no edges" or "all edges."

**Computational cost at 20K/25K:**
- Population of 50 individuals, each encoding 25K edge decisions: 50 * 25K = 1.25M bits per generation.
- Fitness evaluation is the bottleneck. If fitness requires running retrieval queries: ~100 queries * graph traversal per individual * 50 individuals = 5,000 traversals per generation.
- At 100 generations: 500K traversals total. With SQLite-backed traversal at ~1ms per query, this is ~8 minutes.
- Practical for offline/batch optimization (nightly). Not suitable for real-time.

**Algorithm sketch:**
```python
def evolve_edge_set(graph, query_log, generations=100, pop_size=50):
    population = [random_edge_subset(graph.candidate_edges) for _ in range(pop_size)]
    for gen in range(generations):
        fitness_scores = [evaluate_fitness(ind, query_log) for ind in population]
        parents = tournament_select(population, fitness_scores, k=3)
        offspring = []
        for p1, p2 in pairs(parents):
            child = uniform_crossover(p1, p2)  # swap edge inclusion bits
            child = mutate(child, rate=0.02)     # flip ~500 edges per mutation
            offspring.append(child)
        population = elitist_replace(population, offspring, fitness_scores, elite_frac=0.1)
    return best_individual(population)
```

**Strengths:** Explores a wide solution space. Handles multi-objective optimization well. No gradient required. Can optimize non-differentiable fitness functions (like retrieval precision from logged queries).

**Weaknesses:** Slow convergence. Requires an offline query log for fitness evaluation. The "genome" representation for 25K edges is manageable but not trivial. No incremental update -- must re-run when the graph changes significantly.

**Sources:**
- [Graph-Based Genetic Algorithms (EmergentMind)](https://www.emergentmind.com/topics/graph-based-genetic-algorithms-graph-ga) -- survey of GA applications to graph problems
- [Graph-based multi-objective GA (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S2352710225014354) -- NSGA-II for graph structure optimization
- [GA with round-robin tournament selection (PLOS One 2022)](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0274456) -- improved tournament selection for GA

### 1.2 NEAT-like Neuroevolution for Knowledge Graphs

**Core mechanism:** NEAT (NeuroEvolution of Augmenting Topologies) evolves both the topology and weights of neural networks simultaneously. It starts minimal and complexifies. Key innovations: historical markings (innovation numbers) for tracking homologous structures across crossover, speciation to protect structural innovations, and complexification from minimal starting topologies.

**How it maps to belief graphs:**
- **Innovation numbers** -> edge creation timestamps. Every edge gets a monotonic ID when created. During crossover of two graph variants, edges with matching IDs are aligned; non-matching edges are inherited from the fitter parent.
- **Speciation** -> maintain multiple "styles" of graph connectivity (dense local clusters vs. sparse long-range bridges). Protect novel edge patterns from being immediately eliminated.
- **Complexification** -> start with only high-confidence edges (SUPPORTS between beliefs with shared provenance). Incrementally add CONTRADICTS, RELATES_TO, and cross-cluster edges as the system observes retrieval patterns.

**Fitness function:** Same as GA above, but NEAT's incremental growth naturally enforces parsimony -- you only add complexity when it improves fitness.

**Computational cost:** Lower than full GA because populations start small and grow. With 20K nodes, initial genomes might encode only 5K-10K edges. But speciation tracking adds O(pop_size^2) distance calculations per generation. For pop=50, this is 1,250 distance calcs -- cheap.

**Algorithm sketch (adapted for belief graphs):**
```python
def neat_edge_evolution(graph, query_log):
    # Start with minimal edge set: only SUPPORTS edges with weight > 0.7
    initial_edges = graph.edges.filter(type="SUPPORTS", weight__gt=0.7)
    population = [Species(initial_edges) for _ in range(5)]  # 5 species
    
    for gen in range(generations):
        for species in population:
            for individual in species.members:
                # Structural mutations
                if random() < 0.1:  # Add edge
                    src, tgt = sample_candidate_pair(graph)
                    individual.add_edge(src, tgt, type=infer_type(src, tgt))
                if random() < 0.05:  # Remove edge
                    individual.remove_weakest_edge()
                # Weight mutations
                individual.perturb_weights(sigma=0.1)
            
            species.evaluate_fitness(query_log)
        
        # Speciation: group by structural similarity
        population = respeciate(population, threshold=3.0)
        # Reproduce within species
        population = reproduce_within_species(population)
```

**Strengths:** Incremental growth avoids bloat. Speciation preserves diverse graph structures. Historical markings enable meaningful crossover. Well-suited to our "start simple, add complexity" philosophy.

**Weaknesses:** Speciation adds implementation complexity. Distance function between two edge sets needs careful design (Hamming distance on edge bitstrings? Graph edit distance?). Original NEAT paper is from 2002; the core algorithm is mature but knowledge-graph-specific adaptations are novel/unproven.

**Sources:**
- [NEAT original paper (Stanley & Miikkulainen 2002, Evolutionary Computation)](https://nn.cs.utexas.edu/downloads/papers/stanley.ec02.pdf)
- [NEAT Wikipedia overview](https://en.wikipedia.org/wiki/Neuroevolution_of_augmenting_topologies)
- [NEAT algorithm blog (Lunatech 2024)](https://blog.lunatech.com/posts/2024-02-29-the-neat-algorithm-evolving-neural-network-topologies)

### 1.3 Memetic Algorithms: Evolution + Local Search

**Core mechanism:** Memetic algorithms (MAs) combine evolutionary global search with problem-specific local search. After each generation, offspring are improved by a local search operator before entering the next generation. This is "Lamarckian evolution" -- acquired improvements are inherited.

**How it maps to belief graphs:** The global EA explores different edge topologies. The local search refines a given topology by:
1. **Edge weight gradient descent:** For a fixed topology, optimize weights to maximize retrieval precision.
2. **Greedy edge swap:** For each edge, test if replacing it with a nearby candidate improves fitness. Accept improvements.
3. **Triangle completion:** If A->B and B->C exist, test adding A->C. This exploits transitivity.

**Computational cost:** The local search phase adds O(|E|) per individual per generation. With 25K edges and 50 individuals, that is 1.25M local search steps per generation. Each step is a single fitness delta evaluation (fast if incremental). Total: ~2-5 minutes per generation. Still offline-only.

**Algorithm sketch:**
```python
def memetic_edge_optimization(graph, query_log):
    population = evolutionary_init(graph, pop_size=30)
    for gen in range(50):
        # Global: standard GA operators
        offspring = crossover_and_mutate(population)
        # Local: improve each offspring
        for ind in offspring:
            ind = greedy_edge_swap(ind, graph, query_log, max_swaps=100)
            ind = optimize_weights(ind, query_log, steps=50)
        population = select_next_gen(population + offspring)
```

**Strengths:** Converges faster than pure GA. Local search exploits domain structure (transitivity, edge type constraints). The LLM-based memetic framework idea (using an LLM to suggest edge additions based on semantic analysis) is particularly relevant -- we already have LLM-generated beliefs and could use the LLM to suggest semantic edges.

**Weaknesses:** Local search design requires domain expertise. Risk of premature convergence if local search dominates. More complex to implement than pure GA.

**Sources:**
- [Memetic algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Memetic_algorithm)
- [Memetic and Reflective Evolution Framework with LLMs (MDPI 2025)](https://www.mdpi.com/2076-3417/15/15/8735)
- [Self-adaptive memetic algorithm (Scientific Reports 2025)](https://www.nature.com/articles/s41598-025-89289-2)
- [Hybrid optimization and ML survey (Springer 2023)](https://link.springer.com/article/10.1007/s10994-023-06467-x)

---

## 2. Reinforcement Learning for Edge Management

### 2.1 GNN + RL for Link Prediction

**Core mechanism:** A Graph Neural Network encodes the local neighborhood of node pairs into embeddings. An RL agent uses these embeddings as state and decides whether to add, remove, or re-weight edges. The reward signal comes from downstream task performance (retrieval quality).

**How it maps to belief graphs:** The GNN computes a representation of each belief that incorporates its neighbors' information. The RL policy network takes a (source, target, edge_type) triple and outputs an action: {create, strengthen, weaken, prune}. Reward = change in retrieval precision on the next N queries after the action.

**Computational cost:** GNN forward pass on 20K nodes with 25K edges: O(|E| * d) where d is embedding dimension. With d=64, this is ~1.6M multiply-adds per pass -- trivially fast. RL training requires thousands of episodes, each involving multiple GNN forward passes. Training budget: ~1-4 hours on CPU for convergence. Inference (deciding on a single edge action): <1ms.

**Algorithm sketch:**
```python
class EdgeRL:
    def __init__(self, gnn, policy_net):
        self.gnn = gnn          # 2-layer GCN, d=64
        self.policy = policy_net # MLP: 2*d -> 4 actions
    
    def decide_edge(self, src_id, tgt_id, graph):
        embeddings = self.gnn(graph)  # O(|E| * d)
        pair_repr = concat(embeddings[src_id], embeddings[tgt_id])
        action_probs = self.policy(pair_repr)  # create/strengthen/weaken/prune
        return sample(action_probs)
    
    def reward(self, action, query_log_window):
        # Measure retrieval quality change after action
        precision_before = evaluate_retrieval(query_log_window[-10:])
        apply_action(action)
        precision_after = evaluate_retrieval(query_log_window[-10:])
        return precision_after - precision_before
```

**Strengths:** Learns from actual usage patterns. Can operate online (one edge decision per query). GNN captures graph structure for informed decisions. Recent work (2024-2025) on dynamic link prediction with GNNs is mature.

**Weaknesses:** Requires a reward signal, which means we need query logs with relevance labels. Sparse reward problem -- most edge changes have minimal immediate impact. Training instability typical of RL. Adds a neural network dependency to a currently pure-Python/SQLite system.

**Sources:**
- [GNN + RL survey (IntechOpen)](https://www.intechopen.com/chapters/87170)
- [Link prediction with reinforced neighborhood selection (Springer 2025)](https://link.springer.com/chapter/10.1007/978-981-95-3462-3_16)
- [Survey of GNN methods for dynamic link prediction (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/pii/S1877050925007938)
- [Dynamic link prediction with GCN (Scientific Reports 2024)](https://www.nature.com/articles/s41598-023-50977-6)

### 2.2 Multi-Armed Bandit for Edge Selection

**Core mechanism:** Each candidate edge is an "arm" in a bandit problem. Pulling an arm = using that edge during retrieval. Reward = whether the traversal through that edge led to a relevant result. Over time, edges with high reward rates are strengthened; edges that never pay off are pruned.

**How it maps to belief graphs:** When a query arrives, the retrieval system must decide which edges to traverse. Instead of traversing all edges from a matched node, it selects a subset using bandit logic. Each edge maintains a reward distribution. Edges that consistently lead to useful beliefs accumulate reward; edges that lead to irrelevant beliefs accumulate penalty.

This is the most natural fit for agentmemory because we already use Thompson sampling for belief confidence scoring. Extending it to edges is a direct generalization.

**Computational cost:** O(|E_local|) per query, where |E_local| is the number of edges from matched nodes. Typically 5-20 edges per matched node. Sampling from Beta distributions: ~microseconds per edge. Essentially free at query time.

**Algorithm sketch:**
```python
class EdgeBandit:
    """Each edge maintains Beta(alpha, beta) for Thompson sampling."""
    
    def select_edges(self, node_id, k=5):
        edges = graph.edges_from(node_id)
        samples = []
        for edge in edges:
            # Thompson sample from edge's Beta distribution
            score = beta_sample(edge.alpha, edge.beta)
            samples.append((score, edge))
        return top_k(samples, k)
    
    def update(self, edge, was_useful: bool):
        if was_useful:
            edge.alpha += 1   # success
        else:
            edge.beta += 1    # failure
    
    def prune_threshold(self):
        """Remove edges where P(useful) < threshold with high confidence."""
        for edge in graph.edges:
            mean = edge.alpha / (edge.alpha + edge.beta)
            n = edge.alpha + edge.beta
            if mean < 0.1 and n > 20:  # low reward after sufficient trials
                graph.soft_delete_edge(edge)
```

**Strengths:** Minimal computational overhead. Natural extension of existing Thompson sampling. No neural network dependency. Online learning -- improves with every query. Mathematically principled exploration-exploitation tradeoff. Pruning has a clear criterion (posterior probability of usefulness).

**Weaknesses:** Treats edges independently -- ignores that edges interact (a path through edges A and B might be useful even if neither alone is). Cold start: new edges have no data. Reward attribution is noisy -- if a 3-hop path finds a useful result, which edges get credit?

**Sources:**
- [KABB: Knowledge-Aware Bayesian Bandits (arXiv 2025)](https://arxiv.org/html/2502.07350v2) -- Thompson sampling with knowledge distance penalties
- [Thompson sampling tutorial (Stanford)](https://web.stanford.edu/~bvr/pubs/TS_Tutorial.pdf)
- [Dynamic Prior Thompson Sampling (arXiv 2026)](https://arxiv.org/html/2602.00943) -- prior design for cold-start arms

### 2.3 Contextual Bandits: Query-Aware Edge Selection

**Core mechanism:** Extends the bandit approach by conditioning edge selection on the query context. The "context" is the query embedding; the "arms" are candidate edges. A linear model predicts which edges are valuable for which types of queries. An edge might be useful for debugging queries but not for architecture queries.

**How it maps to belief graphs:** When a retrieval query arrives, its embedding is computed. For each candidate edge, the expected reward is: `E[reward] = context^T * edge_feature_vector`. The edge feature vector encodes: edge type, endpoint confidence scores, temporal recency, past reward history. The system learns which edge features predict usefulness for which query types.

**Computational cost:** Linear contextual bandit: O(d^2) per arm per step for LinUCB, where d is context dimension. With d=64 (query embedding) and ~20 candidate edges per query: 20 * 64^2 = ~80K multiply-adds per query. Trivially fast.

**Algorithm sketch:**
```python
class ContextualEdgeBandit:
    """LinUCB-style contextual bandit for edge selection."""
    
    def __init__(self, d=64):
        # Per-edge-type parameters (5 edge types)
        self.A = {etype: np.eye(d) for etype in EDGE_TYPES}      # d x d
        self.b = {etype: np.zeros(d) for etype in EDGE_TYPES}     # d
    
    def select_edges(self, query_embedding, candidate_edges, alpha=0.5):
        scores = []
        for edge in candidate_edges:
            etype = edge.type
            theta = np.linalg.solve(self.A[etype], self.b[etype])
            x = self.featurize(query_embedding, edge)
            ucb = x @ theta + alpha * np.sqrt(x @ np.linalg.solve(self.A[etype], x))
            scores.append((ucb, edge))
        return top_k(scores, k=5)
    
    def update(self, query_embedding, edge, reward):
        x = self.featurize(query_embedding, edge)
        etype = edge.type
        self.A[etype] += np.outer(x, x)
        self.b[etype] += reward * x
    
    def featurize(self, query_emb, edge):
        """Combine query context with edge features."""
        edge_feat = np.array([
            edge.alpha / (edge.alpha + edge.beta),  # historical reward rate
            edge.source.confidence,
            edge.target.confidence,
            days_since(edge.created_at),
            EDGE_TYPE_ONEHOT[edge.type]
        ])
        return np.concatenate([query_emb[:32], edge_feat])  # truncate query for efficiency
```

**Strengths:** Query-aware -- different queries use different edges. Learns edge-type-level patterns ("CONTRADICTS edges are useful for verification queries"). Sublinear regret guarantees (O(d * sqrt(T * log(T)))). Still lightweight enough for online use.

**Weaknesses:** Requires query embeddings at retrieval time (we may already compute these). The featurization is manual and may miss interactions. Matrix inversion per query can be cached but adds bookkeeping.

**Sources:**
- [Scalable contextual bandits survey (arXiv 2025)](https://arxiv.org/html/2505.16918v1)
- [Thompson sampling for contextual bandits (arXiv 2024)](https://arxiv.org/html/2402.10289)
- [Multi-objective linear contextual bandit (arXiv 2025)](https://arxiv.org/pdf/2512.00930)

---

## 3. Dynamic Graph Algorithms

### 3.1 Temporal Knowledge Graphs and Edge Lifecycle

**Core mechanism:** Temporal Knowledge Graphs (TKGs) represent facts as quadruples (subject, relation, object, timestamp) instead of static triples. Each edge has a temporal scope: `valid_from` and `valid_to`. Edge lifecycle stages: creation (inferred or explicit), active period (participates in reasoning), decay (confidence decreases with age), archival/pruning (no longer participates but retained for provenance).

**How it maps to belief graphs:** Our beliefs already have `created_at`. Adding `valid_until` and `last_accessed` to edges enables lifecycle management:
- **Creation:** When a new belief is ingested, edges to related beliefs are proposed by the classification pipeline.
- **Active:** Edge participates in retrieval. Usage is tracked.
- **Decay:** Edge weight decreases via `weight * exp(-lambda * days_since_last_access)`.
- **Pruning:** Edge is soft-deleted when decayed weight falls below threshold and has not been accessed in N days.

**DynTKG approach (2025):** Combines dynamic subgraph pruning with causal-aware knowledge distillation. The subgraph pruning selects relevant temporal neighborhoods around query entities, reducing the graph to a manageable subgraph for reasoning. This directly applies to our retrieval: instead of traversing the full graph, prune to a query-relevant temporal subgraph.

**DERP approach (2025):** Dynamic Evolution and Relation Perception captures how relations between entities change over time, modeling edge evolution as a sequence of states rather than static properties.

**Computational cost:** Adding temporal metadata to edges: O(1) per edge, negligible storage. Temporal decay computation during retrieval: O(|E_local|) per query. Periodic pruning sweep: O(|E|) -- scan all edges, soft-delete decayed ones. At 25K edges, this takes <100ms.

**Algorithm sketch:**
```python
class TemporalEdgeManager:
    def decay_weight(self, edge):
        days_idle = (now() - edge.last_accessed).days
        edge.weight *= exp(-self.decay_rate * days_idle)
        if edge.weight < self.prune_threshold:
            edge.status = 'archived'
    
    def access(self, edge):
        edge.last_accessed = now()
        edge.access_count += 1
        # Reinforce: slightly increase weight on access
        edge.weight = min(1.0, edge.weight + self.reinforce_delta)
    
    def periodic_sweep(self):
        """Run nightly. Decay unused edges, prune dead ones."""
        for edge in graph.all_edges():
            self.decay_weight(edge)
        pruned = graph.edges.filter(status='archived').count()
        return pruned
    
    def propose_new_edges(self, new_belief):
        """When a belief is ingested, propose edges to related beliefs."""
        candidates = semantic_search(new_belief.content, top_k=10)
        for candidate in candidates:
            edge_type = infer_edge_type(new_belief, candidate)
            if edge_type and not graph.edge_exists(new_belief.id, candidate.id):
                graph.add_edge(new_belief.id, candidate.id, 
                             type=edge_type, weight=0.5, status='active')
```

**Strengths:** Simple, interpretable lifecycle model. Low computational cost. Aligns with existing `created_at` metadata. Decay + reinforcement creates a natural "use it or lose it" dynamic. Pruning reduces graph bloat over time.

**Weaknesses:** Decay rate is a hyperparameter that needs tuning. Pure temporal decay ignores semantic importance -- a rarely-accessed but critical edge (e.g., a correction) should not decay. Need exemption rules for locked/correction edges.

**Sources:**
- [Temporal Graph Learning in 2024 (Towards Data Science)](https://towardsdatascience.com/temporal-graph-learning-in-2024-feaa9371b8e2/)
- [DynTKG: Dynamic subgraph pruning (Springer 2025)](https://link.springer.com/article/10.1007/s44443-025-00105-3)
- [DERP: Dynamic Evolution and Relation Perception (MDPI 2025)](https://www.mdpi.com/1999-5903/18/1/3)
- [Temporal reasoning over evolving KGs (arXiv 2025)](https://arxiv.org/html/2509.15464v1)
- [Awesome Dynamic Graph Learning (GitHub)](https://github.com/SpaceLearner/Awesome-DynamicGraphLearning)

### 3.2 Graph Coarsening and Refinement

**Core mechanism:** Graph coarsening reduces a large graph to a smaller one while preserving key structural properties (spectral, community, cut). The coarsened graph is easier to operate on. After optimization, the solution is projected back (refinement/uncoarsening) to the original graph. This is the "V-cycle" of multigrid methods applied to graphs.

**How it maps to belief graphs:** As agentmemory grows, retrieval over 20K+ nodes becomes slower. Coarsening creates a "summary graph" where groups of related beliefs are collapsed into supernodes. Retrieval first operates on the coarsened graph (fast), then refines within the matched supernode's members (precise).

**UGC (Universal Graph Coarsening, NeurIPS 2024):** Works on both homophilic and heterophilic graphs. Uses node features + adjacency information. 4x-15x faster than prior methods with lower spectral error. Directly applicable to belief graphs where some clusters are tightly connected (homophilic) and others represent contradictions (heterophilic).

**AH-UGC (2025):** Extends UGC with Locality-Sensitive Hashing for adaptive coarsening. Type-aware design preserves semantics in heterogeneous graphs -- relevant since our graph has multiple node types (beliefs, observations, tests).

**Computational cost:** UGC on 20K nodes: O(|E| * log|V|) per coarsening level. With 25K edges: ~25K * 14 = 350K operations per level. 3-4 levels of coarsening: ~1-1.5M operations. Runs in <1 second.

**Louvain+ refinement:** The uncoarsening phase revisits each community structure and refines it, optimizing modularity at each level. O(|E|) per refinement pass.

**Algorithm sketch:**
```python
class BeliefGraphCoarsener:
    def coarsen(self, graph, levels=3):
        """Create hierarchy of increasingly coarse graphs."""
        hierarchy = [graph]
        for level in range(levels):
            coarse = self.merge_similar_nodes(hierarchy[-1])
            hierarchy.append(coarse)
        return hierarchy
    
    def merge_similar_nodes(self, graph):
        """Merge nodes connected by strong SUPPORTS/RELATES_TO edges."""
        pairs = graph.edges.filter(
            type__in=["SUPPORTS", "RELATES_TO"],
            weight__gt=0.6
        ).order_by("-weight")
        merged = {}
        for edge in pairs:
            if edge.source not in merged and edge.target not in merged:
                supernode = create_supernode(edge.source, edge.target)
                merged[edge.source] = supernode
                merged[edge.target] = supernode
        return rebuild_graph(graph, merged)
    
    def hierarchical_retrieval(self, query, hierarchy):
        """Search coarse graph first, then refine."""
        # Level 3 (coarsest): find relevant supernodes
        candidates = search(hierarchy[-1], query, top_k=5)
        # Expand supernodes to original nodes
        expanded = [node for sn in candidates for node in sn.members]
        # Level 0 (original): re-rank within expanded set
        return rerank(expanded, query, top_k=10)
```

**Strengths:** Dramatically speeds up retrieval on large graphs. Preserves structural properties. The hierarchy can be precomputed and updated incrementally. Natural fit for "drill-down" retrieval patterns.

**Weaknesses:** Coarsening can lose fine-grained distinctions. CONTRADICTS edges between merged nodes create ambiguity. Needs periodic re-coarsening as the graph evolves. Not directly about edge dynamics -- more about efficient retrieval.

**Sources:**
- [UGC: Universal Graph Coarsening (NeurIPS 2024)](https://nips.cc/virtual/2024/poster/93695)
- [AH-UGC: Adaptive Heterogeneous Graph Coarsening (arXiv 2025)](https://arxiv.org/html/2505.15842)
- [Graph Coarsening with Preserved Spectral Properties (Semantic Scholar)](https://www.semanticscholar.org/paper/Graph-Coarsening-with-Preserved-Spectral-Properties-Jin-Loukas/8fa88f223e646e92bba7ec40ea088603023b8fa1)
- [Awesome Graph Reduction (GitHub, IJCAI 2024)](https://github.com/Emory-Melody/awesome-graph-reduction)
- [Featured Graph Coarsening (ICML 2023)](https://proceedings.mlr.press/v202/kumar23a/kumar23a.pdf)

### 3.3 Spectral Methods for Edge Addition/Removal

**Core mechanism:** The graph Laplacian L = D - A (degree matrix minus adjacency matrix) encodes global structure. Its eigenvalues reveal:
- **Algebraic connectivity** (second-smallest eigenvalue, lambda_2): measures how well-connected the graph is. If lambda_2 drops, the graph is becoming disconnected.
- **Spectral gap** (gap between eigenvalue clusters): reveals the number of natural communities.
- **Fiedler vector** (eigenvector of lambda_2): indicates which edges, if removed, would most disconnect the graph (critical bridges).

**How it maps to belief graphs:**
- **Edge importance:** Compute how much removing each edge changes lambda_2. Edges where removal barely affects connectivity are candidates for pruning.
- **Missing edge detection:** If two nodes are in the same spectral cluster (similar Fiedler vector components) but have no edge, an edge might be missing.
- **Community evolution:** Track the spectral gap over time. If the gap shrinks, communities are dissolving -- edges might need restructuring.

**Computational cost:** Full eigendecomposition of 20K x 20K Laplacian: O(N^3) = 8 * 10^12 operations. This is prohibitively expensive. However:
- **Sparse Laplacian** (only 25K nonzero entries): iterative methods (Lanczos) compute top-k eigenvalues in O(|E| * k * iterations). For k=10 and 100 iterations: 25K * 10 * 100 = 25M operations. Runs in <1 second.
- **Incremental updates:** When one edge changes, eigenvalues shift by a rank-1 perturbation. Can be approximated without recomputation.

**Algorithm sketch:**
```python
class SpectralEdgeAnalyzer:
    def compute_edge_importance(self, graph):
        """Rank edges by their contribution to algebraic connectivity."""
        L = graph.laplacian(sparse=True)
        eigenvalues, eigenvectors = sparse_eigsh(L, k=10, which='SM')
        fiedler = eigenvectors[:, 1]  # second eigenvector
        
        importance = {}
        for edge in graph.edges:
            # Edge importance proportional to difference in Fiedler values
            importance[edge.id] = abs(fiedler[edge.source] - fiedler[edge.target])
        return importance
    
    def suggest_new_edges(self, graph, threshold=0.05):
        """Nodes with similar Fiedler values but no edge."""
        L = graph.laplacian(sparse=True)
        _, eigvecs = sparse_eigsh(L, k=5, which='SM')
        
        suggestions = []
        for i, j in candidate_pairs(graph):
            spectral_dist = np.linalg.norm(eigvecs[i] - eigvecs[j])
            if spectral_dist < threshold and not graph.has_edge(i, j):
                suggestions.append((i, j, spectral_dist))
        return sorted(suggestions, key=lambda x: x[2])
    
    def detect_community_drift(self, graph, prev_eigenvalues):
        """Compare current spectral gap to previous."""
        eigenvalues = compute_top_k_eigenvalues(graph, k=10)
        gap_change = spectral_gap(eigenvalues) - spectral_gap(prev_eigenvalues)
        if abs(gap_change) > self.drift_threshold:
            return True  # communities are restructuring
        return False
```

**Strengths:** Mathematically grounded. Global perspective -- captures structure that local methods miss. Edge importance ranking is principled. Community drift detection is useful for triggering re-optimization.

**Weaknesses:** Even sparse eigendecomposition is more expensive than bandit methods. "Missing edge" detection via spectral clustering produces many false positives. Spectral methods assume smooth community structure -- CONTRADICTS edges violate this assumption. Best used as an occasional diagnostic, not real-time.

**Sources:**
- [Spectral Graph Theory for Community Detection (ResearchGate 2025)](https://www.researchgate.net/publication/396605863_SPECTRAL_GRAPH_THEORY_FOR_COMMUNITY_DETECTION_IN_LARGE-SCALE_SOCIAL_NETWORKS_A_MATHEMATICAL_FRAMEWORK)
- [Advancements in Spectral Graph Theory (Physics Journal 2025)](https://www.physicsjournal.net/archives/2025/vol7issue1/PartB/7-1-21-336.pdf)
- [Comprehensive Review of Community Detection (arXiv 2024)](https://arxiv.org/html/2309.11798v4)
- [Spectral Graph Theory course notes (UW 2024)](https://homes.cs.washington.edu/~jrl/cse422wi24/notes/spectral-graph-theory.html)

### 3.4 Adaptive Community Detection

**Core mechanism:** Standard community detection (Louvain, Leiden) partitions a graph into modules. Adaptive variants track how communities change over time and use those changes to inform edge decisions: strengthen intra-community edges, weaken inter-community edges that don't serve as bridges.

**How it maps to belief graphs:** Run community detection periodically. Each community represents a cluster of related beliefs (e.g., "Python project preferences", "architecture decisions for module X"). When communities shift (a belief moves from one community to another), this signals that edges should be re-evaluated.

**Louvain+ (2024):** Adds an uncoarsening-refinement phase that revisits community assignments at each level. Better quality than standard Louvain.

**Computational cost:** Louvain on 20K nodes / 25K edges: O(|E| * log|V|) per pass, typically 3-5 passes. Total: ~25K * 14 * 5 = 1.75M operations. Runs in <100ms.

**Sources:**
- [Multilevel community detection strategy (Springer 2025)](https://link.springer.com/chapter/10.1007/978-3-032-15984-7_14)
- [n-HDP-GNN: Bayesian community detection for GNNs (Springer 2025)](https://link.springer.com/article/10.1007/s11227-025-08017-9)

---

## 4. Self-Organizing Maps and Competitive Learning

### 4.1 Kohonen SOMs for Knowledge Organization

**Core mechanism:** A Self-Organizing Map is a grid of neurons where each neuron has a weight vector in the same space as the input data. Input vectors are presented one at a time. The closest neuron (Best Matching Unit, BMU) and its grid neighbors update their weights toward the input. Over time, the grid organizes so that similar inputs activate nearby neurons, creating a topology-preserving map of the input space.

**How it maps to belief graphs:** Beliefs are embedded as vectors (we may use HRR or sentence embeddings). A 2D SOM grid organizes beliefs by semantic similarity. Grid adjacency implies semantic relatedness. This provides an alternative edge structure: instead of explicit typed edges, edges are implied by grid proximity.

**For edge management specifically:**
- **Edge suggestion:** If two beliefs map to adjacent SOM cells but have no explicit edge, suggest one.
- **Edge validation:** If two beliefs have an explicit edge but map to distant SOM cells, the edge may be spurious.
- **Cluster boundaries:** Neurons with high quantization error sit at cluster boundaries -- edges crossing these boundaries are inter-cluster bridges.

**DBGSOM (2024):** Directed Batch Growing SOM uses batch learning to control growth, adding neurons only where error accumulates. This avoids the fixed-grid limitation. For belief graphs, DBGSOM would start with a small map and grow it as beliefs are ingested, naturally creating a dynamic topology.

**Computational cost:** Training SOM on 20K vectors with d=64: O(N * grid_size * d) per epoch. With a 50x50 grid (2,500 neurons), 100 epochs: 20K * 2500 * 64 * 100 = 320 billion operations. Too expensive. Mitigation: use batch SOM with mini-batches, reducing to ~3.2B operations (~5-10 minutes on modern CPU). For DBGSOM, the growing approach starts small and is more practical.

**Algorithm sketch:**
```python
class BeliefSOM:
    def __init__(self, grid_size=30):
        self.grid = np.random.randn(grid_size, grid_size, 64)  # 30x30 grid, d=64
        self.belief_map = {}  # belief_id -> (row, col)
    
    def train(self, beliefs, epochs=50):
        for epoch in range(epochs):
            lr = 0.5 * (1 - epoch / epochs)
            radius = self.grid.shape[0] / 2 * (1 - epoch / epochs)
            for belief in shuffle(beliefs):
                vec = belief.embedding
                bmu = self.find_bmu(vec)
                self.update_neighborhood(bmu, vec, lr, radius)
                self.belief_map[belief.id] = bmu
    
    def suggest_edges(self, graph):
        """Beliefs on adjacent cells without edges."""
        suggestions = []
        for b1_id, (r1, c1) in self.belief_map.items():
            for b2_id, (r2, c2) in self.belief_map.items():
                if abs(r1-r2) + abs(c1-c2) == 1:  # grid neighbors
                    if not graph.has_edge(b1_id, b2_id):
                        suggestions.append((b1_id, b2_id))
        return suggestions
    
    def validate_edges(self, graph):
        """Flag edges between beliefs on distant cells."""
        suspicious = []
        for edge in graph.edges:
            r1, c1 = self.belief_map[edge.source]
            r2, c2 = self.belief_map[edge.target]
            dist = abs(r1-r2) + abs(c1-c2)
            if dist > 5:  # distant on map but connected
                suspicious.append(edge)
        return suspicious
```

**Strengths:** Provides a global view of belief organization. Topology preservation gives meaningful proximity. Edge suggestions grounded in semantic similarity. Visualization potential -- plot the SOM to see where belief clusters are.

**Weaknesses:** Computational cost for large grids. Fixed grid topology may not match belief structure. SOM training is offline and must be redone as new beliefs arrive (unless using growing SOM). Does not directly manage edges -- provides signals that other algorithms act on.

**Sources:**
- [Survey on Recent Advances in SOMs (arXiv 2025)](https://arxiv.org/html/2501.08416v1)
- [DBGSOM details in survey](https://arxiv.org/html/2501.08416v1)
- [SOM Wikipedia](https://en.wikipedia.org/wiki/Self-organizing_map)

### 4.2 Growing Neural Gas for Incremental Graph Construction

**Core mechanism:** Growing Neural Gas (GNG) starts with two nodes and incrementally adds nodes and edges as data is presented. Unlike SOMs, GNG has no fixed grid -- the topology emerges from the data. Edges are created between the BMU and second-BMU for each input. Edges have an "age" counter. Old edges are pruned. Nodes with no edges are removed.

**How it maps to belief graphs:** Each belief is an input. GNG nodes represent cluster centroids. GNG edges represent "these clusters are adjacent in the input space." The natural age-based edge pruning directly implements "use it or lose it" dynamics.

**Key properties for agentmemory:**
- **Incremental:** New beliefs are ingested one at a time. No batch retraining needed.
- **Edge aging:** Every step, all edges increment age. When a belief reinforces an edge (it falls near both endpoints), the edge age resets to 0. Edges that reach max_age are deleted. This naturally prunes stale connections.
- **Node insertion:** Every N steps, a new node is inserted near the node with highest accumulated error. This creates finer resolution where beliefs are dense.

**Computational cost:** Per input: O(|V_gng|) for BMU search + O(|E_gng|) for edge aging. With |V_gng| ~1000 centroids and ~3000 edges: ~4000 operations per belief ingestion. Trivially fast.

**Algorithm sketch:**
```python
class BeliefGNG:
    def __init__(self, max_age=50, insert_interval=100):
        self.nodes = [random_node(), random_node()]
        self.edges = [Edge(self.nodes[0], self.nodes[1], age=0)]
        self.max_age = max_age
        self.step_count = 0
    
    def ingest_belief(self, belief_vec):
        # Find two nearest nodes
        bmu1, bmu2 = self.find_two_nearest(belief_vec)
        
        # Create or reset edge between them
        edge = self.find_edge(bmu1, bmu2)
        if edge:
            edge.age = 0  # reinforce
        else:
            self.edges.append(Edge(bmu1, bmu2, age=0))
        
        # Move BMU toward input
        bmu1.weight += 0.1 * (belief_vec - bmu1.weight)
        for neighbor in bmu1.neighbors():
            neighbor.weight += 0.01 * (belief_vec - neighbor.weight)
        
        # Age all edges from BMU
        for edge in bmu1.edges():
            edge.age += 1
        
        # Prune old edges
        self.edges = [e for e in self.edges if e.age < self.max_age]
        
        # Remove isolated nodes
        self.nodes = [n for n in self.nodes if n.degree() > 0]
        
        # Periodically insert new nodes
        self.step_count += 1
        if self.step_count % self.insert_interval == 0:
            worst = max(self.nodes, key=lambda n: n.error)
            worst_neighbor = max(worst.neighbors(), key=lambda n: n.error)
            new_node = Node(weight=(worst.weight + worst_neighbor.weight) / 2)
            self.nodes.append(new_node)
            self.edges.append(Edge(new_node, worst, age=0))
            self.edges.append(Edge(new_node, worst_neighbor, age=0))
            self.remove_edge(worst, worst_neighbor)
    
    def map_to_belief_edges(self, beliefs, graph):
        """Transfer GNG topology to belief graph edges."""
        for gng_edge in self.edges:
            beliefs_at_src = self.beliefs_near(gng_edge.source)
            beliefs_at_tgt = self.beliefs_near(gng_edge.target)
            for b1 in beliefs_at_src:
                for b2 in beliefs_at_tgt:
                    if not graph.has_edge(b1.id, b2.id):
                        graph.suggest_edge(b1.id, b2.id, type="RELATES_TO")
```

**Strengths:** Truly incremental -- no batch reprocessing. Natural edge lifecycle (creation, aging, pruning). Topology emerges from data distribution. Computationally lightweight. No hyperparameter grid size -- grows organically.

**Weaknesses:** Operates on embeddings, not the belief graph directly. Requires mapping GNG topology back to belief edges (lossy). Does not handle typed edges -- all GNG edges are undirected proximity. Does not capture contradiction or supersession relationships. Best used as a complement to typed-edge systems, not a replacement.

**Sources:**
- [GNG original paper (Fritzke 1995, NIPS)](https://dl.acm.org/doi/10.5555/2998687.2998765)
- [GNG learns topologies (ResearchGate)](https://www.researchgate.net/publication/4202425_An_incremental_growing_neural_gas_learns_topologies)

### 4.3 Adaptive Resonance Theory for Stable-Yet-Plastic Knowledge

**Core mechanism:** ART addresses the stability-plasticity dilemma: how to learn new patterns without forgetting old ones. The key is the "vigilance parameter" -- a threshold that controls when to create a new category vs. assimilate input into an existing one. High vigilance = many fine-grained categories (plastic). Low vigilance = few coarse categories (stable).

**How it maps to belief graphs:**
- **Category formation** = creating clusters of related beliefs with edges between them.
- **Vigilance test** = when a new belief arrives, check if it's "close enough" to an existing cluster. If yes, add it and create edges. If no, create a new cluster.
- **Stability** = existing belief clusters and their internal edges are preserved even as new clusters form.
- **Plasticity** = new clusters and cross-cluster edges can form for genuinely novel information.

**TopoART:** Combines ART with topology-learning (growing neural gas), adding noise reduction. Two-layer architecture: Layer A (vigilance = 0.9, fine-grained) for detailed belief clustering. Layer B (vigilance = 0.6, coarse) for topic-level clustering. Only beliefs that persist in Layer A long enough are promoted to Layer B, filtering noise.

**Computational cost:** Vigilance test: O(d) per belief per cluster. With 100 clusters and d=64: 6,400 operations per ingested belief. Cluster maintenance: O(|clusters|) per step. Extremely lightweight.

**Algorithm sketch:**
```python
class BeliefART:
    def __init__(self, vigilance=0.8, d=64):
        self.vigilance = vigilance
        self.clusters = []  # each cluster: (centroid, member_ids, internal_edges)
    
    def ingest_belief(self, belief, graph):
        vec = belief.embedding
        best_match = None
        best_similarity = 0
        
        for cluster in self.clusters:
            sim = cosine_similarity(vec, cluster.centroid)
            if sim > best_similarity:
                best_match = cluster
                best_similarity = sim
        
        if best_similarity >= self.vigilance:
            # Resonance: assimilate into existing cluster
            best_match.add_member(belief.id)
            best_match.update_centroid(vec)
            # Create edges to existing cluster members
            for member_id in best_match.member_ids[-5:]:  # last 5 members
                graph.add_edge(belief.id, member_id, type="RELATES_TO", weight=best_similarity)
        else:
            # Mismatch: create new cluster
            new_cluster = Cluster(centroid=vec, member_ids=[belief.id])
            self.clusters.append(new_cluster)
            # Create cross-cluster bridge to nearest cluster
            if best_match:
                bridge_target = best_match.most_similar_member(vec)
                graph.add_edge(belief.id, bridge_target, type="RELATES_TO", weight=best_similarity)
    
    def adapt_vigilance(self, feedback):
        """Increase vigilance if clusters are too coarse (retrievals imprecise).
           Decrease if too fine (retrievals miss related beliefs)."""
        if feedback.precision < 0.5:
            self.vigilance = min(0.95, self.vigilance + 0.02)
        elif feedback.recall < 0.5:
            self.vigilance = max(0.5, self.vigilance - 0.02)
```

**Strengths:** Directly addresses stability-plasticity. No catastrophic forgetting -- old clusters are preserved. Vigilance parameter provides a single knob for granularity. Computationally cheap. Adaptive vigilance closes the loop with retrieval quality feedback.

**Weaknesses:** Vigilance tuning is critical and fragile. Category proliferation risk at high vigilance. Does not natively handle typed edges (CONTRADICTS, SUPERSEDES). Cluster centroids may not represent any actual belief (centroid drift). Ordering effects -- results depend on ingestion order.

**Sources:**
- [Adaptive Resonance Theory (Wikipedia)](https://en.wikipedia.org/wiki/Adaptive_resonance_theory)
- [ART introduction (Missouri S&T)](https://scholarsmine.mst.edu/cgi/viewcontent.cgi?article=1173&context=comsci_facwork)
- [Stability-plasticity dilemma in continual learning (EmergentMind)](https://www.emergentmind.com/topics/stability-plasticity-dilemma)
- [IMCGNN: Incremental continual graph learning (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/abs/pii/S0925231225000347)
- [Continual learning and catastrophic forgetting survey (arXiv 2024)](https://arxiv.org/html/2403.05175v1)

---

## 5. Synthesis and Recommendations for agentmemory

### 5.1 Approach Comparison Matrix

| Approach | Online? | Typed edges? | Compute cost | Impl. complexity | Fits existing arch? |
|---|---|---|---|---|---|
| GA for topology | No (batch) | Yes | High (minutes) | Medium | Partial |
| NEAT-like evolution | No (batch) | Yes | Medium | High | Partial |
| Memetic (GA + local) | No (batch) | Yes | High | High | Partial |
| GNN + RL | Semi (train offline, infer online) | Yes | Medium-High | High | Low (needs PyTorch) |
| Multi-armed bandit | Yes (per query) | Partial | Very low | Low | High |
| Contextual bandit | Yes (per query) | Yes | Low | Medium | High |
| Temporal lifecycle | Yes (per access) | Yes | Very low | Low | High |
| Graph coarsening | No (periodic) | Partial | Low | Medium | Medium |
| Spectral methods | No (periodic) | No | Medium | Medium | Medium |
| Community detection | No (periodic) | Partial | Low | Low | Medium |
| SOM | No (batch) | No | High | Medium | Low |
| Growing Neural Gas | Yes (per ingestion) | No | Very low | Medium | Medium |
| ART | Yes (per ingestion) | Partial | Very low | Medium | Medium |

### 5.2 Recommended Architecture: Layered Edge Dynamics

Given agentmemory's constraints (SQLite-backed, no PyTorch dependency, online operation preferred, existing Thompson sampling), a layered approach is recommended:

**Layer 1 -- Temporal Lifecycle (always on):**
- Every edge gets `last_accessed`, `access_count`, `decay_weight`.
- On retrieval traversal: update `last_accessed` and `access_count`.
- Nightly sweep: decay unused edges, archive dead ones.
- Exempt locked beliefs and correction edges from decay.
- **Cost:** Negligible. **Complexity:** Low. **Priority:** Implement first.

**Layer 2 -- Thompson Sampling Edge Bandit (always on):**
- Every edge gets `alpha`, `beta` for Beta distribution.
- On retrieval: select edges via Thompson sampling instead of traversing all.
- On feedback ("used" or "ignored"): update alpha/beta.
- Prune edges with low posterior mean after sufficient trials.
- **Cost:** Negligible. **Complexity:** Low. **Priority:** Implement second. Natural extension of existing belief-level Thompson sampling.

**Layer 3 -- ART-based Ingestion (per belief):**
- On belief ingestion: vigilance test against existing clusters.
- Create intra-cluster RELATES_TO edges automatically.
- Create cross-cluster bridge edges for novel beliefs.
- Adaptive vigilance based on retrieval feedback.
- **Cost:** Very low. **Complexity:** Medium. **Priority:** Third.

**Layer 4 -- Spectral Diagnostics (weekly batch):**
- Compute Fiedler vector and spectral gap.
- Identify critical bridge edges (high Fiedler difference).
- Detect community drift.
- Suggest missing edges between spectrally-close beliefs.
- **Cost:** Low (sparse Lanczos). **Complexity:** Medium. **Priority:** Fourth, after Layers 1-3 are proven.

**Layer 5 -- Evolutionary Refinement (optional, monthly):**
- GA or memetic optimization of the full edge set.
- Uses accumulated query logs as fitness oracle.
- Produces a "refined" edge set that replaces the current one.
- **Cost:** High (minutes). **Complexity:** High. **Priority:** Only if Layers 1-4 are insufficient.

### 5.3 Schema Changes Required

```sql
ALTER TABLE mem_edges ADD COLUMN last_accessed TEXT;
ALTER TABLE mem_edges ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE mem_edges ADD COLUMN alpha REAL DEFAULT 1.0;
ALTER TABLE mem_edges ADD COLUMN beta REAL DEFAULT 1.0;
ALTER TABLE mem_edges ADD COLUMN status TEXT DEFAULT 'active';  -- active, decayed, archived
```

### 5.4 Key Design Decisions Still Needed

1. **Reward attribution for multi-hop paths:** When a 3-hop traversal finds a useful result, which edges get credit? Options: all edges in the path (simplest), inverse-distance weighting, or only the last edge.
2. **Decay rate tuning:** What is the half-life for edge decay? Depends on belief volatility. Factual beliefs may need slower decay than procedural ones.
3. **Locked edge exemptions:** Should edges involving locked beliefs be exempt from decay? Probably yes, but this needs validation.
4. **Edge creation trigger:** Currently edges are created only at ingestion time. Should retrieval patterns trigger new edge creation? (e.g., if belief A and belief B are frequently co-retrieved but have no edge, create one.)
5. **Contradiction handling:** CONTRADICTS edges should never be pruned by disuse. They represent active conflicts that need resolution, not stale information.

---

## 6. Implementation Roadmap

1. **Phase 1 (Temporal Lifecycle):** Add schema columns. Implement access tracking in retrieval. Implement nightly decay sweep. ~1 day of work.
2. **Phase 2 (Edge Bandit):** Add alpha/beta columns. Modify retrieval to use Thompson sampling for edge selection. Implement feedback loop from existing `mcp__agentmemory__feedback`. ~2 days.
3. **Phase 3 (ART Ingestion):** Implement vigilance-based clustering. Integrate into belief ingestion pipeline. ~3 days.
4. **Phase 4 (Spectral Diagnostics):** Add scipy.sparse dependency. Implement Fiedler vector computation. Build diagnostic CLI command. ~2 days.
5. **Phase 5 (Evolutionary Refinement):** Design fitness function from query logs. Implement GA with NSGA-II. Build offline optimization script. ~5 days.

Total estimated effort: ~13 days for all five layers. Layers 1-2 alone deliver 80% of the value.
