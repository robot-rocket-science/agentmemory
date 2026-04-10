---
name: Session feedback
description: Corrections and confirmed preferences from working sessions on agentmemory
type: feedback
---

Do not describe fast research sprints as "extensive." All research in this project was done in ~1 day of prompting. New agents must calibrate accordingly (see CS-005).
**Why:** CS-005 case study -- agent said "extensive research" when it was 2-3 hours of work. Direct user correction.
**How to apply:** On session start, check velocity and rigor tier before reporting status. Use hedged language for hypothesis-tier findings.

---

Leave thresholds and unknown numbers as TBD rather than guessing. Numbers come from experiments.
**Why:** User explicitly prefers this. Forced numbers without experimental grounding are noise.
**How to apply:** Wherever a threshold appears in design docs, mark TBD if not yet experimentally derived.

---

When math rendering won't work (terminal/Claude Code), use ASCII math notation, not LaTeX.
**Why:** User pointed out LaTeX was rendering as raw strings in the terminal.
**How to apply:** Always use plain ASCII for math in Claude Code sessions. No $$ or \frac{}{} etc.

---

The interview loop for uncertainty resolution should be multi-turn, not a single question.
**Why:** User corrected the initial design which said "one question per gap." GSD interview sessions loop until clarity is achieved.
**How to apply:** Interview pattern = loop until uncertainty below threshold (TBD), not one-shot question.

---

CONTRADICTS and SUPPORTS edges both contribute to an uncertainty estimate (conflict_ratio), not just separate traversal operators.
**Why:** User corrected the initial edge weight design which treated them independently.
**How to apply:** conflict_ratio = contradict_weight / total_weight. Near 0.5 = maximum uncertainty. Both directions feed the signal.

---

Do NOT penalize/deprioritize heavily-contradicted nodes in traversal. Do the opposite -- surface them urgently.
**Why:** User corrected a design that would have buried conflicts by routing around contradicted nodes. Contradictions must surface quickly for the interview loop to resolve them.
**How to apply:** Contradicted nodes sort to the TOP of the escalation queue. Weighted BFS path scoring uses SUPPORTS weights for confidence ranking; CONTRADICTS is a separate escalation signal, not a traversal penalty.
