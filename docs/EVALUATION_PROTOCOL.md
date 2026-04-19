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

### 3A. Core metrics

| Metric | Description | Source |
|--------|-------------|--------|
| Correction rate | User corrections per turn (FP-adjusted) | Regex patterns + false positive filter |
| Session velocity | Messages per session, sessions per day | Conversation logs grouped by session_id |
| Message length trend | Avg chars per user/assistant message (token proxy) | Conversation log text field |
| Quality score | Composite session quality (-1.0 to +1.0) | Auto-computed on session end |

### 3B. Git-derived metrics

| Metric | Description | Source |
|--------|-------------|--------|
| Fix commit rate | Percentage of commits that are bug fixes | `git log --grep=^fix:` |
| Rework concentration | Files with most fix commits | `git log --diff-filter=M --grep=^fix:` |
| Feature velocity | New feature commits per day | `git log --grep=^feat:` |

### 3C. Cross-machine analysis

| Metric | Description | Source |
|--------|-------------|--------|
| Dev-server history | Pre-memory baseline (Feb-Mar) | `ssh dev-server "cat ~/.claude/history.jsonl"` |
| Workstation logs | Memory-active period (Apr+) | `~/.claude/conversation-logs/` |
| Per-project breakdown | Correction rate by project and day | Both sources, grouped by cwd/project |

**How to run:**

```bash
# Quick report
agentmemory metrics

# With JSON output for tracking
agentmemory metrics --output metrics_$(date +%Y%m%d).json

# Git metrics (run from agentmemory project root)
git log --since="30 days ago" --format="%ai|%s" | \
  awk -F'|' '{day=substr($1,1,10); if($2~/^fix/) fix[day]++; total[day]++} \
  END {for(d in total) printf "%s  %d/%d = %.0f%% fixes\n", d, fix[d]+0, total[d], (fix[d]+0)/total[d]*100}' | sort

# Cross-machine (requires SSH to dev-server)
ssh dev-server "cat ~/.claude/history.jsonl" > /tmp/dev-server-data/history.jsonl
uv run python scripts/backfill_session_metrics.py
```

**Interpretation guide:**

- **Correction rate** (FP-adjusted): target is decreasing over time.
  Measured at 0.97% (workstation, Apr 10-19) with 55% pattern precision.
  Compare across project phases, not raw on/off (too confounded).
- **Session velocity**: stable at ~40 msgs/session. Shorter sessions with
  same output = memory helping. Longer sessions = deeper work (ambiguous).
- **Message length**: tracks token usage proxy. Actual API token counts
  are not yet captured (gap to fix).
- **Fix rate**: expected to increase during hardening phases, decrease
  during stable periods. 13% overall for Apr 10-19.
- **Rework files**: server.py (8 fixes), store.py (6), hook_search.py (4).
  High rework in core modules is normal during active development.

**Baseline data (Run 1, 2026-04-19):**

| Metric | Dev-server (Feb-Mar) | Workstation (Apr) | Note |
|--------|-----------------|-------------|------|
| Messages analyzed | 2,642 | 2,358 | Different log formats |
| Correction rate (raw) | 0.23% | 1.78% | Not comparable (different work) |
| Correction rate (FP-adjusted) | N/A | 0.97% | 55% precision |
| Correction trend | flat | 1.7% -> 0.5% | Suggestive, not significant |
| Avg user msg length | 85 chars | 1,100 chars | Different usage patterns |
| Fix commit rate | N/A | 13% (49/381) | Expected for dev phase |
| Session velocity | N/A | 40 msgs/session | Stable from Apr 14 |

**Known limitations (update as fixed):**

1. Memory-ON vs OFF comparison is confounded by session complexity.
   Memory-ON sessions tend to be development sessions (more corrections).
   Need a controlled experiment to isolate the effect.
2. Correction detection has 55% precision. Major false positive sources:
   quoting correction examples in docs, benchmark data containing "actually",
   code comments with "don't". Needs ML-based or LLM-based classifier.
3. MCP tool calls (search, remember, correct) do NOT appear in conversation
   logs -- they happen server-side via hooks. Cannot distinguish memory-on
   from memory-off sessions using log data alone.
4. Session IDs differ between Claude (UUIDs) and agentmemory (12-char hex).
   Cannot join conversation log data with agentmemory DB sessions.
5. No actual API token counts. Message character length is a rough proxy.
   Need to instrument the MCP server to log tokens consumed per search.
6. Dev-server and workstation data is not comparable (different log formats,
   different project types, different time periods).

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

**Session metrics (deep analysis):**

Cross-machine analysis: 5,000 messages across dev-server (Feb 2-Mar 9, 2,642 msgs)
and workstation (Apr 10-19, 2,358 msgs).

| Metric | Result |
|--------|--------|
| Overall correction rate | 0.97% (FP-adjusted, workstation only) |
| Pattern precision | 55% (19/42 matches are false positives) |
| Phase trend | 1.7% (early) -> 1.4% (hooks) -> 0.5% (stable) |
| Dev-server baseline | 0.23% (not comparable, different work types) |
| Session velocity | Stable at ~40 msgs/session from Apr 14 |
| Fix commit rate | 13% overall (49/381 commits) |
| Top rework files | server.py (8), store.py (6), hook_search.py (4) |
| Token proxy | ~1,100 chars/user msg (workstation), ~85 chars (dev-server) |

mem:reason verdict: UNCERTAIN. Cannot prove memory reduces corrections
with current data. Suggestive trend but n=24 true corrections is
insufficient for statistical significance.

**Acceptance tests:** 872 passing.

**Protocol fixes applied:**
- Added pytest benchmark suite (65 tests) for protocol enforcement
- Added Lin methodology checklist to protocol
- Added LoCoMo ceiling check (93.57%)
- Added session-complete CLI command for portable hook
- Added agentmemory metrics CLI command
- Added git-derived metrics (fix rate, rework concentration)
- Added cross-machine analysis (dev-server SSH, history.jsonl parsing)
- Fixed dev-server SSH config (Tailscale IP -> LAN IP)
- Created this evaluation protocol document

**Gaps identified for Run 2:**
- Improve correction pattern precision from 55% to >80%
- Add actual API token counting (not just message char length)
- Design controlled A/B experiment for correction burden
- Accumulate 3+ months of data for trend significance

### Run 2: (next release)

_(Fill in after next evaluation run)_
