# High-Context Injection: From Database Dump to Shared Understanding

## Origin

On 2026-04-17, agentmemory failed to prevent an error that its own data could have prevented. The system had a locked belief ("robotrocketscience is public-facing") that was stale -- GitHub had locked the account. The agent was corrected 3 times before adapting. The user observed: Japanese is a high-context language that conveys complex technical information implicitly because both parties share deep background context. The memory system should create that same shared background between itself and the LLM.

This document synthesizes research from three parallel investigations into how high-context communication works, how it maps to context injection, and what the injection format should look like.

---

## 1. How High-Context Communication Works

### Hall's Theory (1959)

Edward Hall identified that high-context cultures (Japanese, Arabic, Korean) encode meaning in the surrounding context rather than the words themselves. Specific mechanisms:

- **Implicit rejection**: "We'll consider it" means "no" in Japanese business. The listener decodes from context and relationship.
- **Shared history as bandwidth**: Years of in-group interaction create a compression layer where participants know what to do without explicit instruction.
- **Silence as signal**: Absence of comment means "as expected." Explicit statement means deviation.

Source: Hall, E.T. (1959). *The Silent Language*. Doubleday.

### Ba (Shared Context Space)

Nonaka and Konno (1998) formalized **ba** (place/field) -- a shared space where knowledge creation happens through co-presence. Ba is not a container for information but a relational context that enables tacit-to-tacit knowledge transfer. It works because participants share enough experiential overlap that explicit articulation becomes unnecessary.

Source: Nonaka, I., Konno, N. (1998). "The Concept of Ba." *California Management Review*, 40(3).

### Grice's Cooperative Principle (1975)

Speakers follow four maxims (quantity, quality, relation, manner). **Implicature** arises when speakers appear to violate a maxim -- listeners infer the intended meaning by assuming cooperation. These inferences are "calculated in light of everything in the common ground."

Recent LLM research shows models achieve 76-80% on implicature tasks but struggle with manner implicatures specifically, suggesting they handle surface-level pragmatics but not deeper contextual inference.

Sources:
- Grice, H.P. (1975). "Logic and Conversation." *Syntax and Semantics 3*.
- Pragmatics in LLMs survey: https://arxiv.org/html/2502.12378v2
- Manner implicatures in LLMs: https://www.nature.com/articles/s41598-024-80571-3

### Clark's Common Ground (1996)

Communication is a joint activity, not one-way signal. Meaning is co-constructed. Common ground -- mutual knowledge, beliefs, and assumptions shared by interlocutors -- is the substrate on which all pragmatic inference operates. Without it, implicature fails.

Source: Clark, H.H. (1996). *Using Language*. Cambridge University Press.

### Expert-to-Expert Compression

Expert communication achieves extreme compression through **knowledge encapsulation**: lower-level concepts nest within higher-order ones through repeated use, becoming single addressable units. "Race condition in the cache invalidation path" is 8 words to an expert, 500 words to a junior. Shared technical vocabulary functions as pointers into shared mental models, not as self-contained descriptions.

### Cognitive Science: Schemas and Frames

Fillmore's Frame Semantics (1982): words activate structured knowledge representations. "Buy" evokes an entire commercial transaction frame with roles (buyer, seller, goods, money) -- none need to be stated. Schank and Abelson's Scripts (1977): stereotyped event sequences let people process new input by matching against stored templates.

The common thread: the brain does not process input in isolation. Every new piece of information activates a web of background knowledge. Comprehension is pattern-completion, not decoding.

Sources:
- Fillmore, C.J. (1982). "Frame Semantics." https://brenocon.com/Fillmore%201982_2up.pdf
- Schank, R.C., Abelson, R.P. (1977). *Scripts, Plans, Goals, and Understanding*.

---

## 2. How This Maps to AI Context Injection

### Context Quality Beats Quantity

LLM performance initially improves then **declines** as retrieved passages increase, due to attention scattering ("Lost in the Middle" effect). Hard negatives from strong retrievers are particularly damaging. Every model tested degraded as input grew, some dropping from 95% to 60% past a threshold.

**Implication**: inject fewer, higher-confidence beliefs. Not "everything above a threshold."

Sources:
- Long Context vs. RAG (ICLR 2025): https://arxiv.org/abs/2501.01880
- Databricks RAG research: https://www.databricks.com/blog/long-context-rag-performance-llms

### Operational Heuristics Beat Raw Facts

Anthropic's context engineering guide explicitly recommends: instructions should be "specific enough to guide behavior effectively, yet flexible enough to provide strong heuristics." The guide warns against stuffing exhaustive facts, favoring "diverse canonical examples that portray expected behavior."

"Use yoshi280 when pushing" is a better injection than "robotrocketscience is locked" because it gives the model an actionable heuristic rather than a fact requiring inference.

Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

