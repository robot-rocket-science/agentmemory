# Cross-Project Testing Plan: HRR + FTS5 + BFS

**Date:** 2026-04-09
**Purpose:** Use ~/projects/ as a diverse corpus to test graph construction, retrieval methods, and the HRR vocabulary bridge across different graph shapes, vocabulary patterns, and relationship densities.

---

## Why Multiple Projects Matter

All HRR experiments to date used one project (alpha-seek) with one graph shape: citation-heavy, explicit D### references, consistent vocabulary within a single domain (options trading). That graph is easy to construct (regex) and easy to search (FTS5 keywords overlap heavily).

The open question from HRR_FINDINGS.md: does HRR's value increase for graphs with heterogeneous edge types, sparse explicit references, vocabulary drift, and dense cross-cluster connections? We need different graph shapes to answer that.

---

## Project Inventory (ranked by test value)

### Tier 1: Rich graphs, high test value

| Project | Graph Shape | Why It's Interesting |
|---------|------------|---------------------|
| **gsd-2** | Citation graph with 7 edge types (CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES, CONCEPT_LINK, EVIDENCED_BY) | Already has SQLite graph tables (graph_nodes, graph_edges, mem_nodes, mem_edges). BFS retrieval implemented. Most heterogeneous edge types of any project. Direct comparison: their BFS vs our HRR on same graph. |
| **alpha-seek** | Decision citation graph, 202 decisions, 300+ references | Already tested (Exp 30-35). Baseline. Citation-heavy, regex-constructible. |
| **optimus-prime** | Fork of alpha-seek at larger scale, 40+ milestones, mempalace integration | Same graph shape as alpha-seek but more data. Tests: does HRR scale with more decisions? Vocabulary drift over 40 milestones? |
| **debserver** | Physical network topology (router, switch, AP, client nodes) + infrastructure decision graph | Two distinct graph layers: physical (Cytoscape) and logical (GSD decisions/knowledge). Edge types: ethernet, wifi, backhaul, tailscale. Tests HRR on non-document graphs. |
| **code-monkey** | Module catalog with FTS5 + 384-dim vector embeddings + PostgreSQL contract pipeline | Already has FTS5 and embeddings. Direct A/B: their embedding search vs HRR on module relationships. Multi-layer: contract -> execution -> delivery chain for BFS testing. |
| **evolve** | Skill tree DAG (100+ nodes, prerequisite edges, stat modifications) | Hierarchical graph, not lateral citations. Tests: can HRR traverse prerequisite chains? Nodes have stat-based relationships (armor, thrust, energy) that are semantic but not lexical. |

### Tier 2: Moderate structure, tests specific aspects

| Project | Graph Shape | What It Tests |
|---------|------------|--------------|
| **bigtime** | Requirement-to-phase mapping (50 reqs -> 8 phases), phase dependency DAG | No code, only planning docs. Tests: can we construct a useful graph from planning documents alone? Pure structural relationships. |
| **email-secretary** | Classification taxonomy (priority x category x flags) + subscription tracking | Flat relational, not graph-heavy. Tests: does HRR add value when relationships are categorical (email -> classification) rather than citation-based? |
| **sports-betting-arbitrage** | API pipeline (sportsbook -> normalize -> cache -> analyze), TimescaleDB | Temporal data flow. Tests: can we build and traverse time-ordered event chains via HRR? |
| **alpha-seek-memtest** | Same as alpha-seek + mempalace rooms | Tests mempalace-to-graph bridge: can mempalace room structure inform HRR subgraph partitioning? |
| **jose-bully** | Incident -> evidence -> meeting -> escalation path | Unique: narrative graph with temporal and evidentiary relationships. No code, pure documentation. Tests graph construction from unstructured narrative. |

### Tier 3: Limited structure, low priority

| Project | Notes |
|---------|-------|
| **ascii-evolve** | Small Rust game, ECS components. Might test: component dependency graph. |
| **mud_rust** | Early stage, minimal structure. |
| **orbitgame** | Physics sim, no persistent relationships. |
| **robotrocketscience / umouse** | Paused. Phase-based planning, could test planning-doc graph construction. |
| **stash** | Media metadata + GraphQL. Could test: plugin hook dependency graph. |
| **statistics** | Jupyter notebooks, linear progression. Minimal graph. |
| **archive / codex-setup-package / gsd-agent-framework** | Templates, learning projects, config-only. No useful graph. |

---

## What We're Testing

### T0: Automatic Node Type and Edge Type Discovery (Research Topic)

The system should not require a fixed schema of node types and edge types. When onboarding a new project, it should automatically detect what kinds of entities exist and what kinds of relationships connect them.

This is a prerequisite for everything else -- if graph construction requires manually defining CITES, DECIDED_IN, AGENT_CONSTRAINT, etc. per project, it doesn't generalize. The type system must emerge from the data.

