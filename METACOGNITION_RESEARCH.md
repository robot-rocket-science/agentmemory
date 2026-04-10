# Meta-Cognition Research: "The System Needs to Know What It Knows"

**Date:** 2026-04-09
**Triggered by:** CS-003 -- agent had TODO.md but didn't consult it before asking user for direction.

---

## 1. Meta-Cognition in Cognitive Architectures

**SOAR** provides the strongest meta-cognitive mechanism via impasse-driven substates. When the procedural system cannot make progress (no applicable operators, ties in selection, insufficient knowledge), SOAR automatically creates a substate -- a new problem-solving context where the agent reasons *about its own reasoning*. The substate links to the superstate, giving it access to the parent context. This is recursive: substates can generate their own impasses. SOAR's meta-cognition is not bolted on; it emerges from the same architecture that handles object-level reasoning. (Laird, 2022, arXiv:2205.03854)

**CLARION** takes the opposite approach: an explicit Meta-Cognitive Subsystem (MCS) that monitors, controls, and regulates cognitive processes. CLARION separates explicit knowledge (associative rules) from implicit knowledge (neural networks), and the MCS operates over both. The MCS is architecturally distinct from the reasoning system it monitors. (Sun, 2016)

**ACT-R** has weaker meta-cognitive support. Its production system can fire rules about its own buffer states (a form of self-monitoring), but it lacks SOAR's recursive substates or CLARION's dedicated meta-cognitive module. Meta-cognition in ACT-R tends to be hand-coded into specific models rather than emerging from architectural primitives. (Laird & Mohan, 2022, arXiv:2201.09305)

**Key takeaway for us:** SOAR's impasse mechanism is the closest analog to our problem. The agent hits an impasse ("I don't know what to do next"), and instead of escalating to the user, it should create a substate that inspects its own knowledge (TODO.md). Our triggered beliefs are a lightweight version of SOAR's impasse-substate pattern, without the full recursive architecture.

## 2. Epistemic Logic: Formal Frameworks for "Knowing That You Know"

Epistemic logic formalizes knowledge and belief with modal operators K (knows) and B (believes):

- **S5 (knowledge):** Kp -> KKp (positive introspection: if you know p, you know that you know p) and ~Kp -> K~Kp (negative introspection: if you don't know p, you know you don't). S5 gives agents perfect self-awareness of their epistemic state. Unrealistic for real systems but defines the ideal.
- **S4 (weaker knowledge):** Has positive introspection (Kp -> KKp) but not negative introspection. You know what you know, but you may not know what you don't know. More realistic.
- **KD45 (belief):** Replaces the truth axiom (Kp -> p) with consistency (you don't believe contradictions). Has both positive and negative introspection for beliefs. Standard for modeling belief in multi-agent systems. (van Ditmarsch, 2015, arXiv:1503.00806; Fagin et al., 1995)

**Our failure maps to a violation of S4's positive introspection axiom.** The system believed "TODO.md contains my task list" (it stored this knowledge). But it did not know that it knew this -- it failed to access the meta-level fact "I have a TODO list" when deciding what to do next. In epistemic logic terms: Bp held but KBp did not. The system had the belief but lacked knowledge of that belief at decision time.

**Practical implication:** We don't need full S5 (that's omniscience). We need S4-level positive introspection for operational state: if the system has a state document, it should know it has that state document, and that knowledge should be accessible at decision points.

## 3. Self-Monitoring in LLM Agents (2024-2026)

Recent work directly relevant to our problem:

- **ReMA** (Wan et al., 2025): Multi-agent RL with a meta-thinking agent for strategic oversight paired with a low-level reasoning agent for execution. The meta-agent monitors and redirects the execution agent. Architecturally similar to CLARION's MCS.
- **MetaRAG** (Zhou et al., 2024): Adds explicit monitoring, evaluative criticism, and adaptive planning to retrieval-augmented generation. The system evaluates whether its retrieval was sufficient before generating.
- **Anthropic's introspection research** (Lindsey, 2025): LLMs show emergent introspective awareness -- they can detect changes in their own internal activations. But the capacity is "highly unreliable and context-dependent." Models detect the *strength* of an injected concept but cannot reliably identify its *content*. Separate "do I know this?" circuits operate independently from retrieval circuits. (transformer-circuits.pub/2025/introspection)
- **Knowledge boundary awareness** (Kale et al., 2025): LLMs can be prompted to assess their own factual limits and demarcate feasible from unanswerable tasks.

**Key takeaway:** LLMs have weak, unreliable introspection at the neural level. We cannot rely on the model "just knowing" what it knows. External scaffolding (our triggered beliefs, state registries) is necessary to compensate for what the model cannot do internally.

## 4. Metamemory: Feeling of Knowing and Judgment of Learning

Cognitive psychology distinguishes two metamemory judgments (Schwartz, 1994; Nelson & Narens, 1990):

- **Judgment of Learning (JOL):** "Will I remember this later?" -- a prediction about future recall, made at encoding time.
- **Feeling of Knowing (FOK):** "I know this but can't retrieve it right now" -- a real-time assessment during retrieval failure. The tip-of-the-tongue state.

For AI systems (Cox & Raja, 2011, ResearchGate): metamemory enables the system to judge whether it has enough information to complete a task ("judgment of learning") and to recognize retrieval failures ("I should have something about this but my search didn't find it").

