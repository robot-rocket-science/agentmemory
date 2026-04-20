# mem:wonder: Cross-Project Belief Retrieval Without Contamination

## Query

> Cross-project belief retrieval without contamination: how should agentmemory handle infrastructure-scoped knowledge (deploy procedures, server configs, shared tooling) that applies across multiple projects without breaking project isolation? Must prevent belief flooding while allowing legitimate cross-project procedural knowledge to surface. What do other systems do for this pattern?

## Hypothesis

The current binary scope model (project-isolated vs global) is insufficient. A third scope level ("infrastructure" or "shared") is needed, with explicit flooding controls, to handle knowledge that spans project boundaries without contaminating project-specific retrieval.

## Methodology

- 4 parallel research agents, each investigating one angle
- Agent 1: Prior art (federated KGs, multi-tenant DBs, service meshes, git workspaces)
- Agent 2: Concrete scope model designs with SQL schemas
- Agent 3: Adversarial risk analysis (what could go wrong)
- Agent 4: Experiment design for testing cross-project retrieval
- Prior beliefs from 2 MCP searches (116 beliefs total)

## Prior Beliefs

| ID | Content | Confidence |
|---|---|---|
| `29afa7100fc9` | Default: beliefs from project A NOT retrievable in project B unless cross-project tagged | 78% |
| `15e5d9911c44` | If target node's project_id is different: do not traverse | 91% |
| `f0d223cf2d04` | Multi-project isolation requires partitioned HRR vectors | 78% |
| `7d8bf4719da2` | Auto query-seeded injection when user mentions deploy/dispatch | 37% |
| `3100c9d0128b` | FTS5 OR query scores procedures low, pushing them below K=15 | 33% |
| `99fead7c96d4` | Three scope levels sufficient: global, language-scoped, project-scoped | 37% |

## New Findings

### Agent 1: Prior Art Survey

Four patterns from existing systems:

**1. Federated Knowledge Graphs (Wikidata/SPARQL model)**
- Each source maintains its own graph; queries fan out via `SERVICE` keyword
- SQLite equivalent: `ATTACH DATABASE` lets you query across DBs in one connection
- Pro: no data duplication. Con: latency depends on slowest source.

**2. Multi-Tenant Shared Reference Data (SaaS model) -- RECOMMENDED**
- Tenant-specific data isolated by `tenant_id`. Shared reference data has `tenant_id = NULL`.
- Queries implicitly `UNION` tenant-scoped + global data.
- For agentmemory: add `scope` column, `NULL` = project-only, named scope = shared.
- Minimal schema change, zero architectural overhead.

**3. Service Mesh Hierarchical Config (Consul/Istio model)**
- Layered resolution: project-specific overrides global. Clear precedence rules.
- Maps to agentmemory's locked-belief precedence extended to scope.
- Project belief with higher confidence overrides global on same topic.

**4. Git Submodules (Monorepo model) -- WEAKEST FIT**
- Copies shared content into each consumer. Creates staleness and duplication.
- Violates agentmemory's single-writer model.

### Agent 2: Three Concrete Scope Models

**Model A: Tag-Based Scopes (copy-on-sync)**
- Central `scope_groups` registry in `registry.db`
- Beliefs physically copied into subscribing project DBs
- Pro: simple queries (single DB). Con: sync propagation, conflicts.

**Model B: Virtual Shared Scopes via ATTACH -- RECOMMENDED**
- Separate SQLite DB per scope (`~/.agentmemory/shared/{scope}/memory.db`)
- At query time: `ATTACH` shared DB, run FTS5 with budget split (10 local + 5 shared)
- Flooding prevention: hard per-scope LIMIT in the UNION
- Pro: no data duplication, clean separation. Con: connection management.

```sql
ATTACH '~/.agentmemory/shared/infra/memory.db' AS infra;
SELECT * FROM (
    SELECT *, 'local' AS origin FROM beliefs_fts WHERE beliefs_fts MATCH ?
    ORDER BY rank LIMIT 10
) UNION ALL SELECT * FROM (
    SELECT *, 'infra' AS origin FROM infra.beliefs_fts WHERE infra.beliefs_fts MATCH ?
    ORDER BY rank LIMIT 5
) ORDER BY rank LIMIT 15;
```

