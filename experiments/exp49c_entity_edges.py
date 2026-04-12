"""
Experiment 49c: Entity Detection for CROSS_DOC_ENTITY Edges + H3 Retest

Builds typed semantic edges by detecting shared entities across document sentences.
Then retests HRR vocabulary bridge on jose-bully and debserver (H3).

Entity types detected (zero-LLM):
  - Person names: capitalized bigrams appearing >= 3 times in corpus
  - Incident/exhibit IDs: incident-NN, EXH-NNN patterns
  - Hostnames/services: known infrastructure names from corpus
  - Dates: "Month Day" patterns

Edge types created:
  - PERSON_INVOLVED: sentences mentioning the same person
  - INCIDENT_LINKED: sentences referencing the same incident
  - HOST_LINKED: sentences referencing the same host/service
  - DATE_COOCCURS: sentences referencing the same date
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

# Reuse Exp 45 infrastructure
PYTHONPATH_SET = True  # Run with PYTHONPATH=/Users/thelorax/projects/agentmemory
from experiments.exp49_onboarding_validation import (
    PROJECTS, discover, extract_file_tree, extract_git_history,
    extract_document_sentences, extract_ast_calls,
    extract_directives, analyze_graph, build_fts_from_nodes, search_fts,
)


# ============================================================
# Entity detection
# ============================================================

def detect_entities(nodes: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Detect entities in sentence nodes. Returns {entity_type: [(node_id, entity_value)]}."""

    # First pass: build corpus-level entity candidates
    name_counter: Counter[str] = Counter()
    incident_counter: Counter[str] = Counter()
    host_counter: Counter[str] = Counter()
    date_counter: Counter[str] = Counter()

    name_pattern = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
    incident_pattern = re.compile(r"\b(incident[-_ ]?\d{1,2}|EXH[-_ ]?\d{1,3}|Exhibit\s+\d{1,3})\b", re.IGNORECASE)
    date_pattern = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\b")

    # Common false positive names to exclude
    name_stopwords = {
        "What It", "File Path", "Model Compare", "How To", "If The",
        "On March", "In The", "For The", "When The", "This Is",
        "The Following", "Not The", "Senior Engineering", "Pull Request",
        "Microsoft Teams", "Continuous Integration", "Code Review",
    }

    # Words that indicate a capitalized bigram is a concept/product, not a person
    non_person_words = {
        "home", "assistant", "environment", "server", "service", "system",
        "plug", "smart", "dev", "integration", "engineering", "review",
        "request", "model", "compare", "action", "pipeline", "test",
        "config", "network", "module", "component", "manager", "controller",
        "video", "garage", "door", "sensor", "camera", "bridge", "hub",
        "steps", "plan", "task", "check", "setup", "install", "update",
        "build", "release", "deploy", "monitor", "alert", "status",
        "chat", "support", "takeover", "smoke", "fill", "neural",
        "best", "code", "data", "file", "path", "run", "agent",
    }

    # Infrastructure hostnames (detect from corpus frequency)
    infra_pattern = re.compile(r"\b(willow|archon|alnitak|mintaka|lorax|jellyfin|grafana|prometheus|radarr|sonarr|prowlarr|gluetun|frigate|homeassistant|gitea|qbittorrent|raspberry|pi)\b", re.IGNORECASE)

    for n in nodes:
        content = n.get("content", "")
        if not content:
            continue

        for m in name_pattern.finditer(content):
            name = f"{m.group(1)} {m.group(2)}"
            if name in name_stopwords:
                continue
            # Filter out concept/product names
            words_lower = {m.group(1).lower(), m.group(2).lower()}
            if words_lower & non_person_words:
                continue
            name_counter[name] += 1

        for m in incident_pattern.finditer(content):
            incident_counter[m.group(1).lower().replace(" ", "-")] += 1

        for m in date_pattern.finditer(content):
            date_counter[f"{m.group(1)} {m.group(2)}"] += 1

        for m in infra_pattern.finditer(content):
            host_counter[m.group(1).lower()] += 1

    # Filter to entities appearing in >= 2 nodes (cross-doc relevance)
    valid_names = {n for n, c in name_counter.items() if c >= 2}
    valid_incidents = {n for n, c in incident_counter.items() if c >= 2}
    valid_hosts = {n for n, c in host_counter.items() if c >= 2}
    valid_dates = {n for n, c in date_counter.items() if c >= 2}

    # Second pass: tag each node with its entities
    mentions: dict[str, list[tuple[str, str]]] = {
        "PERSON_INVOLVED": [],
        "INCIDENT_LINKED": [],
        "HOST_LINKED": [],
        "DATE_COOCCURS": [],
    }

    for n in nodes:
        nid = n["id"]
        content = n.get("content", "")
        if not content:
            continue

        for m in name_pattern.finditer(content):
            name = f"{m.group(1)} {m.group(2)}"
            if name in valid_names:
                mentions["PERSON_INVOLVED"].append((nid, name))

        for m in incident_pattern.finditer(content):
            inc = m.group(1).lower().replace(" ", "-")
            if inc in valid_incidents:
                mentions["INCIDENT_LINKED"].append((nid, inc))

        for m in infra_pattern.finditer(content):
            host = m.group(1).lower()
            if host in valid_hosts:
                mentions["HOST_LINKED"].append((nid, host))

        for m in date_pattern.finditer(content):
            date = f"{m.group(1)} {m.group(2)}"
            if date in valid_dates:
                mentions["DATE_COOCCURS"].append((nid, date))

    return mentions


