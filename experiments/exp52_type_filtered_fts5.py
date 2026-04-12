"""Experiment 52: Type-Filtered FTS5 Restores Retrieval Quality

Tests whether filtering the 16K-node multi-layer graph to only
belief/sentence/heading/behavioral_belief nodes restores retrieval
coverage to Exp 47 (586-node) levels.

Hypothesis: Type-blind retrieval caused Exp 48's degradation. Filtering
out file/callable/commit nodes should restore coverage because those
node types drown the 3.6% belief signal.

Methods tested:
  - Unfiltered grep (all 16K nodes)
  - Unfiltered FTS5 (all 16K nodes)
  - Type-filtered grep (belief+sentence+heading+behavioral_belief only)
  - Type-filtered FTS5 (belief+sentence+heading+behavioral_belief only)

Ground truth: 6-topic alpha-seek benchmark, K=15.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Final, TypeAlias

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

NodeDict: TypeAlias = dict[str, dict[str, Any]]
EdgeList: TypeAlias = list[dict[str, Any]]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOP_K: Final[int] = 15

ALPHA_SEEK_DB: Final[Path] = Path(
    "/Users/thelorax/projects/.gsd/workflows/spikes/"
    "260406-1-associative-memory-for-gsd-please-explor/"
    "sandbox/alpha-seek.db"
)

ALPHA_SEEK_ROOT: Final[Path] = Path("/Users/thelorax/projects/alpha-seek")

SKIP_DIRS: Final[set[str]] = {
    ".venv", "__pycache__", ".git", "node_modules", ".egg-info",
    "target", ".mypy_cache", ".pytest_cache", "dist", "build",
}

# Types to KEEP in filtered index
KEEP_TYPES: Final[set[str]] = {"belief", "sentence", "heading", "behavioral_belief"}

# Types to EXCLUDE
EXCLUDE_TYPES: Final[set[str]] = {"file", "callable", "commit"}

TOPICS: Final[dict[str, dict[str, Any]]] = {
    "dispatch_gate": {
        "query": "dispatch gate deploy protocol",
        "needed": ["D089", "D106", "D137"],
    },
    "calls_puts": {
        "query": "calls puts equal citizens",
        "needed": ["D073", "D096", "D100"],
    },
    "capital_5k": {
        "query": "starting capital bankroll",
        "needed": ["D099"],
    },
    "agent_behavior": {
        "query": "agent behavior instructions",
        "needed": ["D157", "D188"],
    },
    "strict_typing": {
        "query": "typing pyright strict",
        "needed": ["D071", "D113"],
    },
    "gcp_primary": {
        "query": "GCP primary compute platform",
        "needed": ["D078", "D120"],
    },
}

# Exp 47 baselines (586 nodes, belief-only)
EXP47_BASELINES: Final[dict[str, dict[str, float]]] = {
    "grep": {"coverage": 0.923, "tokens": 666.0, "precision": 0.211, "mrr": 0.639},
    "fts5": {"coverage": 0.846, "tokens": 287.0, "precision": 0.156, "mrr": 0.833},
}

# Exp 48 baselines (16K nodes, unfiltered)
EXP48_BASELINES: Final[dict[str, dict[str, float]]] = {
    "grep": {"coverage": 0.846, "tokens": 1869.3, "precision": 0.122, "mrr": 0.328},
    "fts5": {"coverage": 0.692, "tokens": 479.5, "precision": 0.100, "mrr": 0.666},
}


# ===================================================================
# Spike DB loader
# ===================================================================

def load_spike_nodes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load all active nodes and edges from the alpha-seek spike DB."""
    db: sqlite3.Connection = sqlite3.connect(str(ALPHA_SEEK_DB))
    nodes: list[dict[str, Any]] = []
    for row in db.execute(
        "SELECT id, content, category FROM mem_nodes WHERE superseded_by IS NULL"
    ):
        nodes.append({
            "id": str(row[0]),
            "content": str(row[1]),
            "type": "belief",
            "category": str(row[2]),
        })

    edges: list[dict[str, Any]] = []
    for row in db.execute(
        "SELECT from_id, to_id, edge_type, weight FROM mem_edges"
    ):
        edges.append({
            "src": str(row[0]),
            "tgt": str(row[1]),
            "type": str(row[2]),
            "weight": float(row[3]),
        })
    db.close()
    return nodes, edges


# ===================================================================
# Extractors (from exp48)
# ===================================================================