**Model C: Hybrid (scope column + optional ATTACH)**
- Add `scope` column to existing project DBs for lightweight tagging
- For heavy cross-project sharing, use ATTACH to dedicated scope DBs
- Graceful degradation: if no shared DBs exist, system works unchanged.

### Agent 3: Risk Analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Privacy/contamination (freelancer with client projects) | HIGH | Default project-isolated; require explicit allowlist; never auto-tag |
| Ranking pollution (large project dominates small project's results) | HIGH | Reserved slots: top-5 local, top-2 cross-project; distance penalty |
| Consistency (contradictory locked beliefs across projects) | MEDIUM | Contradiction detection at retrieval; force user resolution |
| Performance (querying N databases) | LOW | SQLite ATTACH is ~1ms; lazy-load only if local results below threshold |
| User confusion (stale archived project beliefs surfacing) | MEDIUM | Source attribution; time-decay penalty; revoke sharing with one command |
| Directory rename breaks project identity | MEDIUM-HIGH | Hash-based identity with alias table |

### Agent 4: Experiment Design

Proposed test (`tests/experiments/test_cross_project_retrieval.py`):

- 3 project DBs: A (500 beliefs, Python web app), B (200, infrastructure, 20 tagged infra), C (1000, data pipeline)
- 10 cross-scope queries (should find infra beliefs): "how do I deploy", "rollback procedure", etc.
- 10 project-scoped queries (should NOT find foreign beliefs): "what database", "what ORM", etc.

**Pass/fail criteria:**
- Recall: >=8/10 cross-scope queries return >=1 infrastructure belief in top-5
- Precision: <=10% foreign results across project-scoped queries; any single query with >2 foreign beliefs in top-5 is a fail
- Flooding: foreign results never exceed 20% of any result set
- Latency: cross-project retrieval within 2x single-DB baseline

## Gaps and Contradictions

1. **Belief `99fead7c96d4`** says "three scope levels sufficient: global, language-scoped, project-scoped." This wonder suggests infrastructure-scoped is a fourth level not covered by that model. The belief's confidence (37%) is appropriately low.

2. **No consensus on copy vs. federate.** Model A (copy) is simpler but creates staleness. Model B (ATTACH) is cleaner but adds connection management. Both agents recommended Model B but Model A has a simpler migration path.

3. **The freelancer problem has no universal solution.** Cross-project sharing is inherently a trust decision. The system can default to safe (isolated) and require explicit opt-in, but it can't determine which projects should share without user input.

4. **Activation conditions (Layer 0) are per-project.** Even if infrastructure beliefs cross project boundaries, the activation conditions that trigger them ("deploy" -> inject runbook) are stored in the originating project's beliefs. No mechanism exists to inherit activation conditions from shared scopes.

## Proposed Experiments

### Exp 95: Cross-Project Retrieval via ATTACH

Implement Model B (virtual shared scopes) in a test environment:
1. Create `~/.agentmemory/shared/infra/memory.db` with 20 infrastructure beliefs
2. Modify retrieval.py to ATTACH shared DBs and run federated FTS5
3. Test with Agent 4's experiment design (10+10 queries, pass/fail criteria)
4. Measure: recall, precision, flooding ratio, latency overhead

### Exp 96: Scope-Aware Scoring

Test whether scoring adjustments (distance penalty for cross-project, reserved slots) prevent flooding:
1. Run retrieval with and without reserved-slot allocation
2. Measure how often cross-project results displace locally relevant beliefs
3. Find the right budget split (how many of top-15 should come from shared scope?)

## Recommendation

**Start with Model B (ATTACH-based shared scopes).** It requires:
1. A `~/.agentmemory/shared/` directory for scope databases
2. A `scopes.json` config mapping scope names to project lists
3. A retrieval.py change to ATTACH and UNION with budget limits
4. A new MCP tool (`share_belief`) to tag a belief as infrastructure-scoped

No schema changes to existing project databases. Backwards compatible. Defaults to current behavior if no shared scopes exist. The experiment can validate before committing to the architecture.