def build_entity_edges(mentions: dict[str, list[tuple[str, str]]]) -> list[dict[str, Any]]:
    """Build edges between nodes that share entity mentions."""
    edges: list[dict[str, Any]] = []

    for edge_type, mention_list in mentions.items():
        # Group by entity value
        entity_nodes: dict[str, list[str]] = defaultdict(list)
        for nid, entity_val in mention_list:
            entity_nodes[entity_val].append(nid)

        # Create edges between all pairs sharing an entity
        for entity_val, nids in entity_nodes.items():
            unique_nids = list(set(nids))
            # Only create edges across different files
            file_groups: dict[str, list[str]] = defaultdict(list)
            for nid in unique_nids:
                # Extract file from node ID: doc:path:s:N -> path
                parts = nid.split(":")
                if len(parts) >= 2:
                    file_groups[parts[1]].append(nid)

            # Cross-file edges only (within-file is already covered by WITHIN_SECTION)
            files = list(file_groups.keys())
            for i, fa in enumerate(files):
                for fb in files[i+1:]:
                    # One edge per file pair per entity (not per sentence pair)
                    src = file_groups[fa][0]  # representative node from file A
                    tgt = file_groups[fb][0]  # representative node from file B
                    edges.append({
                        "src": src, "tgt": tgt,
                        "type": edge_type,
                        "entity": entity_val,
                    })

    return edges


# ============================================================
# HRR test
# ============================================================

DIM = 2048
RNG = np.random.default_rng(42)


def make_vector(dim: int = DIM) -> np.ndarray:
    v = RNG.standard_normal(dim)
    v /= np.linalg.norm(v)
    return v


def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.real(np.fft.ifft(np.fft.fft(a) * np.fft.fft(b)))


