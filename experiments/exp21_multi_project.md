# Experiment 21: Multi-Project Belief Isolation and Cross-Pollination

**Date:** 2026-04-09
**Status:** Research
**Question:** How should the memory system handle multiple projects without contaminating context, while still sharing cross-cutting beliefs?

---

## 1. How Existing Systems Handle Multi-Project

**Mem0 (v0.1+):** Uses `user_id` + `app_id` + `run_id` as a composite key. Memories are scoped per app by default, but user-level memories span apps. No structural enforcement -- it's tag filtering on flat storage. Source: Mem0 docs, github.com/mem0ai/mem0.

**MemPalace:** Uses a wing/room/drawer hierarchy. Wings are top-level partitions (e.g., "work", "personal", "projects/project-a"). Rooms within wings hold related drawers. Cross-wing search is opt-in. The structure is spatial metaphor over SQLite, not hard isolation.

**Letta (ex-MemGPT):** Uses "agents" as isolation units. Each agent has its own archival memory, core memory, and recall storage. Cross-agent memory sharing requires explicit tool calls. Closest to true DB-level isolation. Source: github.com/letta-ai/letta.

**Pattern:** All three use soft namespacing (tags/keys/hierarchy) rather than hard isolation (separate DBs). The reason is practical -- users want cross-project search when they ask for it.

---

## 2. Privacy Within Local (REQ-017 Extension)

REQ-017 says fully local. But "local" is not sufficient for isolation. A user working on a proprietary trading strategy (project-a) and an open-source web app should not have project-a beliefs injected into web app context that gets sent to a cloud LLM via F4 (see PRIVACY_THREAT_MODEL.md).

**Concrete risk:** User works on project-a with local Ollama (no cloud leak). Switches to web-app project using Claude API. Memory system retrieves "Capital is $5K, sell puts on SPY" into the web-app session. That belief is now in the prompt sent to Anthropic's API. The user never consented to sharing trading strategy data with a cloud provider.

**Implication:** Project scoping is a privacy boundary, not just a convenience feature. Default behavior must be: beliefs from project A are NOT retrievable when working on project B, unless explicitly tagged as cross-project.

---

## 3. Cross-Cutting vs Domain Beliefs

Two belief categories with different scoping rules:

| Type | Examples | Scope | REQ Trace |
|------|----------|-------|-----------|
| **Behavioral** | "Use strict typing", "Don't use async_bash", "Keep responses concise" | ALL projects | REQ-021 (L0) |
| **Domain** | "Capital is $5K", "Use DuckDB for backtesting", "API key is in .env" | Single project | REQ-019, REQ-020 |

Behavioral beliefs are the user's preferences for how the agent acts. They transcend any project. Domain beliefs are facts, decisions, and constraints specific to a codebase or problem space.

**Edge case -- semi-cross-cutting beliefs:** "Always use uv for Python projects" is behavioral but only relevant to Python projects. Implementation: tag as behavioral + language:python. Filter at retrieval time.

---

## 4. Behavioral vs Domain Classification (REQ-021)

REQ-021 already requires behavioral beliefs in L0 regardless of task domain. Multi-project extends this: behavioral beliefs are the ONLY beliefs that should cross project boundaries by default.

Classification signal sources:
- **Explicit:** User marks a belief as behavioral ("always do X") or domain ("for this project, use Y")
- **Implicit:** Beliefs derived from user corrections (REQ-019) about agent behavior -> behavioral. Beliefs about project architecture, data, config -> domain.
- **Keyword heuristics:** "always", "never", "don't ever" -> likely behavioral. Project names, file paths, tech stack -> likely domain.

Misclassification cost: behavioral tagged as domain = user repeats correction in new project. Domain tagged as behavioral = context contamination. The second is worse (privacy leak via F4). Default should be domain-scoped; promotion to behavioral requires higher confidence.

---

## 5. Implementation Options

### Option A: Separate SQLite DBs per project
- Hard isolation. No accidental cross-contamination.
- Behavioral beliefs duplicated across DBs (sync problem).
- Cannot do cross-project search without opening multiple DBs.
- Migration pain when projects merge or restructure.
- **Verdict:** Too rigid. Duplication of behavioral beliefs creates the exact re-correction problem REQ-019 forbids.

### Option B: Single DB, namespace column
- One SQLite DB. Every belief/observation row has a `project_id` column (nullable = global).
- Retrieval queries always include `WHERE project_id = ? OR project_id IS NULL`.
- Behavioral beliefs get `project_id = NULL` (global scope).
- Domain beliefs get `project_id = 'project-a'` (project scope).
- Cross-project search: user explicitly opts in, query drops the WHERE filter.
- **Verdict:** Best balance. Single source of truth, soft isolation, easy to query.

### Option C: Tag-based filtering (Mem0 style)
- No structural enforcement. Beliefs have a `tags` array, project is one tag.
- Relies on query-time filtering -- if the filter is omitted, everything leaks.
- **Verdict:** Too fragile. A single missing filter = privacy violation.

**Recommendation: Option B.** Namespace column with NULL = global. Enforced at the query layer so callers cannot accidentally omit the project filter.

---

## 6. Graph Structure Implications

### Single graph, project-partitioned

One graph. Nodes carry a `project_id` attribute. Traversal respects partition boundaries:

- **Intra-project edges:** Normal traversal (CITES, SUPERSEDES, SUPPORTS, etc.)
- **Cross-project edges:** Only through behavioral/global nodes. A behavioral belief "use strict typing" can have APPLIED_IN edges to multiple projects, but traversal from project A cannot reach project B's domain nodes through this bridge.
- **Global partition:** Behavioral beliefs live in a virtual "global" partition. Always traversable from any project context.

```
[global/behavioral]          [project-a/domain]       [webapp/domain]
  "use strict typing" ----APPLIED_IN----> "tsconfig"
                       ----APPLIED_IN----> "mypy config"
  "don't use async"                       "capital=$5K"    "use React"
                                          "sell puts"      "PostgreSQL"
```

Traversal from webapp context: sees global nodes + webapp domain nodes. Cannot reach "capital=$5K" or "sell puts" even via shared behavioral nodes.

### Project detection

The MCP server needs to know which project is active. Options:
1. **CWD-based:** Infer from working directory (e.g., `/projects/project-a` -> project_id = "project-a"). Simple, fragile.
2. **Explicit parameter:** Every MCP tool call includes `project_id`. Reliable, verbose.
3. **Session-level:** Set project context once per session. MCP `set_project` tool. Balanced.

Recommendation: CWD-based with explicit override. Most sessions work in one project directory. Override handles edge cases.

---

## 7. Summary and Next Steps

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | Single DB, namespace column | Avoids behavioral belief duplication |
| Default scope | Project-isolated | Privacy-first; cross-project is opt-in |
| Behavioral beliefs | Global (NULL project_id) | REQ-021 already requires this |
| Graph partitioning | Soft partitions, bridge through globals only | Prevents domain leakage |
| Project detection | CWD-based + explicit override | Practical default with escape hatch |

Open questions for implementation:
- How to handle project rename/restructure (update project_id across rows?)
- Should the system warn when a domain belief looks cross-cutting ("you said this in project-a too")?
- Granularity: is project_id per-repo, per-directory, or user-defined?