def extract_file_tree(project_root: Path) -> list[dict[str, Any]]:
    """Extract file tree nodes (no edges needed for this experiment)."""
    nodes: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp: Path = Path(root) / f
            rel: str = str(fp.relative_to(project_root))
            nodes.append({"id": f"file:{rel}", "content": f, "type": "file"})
    return nodes


def extract_git_history(project_root: Path) -> list[dict[str, Any]]:
    """Extract commit nodes."""
    r: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "log", "--name-only", "--format=COMMIT:%H|%s|%aI", "--no-merges"],
        capture_output=True, text=True, cwd=project_root,
    )

    nodes: list[dict[str, Any]] = []
    current_msg: str = ""
    current_date: str = ""
    current_hash: str = ""
    current_files: list[str] = []

    def flush_commit() -> None:
        nonlocal current_msg, current_date, current_hash, current_files
        if current_files and current_msg:
            if not current_msg.lower().startswith(("merge", "wip")):
                commit_id: str = f"commit:{current_hash[:8]}"
                nodes.append({
                    "id": commit_id,
                    "content": current_msg,
                    "type": "commit",
                    "date": current_date,
                })
        current_msg = ""
        current_date = ""
        current_hash = ""
        current_files = []

    for line in r.stdout.strip().split("\n"):
        if line.startswith("COMMIT:"):
            flush_commit()
            parts: list[str] = line[7:].split("|", 2)
            current_hash = parts[0]
            current_msg = parts[1] if len(parts) > 1 else ""
            current_date = parts[2] if len(parts) > 2 else ""
            current_files = []
        elif line.strip():
            current_files.append(line.strip())

    flush_commit()
    return nodes


def extract_document_sentences(
    project_root: Path,
) -> list[dict[str, Any]]:
    """Split markdown docs into sentence-level nodes."""
    nodes: list[dict[str, Any]] = []
    sent_pattern: re.Pattern[str] = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    doc_exts: set[str] = {".md", ".rst", ".txt", ".adoc"}
    doc_files: list[str] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fp: Path = Path(root) / f
            if fp.suffix.lower() in doc_exts:
                doc_files.append(str(fp.relative_to(project_root)))

    for rel_path in doc_files:
        fp = project_root / rel_path
        try:
            text: str = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        paragraphs: list[str] = text.split("\n\n")
        sent_idx: int = 0
        for para in paragraphs:
            para = para.strip()
            if not para or para.startswith("```"):
                continue
            if para.startswith("|") or para.startswith("---"):
                continue

            if para.startswith("#"):
                nid: str = f"doc:{rel_path}:h:{sent_idx}"
                nodes.append({
                    "id": nid,
                    "content": para.lstrip("#").strip(),
                    "type": "heading",
                    "file": rel_path,
                })
                sent_idx += 1
                continue

            sentences: list[str] = sent_pattern.split(para)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 20:
                    nid = f"doc:{rel_path}:s:{sent_idx}"
                    nodes.append({
                        "id": nid,
                        "content": sent,
                        "type": "sentence",
                        "file": rel_path,
                    })
                    sent_idx += 1

    return nodes


def extract_ast_calls(project_root: Path) -> list[dict[str, Any]]:
    """Extract callable nodes from Python AST."""
    import ast as python_ast

    nodes: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp: Path = Path(root) / f
            try:
                source: str = fp.read_text(encoding="utf-8")
                tree: python_ast.Module = python_ast.parse(source)
            except Exception:
                continue

            rel: str = str(fp.relative_to(project_root))
            module: str = rel.replace("/", ".").replace(".py", "")

            for node in python_ast.walk(tree):
                if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                    qname: str = f"{module}.{node.name}"
                    nodes.append({
                        "id": f"func:{qname}",
                        "content": f"def {node.name}",
                        "type": "callable",
                        "file": rel,
                        "line": node.lineno,
                    })
    return nodes


def extract_directives(project_root: Path) -> list[dict[str, Any]]:
    """Extract behavioral belief nodes from directive files."""
    nodes: list[dict[str, Any]] = []
    directive_files: list[str] = ["CLAUDE.md", ".cursorrules", ".aider.conf.yml"]
    directive_patterns: list[re.Pattern[str]] = [
        re.compile(r"\bBANNED\b"),
        re.compile(r"\b[Nn]ever\s+\w+"),
        re.compile(r"\b[Aa]lways\s+\w+"),
        re.compile(r"\b[Mm]ust\s+not\b"),
        re.compile(r"\b[Dd]o\s+not\b"),
        re.compile(r"\b[Dd]on't\b"),
    ]

    for df in directive_files:
        fp: Path = project_root / df
        if not fp.exists():
            continue
        try:
            text: str = fp.read_text(encoding="utf-8")
        except Exception:
            continue

        for i_l, line in enumerate(text.split("\n")):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for pat in directive_patterns:
                if pat.search(line):
                    nodes.append({
                        "id": f"directive:{df}:{i_l}",
                        "content": line,
                        "type": "behavioral_belief",
                        "file": df,
                    })
                    break

    return nodes