def unbind(bound: np.ndarray, key: np.ndarray) -> np.ndarray:
    return np.real(np.fft.ifft(np.fft.fft(bound) * np.conj(np.fft.fft(key))))


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def test_hrr_bridge(
    all_nodes: list[dict[str, Any]],
    entity_edges: list[dict[str, Any]],
    fts_db: sqlite3.Connection,
    queries: list[dict[str, Any]],
    project_name: str,
) -> dict[str, Any]:
    """Test whether HRR + entity edges finds things FTS5 misses."""

    if not entity_edges:
        return {"project": project_name, "skipped": True, "reason": "no entity edges"}

    # Build node vectors
    node_vecs: dict[str, np.ndarray] = {}
    edge_type_vecs: dict[str, np.ndarray] = {}
    node_content: dict[str, str] = {n["id"]: n.get("content", "") for n in all_nodes}

    # Collect unique edge types
    edge_types = set(e["type"] for e in entity_edges)
    for et in edge_types:
        edge_type_vecs[et] = make_vector()

    # Assign vectors to nodes appearing in edges
    edge_node_ids: set[str] = set()
    for e in entity_edges:
        edge_node_ids.add(e["src"])
        edge_node_ids.add(e["tgt"])
    for nid in edge_node_ids:
        node_vecs[nid] = make_vector()

    # Build superposition (single partition for simplicity -- entity edges are sparse)
    superposition = np.zeros(DIM)
    for e in entity_edges:
        if e["src"] in node_vecs and e["tgt"] in node_vecs:
            superposition += bind(node_vecs[e["tgt"]], edge_type_vecs[e["type"]])
            superposition += bind(node_vecs[e["src"]], edge_type_vecs[e["type"]])

    # Test queries
    results: list[dict[str, Any]] = []
    for q in queries:
        # FTS5 pass
        fts_hits = search_fts(q["query"], fts_db, top_k=10)
        fts_hit_ids = set(fts_hits)

        # HRR pass: for each FTS5 hit that's in the HRR graph, walk entity edges
        hrr_neighbors: set[str] = set()
        for seed_id in fts_hits:
            if seed_id not in node_vecs:
                continue
            for et in edge_types:
                result_vec = unbind(superposition, edge_type_vecs[et])
                # Score all entity-connected nodes
                for nid, vec in node_vecs.items():
                    if nid == seed_id:
                        continue
                    sim = cos_sim(result_vec, vec)
                    if sim > 0.08:
                        hrr_neighbors.add(nid)

        hrr_only = hrr_neighbors - fts_hit_ids
        combined = fts_hit_ids | hrr_neighbors

        # Check must_find terms
        fts_found_terms: list[str] = []
        combined_found_terms: list[str] = []
        for term in q.get("must_find", []):
            t = term.lower()
            for rid in fts_hits:
                if t in node_content.get(rid, "").lower():
                    fts_found_terms.append(term)
                    break
            for rid in combined:
                if t in node_content.get(rid, "").lower():
                    combined_found_terms.append(term)
                    break

        results.append({
            "query": q["query"],
            "fts_hits": len(fts_hits),
            "hrr_only": len(hrr_only),
            "combined": len(combined),
            "fts_precision": round(len(fts_found_terms) / max(1, len(q.get("must_find", []))), 3),
            "combined_precision": round(len(combined_found_terms) / max(1, len(q.get("must_find", []))), 3),
            "hrr_added_value": len(combined_found_terms) > len(fts_found_terms),
        })

    return {
        "project": project_name,
        "entity_edge_count": len(entity_edges),
        "entity_edge_types": dict(Counter(e["type"] for e in entity_edges)),
        "hrr_node_count": len(node_vecs),
        "query_results": results,
        "hrr_added_value_count": sum(1 for r in results if r["hrr_added_value"]),
    }


# ============================================================
# Test queries for H3 (vocabulary gap scenarios)
# ============================================================

