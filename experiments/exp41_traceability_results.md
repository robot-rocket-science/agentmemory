# Traceability Graph: Extraction Results (Exp 41)

**Date:** 2026-04-10
**Method:** Regex + section-level co-occurrence, zero LLM

## Entity Summary

| Type | Count |
|------|-------|
| requirement | 27 |
| case_study | 38 |
| approach | 15 |
| experiment | 20 |
| phase | 0 |
| **Total** | **100** |

## Edge Summary

| Edge Type | Count |
|-----------|-------|
| CO_OCCURS | 1674 |
| PLANNED_IN | 35 |
| VERIFIED_BY | 31 |
| MAPS_TO | 16 |
| IMPLEMENTS | 3 |
| SATISFIES | 2 |
| **Total** | **1761** |

## Coverage Gaps

| Entity | Issues |
|--------|--------|
| EXP-11 (Scientific Method Model vs Human Memory Categories) | not linked to any requirement |
| EXP-17 (Requirements Traceability as Graph Structure) | not linked to any requirement |
| EXP-18 (Query Expansion Without LLM -- Research) | not linked to any requirement |
| EXP-20 (Information Bottleneck for Belief Compression) | not linked to any requirement |
| EXP-21 (Multi-Project Belief Isolation and Cross-Pollination) | not linked to any requirement |
| EXP-23 (Gray Code Binary Encoding for Semantic Similarity) | not linked to any requirement |
| REQ-013 (Observation Immutability) | no experiment verification |
| REQ-015 (No Unverified Claims) | no experiment verification |
| REQ-016 (Documented Limitations) | no experiment verification |
| REQ-028 (Epistemic State Tagging on Retrieval Results) | no experiment verification |

## Labeled Edges (non-co-occurrence)

| Source | Target | Type | File |
|--------|--------|------|------|
| A006 | PHASE-0 | IMPLEMENTS | APPROACHES.md |
| CS-001 | REQ-019 | MAPS_TO | CASE_STUDIES.md |
| CS-002 | A001 | SATISFIES | experiments/exp17_traceability_research.md |
| CS-002 | REQ-003 | SATISFIES | experiments/exp17_traceability_research.md |
| CS-002 | REQ-005 | IMPLEMENTS | experiments/exp17_traceability_research.md |
| CS-002 | REQ-019 | MAPS_TO | CASE_STUDIES.md |
| CS-002 | REQ-020 | MAPS_TO | CASE_STUDIES.md |
| CS-002 | REQ-021 | MAPS_TO | CASE_STUDIES.md |
| CS-003 | REQ-001 | MAPS_TO | CASE_STUDIES.md |
| CS-003 | REQ-021 | MAPS_TO | CASE_STUDIES.md |
| CS-004 | REQ-019 | MAPS_TO | CASE_STUDIES.md |
| CS-004 | REQ-020 | MAPS_TO | CASE_STUDIES.md |
| CS-008 | REQ-019 | MAPS_TO | CASE_STUDIES.md |
| CS-008 | REQ-021 | MAPS_TO | CASE_STUDIES.md |
| EXP-03 | PHASE-2 | PLANNED_IN | experiments/exp17_traceability_research.md |
| EXP-03 | REQ-019 | MAPS_TO | experiments/exp17_traceability_research.md |
| EXP-03 | REQ-020 | MAPS_TO | experiments/exp17_traceability_research.md |
| EXP-03 | REQ-021 | MAPS_TO | experiments/exp17_traceability_research.md |
| EXP-41 | REQ-001 | MAPS_TO | CASE_STUDIES.md |
| EXP-41 | REQ-019 | MAPS_TO | CASE_STUDIES.md |
| EXP-41 | REQ-027 | MAPS_TO | CASE_STUDIES.md |
| REQ-001 | EXP-03 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-001 | PHASE-0 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-001 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-001 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-002 | EXP-02 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-002 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-002 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-003 | EXP-04 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-003 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-004 | EXP-04 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-004 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-005 | PHASE-1 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-005 | PHASE-1 | PLANNED_IN | REQUIREMENTS.md |
| REQ-006 | PHASE-1 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-006 | PHASE-1 | PLANNED_IN | REQUIREMENTS.md |
| REQ-007 | EXP-03 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-007 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-008 | EXP-02 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-008 | PHASE-3 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-008 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-009 | EXP-02 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-009 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-009 | PHASE-5 | PLANNED_IN | REQUIREMENTS.md |
| REQ-009 | PHASE-5 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-010 | EXP-02 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-010 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-010 | PHASE-5 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-011 | PHASE-4 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-011 | PHASE-4 | PLANNED_IN | REQUIREMENTS.md |
| REQ-012 | PHASE-1 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-012 | PHASE-1 | PLANNED_IN | REQUIREMENTS.md |
| REQ-013 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-014 | EXP-01 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-014 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-015 | PHASE-5 | PLANNED_IN | REQUIREMENTS.md |
| REQ-016 | PHASE-5 | PLANNED_IN | REQUIREMENTS.md |
| REQ-017 | PHASE-5 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-018 | PHASE-5 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-019 | EXP-01 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-019 | EXP-06 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-019 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-020 | EXP-06 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-020 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-021 | EXP-06 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-021 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-021 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-023 | CS-005 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-023 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-023 | PHASE-5 | PLANNED_IN | REQUIREMENTS.md |
| REQ-024 | CS-005 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-024 | PHASE-1 | PLANNED_IN | REQUIREMENTS.md |
| REQ-024 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-025 | CS-005 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-025 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-025 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-025 | REQ-026 | IMPLEMENTS | GRAPH_CONSTRUCTION_RESEARCH.md |
| REQ-026 | CS-005 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-026 | PHASE-2 | PLANNED_IN | REQUIREMENTS.md |
| REQ-026 | PHASE-5 | PLANNED_IN | REQUIREMENTS.md |
| REQ-027 | EXP-01 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-027 | EXP-06 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-027 | EXP-36 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-027 | EXP-40 | VERIFIED_BY | REQUIREMENTS.md |
| REQ-027 | PHASE-1 | PLANNED_IN | REQUIREMENTS.md |
| REQ-027 | PHASE-3 | PLANNED_IN | REQUIREMENTS.md |
| REQ-027 | PHASE-4 | PLANNED_IN | REQUIREMENTS.md |
