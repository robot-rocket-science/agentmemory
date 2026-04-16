"""MAB FactConsolidation adapter with entity-index retrieval.

Instead of FTS5 keyword search, uses a direct entity-name lookup index
built during ingestion. Multi-hop queries are decomposed into sequential
entity lookups, with SUPERSEDES-based conflict resolution at each hop.

This tests the hypothesis that entity-index retrieval closes the
multi-hop chaining gap identified in Exp 1 (58% of failures).

Usage:
    uv run python benchmarks/mab_entity_index_adapter.py --retrieve-only /tmp/exp4_entity.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from datasets import load_dataset  # type: ignore[import-untyped]

from agentmemory.triple_extraction import FactTriple, extract_triple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HF_DATASET: Final[str] = "ai-hyz/MemoryAgentBench"
DEFAULT_SOURCE: Final[str] = "factconsolidation_mh_262k"


# ---------------------------------------------------------------------------
# Entity Index (the core data structure)
# ---------------------------------------------------------------------------


@dataclass
class EntityFact:
    """A resolved fact about an entity."""

    entity: str
    property_name: str
    value: str
    serial: int


class EntityIndex:
    """Maps entity names to their current (highest-serial) facts.

    During ingestion, tracks all facts per (entity, property).
    Automatically resolves conflicts: highest serial wins.
    """

    def __init__(self) -> None:
        # (entity_lower, property) -> list of (serial, value, raw_text)
        self._facts: dict[tuple[str, str], list[tuple[int, str, str]]] = defaultdict(list)
        # entity_lower -> set of properties
        self._entity_props: dict[str, set[str]] = defaultdict(set)

    def add(self, triple: FactTriple) -> None:
        """Add a fact triple to the index."""
        key: tuple[str, str] = (triple.entity.lower(), triple.property_name)
        serial: int = triple.serial if triple.serial is not None else 0
        self._facts[key].append((serial, triple.value, triple.source_text))
        self._entity_props[triple.entity.lower()].add(triple.property_name)

    def resolve(self, entity: str, prop: str | None = None) -> list[EntityFact]:
        """Get current (highest-serial) facts for an entity.

        If prop is specified, returns only facts for that property.
        If prop is None, returns the resolved fact for every property.
        """
        entity_lower: str = entity.lower()
        results: list[EntityFact] = []

        if prop is not None:
            key: tuple[str, str] = (entity_lower, prop)
            facts: list[tuple[int, str, str]] = self._facts.get(key, [])
            if facts:
                best: tuple[int, str, str] = max(facts, key=lambda x: x[0])
                results.append(EntityFact(
                    entity=entity, property_name=prop,
                    value=best[1], serial=best[0],
                ))
        else:
            props: set[str] = self._entity_props.get(entity_lower, set())
            for p in props:
                key = (entity_lower, p)
                facts = self._facts.get(key, [])
                if facts:
                    best = max(facts, key=lambda x: x[0])
                    results.append(EntityFact(
                        entity=entity, property_name=p,
                        value=best[1], serial=best[0],
                    ))

        return results

    def lookup_value(self, value: str) -> list[EntityFact]:
        """Find all entities where this value appears as a fact value.

        Used for reverse lookups in multi-hop (hop-2: given the
        intermediate value, find facts about it as an entity).
        """
        value_lower: str = value.lower()
        results: list[EntityFact] = []
        # Check if the value is itself an entity
        entity_facts: list[EntityFact] = self.resolve(value_lower)
        if entity_facts:
            return entity_facts
        return results

    def has_entity(self, entity: str) -> bool:
        """Check if an entity exists in the index."""
        return entity.lower() in self._entity_props

    def find_partial_entity(self, entity: str) -> str | None:
        """Find an entity by partial match. Returns the matched key or None."""
        entity_lower: str = entity.lower()
        for ent_key in self._entity_props:
            if entity_lower in ent_key or ent_key in entity_lower:
                return ent_key
        return None

    @property
    def entity_count(self) -> int:
        return len(self._entity_props)

    @property
    def fact_count(self) -> int:
        return sum(len(v) for v in self._facts.values())

    @property
    def conflict_count(self) -> int:
        return sum(1 for v in self._facts.values() if len(v) > 1)


# ---------------------------------------------------------------------------
# Question decomposition (regex-based, no LLM)
# ---------------------------------------------------------------------------


def extract_entity_from_question(question: str) -> str | None:
    """Extract the primary named entity from a multi-hop question.

    Looks for quoted entities first, then entity-bearing phrases,
    then proper nouns including single-word and mixed-case names.
    """
    # Quoted entities: "American Pastoral", "Your Hit Parade"
    quoted: list[str] = re.findall(r'"([^"]+)"', question)
    if quoted:
        return quoted[-1]

    # Entity after "created/developed/founded/produced/broadcasted" + name
    # Allows lowercase for things like "centrifugal governor"
    m_created: re.Match[str] | None = re.search(
        r'(?:created|developed|founded|produced|broadcasted|established)\s+'
        r'(?:the\s+)?([A-Za-z][a-zA-Z\s\.\-\'\,]+?)(?:\s+(?:is|was|born|located)\b|\?|$)',
        question,
    )
    if m_created:
        entity: str = m_created.group(1).strip().rstrip("?., ")
        if len(entity) > 2:
            return entity

    # Entity after "that/which/whom" + name + "is/was"
    m_that: re.Match[str] | None = re.search(
        r'(?:that|which|whom)\s+([A-Z][a-zA-Z\s\.\-\'\,]+?)\s+(?:is|was|professes)',
        question,
    )
    if m_that:
        entity = m_that.group(1).strip().rstrip("?., ")
        if len(entity) > 2:
            return entity

    # Entity after "by", "of", "with", "for" at end of question
    # Stop at common verbs (was, is, has, born, located, etc.)
    m: re.Match[str] | None = re.search(
        r'(?:by|of|with|for)\s+([A-Z][a-zA-Z\s\.\-\']+?)'
        r'(?:\s+(?:was|is|has|born|located|played|wrote|created)\b|\?|$)',
        question,
    )
    if m:
        entity = m.group(1).strip().rstrip("?. ")
        if len(entity) > 2:
            return entity

    # "affiliated with <entity>" pattern
    m_affil: re.Match[str] | None = re.search(
        r'affiliated with\s+([A-Z][a-zA-Z\s\.\-\']+?)(?:\s+was\b|\?|$)',
        question,
    )
    if m_affil:
        entity = m_affil.group(1).strip().rstrip("?. ")
        if len(entity) > 2:
            return entity

    # Multi-word capitalized phrase (2+ words)
    caps: list[str] = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', question)
    if caps:
        return caps[-1]

    # Single capitalized word that looks like a proper noun (not a common word)
    # Must be at least 4 chars and not a common English word
    common: frozenset[str] = frozenset({
        "What", "Which", "Where", "When", "How", "Who", "That", "This",
        "The", "Does", "Have", "City", "Name", "Country", "Language",
    })
    single_caps: list[str] = re.findall(r'\b([A-Z][a-z]{3,})\b', question)
    for sc in reversed(single_caps):
        if sc not in common:
            return sc

    return None


def extract_target_property(question: str) -> str | None:
    """Extract what property the question is asking about.

    Maps question phrases to entity index property names.
    """
    q: str = question.lower()

    property_map: list[tuple[str, str]] = [
        ("country of origin", "created_in_country"),
        ("country of citizenship", "citizen_of"),
        ("continent", "continent"),
        ("capital", "capital"),
        ("religion", "religion"),
        ("language", "language"),
        ("official language", "official_language"),
        ("speaks", "speaks_language"),
        ("sport", "sport"),
        ("position", "plays_position"),
        ("author", "author"),
        ("spouse", "married_to"),
        ("birthplace", "born_in"),
        ("born in", "born_in"),
        ("place of death", "died_in"),
        ("died in", "died_in"),
        ("head of state", "head_of_state"),
        ("chairperson", "chairperson"),
        ("head coach", "head_coach"),
        ("employed by", "employed_by"),
        ("works for", "employed_by"),
        ("created by", "created_by"),
        ("developed by", "developed_by"),
        ("broadcaster", "broadcaster"),
        ("produced", "produced_by"),
        ("manufacturer", "produced_by"),
        ("headquarters", "headquarters_city"),
        ("educated", "educated_at"),
        ("famous for", "famous_for"),
        ("performed by", "performed_by"),
        ("founded by", "founded_by"),
        ("member of", "member_of"),
        ("music", "music_type"),
        ("field", "works_in_field"),
        ("worked in", "worked_in_city"),
    ]

    for phrase, prop in property_map:
        if phrase in q:
            return prop

    return None


# ---------------------------------------------------------------------------
# Multi-hop entity-index retrieval
# ---------------------------------------------------------------------------


def multi_hop_retrieve(
    index: EntityIndex,
    question: str,
    max_hops: int = 4,
) -> str:
    """Execute a multi-hop query using iterative entity-index lookups.

    Starting from the entity extracted from the question, iteratively
    chains through entity values up to max_hops deep. At each hop,
    resolved facts about each entity are collected, and each fact's
    value becomes a candidate entity for the next hop.

    Returns concatenated fact texts, newest first.
    """
    entity: str | None = extract_entity_from_question(question)
    if entity is None:
        return ""

    all_facts: list[EntityFact] = []
    visited_entities: set[str] = set()
    current_entities: list[str] = [entity]

    for _hop in range(max_hops):
        next_entities: list[str] = []
        for ent in current_entities:
            ent_lower: str = ent.lower()
            if ent_lower in visited_entities:
                continue
            visited_entities.add(ent_lower)

            facts: list[EntityFact] = index.resolve(ent)
            if not facts:
                partial: str | None = index.find_partial_entity(ent)
                if partial is not None:
                    facts = index.resolve(partial)
                    visited_entities.add(partial)

            all_facts.extend(facts)
            for fact in facts:
                if fact.value.lower() not in visited_entities:
                    next_entities.append(fact.value)

        if not next_entities:
            break
        # Cap breadth to prevent explosion
        current_entities = next_entities[:15]

    # Sort by serial descending (newest first)
    all_facts.sort(key=lambda f: f.serial, reverse=True)

    # Deduplicate
    seen: set[str] = set()
    lines: list[str] = []
    for fact in all_facts:
        line: str = f"{fact.entity} {fact.property_name}: {fact.value}"
        if line not in seen:
            seen.add(line)
            lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def build_entity_index(context: str) -> tuple[EntityIndex, int, int]:
    """Parse all facts from context into an entity index.

    Returns (index, total_lines, triples_extracted).
    """
    index: EntityIndex = EntityIndex()

    lines: list[str] = context.strip().split("\n")
    if lines and lines[0].startswith("Here is"):
        lines = lines[1:]

    total: int = len(lines)
    extracted: int = 0

    for line in lines:
        triple: FactTriple | None = extract_triple(line)
        if triple is not None:
            index.add(triple)
            extracted += 1

    return index, total, extracted


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Exp 4: Entity-index retrieval for multi-hop",
    )
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE,
        help=f"MAB source (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--subset", type=int, default=None,
        help="Limit to first N questions",
    )
    parser.add_argument(
        "--retrieve-only", default=None, metavar="PATH",
        help="Write retrieval results (NO answers) to PATH",
    )
    args: argparse.Namespace = parser.parse_args()

    print("=== Exp 4: Entity-Index Retrieval ===")
    print(f"Source: {args.source}")

    # Load data
    ds = load_dataset(HF_DATASET, split="Conflict_Resolution")  # type: ignore[no-untyped-call]
    context: str = ""
    questions: list[str] = []
    answers: list[list[str]] = []

    for raw_row in ds:  # type: ignore[union-attr]
        row: dict[str, object] = dict(raw_row)  # type: ignore[arg-type]
        metadata: dict[str, object] = row.get("metadata", {})  # type: ignore[assignment]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if str(metadata.get("source", "")) != args.source:
            continue
        context = str(row["context"])
        questions = list(row["questions"])  # type: ignore[arg-type]
        answers = [list(a) for a in row["answers"]]  # type: ignore[union-attr]
        break

    if not context:
        print(f"No data for source: {args.source}")
        return

    if args.subset is not None:
        questions = questions[:args.subset]
        answers = answers[:args.subset]

    # Build entity index
    t0: float = time.monotonic()
    index: EntityIndex
    total_lines: int
    extracted: int
    index, total_lines, extracted = build_entity_index(context)
    build_time: float = time.monotonic() - t0

    print(f"Index built: {index.entity_count} entities, {index.fact_count} facts, "
          f"{index.conflict_count} conflicts, {extracted}/{total_lines} extracted "
          f"in {build_time:.2f}s")

    # Run queries
    per_question: list[dict[str, object]] = []
    ground_truth: list[dict[str, object]] = []

    t1: float = time.monotonic()
    answer_in_ctx: int = 0
    for i, (question, answer_list) in enumerate(zip(questions, answers)):
        ctx: str = multi_hop_retrieve(index, question)
        per_question.append({
            "id": i,
            "question": question,
            "context": ctx,
        })
        ground_truth.append({
            "id": i,
            "answers": answer_list,
        })

        if answer_list[0].lower() in ctx.lower():
            answer_in_ctx += 1

    query_time: float = time.monotonic() - t1

    print(f"Queried {len(questions)} questions in {query_time:.2f}s")
    print(f"Answer in context: {answer_in_ctx}/{len(questions)} = {answer_in_ctx/len(questions)*100:.0f}%")

    # Write output
    if args.retrieve_only:
        retrieve_path: Path = Path(args.retrieve_only)
        gt_path: Path = retrieve_path.with_name(
            retrieve_path.stem + "_gt" + retrieve_path.suffix,
        )
        with retrieve_path.open("w", encoding="utf-8") as f:
            json.dump(per_question, f, indent=2)
        with gt_path.open("w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)
        print(f"Wrote to {args.retrieve_only}")
        print(f"Wrote GT to {gt_path}")
        print("ISOLATION: retrieval file contains NO ground truth")


if __name__ == "__main__":
    main()