H3_QUERIES: dict[str, list[dict[str, Any]]] = {
    "jose-bully": [
        {
            "query": "PR blocked merge gatekeeping",
            "must_find": ["pull request", "merge", "PR", "block"],
            "description": "incident-01 topic via different vocabulary",
        },
        {
            "query": "manager meeting escalation",
            "must_find": ["Anbarasu", "escalat", "meeting"],
            "description": "Anbarasu Chandran meetings (person entity bridge)",
        },
        {
            "query": "evidence documentation proof",
            "must_find": ["exhibit", "evidence", "incident"],
            "description": "Evidence system (exhibit/incident entity bridge)",
        },
        {
            "query": "public shaming team channel correction",
            "must_find": ["correct", "public", "team"],
            "description": "Public correction incidents",
        },
        {
            "query": "work assignment task distribution unfair",
            "must_find": ["work", "assign", "task"],
            "description": "Work distribution grievance",
        },
    ],
    "debserver": [
        {
            "query": "server fleet management debian",
            "must_find": ["willow", "debian", "server"],
            "description": "Primary server (hostname entity bridge)",
        },
        {
            "query": "media streaming video",
            "must_find": ["jellyfin", "media"],
            "description": "Media server (service entity bridge)",
        },
        {
            "query": "network monitoring alerts",
            "must_find": ["prometheus", "grafana", "monitor", "alert"],
            "description": "Monitoring stack (service entity bridge)",
        },
        {
            "query": "VPN tunnel privacy torrent",
            "must_find": ["gluetun", "vpn"],
            "description": "VPN setup (service entity bridge)",
        },
        {
            "query": "git server code hosting",
            "must_find": ["gitea", "mintaka"],
            "description": "Git server (host entity bridge)",
        },
    ],
}


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 70, file=sys.stderr)
    print("Experiment 49c: Entity Detection + H3 Retest", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_results: dict[str, Any] = {}

    for name in ["jose-bully", "debserver"]:
        root = PROJECTS[name]
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Project: {name}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)

        # Extract (reuse pipeline)
        manifest = discover(root)
        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []

        ft_nodes, ft_edges = extract_file_tree(root)
        all_nodes.extend(ft_nodes)
        all_edges.extend(ft_edges)

        if manifest["has_git"]:
            git_nodes, git_edges = extract_git_history(root)
            all_nodes.extend(git_nodes)
            all_edges.extend(git_edges)

        if manifest["doc_count"] > 0:
            doc_nodes, doc_edges = extract_document_sentences(root, manifest["doc_files"])
            all_nodes.extend(doc_nodes)
            all_edges.extend(doc_edges)

        if manifest["languages"]:
            ast_nodes, ast_edges = extract_ast_calls(root, manifest["languages"])
            all_nodes.extend(ast_nodes)
            all_edges.extend(ast_edges)

        if manifest["directives"]:
            dir_nodes = extract_directives(root, manifest["directives"])
            all_nodes.extend(dir_nodes)

        # Entity detection
        print("\n  Entity detection...", file=sys.stderr)
        mentions = detect_entities(all_nodes)
        entity_edges = build_entity_edges(mentions)

        for etype, mention_list in mentions.items():
            entities = set(v for _, v in mention_list)
            nodes_with = len(set(n for n, _ in mention_list))
            print(f"    {etype}: {len(entities)} unique entities, {nodes_with} nodes tagged", file=sys.stderr)
            # Show top entities
            entity_counts = Counter(v for _, v in mention_list)
            for ent, count in entity_counts.most_common(5):
                print(f"      {count:>4}x  {ent}", file=sys.stderr)

        print(f"\n    Entity edges created: {len(entity_edges)}", file=sys.stderr)
        edge_type_counts: Counter[str] = Counter(e["type"] for e in entity_edges)
        for et, count in edge_type_counts.most_common():
            print(f"      {et}: {count}", file=sys.stderr)

        # Add entity edges to graph and re-analyze
        all_edges.extend(entity_edges)
        graph_props = analyze_graph(all_nodes, all_edges)
        print(f"\n    Graph after entity edges:", file=sys.stderr)
        print(f"      Nodes: {graph_props['total_nodes']}, Edges: {graph_props['total_edges']}", file=sys.stderr)
        print(f"      LCC: {graph_props['largest_component']} ({graph_props['largest_component_frac']:.0%})", file=sys.stderr)
        print(f"      Components: {graph_props['num_components']}", file=sys.stderr)

        # Build FTS5 and test HRR
        fts_db = build_fts_from_nodes(all_nodes)
        queries: list[dict[str, Any]] = H3_QUERIES.get(name, [])
        hrr_result = test_hrr_bridge(all_nodes, entity_edges, fts_db, queries, name)

        print(f"\n    HRR bridge test:", file=sys.stderr)
        if hrr_result.get("skipped"):
            print(f"      SKIPPED: {hrr_result['reason']}", file=sys.stderr)
        else:
            print(f"      Entity edges: {hrr_result['entity_edge_count']}", file=sys.stderr)
            print(f"      HRR nodes: {hrr_result['hrr_node_count']}", file=sys.stderr)
            print(f"\n      {'Query':<45} {'FTS5':>6} {'Comb':>6} {'HRR+?':>6}", file=sys.stderr)
            print(f"      {'-'*65}", file=sys.stderr)
            for qr in hrr_result["query_results"]:
                marker = " <--" if qr["hrr_added_value"] else ""
                print(f"      {qr['query'][:44]:<45} {qr['fts_precision']:>6.0%} "
                      f"{qr['combined_precision']:>6.0%} {'YES' if qr['hrr_added_value'] else 'no':>6}{marker}",
                      file=sys.stderr)

            print(f"\n      HRR added value on {hrr_result['hrr_added_value_count']}/{len(queries)} queries",
                  file=sys.stderr)

        all_results[name] = {
            "entity_mentions": {k: len(v) for k, v in mentions.items()},
            "entity_edges": len(entity_edges),
            "entity_edge_types": edge_type_counts,
            "graph": graph_props,
            "hrr_test": hrr_result,
        }

    # H3 verdict
    print(f"\n{'='*70}", file=sys.stderr)
    print("H3 VERDICT: Does HRR add value on non-alpha-seek topologies?", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    for name, r in all_results.items():
        hrr = r["hrr_test"]
        if hrr.get("skipped"):
            print(f"  {name}: SKIPPED ({hrr['reason']})", file=sys.stderr)
        else:
            added = hrr["hrr_added_value_count"]
            total = len(hrr["query_results"])
            print(f"  {name}: HRR added value on {added}/{total} queries "
                  f"({added/total:.0%})", file=sys.stderr)

    # Save
    out = Path("experiments/exp49c_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
