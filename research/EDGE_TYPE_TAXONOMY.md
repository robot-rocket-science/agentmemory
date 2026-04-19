# Edge Type Taxonomy for Automatic Graph Construction

**Date:** 2026-04-10
**Status:** Draft -- T0.1 research output
**Purpose:** Define the candidate universal and discoverable edge types for building belief graphs from arbitrary repositories.

---

## Design Principles

1. **Universal types must work on every repo with git history.** No language-specific or structure-specific assumptions.
2. **Discoverable types are inferred from project structure.** Language, build system, doc conventions determine which additional types apply.
3. **Types are directional.** A IMPORTS B != B IMPORTS A. Direction matters for HRR traversal (correlation is not commutative).
4. **Types must be orthogonal enough for HRR selectivity.** If two types always co-occur on the same edges, one is redundant. Measure overlap in T0.6.
5. **Types are not fixed per project.** The system discovers which types exist for a given repo. Different repos produce different type sets.

---

## Tier 1: Universal Types (git-derived, every repo)

These require only git history. No parsing, no language detection, no structure assumptions.

### CO_CHANGED
- **Source:** `git log --name-only`
- **Definition:** File A and file B were modified in the same commit.
- **Direction:** Undirected (symmetric).
- **Weight:** Number of commits where both appear. Higher weight = tighter coupling.
- **Noise control:** Exclude commits touching >50 files (merge commits, bulk reformats). Exclude .gitignore, lock files.
- **Expected density:** High. Most repos will have many co-change edges. Needs thresholding (e.g., weight >= 3) to be useful.
- **What it reveals:** Empirical coupling. Files that change together are related, regardless of whether they import each other.

### COMMIT_BELIEF
- **Source:** `git log --format` (commit messages) + `git log --name-only` (files touched)
- **Definition:** A commit message sentence asserts something about the files it touched.
- **Direction:** Directed. Belief -> File(s).
- **Node creation:** Each commit message is decomposed into sentences. Each sentence becomes a belief node. Each file touched becomes an edge target.
- **What it reveals:** WHY files changed. "Fix race condition in scheduler" tells you what was wrong and where.
- **Noise control:** Skip merge commits ("Merge branch..."), skip single-word messages ("wip", "fix").

### REFERENCES_ISSUE
- **Source:** Regex on commit messages: `#\d+`, `fixes #\d+`, `closes #\d+`, `resolves #\d+`
- **Definition:** A commit references an issue or PR number.
- **Direction:** Directed. Commit -> Issue/PR.
- **Node creation:** Issue numbers become nodes (even without fetching issue content -- the reference itself is the edge).
- **What it reveals:** Decision linkage. Connects implementation (files changed) to motivation (issue discussion).
- **Limitation:** Only works for repos using GitHub/GitLab issue conventions.

### SUPERSEDES_TEMPORAL
- **Source:** `git log` for same file at different times
- **Definition:** Content at time T2 supersedes content at time T1 for the same file/section.
- **Direction:** Directed. New version -> Old version.
- **Granularity:** File-level (easy) or hunk-level (harder, requires diff parsing).
- **What it reveals:** Belief evolution. What was true then vs now.
- **Practical use:** When retrieving a belief, check if it has been superseded.

### AUTHORED_BY
- **Source:** `git log --format=%aN`
- **Definition:** Person X authored/modified file Y.
- **Direction:** Directed. Person -> File.
- **What it reveals:** Expertise mapping. Who knows what.
- **Relevance:** Low for solo projects. High for multi-contributor repos (boa: 274, dealii: 388).

### Local vs Remote Commits as Distinct Node Types

Local commits and remote commits are **different node types** in the graph, not tags on the same type. They represent different epistemic states:

- **LOCAL_COMMIT_BELIEF** (unpushed, reflog-visible): "I think this is right." Tentative, may be rewritten, amended, or abandoned. Lower confidence. Exists only on the machine that authored it.
- **REMOTE_COMMIT_BELIEF** (pushed to Gitea/GitHub): "This is the decision." Finalized, published, durable. Higher confidence. Visible to all machines.

When a local commit is pushed, this creates a **SUPERSEDES** edge:
```
REMOTE_COMMIT_BELIEF --[SUPERSEDES]--> LOCAL_COMMIT_BELIEF
```
The local version existed first. The remote version replaces it with higher authority.

