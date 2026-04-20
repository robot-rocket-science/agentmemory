# Acceptance Test Results

**Date:** 2026-04-14
**Runner:** `uv run python -m pytest tests/acceptance/ -v --tb=short`
**Duration:** 1.65s

## Summary

| Metric | Count |
|--------|-------|
| Total  | 65    |
| Passed | 62    |
| Failed | 0     |
| Skipped| 3     |
| **Pass rate** | **95.4%** (62/65) |

## Results by File

| Test File | Passed | Failed | Skipped |
|-----------|--------|--------|---------|
| test_cs001_redundant_work.py | 3 | 0 | 0 |
| test_cs002_locked_correction.py | 5 | 0 | 0 |
| test_cs003_consult_state.py | 2 | 0 | 0 |
| test_cs004_context_drift.py | 2 | 0 | 0 |
| test_cs005_maturity_inflation.py | 2 | 0 | 0 |
| test_cs006_cross_session_enforcement.py | 2 | 0 | 0 |
| test_cs007_volume_as_validation.py | 2 | 0 | 0 |
| test_cs008_result_inflation.py | 2 | 0 | 0 |
| test_cs009_supersession.py | 4 | 0 | 0 |
| test_cs010_test_coverage_gaps.py | 1 | 0 | 0 |
| test_cs011_scale_before_validate.py | 2 | 0 | 0 |
| test_cs013_tool_correction.py | 4 | 0 | 0 |
| test_cs014_research_execution_divergence.py | 2 | 0 | 0 |
| test_cs015_dead_approaches.py | 2 | 0 | 0 |
| test_cs016_settled_decisions.py | 2 | 0 | 0 |
| test_cs017_config_drift.py | 1 | 0 | 0 |
| test_cs018_dual_source_truth.py | 1 | 0 | 0 |
| test_cs019_pipeline_integration.py | 2 | 0 | 0 |
| test_cs020_task_id_grounding.py | 2 | 0 | 0 |
| test_cs021_design_vs_research.py | 1 | 0 | 0 |
| test_cs022_multihop_query.py | 2 | 0 | 0 |
| test_cs023_id_collision.py | 2 | 0 | 0 |
| test_cs025_correction_generalization.py | 2 | 0 | 0 |
| test_cs_behavioral_skip.py | 0 | 0 | 3 |
| test_req001_cross_session.py | 1 | 0 | 0 |
| test_req002_contradiction_flagging.py | 5 | 0 | 0 |
| test_req005_crash_recovery.py | 2 | 0 | 0 |
| test_req006_checkpoint_latency.py | 1 | 0 | 0 |
| test_req012_write_durability.py | 3 | 0 | 0 |

## Skipped Tests

| Test | Reason |
|------|--------|
| test_cs012_placeholder | Behavioral test (placeholder) |
| test_cs024_placeholder | Behavioral test (placeholder) |
| test_cs026_placeholder | Behavioral test (placeholder) |

## Failures

None.