**What needs to be discovered automatically:**

Node types:
- Alpha-seek: decision, milestone, sentence, concept
- GSD-2: code module, memory node, wiki page, decision record, conversation
- Evolve: perk node, entity type, system, biome
- Debserver: physical device, service, network segment, config file
- Code-monkey: module, contract, execution, delivery, aerospace component
- Bigtime: requirement, phase, component, technology

Edge types:
- Alpha-seek: CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES
- GSD-2: CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES, CONCEPT_LINK, EVIDENCED_BY
- Evolve: PREREQUISITE, MODIFIES_STAT, BELONGS_TO_BRANCH, UNLOCKS
- Debserver: HOSTS, CONNECTS_TO, DEPENDS_ON, MONITORS, MANAGES
- Code-monkey: IMPORTS, CALLS, DELIVERS_TO, SCOPES, SIMILAR_TO
- Bigtime: REQUIRES, DEPENDS_ON, MAPS_TO, IMPLEMENTS

**Research questions:**
- [ ] Can node types be inferred from file structure, content patterns, or naming conventions?
- [ ] Can edge types be inferred from co-occurrence, reference patterns, dependency analysis, or structural proximity?
- [ ] What is the minimum set of universal edge types (e.g., RELATES_TO, PRECEDES, CONTAINS, REFERENCES) that cover most projects, with project-specific types discovered on top?
- [ ] How do we validate discovered types? (Precision of proposed types vs human judgment)
- [ ] Does the number of edge types affect HRR performance? (More types = more orthogonal vectors = better selectivity, but also more complex queries)

**Approach candidates (to be tested, not committed):**
1. Structural analysis: file extensions -> node types, imports/references -> edge types
2. Pattern matching: D### -> decision citations, M### -> milestone references, URLs -> external sources
3. Co-occurrence statistics: entities appearing in same section/file/commit -> RELATES_TO edges
4. LLM-assisted classification: given a pair of nodes, propose edge type (expensive but accurate)
5. Clustering: group nodes by structural similarity, name clusters, derive types from cluster membership

**Key constraint:** This must work zero-LLM for the common cases (structural patterns, imports, co-occurrence) with optional LLM enrichment for semantic edges. Per the project's design principle.

**Test plan:** Run automatic type discovery on each Tier 1 project. Compare discovered types against the manually-identified types listed above. Measure precision and recall of type discovery.

---

### T1: Graph Construction Methods

Can we build sentence-level belief graphs from projects that DON'T have explicit D### citation syntax?