When a local commit is amended or rebased before pushing, the reflog captures the abandoned version:
```
LOCAL_COMMIT_BELIEF (new) --[SUPERSEDES]--> LOCAL_COMMIT_BELIEF (old, reflog-only)
```
The old version was the prior tentative belief, superseded by the rewrite.

This gives the graph a temporal belief-evolution chain: tentative local -> revised local -> finalized remote.

**Detection:**
- `git log --branches --not --remotes` shows local-only commits
- `git reflog` shows all local history including rebases and amends
- `git log origin/main..HEAD` shows commits ahead of remote

**Not applicable to public repos** -- we only have what was pushed.

**Multi-source history for personal projects:**
The user develops on two machines (lorax, server-a) and pushes to two remotes (Gitea on server-c:2222 for personal projects, GitHub for public contributions). This means:
- Gitea history = canonical "remote" for personal projects (receives pushes from both machines)
- Local reflogs on lorax and server-a = ephemeral in-progress commits
- GitHub = public contributions and issue tracking
- The research corpus on server-a has only pushed history (rsync'd .git, no reflog from lorax)
- For production use, the extractor should query both the repo's git log AND the local reflog to capture the full local/remote distinction.

**Multi-machine development complication:**
The same project (e.g., project-a) is developed on both lorax and server-a, with Gitea as the unifying remote. This means:
- Gitea has the union of all pushed commits from both machines
- lorax's reflog has lorax-local ephemeral commits (amends, rebases, abandoned branches)
- server-a's reflog has server-a-local ephemeral commits
- A commit authored on server-a and pushed to Gitea will appear in lorax's `git log` after a fetch, but NOT in lorax's reflog (it was never a local HEAD there)
- To get the full picture for a project, the extractor must: (a) pull from Gitea for all pushed history, (b) read the local reflog on whichever machine it's running on for ephemeral local history, (c) tag each commit with origin machine if determinable (author hostname, committer date alignment with reflog)
- The research corpus on server-a only has pushed history (rsync'd .git without lorax's reflog). This is sufficient for the graph construction experiments.

---

## Tier 2: Language-Discoverable Types (import/dependency parsing)

These require detecting the project language and parsing import statements. The system auto-detects which apply based on file extensions and build files.

### IMPORTS
- **Source:** Language-specific import parsing
- **Definition:** File A imports/includes/uses file B.
- **Direction:** Directed. Importer -> Imported.
- **Detection:**
  - Python: `import X`, `from X import Y`
  - Rust: `use crate::X`, `mod X`
  - TypeScript/JS: `import ... from 'X'`, `require('X')`
  - C/C++: `#include "X"` (local includes only, not system headers)
  - Go: `import "X"`
- **Resolution:** Must resolve import paths to actual file paths. This is the hard part (relative imports, re-exports, barrel files, path aliases).
- **What it reveals:** Explicit dependency structure. The backbone of code architecture.

### PACKAGE_DEPENDS_ON
- **Source:** Build system manifests
- **Definition:** Package A depends on package B (at package level, not file level).
- **Direction:** Directed. Dependent -> Dependency.
- **Detection:**
  - Cargo.toml: `[dependencies]`, `[workspace.members]`
  - package.json: `dependencies`, `devDependencies`, workspace `packages`
  - go.mod: `require`
  - CMakeLists.txt: `target_link_libraries`, `add_subdirectory`
  - pyproject.toml: `dependencies`
- **What it reveals:** Coarse-grained architecture. Which packages/modules depend on which.

---

## Tier 3: Structure-Discoverable Types (project conventions)

These require detecting specific project structures. The system checks for marker files/directories.

### TESTS
- **Source:** Naming convention matching
- **Definition:** Test file A tests source file B.
- **Direction:** Directed. Test -> Source.
- **Detection:**
  - Python: `test_foo.py` -> `foo.py`, `tests/test_foo.py` -> `src/foo.py`
  - Rust: `#[cfg(test)] mod tests` in same file (self-edge), or `tests/` directory
  - JS/TS: `foo.test.ts` -> `foo.ts`, `__tests__/foo.test.ts` -> `foo.ts`
  - C++: `test_foo.cpp` -> `foo.cpp`
- **What it reveals:** What code is tested and how.

### DOCUMENTS
- **Source:** Path/name matching between docs and code
- **Definition:** Document A describes code file/module B.
- **Direction:** Directed. Doc -> Code.
- **Detection:** `docs/auth.md` -> `src/auth/`, `README.md` references in markdown links.
- **What it reveals:** Which code has documentation and which doesn't.

### SERVICE_DEPENDS_ON
- **Source:** docker-compose.yml `depends_on`, `links`
- **Definition:** Service A depends on service B at runtime.
- **Direction:** Directed. Dependent -> Dependency.
- **Detection:** Parse docker-compose YAML.
- **What it reveals:** Runtime architecture. How services compose.

### CITES / DECISION_REFERENCE
- **Source:** Regex patterns in markdown: D###, M###, RFC-###, ADR-###
- **Definition:** Document A cites decision/milestone B.
- **Direction:** Directed. Citing -> Cited.
- **Detection:** Project-specific patterns. D### for GSD projects. ADR-### for ADR repos. RFC ### for spec projects.
- **What it reveals:** Decision lineage. How decisions reference and build on each other.
- **Generalization:** The regex patterns are project-specific, but the CITES type is universal. The system discovers which citation patterns exist by scanning for high-frequency alphanumeric patterns followed by numbers.

### IMPLEMENTS
- **Source:** Planning docs (requirement -> phase/file mapping)
- **Definition:** Code file A implements requirement/feature B.
- **Direction:** Directed. Implementation -> Requirement.
- **Detection:** .planning/ or .gsd/ directories with requirement-to-phase mappings.
- **What it reveals:** Traceability from requirements to code.

---

## Tier 4: Composite / Refined Types (derived from combining Tier 1-3)

These are not directly extracted but inferred by combining node types and edge sources.

### COUPLING (refined CO_CHANGED)
- **Rule:** CO_CHANGED edge where neither file imports the other.
- **What it means:** Files are coupled (change together) but have no explicit dependency. Often indicates shared assumptions, hidden coupling, or a missing abstraction.

### CROSS_BOUNDARY (refined CO_CHANGED + IMPORTS)
- **Rule:** CO_CHANGED edge that crosses package/module boundaries (different top-level directories, different Cargo workspace members).
- **What it means:** Cross-cutting concern. Changes in one module require changes in another.

### TEST_COVERAGE_GAP (refined TESTS)
- **Rule:** Source file with no TESTS edge pointing to it.
- **What it means:** Untested code.

### STALE_DOC (refined DOCUMENTS + SUPERSEDES_TEMPORAL)
- **Rule:** DOCUMENTS edge where the doc hasn't changed since the code was last modified.
- **What it means:** Documentation may be out of date.

---

## Discovery Protocol

When onboarding a new repo, the system runs this sequence:

1. **Detect language(s):** File extensions + build files from corpus_map.py manifest.
2. **Always extract:** Tier 1 types (git-derived). These work universally.
3. **Detect and extract Tier 2:** Based on detected languages, run applicable import parsers.
4. **Detect and extract Tier 3:** Based on structural markers (.planning/, docker-compose.yml, etc.), run applicable structural parsers.
5. **Derive Tier 4:** Combine Tier 1-3 edges with node types to produce refined types.
6. **Report type inventory:** For this repo, edges of types [CO_CHANGED: 1204, IMPORTS: 387, TESTS: 52, ...].

No manual configuration. The type set is the output of discovery, not an input.

---

## HRR Implications

Each edge type gets a random orthogonal vector in R^n. More types = more selectivity.

| Types in graph | Required DIM for orthogonality | Notes |
|---------------|-------------------------------|-------|
| 3-5 | 512+ | Sufficient separation |
| 6-10 | 1024+ | Comfortable |
| 11-15 | 2048+ | Our working dimension |
| 15+ | 4096+ | Unlikely to need more than 15 types |

The Tier 4 composite types are refinements of Tier 1-3 types. They share the same HRR edge vector as their parent type (CO_CHANGED -> COUPLING uses the CO_CHANGED vector). The refinement is metadata, not a new vector.

---

## Open Questions

- [ ] Should CO_CHANGED edges be thresholded by weight? If so, what threshold? (Experiment in T0.6)
- [ ] How do we handle files that appear in 100+ commits together (e.g., Cargo.toml and Cargo.lock)? Cap weight or exclude?
- [ ] For COMMIT_BELIEF, how do we decompose commit messages into sentences? Simple period-split or something smarter?
- [ ] For CITES, can we auto-detect citation patterns (e.g., "D\d{3}" appears 50+ times in markdown) without hardcoding?
- [ ] What's the minimum edge count per type for HRR to be useful? (A type with 2 edges isn't worth a vector.)
