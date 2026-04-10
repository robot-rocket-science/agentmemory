# Experiment 17: Requirements Traceability as Graph Structure

**Date:** 2026-04-09
**Type:** Literature review and feasibility analysis
**Question:** Can aerospace/defense traceability graph structures improve agentic memory systems, or is it bureaucratic overhead?

---

## 1. How Standards Structure Traceability Graphs

### DO-178C (Avionics Software)

DO-178C mandates bidirectional traceability as a directed acyclic graph (DAG). The hierarchy:

```
System Requirements
  -> High-Level Requirements (HLR)
    -> Low-Level Requirements (LLR)
      -> Source Code
        -> Test Cases
          -> Test Results
```

Edge types are implicit but consistent: each level "derives from" the one above and is "verified by" test artifacts. The depth of traceability required scales with software criticality level (A through D). Level A requires full bidirectional tracing from system requirements down to object code; Level D only needs HLR-to-test traceability.

Key insight: traceability depth should scale with criticality, not be uniform everywhere. Source: [Parasoft DO-178C Traceability](https://www.parasoft.com/learning-center/do-178c/requirements-traceability/)

### MIL-STD-498 (DoD Software)

Uses a Requirements Traceability Verification Matrix (RTVM) with four verification methods: demonstration, analysis, inspection, and testing. Each requirement must trace to at least one verification method. Requirements at each decomposition level may generate "derived requirements" not directly traceable upward -- these must still be documented and justified. Source: [MIL-STD-498 Wikipedia](https://en.wikipedia.org/wiki/MIL-STD-498)

### ISO 26262 (Automotive Functional Safety)

Adds a concept DO-178C lacks: ASIL decomposition. A high-ASIL requirement can be decomposed into redundant lower-ASIL requirements allocated to independent components. This maps well to agent memory: a high-level requirement like "cross-session decision retention" could decompose into independent sub-requirements (storage, retrieval, conflict detection) that can be verified separately. Source: [Infineon ASIL Decomposition](https://community.infineon.com/t5/Knowledge-Base-Articles/ASIL-decomposition-ISO-26262/ta-p/852405)

### NASA Graph Theory Application

NASA explicitly models requirements traceability as a directed acyclic graph (forest). Properties: generally no single root node, generally disconnected, acyclic, directed. This matches our situation -- we have 22 requirements that form multiple independent trees, not one monolithic hierarchy. Source: [NASA Graph Theory Traceability (PDF)](https://www.nasa.gov/wp-content/uploads/2016/10/482456main_1530_-_graph_theory_traceability_01.pdf)

---

## 2. Mapping to Knowledge Graph Edge Types

Synthesizing across the three standards, the minimal useful edge type set:

| Edge Type | Meaning | Example from Our System |
|-----------|---------|------------------------|
| DERIVES_FROM | Child requirement exists because of parent | REQ-019 (single-correction learning) derives from REQ-001 (cross-session retention) |
| IMPLEMENTS | Artifact realizes a requirement | exp1_extraction_pipeline.py implements REQ-005 |
| VERIFIES | Test demonstrates requirement is met | exp2 results verify REQ-002 (belief consistency) |
| VALIDATES | Acceptance test confirms user-level need | CS-002 (case study) validates REQ-019 behavior |
| SATISFIES | Approach addresses a requirement | A001 (citation-backbone graph) satisfies REQ-003 |
| SUPERSEDES | Approach/requirement replaces another | A002 supersedes A001 |
| CONFLICTS_WITH | Two beliefs/requirements are in tension | REQ-003 (token budget) conflicts with REQ-006 (recall) |

SARA, a Rust CLI tool, demonstrates this exact pattern for markdown-based requirements. It stores typed relationships (derives, satisfies, depends_on) in YAML frontmatter and auto-infers reverse links. This is directly applicable -- our documents already use a similar ID scheme (REQ-XXX, A0XX, CS-XXX, EXP-XX). Source: [SARA on DEV Community](https://dev.to/tumf/sara-a-cli-tool-for-managing-markdown-requirements-with-knowledge-graphs-nco)

---

## 3. Automatic Extraction from Our Documents

Our current documents already contain traceability links, but they are embedded in prose:

- REQUIREMENTS.md: "Plan trace: Phase 2", "Experiment trace: Experiment 3"
- CASE_STUDIES.md: "REQ mapping: REQ-019, REQ-020, REQ-021"
- APPROACHES.md: Linked to experiments by description, not by explicit ID
- EXPERIMENTS.md: Research questions reference requirements implicitly

**Extraction feasibility: high.** The REQ-XXX, CS-XXX, A0XX patterns are regex-extractable. A simple script could:
1. Scan all .md files for ID patterns (REQ-\d{3}, CS-\d{3}, A\d{3}, EXP-\d+)
2. Extract co-occurrence within sections to infer edges
3. Use field labels ("Plan trace:", "REQ mapping:") to type the edges
4. Output a graph (adjacency list or GraphML)

Estimated effort: 2-4 hours for a working prototype. No LLM needed for extraction from structured documents.

For unstructured prose, recent work (Karlsruhe Institute of Technology, 2024) shows LLM-based RAG can recover traceability links between natural language requirements and code with performance exceeding traditional IR baselines. Graph-RAG approaches that combine keyword, vector, and graph indexing outperform flat RAG for compliance checking. Source: [KIT Traceability Link Recovery](https://publikationen.bibliothek.kit.edu/1000178589/156854596), [Graph-RAG for Traceability (arXiv)](https://arxiv.org/html/2412.08593v1)

---

## 4. Queries This Enables

With a traceability graph, these queries become trivial (currently they require manual document scanning):

**Coverage gaps:**
- "Which requirements have no experiment trace?" (orphan nodes with no VERIFIES incoming edge)
- "Which experiments don't trace to any requirement?" (orphan verification artifacts)
- "Which approaches have no test results?" (IMPLEMENTS with no VERIFIES downstream)

**Impact analysis:**
- "If I change the token budget (REQ-003), what experiments, approaches, and case studies are affected?" (transitive closure from REQ-003)
- "What breaks if I drop the Bayesian calibration approach?" (reverse traversal from A003)

**Completeness:**
- "Show the full trace from REQ-001 through derived requirements, implementations, tests, and acceptance tests" (path enumeration)
- "Which requirements are verified but not validated?" (has VERIFIES edge but no VALIDATES edge)

**Provenance:**
- "Why do we believe the token budget should be 2,000?" (trace REQ-003 backward through evidence chain)
- "What evidence supports approach A001 over A002?" (compare subgraphs)

---

## 5. Agent Memory Traceability: Novel or Existing?

**Partially novel.** The components exist separately but the combination is new:

- MemOS (MemTensor, 2025) implements memory lifecycle management with versioning and access policies but does not use requirements-style traceability. Source: [MemOS Paper](https://statics.memtensor.com.cn/files/MemOS_0707.pdf)
- PROV-AGENT (2025) addresses provenance tracking for agentic workflows but focuses on execution traces, not belief/decision traceability.
- Medical multi-agent systems require auditable, role-filtered, versioned memory but use access-control models, not traceability graphs.
- Graph-RAG systems build knowledge graphs from documents but don't impose the hierarchical requirement/verification/validation structure.

**What's novel in our application:** treating the agent's belief revision chain (observation -> belief -> test -> revision) as a formal traceability chain with typed edges. No existing agent memory system maps the scientific method model onto aerospace-style traceability. The closest analog is compliance knowledge graphs used in regulated industries, but those track external rules, not internal agent beliefs.

---

## 6. Traceability vs. Provenance in the Scientific Method Model

Our existing model already has an implicit traceability chain:

```
Observation (raw log data)
  -> Belief (extracted claim with confidence)
    -> Hypothesis (testable prediction)
      -> Experiment (protocol and execution)
        -> Evidence (results with metrics)
          -> Revision (updated belief or rejection)
```

This IS a traceability chain. The edges are: EXTRACTED_FROM, PREDICTS, TESTED_BY, PRODUCES, REVISES. Adding formal requirements traceability on top creates a second, orthogonal graph:

```
User Need -> Requirement -> Derived Requirement -> Implementation -> Verification -> Validation
```

The two graphs intersect at implementation artifacts (experiments, code) and at validation (case studies test both requirement satisfaction and belief correctness).

---

## 7. Verdict: Overhead or Value?

**Value, with constraints.**

The traceability structure adds clear value for three operations we already do manually:
1. Finding coverage gaps (which requirements lack evidence)
2. Impact analysis (what changes when a decision changes)
3. Provenance queries (why do we believe X)

The overhead risk is real if we over-formalize. DO-178C Level A traceability is crushing for a research project. The right analog is Level D: trace high-level requirements to tests, skip detailed code-level tracing until we have production code.

**Recommended approach:**
- Extract the traceability graph from existing documents (regex, 2-4 hours)
- Store as a lightweight adjacency list or use SARA-style YAML frontmatter
- Do NOT build a separate graph database yet -- overkill at this stage
- Add graph queries as a verification step before declaring requirements met
- Revisit full traceability when we have production code to trace into

**Key risk:** traceability maintenance. If the graph goes stale because we forget to update edges when documents change, it becomes worse than no graph (false confidence). Mitigation: automated extraction on every commit, not manual maintenance.
