# Benchmark Execution Plan

## Goal

Run agentmemory against established benchmarks in an isolated environment to produce comparable scores.

## Benchmarks

### LoCoMo (Primary)
- **Paper:** Maharana et al., ACL 2024
- **Dataset:** https://snap-research.github.io/locomo/
- **What it measures:** Factual recall, multi-hop reasoning, temporal reasoning, open-ended questions across multi-session conversations
- **Baseline to beat:** 74% (Letta filesystem-only with gpt-4o-mini)
- **Leaderboard ceiling:** 92.3% (EverMemOS, cloud LLM, closed source)
- **Output:** F1 score, comparable to published leaderboard

### MemoryAgentBench (Secondary)
- **Paper:** arXiv:2507.05257 (ICLR 2026)
- **What it measures:** Accurate retrieval, test-time learning, long-range understanding, selective forgetting, multi-hop conflict resolution
- **Key number:** Multi-hop conflict resolution ceiling at 7% across all tested methods
- **Output:** Per-task accuracy scores

## Environment

### Option A: GCP VM (preferred for reproducibility)
- Fresh Ubuntu VM, no prior state
- Docker container with pinned Python version and dependencies
- agentmemory installed from clean git clone
- No project-specific data, no bleeding from personal usage
- Results and logs captured as artifacts

### Option B: server-a (cheaper, less isolated)
- Dedicated Docker container on server-a
- Clean volume mount, no shared state
- Risk: server-a has other processes that could affect timing benchmarks

### Recommendation: Option A for final results, Option B for development/debugging

## Interface Adapter

LoCoMo provides multi-session conversation transcripts with ground-truth Q&A pairs. agentmemory needs a thin wrapper:

1. **Ingest adapter:** Accept LoCoMo transcript format (speaker, utterance, session boundaries) and feed to agentmemory's ingest pipeline
2. **Query adapter:** Accept LoCoMo questions and translate to agentmemory search queries
3. **Response formatter:** Return agentmemory's retrieved content in LoCoMo's expected answer format
4. **Session boundary handler:** Signal session breaks to agentmemory so it treats each session as a separate conversation

## Execution Steps

1. Download LoCoMo dataset and understand format
2. Write ingest adapter (transcript -> agentmemory ingest calls)
3. Write query adapter (LoCoMo questions -> agentmemory search)
4. Write response formatter
5. Run on a small subset locally to verify the pipeline works
6. Provision GCP VM with Docker
7. Run full benchmark in container
8. Capture results, compute F1
9. Compare against leaderboard
10. Write honest analysis of results

## What to measure beyond the score

- Retrieval latency per query
- Token usage (how much context does agentmemory inject vs competitors)
- Which question categories agentmemory handles well vs poorly
- Whether the feedback loop improves scores over repeated sessions (LoCoMo is multi-session)
- Where corrections/supersessions appear in the dataset and whether agentmemory handles them

## Time estimate

- Adapter development: 1 day
- Local debugging: 0.5 days
- GCP setup + full run: 0.5 days
- MemoryAgentBench (if pursuing): 1 additional day
- Analysis and writeup: 0.5 days
- Total: 2-3 days

## Risks

- LoCoMo may test capabilities agentmemory doesn't have (e.g., open-ended generation requires an LLM, not just retrieval)
- The benchmark may favor systems that use cloud LLMs for synthesis (agentmemory is retrieval-focused)
- A mediocre score is still publishable if the analysis is honest about why