**Our CS-003 failure is an FOK failure.** The system should have experienced a functional equivalent of "I feel like I have a task list somewhere" when it hit the decision point. Instead, it had no FOK signal at all -- it went straight to the user. A metamemory system would route the agent through a self-check: "Before asking the user, do I have any state documents that might answer this question?"

**Design implication:** We need a functional FOK -- a pre-retrieval check that fires before certain actions (asking the user, claiming validation, starting new work). This is exactly what triggered beliefs provide.

## 5. Event-Condition-Action Rules: Our Proposed Mechanism

ECA rules (Event-Condition-Action) are well-established in database systems and production rule engines. The pattern: when an **event** occurs, check a **condition**, then execute an **action**.

Our triggered beliefs map directly:

| Component | ECA Pattern | Our Implementation |
|-----------|------------|-------------------|
| Event | Database update, timer, external signal | "task_list_empty", "about_to_ask_user", "claiming_validation" |
| Condition | Query against current state | "TODO.md exists AND has items" |
| Action | Database operation, notification | "Retrieve and present TODO items instead of asking user" |

**Conflict resolution** matters when multiple rules fire. Production systems use specificity (more specific rules win) or priority ordering. For our triggered beliefs, priority should be: (1) safety/locked beliefs first, (2) user corrections second, (3) operational rules third, (4) learned patterns last.

**Forward chaining vs. backward chaining:** Our triggers are forward-chaining (event happens -> check conditions -> fire actions). This is simpler and more predictable than backward-chaining (goal appears -> find rules that could achieve it -> check if conditions hold). Forward chaining is the right choice for operational self-monitoring.

## 6. Connection to Our Scientific Method Model

The scientific method model (observe/believe/test/revise) already has the primitives. Meta-cognition extends them:

```
OBJECT LEVEL                          META LEVEL
-----------                           ----------
Observations about the project   -->  Observations about the system's own state
Beliefs about the domain         -->  Beliefs about what the system knows (meta-beliefs)
Tests of domain beliefs          -->  Tests of whether self-knowledge was accessed when needed
Revisions to domain beliefs      -->  Revisions to operational rules when self-monitoring fails
```

**Triggered beliefs are pre-programmed test conditions.** In the scientific method, you design experiments before you need them. Triggered beliefs are the same: we design the self-checks before the failure occurs. "When about to ask the user for direction, test whether TODO.md has items" is an experiment protocol written in advance.

**The feedback loop applies to meta-beliefs too.** If a triggered belief fires and the action was useful (agent consulted TODO.md and found relevant tasks), reinforce it. If it fires and the action was not useful (TODO.md was empty and irrelevant), downgrade it. Same confidence mechanics, same revision chain.

**Infinite regress risk is bounded.** Epistemic logic warns about Kp -> KKp -> KKKp chains. We bound this: meta-beliefs are loaded at L0 (always present), they are not themselves subject to meta-meta-beliefs, and they are locked (not revisable by the system, only by the user). Two levels: object beliefs and meta-beliefs. No third level.

---

## Summary of Recommendations

1. **Implement triggered beliefs as ECA rules** within the existing belief infrastructure. No new tables needed.
2. **Triggered beliefs operate at L0** -- always loaded, never subject to token budget trimming.
3. **Lock triggered beliefs by default** -- the system should not revise its own self-monitoring rules without user approval.
4. **Four initial triggers:** (a) before asking user for direction -> check TODO.md, (b) before claiming validation -> check REQUIREMENTS.md, (c) before starting work -> check recent completions, (d) after context compression -> verify locked beliefs survived.
5. **Bound the meta-level to two layers** (object + meta). No meta-meta-beliefs.

---

## Sources

- [Laird, 2022 - Introduction to the Soar Cognitive Architecture](https://arxiv.org/pdf/2205.03854)
- [Laird & Mohan, 2022 - Analysis and Comparison of ACT-R and Soar](https://arxiv.org/abs/2201.09305)
- [van Ditmarsch, 2015 - Introduction to Logics of Knowledge and Belief](https://arxiv.org/pdf/1503.00806)
- [Stanford Encyclopedia of Philosophy - Epistemic Logic](https://plato.stanford.edu/entries/logic-epistemic/)
- [Lindsey, 2025 - Emergent Introspective Awareness in LLMs](https://transformer-circuits.pub/2025/introspection/index.html)
- [Cox & Raja - Metacognition and Metamemory Concepts for AI Systems](https://www.researchgate.net/publication/235219069_Metacognition_and_Metamemory_Concepts_for_AI_Systems)
- [Wan et al., 2025 - ReMA: Multi-Agent Metacognition](https://www.emergentmind.com/topics/metacognitive-capabilities-in-llms)
- [Zhou et al., 2024 - MetaRAG](https://www.emergentmind.com/topics/metacognitive-capabilities-in-llms)
- [Kale et al., 2025 - Knowledge Boundary Awareness](https://www.emergentmind.com/topics/self-recognition-capabilities-in-llms)
- [ScienceDirect - Event-Condition-Action Rules](https://www.sciencedirect.com/topics/computer-science/event-condition-action-rule)
- [40 Years of Cognitive Architectures (Kotseruba & Tsotsos, 2018)](https://link.springer.com/article/10.1007/s10462-018-9646-y)