| Method | Works For | Doesn't Work For |
|--------|----------|-----------------|
| Regex citation extraction | alpha-seek, optimus-prime, gsd-2 (D###, M### syntax) | Everything else |
| Co-occurrence (same file/section) | All projects with docs | Low precision without filtering |
| Keyword/entity co-reference | Projects with consistent terminology | Vocabulary-drift projects |
| Planning doc structure (requirement -> phase mapping) | bigtime, debserver, code-monkey (have .planning/) | Projects without structured planning |
| Import/dependency parsing | code-monkey (Python imports), gsd-2 (TypeScript), evolve (Rust use statements) | Non-code projects |
| Config/YAML relationship extraction | debserver (docker-compose, ansible), stash (plugin hooks) | Code-only projects |

**Experiment idea:** For each Tier 1 project, attempt graph construction using all applicable methods. Measure edge count, precision (sampled), and overlap between methods.

### T2: HRR Vocabulary Bridge Across Graph Shapes

The 184x separation result (Exp 34 Test A) used manually-classified AGENT_CONSTRAINT edges in alpha-seek. Does the vocabulary bridge hold for:

| Graph Shape | Test Case | Expected Difficulty |
|-------------|----------|-------------------|
| Heterogeneous edges | gsd-2: CONCEPT_LINK edges connecting decisions with different vocabulary | Medium -- edges exist, 7 types give rich selectivity |
| Skill tree | evolve: can HRR connect "armor plating" (defense perk) to "energy shield" (different perk, same defensive category) via prerequisite paths? | Hard -- prerequisite edges are structural, not semantic |
| Infrastructure topology | debserver: can HRR connect "willow GPU" to "jellyfin transcoding" when they share no words but are linked by service dependency? | Hard -- physical/logical gap |
| Module catalog | code-monkey: can HRR connect aerospace modules in different subdomains that share no keywords but have similar usage patterns? | Medium -- embeddings exist for comparison |
| Planning-only | bigtime: can HRR connect Phase 4 (Work Scheduling) to Phase 7 (Preemption) via shared dependency on Phase 3 (Resource Monitoring)? | Easy -- clean DAG, small graph |

### T3: Where FTS5 Fails and HRR Succeeds (and Vice Versa)

For each project, identify queries where:
- FTS5 finds the target but HRR doesn't (keyword overlap but no structural connection)
- HRR finds the target but FTS5 doesn't (structural connection but vocabulary mismatch)
- Both find it (redundant)
- Neither finds it (gap in both methods)

This directly measures the complementarity claim from HRR_FINDINGS.md.

### T4: BFS Reliability at Different Graph Depths

| Project | Expected Max Useful Depth | Why |
|---------|--------------------------|-----|
| alpha-seek | 2-3 hops (D -> cites -> cites -> D) | Citation chains |
| gsd-2 | 3-4 hops (decision -> milestone -> concept_link -> decision) | Richer edge types allow deeper meaningful traversal |
| evolve | 5-10 hops (root -> perk -> perk -> ... -> leaf) | Deep tree structure |
| debserver | 3-4 hops (service -> host -> network -> host -> service) | Infrastructure path traversal |
| code-monkey | 4-5 hops (contract -> scope -> module -> similar_module -> prior_contract) | Pipeline depth |

### T5: Subgraph Partitioning Strategies

HRR requires subgraph partitioning to stay within capacity (k < n/9). Different projects suggest different partitioning strategies:

| Strategy | Natural Fit |
|----------|------------|
| By topic/cluster | alpha-seek (by milestone), gsd-2 (by extension) |
| By edge type | gsd-2 (7 types), debserver (physical vs logical) |
| By mempalace room | optimus-prime, alpha-seek-memtest (already have room assignments) |
| By module/directory | code-monkey (by layer), evolve (by system) |
| By time window | sports-betting-arbitrage (temporal), optimus-prime (by milestone era) |

---

## Execution Order

### Phase 1: Extract and normalize graphs (no HRR yet)
- [ ] gsd-2: Export existing SQLite graph (graph_nodes, graph_edges, mem_nodes, mem_edges) to a common format
- [ ] alpha-seek: Already have sentence graph from Exp 31 (1,195 nodes, 1,485 edges). Export to same format.
- [ ] optimus-prime: Build sentence graph using same methods as alpha-seek (regex D### + co-occurrence)
- [ ] evolve: Extract skill tree from GENOME_GRAPH in genome.py. Convert to node/edge format.
- [ ] debserver: Extract topology graph from netmap models.py + GSD decisions
- [ ] code-monkey: Extract module catalog relationships + contract pipeline edges
- [ ] bigtime: Extract requirement-to-phase mapping + phase dependency DAG from planning docs

### Phase 2: Characterize graph shapes
- [ ] For each graph: node count, edge count, edge type distribution, average degree, diameter, clustering coefficient
- [ ] Identify which graphs are citation-heavy vs topology vs hierarchical vs temporal
- [ ] Measure vocabulary overlap between connected nodes (cosine similarity of raw text) -- this predicts where FTS5 will succeed and HRR will be needed

### Phase 3: FTS5 baseline
- [ ] Build FTS5 indexes for each project's sentence-level content
- [ ] Run retrieval queries (reuse Exp 29 methodology adapted per project)
- [ ] Measure: which queries succeed, which fail, and why (vocabulary mismatch? too generic? wrong granularity?)

### Phase 4: HRR single-hop on each graph
- [ ] Encode each graph in HRR (DIM=2048, partitioned to stay within capacity)
- [ ] Run typed single-hop traversal
- [ ] Measure: P@5, R@5, P@10, R@10 per edge type per project
- [ ] Compare to FTS5: identify queries where HRR finds targets FTS5 misses (and vice versa)

### Phase 5: BFS baseline
- [ ] Build SQLite adjacency tables for each graph
- [ ] Run BFS at depths 1-4
- [ ] Measure: reachable nodes per depth, time per query

### Phase 6: Combined pipeline evaluation
- [ ] For each project, run the full pipeline: FTS5 + HRR single-hop + BFS from hits
- [ ] Measure: combined recall vs any single method
- [ ] Identify the marginal contribution of each method per graph shape

### Phase 7: Cross-project synthesis
- [ ] Which graph shapes benefit most from HRR?
- [ ] Which graph shapes are fully served by FTS5 + BFS?
- [ ] What is the minimum graph density/heterogeneity where HRR adds measurable value?
- [ ] Does mempalace room structure improve subgraph partitioning?

---

## Success Criteria

1. We can construct sentence-level graphs for at least 5 projects with different graph shapes
2. We measure FTS5 vs HRR vs BFS independently on each graph with reproducible metrics
3. We identify at least 2 graph shapes where HRR adds measurable recall over FTS5 + BFS alone
4. We identify at least 1 graph shape where HRR adds no value (confirming it's not universally needed)
5. We have evidence-backed recommendations for when to use HRR vs when FTS5 + BFS suffices
