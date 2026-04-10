# Experiment 32 Results: HRR for Edge Discovery

**Date:** 2026-04-09
**Hypothesis:** HRR can discover sentence-to-sentence edges during onboarding without regex.
**Result:** FAILED. Precision 0.001, recall 0.005. Essentially random.

## What Went Wrong

The approach bound `node * parent * type` and tried to unbind `type` from another decision's superposition. The math doesn't work for this purpose:

```
unbind(type_j, S) = sum(node_i * parent_i * (type_i # type_j))
```

When types match, you get `node * parent` -- but comparing this against raw `node` vectors (without parent binding) doesn't produce meaningful similarity.

## What This Tells Us

HRR has two distinct capabilities:
1. **Encoding and traversing KNOWN relationships** -- VALIDATED (Exp 31: 5/5 recall on known CITES edges)
2. **Discovering NEW relationships from structure** -- INVALIDATED (this experiment)

HRR is excellent at (1) and not suitable for (2). The graph must be built by other means first, then encoded in HRR for traversal.

## For Onboarding

Graph construction should use:
- Regex/pattern matching for explicit citations (D###, M###, URLs, file paths)
- Content similarity (BoW, SimHash, or learned embeddings) for topical edges
- Co-occurrence within documents/sections for structural edges
- The LLM-in-the-loop `directive` tool for user-stated relationships
- The `remember`/`correct` tools for user-confirmed relationships

Then HRR encodes the constructed graph for fast typed traversal.

**HRR is the traversal layer, not the construction layer.**
