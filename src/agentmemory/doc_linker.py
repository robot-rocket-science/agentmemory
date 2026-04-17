"""Document linking pipeline for Obsidian vault integration.

Scans project documents (.md files), extracts cross-references
(REQ-###, CS-###, Exp ##, belief IDs), and exports them as
Obsidian vault notes with wikilinks. Creates bidirectional links
between documents and beliefs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agentmemory.store import MemoryStore

# ---------------------------------------------------------------------------
# Reference patterns
# ---------------------------------------------------------------------------

# REQ-001 through REQ-999
_REQ_RE: Final[re.Pattern[str]] = re.compile(r"\bREQ-(\d{3})\b")
# CS-001 through CS-999
_CS_RE: Final[re.Pattern[str]] = re.compile(r"\bCS-(\d{2,3})\b")
# Exp 1, Exp 5b, Exp 62, etc.
_EXP_RE: Final[re.Pattern[str]] = re.compile(r"\bExp\s+(\d{1,3}[a-z]?)\b")
# Decision D### (from cross-project refs)
_DECISION_RE: Final[re.Pattern[str]] = re.compile(r"\bD(\d{3})\b")
# 12-char hex belief IDs in text (not already in wikilinks)
_BELIEF_ID_RE: Final[re.Pattern[str]] = re.compile(r"\b([0-9a-f]{12})\b")

# Directories to skip when scanning for documents
_SKIP_DIRS: Final[frozenset[str]] = frozenset({
    "beliefs", "_index", "_dashboards", "_canvas", "_archive",
    ".obsidian", ".venv", ".git", "__pycache__", "node_modules",
    ".claude", "dist", "build", ".egg-info",
})


@dataclass
class DocRef:
    """A cross-reference found in a document."""
    ref_type: str  # "REQ" | "CS" | "EXP" | "DECISION" | "BELIEF"
    ref_id: str    # e.g., "003", "006", "44", "a1b2c3d4e5f6"
    display: str   # e.g., "REQ-003", "CS-006", "Exp 44"


@dataclass
class ProjectDoc:
    """A project document with extracted metadata and references."""
    original_path: Path
    relative_path: str
    title: str
    doc_type: str  # "research" | "experiment" | "case_study" | "design" | "other"
    content: str
    refs: list[DocRef] = field(default_factory=lambda: [])


@dataclass
class LinkResult:
    """Result of the document linking pipeline."""
    docs_exported: int
    refs_linked: int
    belief_refs_added: int
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Document scanning
# ---------------------------------------------------------------------------

def _classify_doc(rel_path: str, filename: str) -> str:
    """Classify a document by its path and name."""
    lower: str = rel_path.lower()
    fname: str = filename.lower()
    if "experiment" in lower or lower.startswith("experiments/") or fname.startswith("exp"):
        return "experiment"
    if "case_stud" in lower or "cs-" in fname:
        return "case_study"
    if "requirement" in lower or "req" in fname:
        return "requirement"
    if any(w in lower for w in ("research", "architecture", "design", "pipeline", "approach")):
        return "research"
    if "benchmark" in lower or "results" in lower:
        return "benchmark"
    return "other"


def scan_project_docs(project_path: Path) -> list[ProjectDoc]:
    """Scan a project directory for markdown documents.

    Skips vault output directories, .venv, .git, etc.
    Extracts title from first H1 heading or filename.
    """
    docs: list[ProjectDoc] = []

    for md_file in sorted(project_path.rglob("*.md")):
        # Skip excluded directories
        parts: tuple[str, ...] = md_file.relative_to(project_path).parts
        if any(p in _SKIP_DIRS for p in parts):
            continue
        # Skip files in the vault output
        if any(p.startswith("_") for p in parts[:-1]):
            continue

        try:
            content: str = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel_path: str = str(md_file.relative_to(project_path))

        # Extract title from first H1 or filename
        title: str = md_file.stem
        for line in content.split("\n")[:10]:
            if line.startswith("# "):
                title = line[2:].strip()
                break

        doc_type: str = _classify_doc(rel_path, md_file.name)

        doc: ProjectDoc = ProjectDoc(
            original_path=md_file,
            relative_path=rel_path,
            title=title,
            doc_type=doc_type,
            content=content,
        )
        docs.append(doc)

    return docs


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------

def extract_refs(content: str) -> list[DocRef]:
    """Extract all cross-references from document content."""
    refs: list[DocRef] = []
    seen: set[str] = set()

    for match in _REQ_RE.finditer(content):
        key: str = f"REQ-{match.group(1)}"
        if key not in seen:
            seen.add(key)
            refs.append(DocRef("REQ", match.group(1), key))

    for match in _CS_RE.finditer(content):
        key = f"CS-{match.group(1)}"
        if key not in seen:
            seen.add(key)
            refs.append(DocRef("CS", match.group(1), key))

    for match in _EXP_RE.finditer(content):
        key = f"Exp-{match.group(1)}"
        if key not in seen:
            seen.add(key)
            refs.append(DocRef("EXP", match.group(1), f"Exp {match.group(1)}"))

    for match in _DECISION_RE.finditer(content):
        key = f"D{match.group(1)}"
        if key not in seen:
            seen.add(key)
            refs.append(DocRef("DECISION", match.group(1), key))

    return refs


def find_beliefs_mentioning_doc(
    store: MemoryStore,
    doc_title: str,
    doc_refs: list[DocRef],
) -> list[str]:
    """Find belief IDs whose content mentions this document or its references.

    Searches for the document title and key reference IDs in belief content.
    """
    search_terms: list[str] = [doc_title]
    for ref in doc_refs[:10]:  # limit to avoid huge queries
        search_terms.append(ref.display)

    belief_ids: set[str] = set()
    for term in search_terms:
        # Use FTS5 search via the store
        try:
            rows = store.query(
                "SELECT id FROM search_index WHERE search_index MATCH ?",
                (f'"{term}"',),
            )
            for row in rows:
                belief_ids.add(str(row[0]))
        except Exception:
            continue

    return list(belief_ids)[:50]  # cap at 50 to avoid bloat


# ---------------------------------------------------------------------------
# Document export to vault
# ---------------------------------------------------------------------------

def _doc_vault_id(doc: ProjectDoc) -> str:
    """Generate a stable vault filename for a document."""
    # Use the relative path, replacing separators with dashes
    slug: str = doc.relative_path.replace("/", "-").replace("\\", "-")
    if slug.endswith(".md"):
        slug = slug[:-3]
    # Sanitize for filesystem
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
    return slug


def doc_to_markdown(
    doc: ProjectDoc,
    belief_links: list[str],
) -> str:
    """Convert a ProjectDoc into an Obsidian vault note with wikilinks.

    Adds frontmatter with doc metadata, injects wikilinks for cross-references,
    and appends a "Related Beliefs" section.
    """
    lines: list[str] = ["---"]
    lines.append(f"doc_type: {doc.doc_type}")
    lines.append(f"original_path: {doc.relative_path}")
    lines.append("auto_generated: true")
    lines.append("---")
    lines.append("")
    lines.append(f"# {doc.title}")
    lines.append("")
    lines.append(f"*Source: `{doc.relative_path}`*")
    lines.append("")

    # Build a linkified version of the content
    # Replace reference patterns with wikilinks
    linkified: str = doc.content

    # Remove existing frontmatter from content (we add our own)
    fm_match: re.Match[str] | None = re.match(r"^---\n.*?\n---\n", linkified, re.DOTALL)
    if fm_match:
        linkified = linkified[fm_match.end():]

    # Remove original H1 (we add our own)
    linkified = re.sub(r"^#\s+.*\n", "", linkified, count=1)

    lines.append(linkified.strip())
    lines.append("")

    # Cross-references section
    if doc.refs:
        lines.append("## Cross-References")
        lines.append("")
        ref_types: dict[str, list[DocRef]] = {}
        for ref in doc.refs:
            ref_types.setdefault(ref.ref_type, []).append(ref)
        for rtype in sorted(ref_types.keys()):
            refs_list: list[DocRef] = ref_types[rtype]
            displays: list[str] = [f"[[{r.display}]]" for r in refs_list]
            lines.append(f"- **{rtype}**: {', '.join(displays)}")
        lines.append("")

    # Related beliefs section
    if belief_links:
        lines.append("## Related Beliefs")
        lines.append("")
        for bid in belief_links[:30]:
            lines.append(f"- [[{bid}]]")
        if len(belief_links) > 30:
            lines.append(f"- ... and {len(belief_links) - 30} more")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reference index notes
# ---------------------------------------------------------------------------

def _generate_ref_index(
    ref_type: str,
    ref_map: dict[str, list[str]],
    docs_dir: Path,
) -> None:
    """Generate an index note for a reference type (REQ, CS, Exp, etc.).

    Creates one note per unique reference ID, linking to all documents
    that mention it.
    """
    for ref_id, doc_ids in sorted(ref_map.items()):
        lines: list[str] = [
            "---",
            "auto_generated: true",
            f"ref_type: {ref_type}",
            "---",
            "",
            f"# {ref_id}",
            "",
            "## Documents",
            "",
        ]
        for did in doc_ids:
            lines.append(f"- [[{did}]]")
        lines.append("")

        safe_name: str = re.sub(r"[^a-zA-Z0-9_-]", "_", ref_id)
        (docs_dir / f"{safe_name}.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Main linking pipeline
# ---------------------------------------------------------------------------

def link_documents(
    store: MemoryStore,
    project_path: Path,
    vault_path: Path,
    docs_subfolder: str = "_docs",
) -> LinkResult:
    """Scan project documents, export to vault with cross-references.

    Steps:
    1. Scan project for .md files
    2. Extract references from each document
    3. Find beliefs that mention each document
    4. Export documents as vault notes with wikilinks
    5. Generate reference index notes (one per REQ, CS, Exp, etc.)
    """
    import time
    start: float = time.monotonic()

    docs_dir: Path = vault_path / docs_subfolder
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Scan
    project_docs: list[ProjectDoc] = scan_project_docs(project_path)

    # Step 2-4: Extract refs, find beliefs, export
    total_refs: int = 0
    total_belief_refs: int = 0
    exported: int = 0

    # Track reference -> doc mappings for index generation
    ref_to_docs: dict[str, list[str]] = {}

    for doc in project_docs:
        doc.refs = extract_refs(doc.content)
        total_refs += len(doc.refs)

        # Find beliefs mentioning this doc
        belief_links: list[str] = find_beliefs_mentioning_doc(
            store, doc.title, doc.refs
        )
        total_belief_refs += len(belief_links)

        # Export
        vault_id: str = _doc_vault_id(doc)
        md_content: str = doc_to_markdown(doc, belief_links)
        (docs_dir / f"{vault_id}.md").write_text(md_content, encoding="utf-8")
        exported += 1

        # Track refs for index
        for ref in doc.refs:
            ref_to_docs.setdefault(ref.display, []).append(vault_id)

    # Step 5: Generate reference index notes
    _generate_ref_index("reference", ref_to_docs, docs_dir)

    elapsed: float = time.monotonic() - start
    return LinkResult(
        docs_exported=exported,
        refs_linked=total_refs,
        belief_refs_added=total_belief_refs,
        elapsed_seconds=round(elapsed, 2),
    )
