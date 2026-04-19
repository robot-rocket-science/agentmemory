<sub>[<- Chapter 7 - Benchmark Protocol](BENCHMARK_PROTOCOL.md) . [Contents](README.md)</sub>

# Evaluation Protocol: Three-Part Quality Assurance

> **Live document.** Update after every evaluation run with lessons learned,
> gap fixes, and procedure refinements. Goal: after 2-4 runs this protocol
> executes flawlessly on subsequent iterations.

## Purpose

This protocol defines how to evaluate agentmemory rigorously. It has three
complementary parts that together cover correctness, capability, and
real-world impact:

| Part | What it proves | Tool | Cadence |
|------|---------------|------|---------|
| 1. Benchmarks | Retrieval quality vs published baselines | `pytest benchmarks/test_benchmark_suite.py` | Per release |
| 2. Acceptance Tests | Feature correctness per case studies | `uv run pytest tests/` | Every commit (CI) |
| 3. Session Metrics | Real-world user impact | `agentmemory metrics` | Weekly / per release |

No single part is sufficient. Benchmarks measure retrieval in isolation.
Acceptance tests verify features work. Session metrics measure whether
those features actually help users.

---

## Part 1: Benchmarks

**What:** Run 5 published benchmarks (MAB SH, MAB MH, StructMemEval,
LongMemEval, LoCoMo) against the current release using the
contamination-proof pytest suite.

**Protocol:** [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md)

**How to run:**

```bash
# Step 1: Run retrieval adapters (slow, ~30min total)
uv run pytest benchmarks/test_benchmark_suite.py -v --run-retrieval -m retrieval

# Step 2: Validate contamination (fast)
uv run pytest benchmarks/test_benchmark_suite.py -v -m contamination

# Step 3: Generate predictions via sub-agents (manual, uses Agent tool)
# See BENCHMARK_PROTOCOL.md for batch prompting instructions

# Step 4: Score + validate (fast)
uv run pytest benchmarks/test_benchmark_suite.py -v -m scoring

# Step 5: Full protocol validation (fast)
uv run pytest benchmarks/test_benchmark_suite.py -v
```

**Pass criteria:** 60/65 tests pass (5 retrieval tests skip without flag).
All contamination checks must pass. LoCoMo score must be below 93.57%
ceiling.

**Key metrics:**
- MAB SH 262K: SEM (target: >88%)
- MAB MH 262K: SEM (target: >7% paper ceiling)
- StructMemEval: Accuracy (target: 100%)
- LongMemEval: Opus judge accuracy (target: >59%)
- LoCoMo: F1 (target: >50%, note reader variance caveat)

**Lin methodology checklist:** Every benchmark run must produce a
methodology JSON with all 11 required fields. See BENCHMARK_PROTOCOL.md.

**After running:** Update `docs/BENCHMARK_RESULTS.md` with new numbers.
Save results to `benchmarks/results_<version>/`.

---

## Part 2: Acceptance Tests

**What:** 872 tests covering all 35 case studies, all requirements
(REQ-001 through REQ-027), scoring, classification, correction detection,
design decisions, and edge cases.

**How to run:**

```bash
# Full test suite
uv run pytest tests/ -x -q

# Acceptance tests only (case studies + requirements)
uv run pytest tests/acceptance/ -v

# Validation tests only (design decisions, score inflation, onboard)
uv run pytest tests/validation/ -v
```

**Pass criteria:** All tests pass. Zero tolerance for regressions.

**Key test categories:**
- `tests/acceptance/test_cs*.py` -- 27 tests for 11 case studies (CS-012 through CS-035)
- `tests/acceptance/test_req*.py` -- 25 tests for 6 requirements
- `tests/validation/test_design_decisions.py` -- 19 tests for open questions
- `tests/validation/test_score_inflation.py` -- 13 tests for Bayesian calibration
- `tests/test_scoring.py` -- 181 tests for scoring pipeline
- `tests/test_correction_detection.py` -- correction detection accuracy

**After running:** If new case studies or requirements are added, write
acceptance tests before marking them complete.

---

## Part 3: Session Metrics

**What:** Analyze real conversation logs to measure agentmemory's impact
on actual user sessions. This is the only evaluation that measures whether
the system helps users in practice.

