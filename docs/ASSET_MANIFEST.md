# Asset Manifest (planning doc)

This file tracks the visual assets that live outside this repo (currently in
`~/projects/robotrocketscience`) and need to be copied in so the handbook can
embed them. Delete this file once every asset below is committed and wired up.

---

## Case-study cartoons

The six cartoons starring **Glitch** (snail) and **Clawd** (crab) already have
ASCII-art scripts in [`website-content/cartoons.md`](../website-content/cartoons.md).
The rendered image versions from the project writeup should live at the paths
below.

**Proposed home chapter:** new **Appendix A - Case Studies in Illustration**
at the end of the handbook, inserted after [Chapter 9 - Research
Freeze](RESEARCH_FREEZE_20260416.md). Each cartoon gets a short caption
linking to the source case study in `research/CASE_STUDIES.md`.

**Expected repo paths and slotting:**

| File (commit here) | Case study | Theme | Caption to use |
|---|---|---|---|
| `docs/images/cartoons/01-no-implementation.png` | CS-002 / CS-006 | Locked-scope violation: agent forgets research-only directive | "When locked beliefs are not enforced, scope creep returns every session." |
| `docs/images/cartoons/02-sycophantic-collapse.png` | CS-024 | Agent caves under mild questioning | "A single skeptical prompt should not collapse two weeks of work." |
| `docs/images/cartoons/03-task-41.png` | CS-020 | Entity-ID substitution ("exp40" instead of "exp41") | "The number was in the instruction. Verify entity IDs before acting." |
| `docs/images/cartoons/04-extensive-research.png` | CS-005 | Overclaiming rigor ("EXTENSIVE research... 2.5 hours") | "Do not overclaim rigor. Qualify the tier." |
| `docs/images/cartoons/05-validating-the-validation.png` | CS-007b | Conflating "not random" with "correct" | "Non-randomness is not correctness." |
| `docs/images/cartoons/06-big-numbers.png` | CS-008 | Impressive-sounding metrics that do not answer the question | "Precision without recall is not validation." |

**Wiring plan once files land:**
1. Create `docs/APPENDIX_CASE_STUDIES.md` with nav bar (prev: Chapter 9, contents, next: none).
2. Embed each cartoon inline, in the order above, with the caption and a link to the matching case study entry.
3. Update [`docs/README.md`](README.md) contents to list Appendix A.
4. Update root `README.md` documentation section to mention it.

---

## Benchmark charts

The writeup at [robotrocketscience.com/projects/agentmemory](https://robotrocketscience.com/projects/agentmemory)
contains per-benchmark charts that should be reused in the handbook for the
"numbers at a glance" experience the README currently lacks.

**Proposed home chapter:** [Chapter 8 - Benchmark Results](BENCHMARK_RESULTS.md),
with a hero chart also embedded in the root README above the benchmarks table.

**Expected repo paths and slotting:**

| File (commit here) | Depicts | Where it goes |
|---|---|---|
| `docs/images/benchmarks/overview.png` | All 5 benchmarks, agentmemory vs. best-published, single figure | Hero chart, placed immediately under the "Benchmarks" heading in root [`README.md`](../README.md) and at the top of [Chapter 8](BENCHMARK_RESULTS.md) |
| `docs/images/benchmarks/locomo.png` | LoCoMo F1: agentmemory 66.1% vs GPT-4o-turbo 51.6% | Chapter 8, inline with the LoCoMo section |
| `docs/images/benchmarks/mab-sh.png` | MAB single-hop 262K: Opus 90%, Haiku 62%, baselines | Chapter 8, MAB SH section |
| `docs/images/benchmarks/mab-mh.png` | MAB multi-hop 262K: 60% vs <=7% ceiling | Chapter 8, MAB MH section (the 8.6x headline) |
| `docs/images/benchmarks/structmemeval.png` | StructMemEval 100% (14/14) vs vector-store failure modes | Chapter 8, StructMemEval section |
| `docs/images/benchmarks/longmemeval.png` | LongMemEval 59.0% vs 60.6% GPT-4o | Chapter 8, LongMemEval section |
| `docs/images/benchmarks/version-progression.png` (optional) | v1.0 to v1.1 to v1.2 score trajectory | Chapter 8, methodology/history section |

**Wiring plan once files land:**
1. Embed each chart inline in Chapter 8 next to its prose section, with alt text describing the metric and the comparison.
2. Embed `overview.png` in the root `README.md` directly under `## Benchmarks` and above the note block, so readers see the headline visual before the caveat and the table.
3. Add the `overview.png` to the "At a glance" region of Chapter 8 as well.
4. Update [Chapter 9 - Research Freeze](RESEARCH_FREEZE_20260416.md) to reference `version-progression.png` if it lands.

---

## Other assets from the writeup

If the writeup has additional diagrams beyond what is listed above (for
example, a belief-lifecycle illustration or a retrieval-layer animation), the
natural homes are:

- **Retrieval-layer or belief-lifecycle diagrams** -> [Chapter 5 - Architecture](ARCHITECTURE.md), next to the existing pipeline SVG.
- **Onboarding / ingestion illustrations** -> [Chapter 1 - Installation](INSTALL.md) Step 5 (onboard).
- **Obsidian screenshots beyond the current graph view** -> [Chapter 4 - Obsidian Integration](OBSIDIAN.md).

Drop them in `docs/images/<topic>/<name>.png` and tell me what they depict and
I will wire them into the correct chapter.

---

## Format notes

- PNG is preferred for photographic/illustrative assets (cartoons, charts with gradients).
- SVG is preferred for flat diagrams (the existing `pipeline-architecture.svg` is a good template).
- Target width in rendered markdown is roughly 780 px, matching the writeup's `<img>` style.
- Please commit the source file alongside the export when feasible (for example, `cartoon-01.excalidraw` or `chart-locomo.py` next to the PNG) so future edits do not require reverse-engineering.