### Compiled Context Outperforms Raw Chunks

Document-level metadata appended to chunks outperforms chunk-level LLM-generated summaries, boosting QA accuracy from ~55% to ~73%. Structured metadata and document-level context beats per-chunk summarization.

Sources:
- Snowflake RAG: https://www.snowflake.com/en/engineering-blog/impact-retrieval-chunking-finance-rag/
- Anthropic Contextual Retrieval: https://towardsdatascience.com/understanding-context-and-contextual-retrieval-in-rag/

### Common Ground Tracking in Dialogue Systems

MindDial (2023) introduces explicit mind modules tracking three belief levels: speaker's belief, listener's belief, and speaker's prediction of listener's belief. Common Ground Tracking (CGT) focuses on the shared proposition space all participants accept as true.

Sources:
- MindDial: https://arxiv.org/abs/2306.15253
- CGT: https://arxiv.org/abs/2403.17284

### Claude-Specific Context Placement

Anthropic's guidance: place long documents at the top, queries at the bottom (up to 30% improvement). Use XML tags or markdown headers to delineate sections. Context should be "the smallest set of high-signal tokens that maximize the likelihood of some desired outcome."

Sources:
- https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

### Shared Mental Models in Human-AI Teams

Kaur (2024) and multiple ICIS 2025 papers identify three mechanisms: data contextualization, reasoning transparency, and performance feedback. When humans lack adequate domain mental models, they cannot verify AI recommendations.

Sources:
- https://www.semanticscholar.org/paper/Building-Shared-Mental-Models-between-Humans-and-AI-Kaur/bc47b075dcbb2a170740d5da1d51d954efb62748
- https://arxiv.org/abs/2510.08104

---

## 3. Proposed Injection Redesign: The "Ba" Protocol

### Current Format (failed)

```
AGENTMEMORY: 12 belief(s) relevant to your prompt:
[39% LOCKED 6d] (correction) yoshi280 is private, robotrocketscience is public-facing
[28% 6d] (requirement) Always use uv for Python
[25% 6d] (factual) agentmemory repo hosted on GitHub
...
```

This is low-context communication: every fact stated explicitly, weighted numerically, presented without relationship to other facts. The LLM processes it as independent assertions, not a coherent situational picture.

### New Format: Three Zones

A Japanese technical manual handling a status change would not re-enumerate all known facts. It would note the deviation and assume the reader already knows the background. The injection should work the same way: establish shared ground, flag deviations, then list applicable constraints.

```
== OPERATIONAL STATE ==
[!] robotrocketscience GitHub account is LOCKED (changed 2h ago, overrides prior belief that it was public-facing)
[!] yoshi280 is now the only active GitHub account for public repos

== STANDING CONSTRAINTS ==
- Use uv for all Python package management
- Do not commit large data files
- Commits: atomic, concise, no co-authorship lines

== BACKGROUND (assume true unless contradicted above) ==
- agentmemory repo hosted on GitHub under yoshi280
- Project is in Phase 4, 260 tests passing
- 3 git remotes: origin (gitea), github (yoshi280), github-rrs (robotrocketscience)
```

### Design Principles

**1. State-change-first (deviation from norm).** The top zone contains only things that recently changed or contradict a prior assumption. Silence means "as expected." This is the Japanese pattern: explicit statement signals deviation, not confirmation.

**2. Constraints as imperatives, not scored facts.** The middle zone drops confidence percentages for locked constraints. A locked belief is a rule. "[39% LOCKED]" undermines authority -- 39% reads as uncertain. Rules are stated once, plainly.

**3. Background as shared assumption.** The bottom zone is context the LLM should take as given unless the top zone overrides it. This creates ba -- the LLM assumes these are true and only re-evaluates when something in the deviation zone contradicts them.

### Implementation

The formatter classifies `ScoredBelief` results into three buckets:

- **State changes**: `belief_type == "correction"` created in last 72h, or any belief that supersedes another via SUPERSEDES edges. Formatted with `[!]` prefix and explicit mention of what it overrides.
- **Standing constraints**: All locked beliefs. Bare imperative statements, no scores.
- **Background**: Everything else above relevance threshold. Dash-prefixed assertions, no metadata.

---

## 4. Key Insight

The goal is not maximum information transfer. It is maximum **inferential leverage** per token. Two experts communicate efficiently not because they transmit more data, but because each word activates a dense web of shared context. The injection system should function the same way: not a dump of everything potentially relevant, but a compressed, structured signal that activates the right reasoning frame in the LLM.

The three-zone format achieves this by separating signal types (deviations vs rules vs background) so the LLM knows which processing mode to apply to each section, rather than evaluating 50 scored items with identical formatting.
