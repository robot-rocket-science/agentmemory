# Cross-Project Testing Plan: HRR + FTS5 + BFS

**Date:** 2026-04-09
**Purpose:** Use ~/projects/ as a diverse corpus to test graph construction, retrieval methods, and the HRR vocabulary bridge across different graph shapes, vocabulary patterns, and relationship densities.

---

## Why Multiple Projects Matter

All HRR experiments to date used one project (project-a) with one graph shape: citation-heavy, explicit D### references, consistent vocabulary within a single domain (options trading). That graph is easy to construct (regex) and easy to search (FTS5 keywords overlap heavily).

The open question from HRR_FINDINGS.md: does HRR's value increase for graphs with heterogeneous edge types, sparse explicit references, vocabulary drift, and dense cross-cluster connections? We need different graph shapes to answer that.

---

## Project Inventory (ranked by test value)

### Tier 1: Rich graphs, high test value

| Project | Graph Shape | Why It's Interesting |
|---------|------------|---------------------|
| **gsd-2** | Citation graph with 7 edge types (CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES, CONCEPT_LINK, EVIDENCED_BY) | Already has SQLite graph tables (graph_nodes, graph_edges, mem_nodes, mem_edges). BFS retrieval implemented. Most heterogeneous edge types of any project. Direct comparison: their BFS vs our HRR on same graph. |
| **project-a** | Decision citation graph, 202 decisions, 300+ references | Already tested (Exp 30-35). Baseline. Citation-heavy, regex-constructible. |
| **project-b** | Fork of project-a at larger scale, 40+ milestones, mempalace integration | Same graph shape as project-a but more data. Tests: does HRR scale with more decisions? Vocabulary drift over 40 milestones? |
| **project-d** | Physical network topology (router, switch, AP, client nodes) + infrastructure decision graph | Two distinct graph layers: physical (Cytoscape) and logical (GSD decisions/knowledge). Edge types: ethernet, wifi, backhaul, tailscale. Tests HRR on non-document graphs. |
| **project-e** | Module catalog with FTS5 + 384-dim vector embeddings + PostgreSQL contract pipeline | Already has FTS5 and embeddings. Direct A/B: their embedding search vs HRR on module relationships. Multi-layer: contract -> execution -> delivery chain for BFS testing. |
| **evolve** | Skill tree DAG (100+ nodes, prerequisite edges, stat modifications) | Hierarchical graph, not lateral citations. Tests: can HRR traverse prerequisite chains? Nodes have stat-based relationships (armor, thrust, energy) that are semantic but not lexical. |

### Tier 2: Moderate structure, tests specific aspects

| Project | Graph Shape | What It Tests |
|---------|------------|--------------|
| **bigtime** | Requirement-to-phase mapping (50 reqs -> 8 phases), phase dependency DAG | No code, only planning docs. Tests: can we construct a useful graph from planning documents alone? Pure structural relationships. |
| **project-f** | Classification taxonomy (priority x category x flags) + subscription tracking | Flat relational, not graph-heavy. Tests: does HRR add value when relationships are categorical (email -> classification) rather than citation-based? |
| **project-g-arbitrage** | API pipeline (sportsbook -> normalize -> cache -> analyze), TimescaleDB | Temporal data flow. Tests: can we build and traverse time-ordered event chains via HRR? |
| **project-a-test** | Same as project-a + mempalace rooms | Tests mempalace-to-graph bridge: can mempalace room structure inform HRR subgraph partitioning? |
| **project-c** | Incident -> evidence -> meeting -> escalation path | Unique: narrative graph with temporal and evidentiary relationships. No code, pure documentation. Tests graph construction from unstructured narrative. |

### Tier 3: Limited structure, low priority (personal)

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

### Public GitHub Repos (clone to server-a with full git history)

Organized by discipline. Each chosen for a distinct graph shape that tests different aspects of automatic type discovery, graph construction, and retrieval.

