# /mem:wonder Baseline Test (2026-04-11)

## Query
"how should core beliefs be ranked when confidence scores are flat and all beliefs have equal evidence"

## Context
First real test of /mem:wonder on a fresh DB with ~15k beliefs from a single bulk onboard. No conversation history ingested yet, no retrieval frequency data, no temporal variance.

## Results
- Returned 29 beliefs
- All scored 90% confidence (flat, as expected)
- Token budget: not reported (wonder uses 4000 default)

## Usefulness Assessment

### Genuinely useful beliefs surfaced (7/29):
1. "The metric should be 'how many wrong things does the system store that the human will have to fix?' not 'how many right things did we find?'" -- directly relevant reframe
2. "Recency + relevance scoring for ranking (no Bayesian confidence)" -- names an alternative approach
3. "Beta(50,50) and Beta(1,1) both have confidence 0.5, but the first means 'we're sure it's a coin flip' and the second means 'we have no idea'" -- important nuance about what confidence actually means
4. "Decay scoring should be implemented with the following priorities" -- points to existing design work
5. "Not all evidence is equal" -- relevant principle
6. "They are harmful when used as a multiplicative scoring factor for retrieval ranking" -- warning about a specific pitfall
7. "Weighted BFS path scoring uses SUPPORTS edge weights for ranking confidence" -- existing architecture decision

### Tangentially related but not actionable (12/29):
- Generic statements about confidence, evidence, ranking that don't help with the specific problem
- Statements about the system's architecture that are true but don't answer the question

### Noise (10/29):
- "D073: calls and puts are equal citizens" -- from alpha-seek domain, irrelevant
- "Not all checkmarks are equal" -- generic
- "Everything is equally soft" -- vague without context
- Statements about scheduling, schema, other topics that matched keywords but not intent

## Assessment
- **Precision: ~24% (7/29)** -- about 1 in 4 results were genuinely useful for the research question
- **The useful results WERE useful** -- they pointed to existing design decisions and research that directly inform the ranking problem. Without wonder, I would have had to manually search for these.
- **Noise is the main problem** -- FTS5 keyword matching pulls in anything with "confidence", "ranking", "evidence", "equal" regardless of whether it's about OUR ranking problem or some other context.
- **No subagent spawning happened** -- the CLI just dumped beliefs. The slash command instructions for spawning subagents weren't triggered because this was a CLI call, not a slash command invocation.

## What would improve this
1. **Better relevance filtering** -- FTS5 keyword matching is too broad. Semantic similarity (embeddings) would dramatically reduce noise.
2. **Context windowing** -- beliefs near useful beliefs in the document graph are more likely to be useful too. Graph traversal from high-scoring hits could surface related context.
3. **The subagent pattern** -- if wonder had spawned 4 agents to research different angles, the useful beliefs would have been amplified by additional research context rather than sitting in a flat list.
4. **Type filtering** -- corrections and requirements were more useful than generic factual statements in this query. Wonder could prioritize those.
