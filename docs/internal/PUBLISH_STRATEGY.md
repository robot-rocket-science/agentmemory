# Publish Strategy Decision

**Date:** 2026-04-16 08:45 UTC

## Decision

Publish the article and code under MIT license.

## Rationale

1. **Anthropic ecosystem play.** The system runs on MCP, uses Claude Code
   hooks, spawns Claude subagents. Every user of agentmemory is a paying
   Anthropic customer. Open-sourcing makes Claude more valuable, not less.

2. **Code without understanding is not threatening.** The real value is the
   85 experiments, failure taxonomy, contamination protocol, and the judgment
   calls that produced the results. A competitor can clone the repo, but the
   methodology took weeks of disciplined research. That transfers through
   hiring, not through `git clone`.

3. **Public repo is a stronger signal than a private demo.** Published code
   with documented contamination history, honest failure reporting, and a
   code audit is verifiable. That is what a research-oriented hiring team
   evaluates.

4. **Competitive risk is overstated.** The memory systems space is crowded
   (Mem0, Letta, Zep, Graphiti, dozens of papers). The differentiator is
   methodology and results, not code. Publishing raises visibility in a way
   that secrecy cannot.

## Framing Constraints

Two claims must be stated precisely:

1. **Multi-hop:** "Demonstrates a viable approach that breaks through a
   published ceiling" (7% to 55%, 7.8x). NOT "solves the problem." 45%
   still fails. The article handles this correctly.

2. **LongMemEval:** "Matches the published baseline" (59.0% vs 60.6%,
   -1.6pp). Uses Opus as judge, not GPT-4o as the paper specifies.
   The comparison has an asterisk until the same judge is used. The
   article discloses this.

## Execution Plan

- Publish the article on robotrocketscience (public GitHub) first.
- Benchmark code and experiment docs are included.
- Production `src/agentmemory/` can be delayed by a few weeks if desired,
  to have the Anthropic conversation first. The article, experiment docs,
  and benchmark code are the proof of work; the production modules are the
  implementation detail.

## Git Repos

- **robot-rocket-science** (public GitHub): public-facing, shares source code (renamed from yoshi280 on 2026-04-18)
- **Gitea** (internal): configuration control, primary development repo

Note: The `robotrocketscience` (no hyphens) GitHub account is locked by GitHub. The active public account is `robot-rocket-science` (with hyphens).
