"""Exp 41: Requirements Traceability Graph Extraction.

Scans all project .md files for entity IDs (REQ-XXX, CS-XXX, AXXX, Exp N,
Phase N) and extracts co-occurrence and labeled edges into a traceability
graph. Outputs adjacency list, coverage gaps, and summary statistics.

No LLM calls. Pure regex + section-level co-occurrence.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

EntityId: TypeAlias = str  # e.g. "REQ-001", "CS-003", "A027", "EXP-05", "PHASE-2"

@dataclass(frozen=True)
class Edge:
    source: EntityId
    target: EntityId
    edge_type: str        # VERIFIES, IMPLEMENTS, MAPS_TO, CO_OCCURS, etc.
    source_file: str
    context: str           # snippet where the link was found


@dataclass
class Entity:
    entity_id: EntityId
    entity_type: str       # requirement, case_study, approach, experiment, phase
    label: str             # human-readable name
    source_file: str       # where it is defined
    source_line: int


@dataclass
class TraceabilityGraph:
    entities: dict[EntityId, Entity] = field(default_factory=lambda: dict[EntityId, Entity]())
    edges: list[Edge] = field(default_factory=lambda: list[Edge]())


# ---------------------------------------------------------------------------
# ID patterns
# ---------------------------------------------------------------------------

# Canonical patterns for each entity type
ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "requirement": re.compile(r"\bREQ-(\d{3})\b"),
    "case_study":  re.compile(r"\bCS-(\d{3})\b"),
    "approach":    re.compile(r"\bA(\d{3})\b"),
    "experiment":  re.compile(r"\b[Ee]xp(?:eriment)?\s*(\d{1,2}[a-z]?)\b"),
    "phase":       re.compile(r"\b[Pp]hase\s+(\d+)\b"),
}

def normalize_id(entity_type: str, raw_number: str) -> EntityId:
    """Normalize raw match into canonical EntityId."""
    match entity_type:
        case "requirement":
            return f"REQ-{raw_number}"
        case "case_study":
            return f"CS-{raw_number}"
        case "approach":
            return f"A{raw_number}"
        case "experiment":
            num = raw_number.lower()
            if num.isdigit():
                return f"EXP-{int(num):02d}"
            return f"EXP-{num}"
        case "phase":
            return f"PHASE-{raw_number}"
        case _:
            return f"UNKNOWN-{raw_number}"


# ---------------------------------------------------------------------------
# Labeled edge extraction (field labels in prose)
# ---------------------------------------------------------------------------

LABELED_EDGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("VERIFIED_BY",    re.compile(r"[Ee]xperiment\s+trace:\s*(.+)", re.IGNORECASE)),
    ("PLANNED_IN",     re.compile(r"[Pp]lan\s+trace:\s*(.+)", re.IGNORECASE)),
    ("MAPS_TO",        re.compile(r"REQ\s+mapping:\s*(.+)", re.IGNORECASE)),
    ("VERIFIED_BY",    re.compile(r"[Ee]vidence:\s*(.+)", re.IGNORECASE)),
    ("IMPLEMENTS",     re.compile(r"[Ii]mplements?\s+(.+)", re.IGNORECASE)),
    ("SATISFIES",      re.compile(r"[Ss]atisfies?\s+(.+)", re.IGNORECASE)),
    ("SUPERSEDES",     re.compile(r"[Ss]uperseded?\s+by\s+(.+)", re.IGNORECASE)),
]


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def find_md_files(project_root: Path) -> list[Path]:
    """Find all .md files excluding .venv, node_modules, .git."""
    excludes = {".venv", "node_modules", ".git", ".planning"}
    results: list[Path] = []
    for p in sorted(project_root.rglob("*.md")):
        if any(part in excludes for part in p.parts):
            continue
        results.append(p)
    return results


def extract_entity_definitions(lines: list[str], filepath: Path) -> list[Entity]:
    """Extract entity definitions (where an entity is first defined/headed)."""
    entities: list[Entity] = []
    fname = str(filepath)

    for i, line in enumerate(lines):
        # REQ definitions: "### REQ-NNN: Label"
        m = re.match(r"^#{1,4}\s+REQ-(\d{3}):\s*(.+)", line)
        if m:
            entities.append(Entity(
                entity_id=f"REQ-{m.group(1)}",
                entity_type="requirement",
                label=m.group(2).strip(),
                source_file=fname,
                source_line=i + 1,
            ))

        # CS definitions: "## CS-NNN: Label"
        m = re.match(r"^#{1,4}\s+CS-(\d{3}):\s*(.+)", line)
        if m:
            entities.append(Entity(
                entity_id=f"CS-{m.group(1)}",
                entity_type="case_study",
                label=m.group(2).strip(),
                source_file=fname,
                source_line=i + 1,
            ))

        # Approach definitions: "### [AXXX] Label"
        m = re.match(r"^#{1,4}\s+\[A(\d{3})\]\s*(.+)", line)
        if m:
            entities.append(Entity(
                entity_id=f"A{m.group(1)}",
                entity_type="approach",
                label=m.group(2).strip(),
                source_file=fname,
                source_line=i + 1,
            ))

        # Experiment definitions: "## Experiment N:" or "# Experiment N:"
        m = re.match(r"^#{1,4}\s+[Ee]xp(?:eriment)?\s+(\d{1,2}[a-z]?)[\s:]+(.+)", line)
        if m:
            eid = normalize_id("experiment", m.group(1))
            entities.append(Entity(
                entity_id=eid,
                entity_type="experiment",
                label=m.group(2).strip(),
                source_file=fname,
                source_line=i + 1,
            ))

    return entities


def split_sections(lines: list[str]) -> list[tuple[int, int, str]]:
    """Split markdown into sections by heading. Returns (start, end, heading_text)."""
    sections: list[tuple[int, int, str]] = []
    heading_lines: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        if re.match(r"^#{1,4}\s+", line):
            heading_lines.append((i, line.strip()))

    for idx, (start, heading) in enumerate(heading_lines):
        end = heading_lines[idx + 1][0] if idx + 1 < len(heading_lines) else len(lines)
        sections.append((start, end, heading))

    if not heading_lines and lines:
        sections.append((0, len(lines), "(no heading)"))

    return sections


def extract_ids_from_text(text: str) -> dict[str, set[str]]:
    """Extract all entity IDs from a block of text, grouped by type."""
    found: dict[str, set[str]] = defaultdict(set)
    for etype, pattern in ENTITY_PATTERNS.items():
        for m in pattern.finditer(text):
            eid = normalize_id(etype, m.group(1))
            found[etype].add(eid)
    return dict(found)


def extract_subject_from_heading(heading: str) -> EntityId | None:
    """Extract the primary entity ID from a section heading."""
    # "### REQ-019: Single-Correction Learning"
    m = re.search(r"REQ-(\d{3})", heading)
    if m:
        return f"REQ-{m.group(1)}"
    # "## CS-003: ..."
    m = re.search(r"CS-(\d{3})", heading)
    if m:
        return f"CS-{m.group(1)}"
    # "### [A027] ..."
    m = re.search(r"\[A(\d{3})\]", heading)
    if m:
        return f"A{m.group(1)}"
    # "## Experiment 5: ..."
    m = re.search(r"[Ee]xp(?:eriment)?\s+(\d{1,2}[a-z]?)", heading)
    if m:
        return normalize_id("experiment", m.group(1))
    return None


def extract_labeled_edges(
    lines: list[str],
    section_ids: dict[str, set[str]],
    filepath: str,
    section_heading: str,
) -> list[Edge]:
    """Extract edges from labeled fields like 'Experiment trace: Exp 2, 5'."""
    edges: list[Edge] = []

    # Determine the "subject" from the heading first (reliable),
    # then fall back to section content (fragile when multiple IDs present)
    subject: EntityId | None = extract_subject_from_heading(section_heading)
    if subject is None:
        for etype in ["requirement", "case_study", "approach", "experiment"]:
            ids = section_ids.get(etype, set())
            if len(ids) == 1:
                subject = next(iter(ids))
                break

    if subject is None:
        return edges

    full_text = "\n".join(lines)
    for edge_type, pattern in LABELED_EDGE_PATTERNS:
        for m in pattern.finditer(full_text):
            value = m.group(1)
            # Extract all IDs from the value
            refs = extract_ids_from_text(value)
            for ref_ids in refs.values():
                for ref_id in ref_ids:
                    if ref_id != subject:
                        edges.append(Edge(
                            source=subject,
                            target=ref_id,
                            edge_type=edge_type,
                            source_file=filepath,
                            context=m.group(0)[:120],
                        ))

    return edges


def extract_cooccurrence_edges(
    section_ids: dict[str, set[str]],
    filepath: str,
    section_heading: str,
) -> list[Edge]:
    """Extract CO_OCCURS edges from IDs appearing in the same section."""
    all_ids: list[EntityId] = []
    for ids in section_ids.values():
        all_ids.extend(sorted(ids))

    edges: list[Edge] = []
    for i in range(len(all_ids)):
        for j in range(i + 1, len(all_ids)):
            a, b = all_ids[i], all_ids[j]
            # Skip self and skip same-type co-occurrence within definition sections
            if a == b:
                continue
            edges.append(Edge(
                source=a,
                target=b,
                edge_type="CO_OCCURS",
                source_file=filepath,
                context=section_heading[:120],
            ))

    return edges


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def build_traceability_graph(project_root: Path) -> TraceabilityGraph:
    """Build the full traceability graph from all .md files."""
    graph = TraceabilityGraph()
    md_files = find_md_files(project_root)

    for filepath in md_files:
        text = filepath.read_text(encoding="utf-8")
        lines = text.splitlines()
        fname = str(filepath.relative_to(project_root))

        # Extract entity definitions
        for entity in extract_entity_definitions(lines, filepath):
            if entity.entity_id not in graph.entities:
                graph.entities[entity.entity_id] = entity

        # Process section by section
        sections = split_sections(lines)
        for start, end, heading in sections:
            section_lines = lines[start:end]
            section_text = "\n".join(section_lines)
            section_ids = extract_ids_from_text(section_text)

            # Labeled edges
            graph.edges.extend(
                extract_labeled_edges(section_lines, section_ids, fname, heading)
            )

            # Co-occurrence edges (only across different entity types)
            graph.edges.extend(
                extract_cooccurrence_edges(section_ids, fname, heading)
            )

    return graph


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def deduplicate_edges(edges: list[Edge]) -> list[Edge]:
    """Deduplicate edges, preferring labeled over CO_OCCURS."""
    seen: dict[tuple[str, str, str], Edge] = {}
    for e in edges:
        key = (e.source, e.target, e.edge_type)
        if key not in seen:
            seen[key] = e
    # Also: if a labeled edge exists between A and B, drop their CO_OCCURS
    labeled_pairs: set[tuple[str, str]] = set()
    for e in edges:
        if e.edge_type != "CO_OCCURS":
            labeled_pairs.add((e.source, e.target))
            labeled_pairs.add((e.target, e.source))

    result: list[Edge] = []
    for e in seen.values():
        if e.edge_type == "CO_OCCURS" and (e.source, e.target) in labeled_pairs:
            continue
        result.append(e)
    return result


def compute_coverage_gaps(graph: TraceabilityGraph) -> dict[str, list[str]]:
    """Find entities with missing traceability links."""
    gaps: dict[str, list[str]] = {}

    # All edge targets and sources per entity
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        outgoing[e.source].add(e.edge_type)
        incoming[e.target].add(e.edge_type)

    # Requirements without experiment verification
    for eid, entity in graph.entities.items():
        if entity.entity_type == "requirement":
            has_verification = (
                "VERIFIED_BY" in outgoing.get(eid, set())
                or "VERIFIED_BY" in incoming.get(eid, set())
            )
            has_any_link = bool(outgoing.get(eid)) or bool(incoming.get(eid))
            issues: list[str] = []
            if not has_verification:
                issues.append("no experiment verification")
            if not has_any_link:
                issues.append("orphan (no links at all)")
            if issues:
                gaps[eid] = issues

    # Experiments not linked to any requirement
    for eid, entity in graph.entities.items():
        if entity.entity_type == "experiment":
            has_req_link = False
            for e in graph.edges:
                if (e.source == eid or e.target == eid):
                    other = e.target if e.source == eid else e.source
                    if other.startswith("REQ-"):
                        has_req_link = True
                        break
            if not has_req_link:
                gaps[eid] = gaps.get(eid, []) + ["not linked to any requirement"]

    # Approaches not linked to anything
    for eid, entity in graph.entities.items():
        if entity.entity_type == "approach":
            has_any = bool(outgoing.get(eid)) or bool(incoming.get(eid))
            if not has_any:
                gaps[eid] = gaps.get(eid, []) + ["orphan approach (no links)"]

    return gaps


def summarize(graph: TraceabilityGraph) -> str:
    """Produce a human-readable summary."""
    lines: list[str] = []
    lines.append("# Traceability Graph: Extraction Results (Exp 41)")
    lines.append(f"\n**Date:** 2026-04-10")
    lines.append(f"**Method:** Regex + section-level co-occurrence, zero LLM")
    lines.append("")

    # Entity counts
    type_counts: dict[str, int] = defaultdict(int)
    for e in graph.entities.values():
        type_counts[e.entity_type] += 1
    lines.append("## Entity Summary")
    lines.append("")
    lines.append("| Type | Count |")
    lines.append("|------|-------|")
    for etype in ["requirement", "case_study", "approach", "experiment", "phase"]:
        lines.append(f"| {etype} | {type_counts.get(etype, 0)} |")
    lines.append(f"| **Total** | **{len(graph.entities)}** |")
    lines.append("")

    # Edge counts by type
    edge_counts: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        edge_counts[e.edge_type] += 1
    lines.append("## Edge Summary")
    lines.append("")
    lines.append("| Edge Type | Count |")
    lines.append("|-----------|-------|")
    for etype, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {etype} | {count} |")
    lines.append(f"| **Total** | **{len(graph.edges)}** |")
    lines.append("")

    # Coverage gaps
    gaps = compute_coverage_gaps(graph)
    lines.append("## Coverage Gaps")
    lines.append("")
    if gaps:
        lines.append("| Entity | Issues |")
        lines.append("|--------|--------|")
        for eid in sorted(gaps.keys()):
            issues_str = "; ".join(gaps[eid])
            label = graph.entities[eid].label if eid in graph.entities else "(undefined)"
            lines.append(f"| {eid} ({label}) | {issues_str} |")
    else:
        lines.append("No coverage gaps found.")
    lines.append("")

    # Labeled edges (non-CO_OCCURS) -- the high-value edges
    labeled = [e for e in graph.edges if e.edge_type != "CO_OCCURS"]
    lines.append("## Labeled Edges (non-co-occurrence)")
    lines.append("")
    lines.append("| Source | Target | Type | File |")
    lines.append("|--------|--------|------|------|")
    for e in sorted(labeled, key=lambda x: (x.source, x.target)):
        lines.append(f"| {e.source} | {e.target} | {e.edge_type} | {e.source_file} |")
    lines.append("")

    return "\n".join(lines)


def to_adjacency_json(graph: TraceabilityGraph) -> str:
    """Export as JSON adjacency list for downstream consumption."""
    adj: dict[str, list[dict[str, str]]] = defaultdict(list)
    for e in graph.edges:
        adj[e.source].append({
            "target": e.target,
            "type": e.edge_type,
            "file": e.source_file,
        })
    # Also include reverse for undirected co-occurrence
    for e in graph.edges:
        if e.edge_type == "CO_OCCURS":
            adj[e.target].append({
                "target": e.source,
                "type": e.edge_type,
                "file": e.source_file,
            })

    entities_out: dict[str, dict[str, str | int]] = {}
    for eid, ent in graph.entities.items():
        entities_out[eid] = {
            "type": ent.entity_type,
            "label": ent.label,
            "file": ent.source_file,
            "line": ent.source_line,
        }

    return json.dumps({
        "entities": entities_out,
        "adjacency": dict(adj),
        "edge_count": len(graph.edges),
        "entity_count": len(graph.entities),
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Scanning: {project_root}")
    print(f"Files: {len(find_md_files(project_root))}")
    print()

    graph = build_traceability_graph(project_root)

    # Deduplicate
    raw_count = len(graph.edges)
    graph.edges = deduplicate_edges(graph.edges)
    dedup_count = len(graph.edges)

    print(f"Entities: {len(graph.entities)}")
    print(f"Edges (raw): {raw_count}")
    print(f"Edges (deduped): {dedup_count}")
    print()

    # Write summary
    summary = summarize(graph)
    summary_path = project_root / "experiments" / "exp41_traceability_results.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Summary written to: {summary_path.relative_to(project_root)}")

    # Write adjacency JSON
    adj_json = to_adjacency_json(graph)
    json_path = project_root / "experiments" / "exp41_traceability_graph.json"
    json_path.write_text(adj_json, encoding="utf-8")
    print(f"Graph JSON written to: {json_path.relative_to(project_root)}")

    # Print coverage gaps
    gaps = compute_coverage_gaps(graph)
    if gaps:
        print(f"\nCoverage gaps: {len(gaps)}")
        for eid in sorted(gaps.keys()):
            label = graph.entities[eid].label if eid in graph.entities else "(undefined)"
            print(f"  {eid} ({label}): {'; '.join(gaps[eid])}")
    else:
        print("\nNo coverage gaps found.")


if __name__ == "__main__":
    main()
