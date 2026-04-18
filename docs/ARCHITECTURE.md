# Architecture

![agentmemory system architecture: ingestion, retrieval, and feedback pipeline](pipeline-architecture.svg)

Conversations become scored beliefs. Beliefs get stronger when they help, weaker when they hurt. The system learns what matters over time.

- **Bayesian confidence.** Beta-Bernoulli model with Thompson sampling. Beliefs that help get stronger; beliefs that hurt get weaker.
- **Multi-layer retrieval.** Locked constraints (L0) + behavioral directives (L1) + FTS5 keyword search (L2) + HRR structural bridge + BFS graph traversal (L3). Compressed to fit a token budget.
- **Graph-backed knowledge.** 12 edge types (SUPERSEDES, CONTRADICTS, SUPPORTS, CALLS, CITES, TESTS, IMPLEMENTS, RELATES_TO, TEMPORAL_NEXT, CO_CHANGED, CONTAINS, COMMIT_TOUCHES) enable multi-hop traversal and contradiction detection.
- **Correction detection.** 92% accuracy, zero LLM cost. Corrections auto-create high-confidence beliefs.
- **LLM classification.** Haiku classifies belief type/persistence at 99% accuracy, ~$0.005/session.
- **Project onboarding.** 8 extractors pull structure from git history, AST, docs, citations, tests, implementations, and directives.
- **Temporal decay.** Content-aware half-lives (facts 14 days, corrections 8 weeks, requirements 24 weeks). Session velocity scaling.
- **Per-project isolation.** Each project gets its own SQLite database at `~/.agentmemory/projects/<hash>/`.

For deeper architecture notes see [V2_ARCHITECTURE.md](V2_ARCHITECTURE.md).