# ===================================================================
# Retrieval methods
# ===================================================================

def build_fts(nodes: list[dict[str, Any]]) -> sqlite3.Connection:
    """Build in-memory FTS5 index with porter stemming from node list."""
    db: sqlite3.Connection = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE fts USING fts5(id, content, tokenize='porter')"
    )
    for n in nodes:
        content: str = str(n.get("content", ""))
        if len(content) > 10:
            db.execute("INSERT INTO fts VALUES (?, ?)", (n["id"], content))
    db.commit()
    return db


def search_fts(
    query: str, fts_db: sqlite3.Connection, top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """FTS5 search with OR terms + BM25 ranking."""
    terms: list[str] = [t.strip() for t in query.split() if len(t.strip()) > 2]
    if not terms:
        return []
    fts_query: str = " OR ".join(terms)
    try:
        results: list[tuple[str, float]] = [
            (str(r[0]), float(r[1]))
            for r in fts_db.execute(
                "SELECT id, bm25(fts) FROM fts WHERE fts MATCH ? "
                "ORDER BY bm25(fts) LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
        ]
        return results
    except Exception:
        return []


def grep_search(
    query: str, nodes: dict[str, str], top_k: int = TOP_K,
) -> list[tuple[str, float]]:
    """Case-insensitive grep ranked by term frequency."""
    query_terms: list[str] = [t.lower() for t in query.split() if len(t) >= 2]
    scores: list[tuple[str, float]] = []

    for nid, content in nodes.items():
        content_lower: str = content.lower()
        match_count: int = 0
        for term in query_terms:
            match_count += len(re.findall(re.escape(term), content_lower))
        if match_count > 0:
            scores.append((nid, float(match_count)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


def extract_decision_id(node_id: str) -> str | None:
    """Extract D### from a node ID."""
    m: re.Match[str] | None = re.match(r"(D\d{3})", node_id)
    return m.group(1) if m else None


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


# ===================================================================
# Evaluation
# ===================================================================

def evaluate_method(
    method_name: str,
    results: list[tuple[str, float]],
    needed_decisions: list[str],
    node_content: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a retrieval method against ground truth."""
    needed: set[str] = set(needed_decisions)
    found_decisions: set[str] = set()
    first_relevant_rank: int | None = None
    total_tokens: int = 0
    relevant_count: int = 0

    for rank, (nid, _score) in enumerate(results):
        did: str | None = extract_decision_id(nid)
        content: str = node_content.get(nid, "")
        total_tokens += estimate_tokens(content)

        if did and did in needed:
            found_decisions.add(did)
            relevant_count += 1
            if first_relevant_rank is None:
                first_relevant_rank = rank + 1

    coverage: float = len(found_decisions) / len(needed) if needed else 0.0
    precision: float = relevant_count / len(results) if results else 0.0
    mrr: float = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

    return {
        "method": method_name,
        "result_count": len(results),
        "found": sorted(found_decisions),
        "missed": sorted(needed - found_decisions),
        "coverage": round(coverage, 3),
        "tokens": total_tokens,
        "precision": round(precision, 3),
        "mrr": round(mrr, 3),
    }


# ===================================================================
# Main pipeline
# ===================================================================

def main() -> None:
    """Run type-filtered retrieval experiment."""
    print("=" * 60, file=sys.stderr)
    print("Exp 52: Type-Filtered FTS5 Retrieval", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    t_start: float = time.perf_counter()

    # ------------------------------------------------------------------
    # Stage 1: Load spike DB (belief nodes)
    # ------------------------------------------------------------------
    print("\n[1/5] Loading spike DB...", file=sys.stderr)
    spike_nodes, _spike_edges = load_spike_nodes()
    print(f"  Loaded {len(spike_nodes)} belief nodes", file=sys.stderr)

    # ------------------------------------------------------------------
    # Stage 2: Extract multi-layer nodes from alpha-seek
    # ------------------------------------------------------------------
    print("\n[2/5] Extracting multi-layer nodes...", file=sys.stderr)

    file_nodes: list[dict[str, Any]] = extract_file_tree(ALPHA_SEEK_ROOT)
    print(f"  File nodes: {len(file_nodes)}", file=sys.stderr)

    commit_nodes: list[dict[str, Any]] = extract_git_history(ALPHA_SEEK_ROOT)
    print(f"  Commit nodes: {len(commit_nodes)}", file=sys.stderr)

    doc_nodes: list[dict[str, Any]] = extract_document_sentences(ALPHA_SEEK_ROOT)
    heading_count: int = sum(1 for n in doc_nodes if n["type"] == "heading")
    sentence_count: int = sum(1 for n in doc_nodes if n["type"] == "sentence")
    print(f"  Doc nodes: {len(doc_nodes)} ({heading_count} headings, {sentence_count} sentences)", file=sys.stderr)

    callable_nodes: list[dict[str, Any]] = extract_ast_calls(ALPHA_SEEK_ROOT)
    print(f"  Callable nodes: {len(callable_nodes)}", file=sys.stderr)

    directive_nodes: list[dict[str, Any]] = extract_directives(ALPHA_SEEK_ROOT)
    print(f"  Directive nodes: {len(directive_nodes)}", file=sys.stderr)

    # Combine all nodes
    all_nodes: list[dict[str, Any]] = (
        spike_nodes + file_nodes + commit_nodes + doc_nodes
        + callable_nodes + directive_nodes
    )
    print(f"\n  TOTAL nodes: {len(all_nodes)}", file=sys.stderr)

    # Type distribution
    type_counts: Counter[str] = Counter(n["type"] for n in all_nodes)
    for ntype, count in type_counts.most_common():
        pct: float = 100.0 * count / len(all_nodes)
        print(f"    {ntype}: {count} ({pct:.1f}%)", file=sys.stderr)

    # ------------------------------------------------------------------
    # Stage 3: Build filtered subset
    # ------------------------------------------------------------------
    print("\n[3/5] Building type-filtered subset...", file=sys.stderr)
    filtered_nodes: list[dict[str, Any]] = [
        n for n in all_nodes if n["type"] in KEEP_TYPES
    ]
    filtered_type_counts: Counter[str] = Counter(n["type"] for n in filtered_nodes)
    print(f"  Filtered nodes: {len(filtered_nodes)}", file=sys.stderr)
    for ntype, count in filtered_type_counts.most_common():
        pct = 100.0 * count / len(filtered_nodes)
        print(f"    {ntype}: {count} ({pct:.1f}%)", file=sys.stderr)

    # ------------------------------------------------------------------
    # Stage 4: Build indexes
    # ------------------------------------------------------------------
    print("\n[4/5] Building FTS5 indexes...", file=sys.stderr)

    fts_unfiltered: sqlite3.Connection = build_fts(all_nodes)
    unf_count: int = fts_unfiltered.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
    print(f"  Unfiltered FTS5: {unf_count} indexed", file=sys.stderr)

    fts_filtered: sqlite3.Connection = build_fts(filtered_nodes)
    filt_count: int = fts_filtered.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
    print(f"  Filtered FTS5: {filt_count} indexed", file=sys.stderr)

    # Build content dicts for grep
    all_content: dict[str, str] = {
        n["id"]: str(n.get("content", "")) for n in all_nodes
    }
    filtered_content: dict[str, str] = {
        n["id"]: str(n.get("content", "")) for n in filtered_nodes
    }

    # ------------------------------------------------------------------
    # Stage 5: Run retrieval on all 6 topics x 4 methods
    # ------------------------------------------------------------------
    print("\n[5/5] Running retrieval tests...", file=sys.stderr)

    per_topic: dict[str, dict[str, Any]] = {}
    method_names: list[str] = [
        "grep_unfiltered", "fts5_unfiltered",
        "grep_filtered", "fts5_filtered",
    ]

    for topic_name, topic_data in TOPICS.items():
        query: str = topic_data["query"]
        needed: list[str] = topic_data["needed"]
        print(f"\n  Topic: {topic_name} ({query})", file=sys.stderr)

        # Unfiltered grep
        grep_unf_results: list[tuple[str, float]] = grep_search(
            query, all_content, TOP_K,
        )
        grep_unf_eval: dict[str, Any] = evaluate_method(
            "grep_unfiltered", grep_unf_results, needed, all_content,
        )

        # Unfiltered FTS5
        fts_unf_results: list[tuple[str, float]] = search_fts(
            query, fts_unfiltered, TOP_K,
        )
        fts_unf_eval: dict[str, Any] = evaluate_method(
            "fts5_unfiltered", fts_unf_results, needed, all_content,
        )

        # Filtered grep
        grep_filt_results: list[tuple[str, float]] = grep_search(
            query, filtered_content, TOP_K,
        )
        grep_filt_eval: dict[str, Any] = evaluate_method(
            "grep_filtered", grep_filt_results, needed, filtered_content,
        )

        # Filtered FTS5
        fts_filt_results: list[tuple[str, float]] = search_fts(
            query, fts_filtered, TOP_K,
        )
        fts_filt_eval: dict[str, Any] = evaluate_method(
            "fts5_filtered", fts_filt_results, needed, filtered_content,
        )

        per_topic[topic_name] = {
            "query": query,
            "needed": needed,
            "grep_unfiltered": grep_unf_eval,
            "fts5_unfiltered": fts_unf_eval,
            "grep_filtered": grep_filt_eval,
            "fts5_filtered": fts_filt_eval,
        }

        for method in method_names:
            ev: dict[str, Any] = per_topic[topic_name][method]
            status: str = "PASS" if ev["coverage"] >= 1.0 else f"MISS {ev['missed']}"
            print(
                f"    {method:20s}: cov={ev['coverage']:.3f} "
                f"prec={ev['precision']:.3f} mrr={ev['mrr']:.3f} "
                f"tok={ev['tokens']:5d}  {status}",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # Aggregate results
    # ------------------------------------------------------------------
    aggregates: dict[str, dict[str, float]] = {}
    for method in method_names:
        all_found: int = 0
        all_needed: int = 0
        all_cov: list[float] = []
        all_tok: list[float] = []
        all_prec: list[float] = []
        all_mrr: list[float] = []

        for topic_data_out in per_topic.values():
            ev = topic_data_out[method]
            all_found += len(ev["found"])
            all_needed += len(topic_data_out["needed"])
            all_cov.append(ev["coverage"])
            all_tok.append(float(ev["tokens"]))
            all_prec.append(ev["precision"])
            all_mrr.append(ev["mrr"])

        aggregates[method] = {
            "micro_coverage": round(all_found / max(1, all_needed), 3),
            "macro_coverage": round(sum(all_cov) / len(all_cov), 3),
            "mean_tokens": round(sum(all_tok) / len(all_tok), 1),
            "mean_precision": round(sum(all_prec) / len(all_prec), 3),
            "mean_mrr": round(sum(all_mrr) / len(all_mrr), 3),
            "total_found": all_found,
            "total_needed": all_needed,
        }

    t_total: float = time.perf_counter() - t_start

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    output: dict[str, Any] = {
        "experiment": "exp52_type_filtered_fts5",
        "date": "2026-04-10",
        "total_time_s": round(t_total, 2),
        "node_counts": {
            "total": len(all_nodes),
            "filtered": len(filtered_nodes),
            "type_distribution": dict(type_counts),
            "filtered_type_distribution": dict(filtered_type_counts),
        },
        "fts_indexed": {
            "unfiltered": unf_count,
            "filtered": filt_count,
        },
        "per_topic": per_topic,
        "aggregates": aggregates,
        "baselines": {
            "exp47_586_nodes": EXP47_BASELINES,
            "exp48_16k_unfiltered": EXP48_BASELINES,
        },
    }

    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)

    # Summary to stderr
    print("\n" + "=" * 60, file=sys.stderr)
    print("AGGREGATE RESULTS", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"{'Method':<22s} {'Cov@15':>8s} {'Tokens':>8s} {'Prec':>8s} {'MRR':>8s}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    # Show baselines
    for bl_name, bl_methods in [("Exp47 (586n)", EXP47_BASELINES), ("Exp48 (16Kn)", EXP48_BASELINES)]:
        for m_name, m_vals in bl_methods.items():
            label: str = f"{bl_name} {m_name}"
            print(
                f"{label:<22s} {m_vals['coverage']:>7.1%} {m_vals['tokens']:>8.0f} "
                f"{m_vals['precision']:>7.1%} {m_vals['mrr']:>8.3f}",
                file=sys.stderr,
            )

    print("-" * 60, file=sys.stderr)

    for method in method_names:
        agg: dict[str, float] = aggregates[method]
        print(
            f"{method:<22s} {agg['micro_coverage']:>7.1%} {agg['mean_tokens']:>8.1f} "
            f"{agg['mean_precision']:>7.1%} {agg['mean_mrr']:>8.3f}",
            file=sys.stderr,
        )

    print("=" * 60, file=sys.stderr)
    print(f"Total time: {t_total:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