#### Web Framework
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [saleor/saleor](https://github.com/saleor/saleor) | ~22.8K | Python/Django | Entity-relationship (Django models) + GraphQL API schema + plugin architecture. Three overlapping graph topologies from one codebase. |
| [blitz-js/blitz](https://github.com/blitz-js/blitz) | ~14.1K | TypeScript | Cross-package monorepo + Prisma entity graph. Tests cross-package dependency extraction. |

#### AI/ML Pipeline
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [ludwig-ai/ludwig](https://github.com/ludwig-ai/ludwig) | ~11.7K | Python | Config-to-code mapping (YAML -> Python modules) + deep module hierarchy (data types -> encoders -> combiners -> decoders). Tests implicit pipeline DAG discovery from config files. |
| [mlflow/mlflow](https://github.com/mlflow/mlflow) | ~25.3K | Python | Multi-component layered architecture. REST API -> backend stores -> artifact stores. Cross-cutting concerns (tracking touches everything). |

#### Controls/Robotics
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [PX4/PX4-Autopilot](https://github.com/PX4/PX4-Autopilot) | ~11.5K | C++ | uORB pub/sub message bus overlaying module dependency graph. Sensor fusion pipeline, flight mode state machines, HAL layers. Multi-layer graph. |
| [ros2/rclcpp](https://github.com/ros2/rclcpp) | ~740 | C++ | Clean layered architecture. Typed pub/sub (topics, services, actions). Small enough to verify graph construction correctness. |

#### Physics Simulation
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [bulletphysics/bullet3](https://github.com/bulletphysics/bullet3) | ~14.4K | C++ | Pipeline graph (broadphase -> narrowphase -> constraint solving -> integration) + class hierarchy for shapes/constraints/solvers. |
| [taichi-dev/taichi](https://github.com/taichi-dev/taichi) | ~28.1K | C++/Python | Dual graph: compiler pipeline (frontend -> IR -> optimization -> backend codegen) AND physics simulation abstractions. Bridges compiler and physics categories. |

#### DevOps/Infrastructure-as-Code
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [hashicorp/terraform](https://github.com/hashicorp/terraform) | ~48.1K | Go | Resource dependency DAG is the core abstraction. The code IS about graph construction (config -> graph building -> graph walking -> provider RPC). Meta-test. |
| [pulumi/pulumi](https://github.com/pulumi/pulumi) | ~25.0K | Go | Cross-language SDK graph (same concepts in Go/Python/TS/C#) + resource dependency graph + plugin system. Tests structural parallels across language boundaries. |

#### Compiler/Language Tooling
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [boa-dev/boa](https://github.com/boa-dev/boa) | ~7.2K | Rust | Deep linear pipeline: lexer -> parser -> AST -> bytecode compiler -> VM. ECMAScript spec compliance creates code-to-spec cross-references. |
| [babel/babel](https://github.com/babel/babel) | ~43.9K | TypeScript | ~150 internal packages, plugin composition, monorepo. Tests graph construction at scale with many small interconnected packages. Also serves as monorepo test case. |

#### Game Engine
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [bevyengine/bevy](https://github.com/bevyengine/bevy) | ~45.5K | Rust | ECS architecture (components orthogonal, systems create implicit dependency via queries) + explicit render graph DAG + plugin dependency layer. Multiple overlapping topologies. |

#### Database/Storage Engine
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [duckdb/duckdb](https://github.com/duckdb/duckdb) | ~37.3K | C++ | Query pipeline (parser -> binder -> optimizer -> physical planner -> executor) + storage layer (buffer manager, WAL, catalog). Operator trees are literal graph structures. |
| [cockroachdb/cockroach](https://github.com/cockroachdb/cockroach) | ~32.0K | Go | Distributed layered: SQL -> distribution -> replication (Raft) -> storage. Inter-node communication graphs on top of code dependency graphs. |

#### Embedded Systems/Firmware
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [espressif/esp-idf](https://github.com/espressif/esp-idf) | ~17.8K | C | HAL layers + Kconfig build configuration dependency graph + peripheral bus topology (SPI, I2C sharing). Strict layered graph + config graph. |
| [micropython/micropython](https://github.com/micropython/micropython) | ~21.6K | C | Port x module matrix (each port selects from shared modules) + compiler pipeline. Tests graph construction with conditional compilation / platform variants. |

#### Data Engineering/ETL
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [apache/airflow](https://github.com/apache/airflow) | ~45.0K | Python | Core abstraction IS a DAG. ~80 provider packages form plugin graph. Executor/scheduler/worker communication adds runtime topology. |
| [dagster-io/dagster](https://github.com/dagster-io/dagster) | ~15.3K | Python | Software-defined asset dependency graph (first-class). Resource injection graph. More structured than Airflow -- better for typed edge extraction. |

#### Scientific Computing
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [dealii/dealii](https://github.com/dealii/dealii) | ~1.65K | C++ | Deep class hierarchy (base -> lac -> fe -> dofs -> grid -> numerics). Solver-preconditioner composition graph. Tutorial-to-code cross-references. |
| [su2code/SU2](https://github.com/su2code/SU2) | ~1.67K | C++ | Multi-physics coupling with bidirectional solver data exchange. Config-driven solver selection creates config-to-code mapping. |

#### Networking/Protocol
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [quinn-rs/quinn](https://github.com/quinn-rs/quinn) | ~5.0K | Rust | QUIC protocol state machines (connection + stream states) + layered architecture (quinn -> quinn-proto -> rustls). |
| [smoltcp-rs/smoltcp](https://github.com/smoltcp-rs/smoltcp) | ~4.4K | Rust | Network protocol layer cake (Ethernet -> ARP -> IP -> TCP/UDP). Small (~200 files) -- can manually verify graph construction correctness. |

#### Security/Cryptography
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [openssl/openssl](https://github.com/openssl/openssl) | ~29.9K | C | Algorithm dispatch via provider system (indirection graph). Certificate chain validation is literal graph traversal. Protocol state machines. |
| [rustls/rustls](https://github.com/rustls/rustls) | ~7.3K | Rust | TLS handshake state machine + cipher suite selection matrix + certificate chain. Smaller/cleaner than OpenSSL -- same graph shape, easier to verify. |

#### Documentation/Specification (pure text)
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [joelparkerhenderson/architecture-decision-record](https://github.com/joelparkerhenderson/architecture-decision-record) | ~14.3K | Markdown | Pure documentation graph. Decisions reference other decisions, templates reference concepts. Tests graph construction from Markdown with semantic cross-references. No code. |
| [commonmark/commonmark-spec](https://github.com/commonmark/commonmark-spec) | ~5.1K | Mixed | Three-layer cross-reference: spec sections <-> test cases <-> reference implementations. |

#### Monorepo
| Repo | Stars | Language | Graph Shape |
|------|-------|----------|-------------|
| [nrwl/nx](https://github.com/nrwl/nx) | ~28.5K | TypeScript | Nx IS a graph tool -- it builds and visualizes dependency graphs. The repo itself is a monorepo of many packages. Meta-test: can our graph construction match what Nx computes? |

### Corpus Summary

| Dimension | Count |
|-----------|-------|
| Personal projects (Tier 1-2) | 11 |
| Public repos | 26 unique (27 slots, Babel counts in 2 categories) |
| **Total test corpus** | **37 projects** |
| Languages | Python, TypeScript, Rust, Go, C++, C, Markdown |
| Graph shapes | Import/dependency, entity-relationship, pub/sub, state machine, pipeline/DAG, config-to-code, plugin/provider, class hierarchy, protocol layers, cross-language parallel, pure text semantic |
| Size range | ~200 files (smoltcp) to 100K+ files (cockroach, airflow) |

---

## What We're Testing

### T0: Automatic Node Type and Edge Type Discovery (Research Topic)

The system should not require a fixed schema of node types and edge types. When onboarding a new project, it should automatically detect what kinds of entities exist and what kinds of relationships connect them.

This is a prerequisite for everything else -- if graph construction requires manually defining CITES, DECIDED_IN, AGENT_CONSTRAINT, etc. per project, it doesn't generalize. The type system must emerge from the data.

**What needs to be discovered automatically:**

Node types:
- project-a: decision, milestone, sentence, concept
- GSD-2: code module, memory node, wiki page, decision record, conversation
- Evolve: perk node, entity type, system, biome
- project-d: physical device, service, network segment, config file
- Code-monkey: module, contract, execution, delivery, aerospace component
- Bigtime: requirement, phase, component, technology

Edge types:
- project-a: CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES
- GSD-2: CITES, DECIDED_IN, RELATES_TO, SOURCED_FROM, SUPERSEDES, CONCEPT_LINK, EVIDENCED_BY
- Evolve: PREREQUISITE, MODIFIES_STAT, BELONGS_TO_BRANCH, UNLOCKS
- project-d: HOSTS, CONNECTS_TO, DEPENDS_ON, MONITORS, MANAGES
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
6. Git history analysis: co-change -> coupling edges, commit messages -> belief nodes, issue refs -> citation edges, temporal ordering -> SUPERSEDES edges

**Key constraint:** This must work zero-LLM for the common cases (structural patterns, imports, co-occurrence) with optional LLM enrichment for semantic edges. Per the project's design principle.

**Test plan:** Run automatic type discovery on each Tier 1 project. Compare discovered types against the manually-identified types listed above. Measure precision and recall of type discovery.

---

### T1: Graph Construction Methods

Can we build sentence-level belief graphs from projects that DON'T have explicit D### citation syntax?

| Method | Works For | Doesn't Work For |
|--------|----------|-----------------|
| Regex citation extraction | project-a, project-b, gsd-2 (D###, M### syntax) | Everything else |
| Co-occurrence (same file/section) | All projects with docs | Low precision without filtering |
| Keyword/entity co-reference | Projects with consistent terminology | Vocabulary-drift projects |
| Planning doc structure (requirement -> phase mapping) | bigtime, project-d, project-e (have .planning/) | Projects without structured planning |
| Import/dependency parsing | project-e (Python imports), gsd-2 (TypeScript), evolve (Rust use statements) | Non-code projects |
| Config/YAML relationship extraction | project-d (docker-compose, ansible), stash (plugin hooks) | Code-only projects |
| **Git history: co-change analysis** | All projects with commits | New/empty repos |
| **Git history: commit message decomposition** | All projects (commit msgs are universal) | Repos with empty/unhelpful commit msgs |
| **Git history: issue/PR references** | Projects using #123/fixes #N conventions | Projects without issue trackers |
| **Git history: temporal supersession** | Projects with long history, evolving decisions | Single-commit repos |

**Git history as a universal graph construction signal:**

Git history is the one data source every project has (if it uses version control). Unlike D### citations or .planning/ docs, commits are project-agnostic. Key edge types derivable from history:

- **CO_CHANGED**: files modified in the same commit. Stronger coupling signal than directory co-location. Weighted by frequency (files changed together 10 times > 1 time).
- **SUPERSEDES_TEMPORAL**: same file/section modified at T2 after T1. The T2 content supersedes T1. Commit message explains why.
- **REFERENCES_ISSUE**: commit message contains #123, "fixes #456", "closes #789". Edges to issue/PR nodes.
- **AUTHORED_BY**: who wrote/modified what. Irrelevant for solo projects, critical for multi-contributor repos.
- **COMMIT_BELIEF**: each commit message is a sentence-level belief node. "Fix race condition in scheduler by adding mutex" asserts: (1) there was a race condition, (2) it was in the scheduler, (3) a mutex fixes it. Three beliefs from one commit.

This means even a repo with zero documentation still produces a graph from its commit history alone.

**Experiment idea:** For each Tier 1 project, attempt graph construction using all applicable methods including git history. Measure edge count, precision (sampled), and overlap between methods. Specifically measure how much the git-history-derived edges overlap with edges from other methods (high overlap = redundant, low overlap = complementary).

### T2: HRR Vocabulary Bridge Across Graph Shapes

The 184x separation result (Exp 34 Test A) used manually-classified AGENT_CONSTRAINT edges in project-a. Does the vocabulary bridge hold for:

| Graph Shape | Test Case | Expected Difficulty |
|-------------|----------|-------------------|
| Heterogeneous edges | gsd-2: CONCEPT_LINK edges connecting decisions with different vocabulary | Medium -- edges exist, 7 types give rich selectivity |
| Skill tree | evolve: can HRR connect "armor plating" (defense perk) to "energy shield" (different perk, same defensive category) via prerequisite paths? | Hard -- prerequisite edges are structural, not semantic |
| Infrastructure topology | project-d: can HRR connect "server-b GPU" to "jellyfin transcoding" when they share no words but are linked by service dependency? | Hard -- physical/logical gap |
| Module catalog | project-e: can HRR connect aerospace modules in different subdomains that share no keywords but have similar usage patterns? | Medium -- embeddings exist for comparison |
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
| project-a | 2-3 hops (D -> cites -> cites -> D) | Citation chains |
| gsd-2 | 3-4 hops (decision -> milestone -> concept_link -> decision) | Richer edge types allow deeper meaningful traversal |
| evolve | 5-10 hops (root -> perk -> perk -> ... -> leaf) | Deep tree structure |
| project-d | 3-4 hops (service -> host -> network -> host -> service) | Infrastructure path traversal |
| project-e | 4-5 hops (contract -> scope -> module -> similar_module -> prior_contract) | Pipeline depth |

### T5: Subgraph Partitioning Strategies

HRR requires subgraph partitioning to stay within capacity (k < n/9). Different projects suggest different partitioning strategies:

| Strategy | Natural Fit |
|----------|------------|
| By topic/cluster | project-a (by milestone), gsd-2 (by extension) |
| By edge type | gsd-2 (7 types), project-d (physical vs logical) |
| By mempalace room | project-b, project-a-test (already have room assignments) |
| By module/directory | project-e (by layer), evolve (by system) |
| By time window | project-g-arbitrage (temporal), project-b (by milestone era) |

---

## Execution Order

### Phase 1: Extract and normalize graphs (no HRR yet)
- [ ] gsd-2: Export existing SQLite graph (graph_nodes, graph_edges, mem_nodes, mem_edges) to a common format
- [ ] project-a: Already have sentence graph from Exp 31 (1,195 nodes, 1,485 edges). Export to same format.
- [ ] project-b: Build sentence graph using same methods as project-a (regex D### + co-occurrence)
- [ ] evolve: Extract skill tree from GENOME_GRAPH in genome.py. Convert to node/edge format.
- [ ] project-d: Extract topology graph from netmap models.py + GSD decisions
- [ ] project-e: Extract module catalog relationships + contract pipeline edges
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

## Infrastructure

**Research corpus host: server-a** (192.168.1.169 / Tailscale 100.115.33.31)
- CachyOS (Arch-based), development workstation
- More disk and CPU than local machine
- Access via SSH over Tailscale
- Clone ALL repos here with full git history (no shallow clones -- we need commit history for temporal graph construction)
- Run extraction scripts and experiments here

**Corpus layout on server-a:**
```
~/agentmemory-corpus/
  personal/          # mirror of ~/projects/ Tier 1-2 (full git history)
    project-a/
    project-b/
    gsd-2/
    project-d/
    project-e/
    evolve/
    bigtime/
    project-f/
    project-g-arbitrage/
    project-a-test/
    project-c/
  public/            # full clones from GitHub
    web/saleor/
    web/blitz/
    aiml/ludwig/
    aiml/mlflow/
    controls/px4-autopilot/
    controls/rclcpp/
    physics/bullet3/
    physics/taichi/
    devops/terraform/
    devops/pulumi/
    compiler/boa/
    compiler/babel/
    game/bevy/
    database/duckdb/
    database/cockroach/
    embedded/esp-idf/
    embedded/micropython/
    etl/airflow/
    etl/dagster/
    scicomp/dealii/
    scicomp/su2/
    networking/quinn/
    networking/smoltcp/
    security/openssl/
    security/rustls/
    docs/architecture-decision-record/
    docs/commonmark-spec/
    monorepo/nx/
  extracted/          # output: normalized graphs, FTS5 indexes, HRR encodings
  results/            # experiment results per project
```

Both personal and public projects get the same extraction pipeline. Unified corpus, unified experiments.

---

## Success Criteria

1. We can construct sentence-level graphs for at least 5 projects with different graph shapes
2. We measure FTS5 vs HRR vs BFS independently on each graph with reproducible metrics
3. We identify at least 2 graph shapes where HRR adds measurable recall over FTS5 + BFS alone
4. We identify at least 1 graph shape where HRR adds no value (confirming it's not universally needed)
5. We have evidence-backed recommendations for when to use HRR vs when FTS5 + BFS suffices
