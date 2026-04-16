"""Structured fact triple extraction from text.

Extracts (entity, property, value) triples from structured fact statements.
Used during ingestion to create entity-level graph edges and enable
SUPERSEDES-based conflict resolution.

Regex-only extraction (no LLM calls). Falls through gracefully when
text does not match any known pattern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FactTriple:
    """A structured fact extracted from text."""

    entity: str
    property_name: str
    value: str
    serial: int | None = None
    source_text: str = ""


# Ordered list of (regex_pattern, entity_group, property_label, value_group).
# Patterns are tried in order; first match wins.
# Groups are 1-indexed regex capture groups.
_FACT_PATTERNS: list[tuple[re.Pattern[str], int, str, int]] = [
    # "X is a citizen of Y"
    (re.compile(r"^(.+?)\s+is a citizen of\s+(.+)$", re.I), 1, "citizen_of", 2),
    # "X plays the position of Y"
    (re.compile(r"^(.+?)\s+plays the position of\s+(.+)$", re.I), 1, "plays_position", 2),
    # "X is associated with the sport of Y"
    (re.compile(r"^(.+?)\s+is associated with the sport of\s+(.+)$", re.I), 1, "sport", 2),
    # "X is affiliated with the religion of Y"
    (re.compile(r"^(.+?)\s+is affiliated with the religion of\s+(.+)$", re.I), 1, "religion", 2),
    # "The author of X is Y"
    (re.compile(r"^The author of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "author", 2),
    # "The original language of X is Y"
    (re.compile(r"^The (?:origianl|original) language of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "language", 2),
    # "X was created in the country of Y"
    (re.compile(r"^(.+?)\s+was created in the country of\s+(.+)$", re.I), 1, "created_in_country", 2),
    # "X was founded by Y"
    (re.compile(r"^(.+?)\s+was founded by\s+(.+)$", re.I), 1, "founded_by", 2),
    # "X was created by Y"
    (re.compile(r"^(.+?)\s+was created by\s+(.+)$", re.I), 1, "created_by", 2),
    # "X was developed by Y"
    (re.compile(r"^(.+?)\s+was developed by\s+(.+)$", re.I), 1, "developed_by", 2),
    # "The type of music that X plays is Y"
    (re.compile(r"^The type of music that\s+(.+?)\s+plays is\s+(.+)$", re.I), 1, "music_type", 2),
    # "The company that produced X is Y"
    (re.compile(r"^The company that produced\s+(.+?)\s+is\s+(.+)$", re.I), 1, "produced_by", 2),
    # "X is employed by Y"
    (re.compile(r"^(.+?)\s+is employed by\s+(.+)$", re.I), 1, "employed_by", 2),
    # "X is married to Y"
    (re.compile(r"^(.+?)\s+is married to\s+(.+)$", re.I), 1, "married_to", 2),
    # "X speaks the language of Y"
    (re.compile(r"^(.+?)\s+speaks the language of\s+(.+)$", re.I), 1, "speaks_language", 2),
    # "X is located in the continent of Y"
    (re.compile(r"^(.+?)\s+is located in the continent of\s+(.+)$", re.I), 1, "continent", 2),
    # "X is located in the country of Y"
    (re.compile(r"^(.+?)\s+is located in the country of\s+(.+)$", re.I), 1, "located_in_country", 2),
    # "X was born in Y"
    (re.compile(r"^(.+?)\s+was born in\s+(.+)$", re.I), 1, "born_in", 2),
    # "X died in Y"
    (re.compile(r"^(.+?)\s+died in\s+(.+)$", re.I), 1, "died_in", 2),
    # "X worked in the city of Y"
    (re.compile(r"^(.+?)\s+worked in the city of\s+(.+)$", re.I), 1, "worked_in_city", 2),
    # "X works in the field of Y"
    (re.compile(r"^(.+?)\s+works in the field of\s+(.+)$", re.I), 1, "works_in_field", 2),
    # "The original broadcaster of X is Y"
    (re.compile(r"^The (?:origianl|original) broadcaster of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "broadcaster", 2),
    # "X is a member of Y"
    (re.compile(r"^(.+?)\s+is a member of\s+(.+)$", re.I), 1, "member_of", 2),
    # "The capital of X is Y"
    (re.compile(r"^The capital of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "capital", 2),
    # "The head of state of X is Y"
    (re.compile(r"^The head of (?:state|government) of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "head_of_state", 2),
    # "The chairperson of X is Y"
    (re.compile(r"^The (?:chairperson|chairman|director|CEO|manager|president|governor) of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "chairperson", 2),
    # "The Governor/Tanaiste/etc of X is Y"
    (re.compile(r"^The (?:Governor|Tánaiste|Premier|Mayor) (?:of\s+)?(.+?)\s+is\s+(.+)$", re.I), 1, "head_of_state", 2),
    # "The headquarters of X is located in the city of Y"
    (re.compile(r"^The headquarters of\s+(.+?)\s+is located in the city of\s+(.+)$", re.I), 1, "headquarters_city", 2),
    # "The university where X was educated is Y" (note typo: "univeristy")
    (re.compile(r"^The (?:univeristy|university) where\s+(.+?)\s+was educated is\s+(.+)$", re.I), 1, "educated_at", 2),
    # "X was performed by Y"
    (re.compile(r"^(.+?)\s+was performed by\s+(.+)$", re.I), 1, "performed_by", 2),
    # "X is famous for Y"
    (re.compile(r"^(.+?)\s+is famous for\s+(.+)$", re.I), 1, "famous_for", 2),
    # "The head coach of X is Y"
    (re.compile(r"^The head coach of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "head_coach", 2),
    # "The religion of X is Y"
    (re.compile(r"^The religion of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "religion", 2),
    # "The official language of X is Y"
    (re.compile(r"^The official language of\s+(.+?)\s+is\s+(.+)$", re.I), 1, "official_language", 2),
]

# Pattern to extract serial number from numbered list format: "123. fact text"
_SERIAL_RE: re.Pattern[str] = re.compile(r"^(\d+)\.\s+(.+)$")


def extract_triple(text: str) -> FactTriple | None:
    """Extract a structured triple from a single fact statement.

    Handles numbered list format ("123. Entity is a citizen of Country")
    and plain text ("Entity is a citizen of Country").

    Returns None if no pattern matches.
    """
    line: str = text.strip().rstrip(".")

    # Try to extract serial number from numbered list format
    serial: int | None = None
    fact_text: str = line
    serial_match: re.Match[str] | None = _SERIAL_RE.match(line)
    if serial_match:
        serial = int(serial_match.group(1))
        fact_text = serial_match.group(2).strip().rstrip(".")

    # Try each pattern
    for pattern, entity_group, prop_name, value_group in _FACT_PATTERNS:
        m: re.Match[str] | None = pattern.match(fact_text)
        if m is not None:
            entity: str = m.group(entity_group).strip()
            value: str = m.group(value_group).strip()
            if entity and value:
                return FactTriple(
                    entity=entity,
                    property_name=prop_name,
                    value=value,
                    serial=serial,
                    source_text=text.strip(),
                )

    return None


def find_conflicting_triples(
    triples: list[FactTriple],
    new_triple: FactTriple,
) -> list[FactTriple]:
    """Find existing triples that conflict with a new triple.

    A conflict exists when two triples share the same (entity, property)
    but have different values. Returns all conflicting triples, sorted
    by serial number (lowest first).
    """
    conflicts: list[FactTriple] = []
    new_entity_lower: str = new_triple.entity.lower()
    for existing in triples:
        if (
            existing.entity.lower() == new_entity_lower
            and existing.property_name == new_triple.property_name
            and existing.value.lower() != new_triple.value.lower()
        ):
            conflicts.append(existing)

    # Sort by serial (None goes first, then ascending)
    conflicts.sort(key=lambda t: t.serial if t.serial is not None else -1)
    return conflicts


def resolve_conflict(triples: list[FactTriple]) -> FactTriple | None:
    """Given a list of conflicting triples about the same (entity, property),
    return the one with the highest serial number (newest fact wins).

    Returns None if the list is empty.
    """
    if not triples:
        return None

    best: FactTriple = triples[0]
    for t in triples[1:]:
        if t.serial is not None and (best.serial is None or t.serial > best.serial):
            best = t
    return best