**How to run:**

```bash
# Quick report from conversation logs
agentmemory metrics

# With JSON output for tracking over time
agentmemory metrics --output metrics_$(date +%Y%m%d).json
```

**Metrics computed:**

| Metric | Description | Source |
|--------|-------------|--------|
| Correction rate | User corrections per turn | Regex patterns on user turns |
| Memory-ON vs OFF | Correction rate comparison | Presence of mcp__agentmemory calls |
| Searches performed | How often memory is queried | MCP tool call detection |
| Feedback given | How often beliefs get scored | agentmemory DB sessions table |
| Beliefs created | System learning rate | agentmemory DB sessions table |
| Session velocity | Items per hour | agentmemory DB sessions table |
| Quality score | Composite session quality | Auto-computed on session end |

**Interpretation guide:**

- **Correction rate** should decrease over time as the system learns user
  preferences. Currently ~1.6% overall. Compare memory-ON vs OFF sessions,
  but note the confounding variable caveat (complexity differs).
- **Searches performed** indicates engagement. More searches = more
  retrieval opportunities = more chances for the system to help.
- **Feedback given** > 0 means the Bayesian feedback loop is active.
  Sessions with zero feedback indicate the loop isn't firing.
- **Quality score** is -1.0 to +1.0. Computed from feedback_rate,
  correction_density, and belief_creation. Higher is better.

**Known limitations (update as fixed):**

1. Memory-ON vs OFF comparison is confounded by session complexity.
   Memory-ON sessions tend to be development sessions (more corrections).
   Need a controlled experiment to isolate the effect.
2. Correction detection uses regex patterns that may miss subtle corrections
   or flag false positives (e.g., "don't" in a code instruction).
3. Only 11/365 sessions currently show agentmemory usage in conversation
   logs. This may undercount because hook-injected searches don't appear
   as visible tool calls in the log.
4. Session IDs differ between Claude (UUIDs) and agentmemory (12-char hex).
   Cannot join conversation log data with agentmemory DB sessions.

**After running:** Save the JSON output. Compare with previous runs.
Track correction rate trend over time. Update this section with any
new findings or procedure fixes.

---

## Combined Evaluation Checklist

Run before every release:

- [ ] `uv run pytest tests/ -x -q` -- all 872+ tests pass
- [ ] `uv run pytest benchmarks/test_benchmark_suite.py -v` -- 60/65 pass
- [ ] `agentmemory metrics --output metrics_<version>.json` -- report generated
- [ ] `docs/BENCHMARK_RESULTS.md` updated with current numbers
- [ ] `benchmarks/results_<version>/` directory committed
- [ ] Methodology metadata files populated (Lin checklist)
- [ ] README benchmark tables reflect current release

---

## Run Log

Track each evaluation run here. Note issues encountered and fixes applied.

### Run 1: v2.2.2 (2026-04-19)

**Benchmarks:** Full 5-benchmark re-run. MAB SH 92%, MAB MH 58%,
StructMemEval 100%, LongMemEval 59.6%, LoCoMo 50.8%.

**Issues found:**
- LoCoMo adapter had Mode 1 contamination bug in --retrieve-only mode
  (wrote answer + f1 into retrieval file). Fixed: commit d07eb2e.
- LoCoMo reader prompts lacked category-specific instructions (date hints,
  short-phrase constraint, inline forced-choice). Fixed: commit b69c0ba.
- Session-end hook used hardcoded import paths that failed outside the
  agentmemory project directory. Fixed: added session-complete CLI command.
- Quality score never auto-computed. Fixed: wired into session-complete.

**Session metrics:** 4319 turns, 365 sessions, 8 days of data.
Correction rate 1.64% overall. Memory-ON vs OFF comparison confounded.
Only 11 sessions show agentmemory usage in logs.

**Acceptance tests:** 872 passing.

**Protocol fixes applied:**
- Added pytest benchmark suite (65 tests) for protocol enforcement
- Added Lin methodology checklist to protocol
- Added LoCoMo ceiling check (93.57%)
- Added session-complete CLI command for portable hook
- Added agentmemory metrics CLI command
- Created this evaluation protocol document

### Run 2: (next release)

_(Fill in after next evaluation run)_
