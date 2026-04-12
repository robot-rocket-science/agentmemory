"""Experiment 53: Vocabulary Gap Prevalence Across Projects

Measures what fraction of directive/behavioral beliefs are unreachable by
text-based retrieval (FTS5) across 5 real projects.  For each directive,
3 situation-based queries are generated using rule-based heuristics (no LLM).
If none of the 3 queries retrieves the directive in top-30 FTS5 results,
the directive has a vocabulary gap.

Hypotheses:
  H1: Vocabulary gap prevalence >= 5% of directive beliefs across all 5 projects
  H2: Tool/command bans + domain jargon account for >= 50% of gaps
  H3: >= 80% of vocab-gap beliefs are HRR-bridgeable
  H4: Doc-rich projects have lower gap rates than doc-light projects

Null: Gap prevalence < 3%, HRR adds negligible value
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

GapCategory = str  # one of the GAP_CATEGORIES below

GAP_CATEGORIES: Final[list[str]] = [
    "tool_ban",
    "domain_jargon",
    "cross_domain_constraint",
    "implicit_rule",
    "emphatic_prohibition",
    "other",
]


@dataclass
class Directive:
    """A directive or behavioral belief extracted from a project."""

    text: str
    source_file: str
    pattern_matched: str
    project: str


@dataclass
class QuerySet:
    """Three situation-based queries for a directive."""

    queries: list[str]
    low_confidence: bool = False


@dataclass
class GapResult:
    """Result of vocab-gap testing for a single directive."""

    directive: Directive
    queries: QuerySet
    fts5_hits: dict[str, list[str]]  # query -> list of matching texts
    text_reachable: bool
    gap_category: str | None = None
    hrr_bridgeable: bool | None = None
    colocated_directives: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class ProjectResult:
    """Aggregated results for a single project."""

    project: str
    path: str
    total_directives: int
    total_sentences: int
    gap_count: int
    gap_rate: float
    gap_categories: dict[str, int]
    hrr_bridgeable_count: int
    hrr_bridgeable_rate: float
    directives: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKIP_DIRS: Final[set[str]] = {
    ".venv", "__pycache__", ".git", "node_modules", ".egg-info",
    "target", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".tox", ".ruff_cache",
}

PROJECTS: Final[dict[str, Path]] = {
    "alpha-seek": Path("/Users/thelorax/projects/alpha-seek"),
    "optimus-prime": Path("/Users/thelorax/projects/optimus-prime"),
    "debserver": Path("/Users/thelorax/projects/debserver"),
    "jose-bully": Path("/Users/thelorax/projects/jose-bully"),
    "code-monkey": Path("/Users/thelorax/projects/code-monkey"),
}

# Patterns that indicate directive/behavioral beliefs
DIRECTIVE_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\b(always)\b", re.IGNORECASE),
    re.compile(r"\b(never)\b", re.IGNORECASE),
    re.compile(r"\b(don['']t)\b", re.IGNORECASE),
    re.compile(r"\b(must not)\b", re.IGNORECASE),
    re.compile(r"\b(banned)\b", re.IGNORECASE),
    re.compile(r"\b(do not)\b", re.IGNORECASE),
    re.compile(r"\bstop\b", re.IGNORECASE),
    re.compile(r"\b(from now on)\b", re.IGNORECASE),
    re.compile(r"\b(mandatory)\b", re.IGNORECASE),
    re.compile(r"\b(non-negotiable)\b", re.IGNORECASE),
    re.compile(r"\b(must always)\b", re.IGNORECASE),
    re.compile(r"\b(MUST)\b"),  # case-sensitive: emphatic MUST
    re.compile(r"\b(shall not)\b", re.IGNORECASE),
    re.compile(r"\b(forbidden)\b", re.IGNORECASE),
    re.compile(r"\b(required)\b", re.IGNORECASE),
    re.compile(r"\b(IMPORTANT)\b"),  # case-sensitive: emphatic
]

# Sentences to skip (headings, table headers, boilerplate)
SKIP_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"^\s*#"),  # markdown headings
    re.compile(r"^\s*\|"),  # table rows
    re.compile(r"^\s*```"),  # code blocks
    re.compile(r"^\s*-\s*$"),  # empty list items
    re.compile(r"^\s*$"),  # empty lines
]

TOP_K: Final[int] = 30

# ---------------------------------------------------------------------------
# Common tool/command purpose mappings for query generation
# ---------------------------------------------------------------------------

TOOL_PURPOSE_MAP: Final[dict[str, list[str]]] = {
    "async_bash": ["background execution", "long running task", "parallel command"],
    "await_job": ["wait for completion", "check job status", "poll results"],
    "pyright": ["type checking Python code", "static analysis", "type errors"],
    "docker": ["containerize application", "build deployment image", "isolate dependencies"],
    "git push --force": ["overwrite remote history", "rewrite branch", "force update"],
    "git rebase -i": ["squash commits", "edit commit history", "clean up branch"],
    "ssh": ["remote machine access", "connect to server", "run command remotely"],
    "scp": ["copy files to server", "transfer data remotely", "upload artifacts"],
    "rsync": ["sync files between machines", "deploy code", "mirror directory"],
    "gcloud": ["cloud compute setup", "GCP resource management", "cloud deployment"],
    "pip": ["install Python packages", "manage dependencies", "add library"],
    "conda": ["manage Python environment", "install packages", "create env"],
    "uv": ["manage Python packages", "install dependencies", "run scripts"],
    "make": ["build project", "run task", "compile code"],
    "curl": ["fetch URL", "API request", "download file"],
    "wget": ["download file", "fetch resource", "grab URL"],
    "npm": ["install JavaScript packages", "manage node dependencies", "run scripts"],
    "pytest": ["run tests", "check test suite", "verify code works"],
    "mypy": ["type checking", "static analysis Python", "find type bugs"],
    "ruff": ["lint Python code", "format code", "check style"],
    "black": ["format Python code", "auto-format", "code style"],
}

# Domain-specific term mappings: jargon -> plain description
DOMAIN_TERM_MAP: Final[dict[str, list[str]]] = {
    "walk-forward": ["evaluate strategy over time", "test on rolling periods",
                     "sequential validation"],
    "kelly": ["optimal bet sizing", "how much to wager", "position sizing"],
    "sharpe": ["risk-adjusted performance", "return per unit risk",
               "portfolio quality metric"],
    "otm": ["cheap option contract", "out of money option", "low probability bet"],
    "dte": ["time until option expires", "days remaining on contract",
            "option expiration window"],
    "pnl": ["profit and loss", "trading results", "money made or lost"],
    "backtest": ["test strategy on historical data", "simulate past trades",
                 "validate approach"],
    "dispatch": ["send job to compute", "deploy to server", "run remotely"],
    "embargo": ["waiting period between data", "buffer zone in time",
                "separation between train and test"],
    "holdout": ["reserved test data", "data not used for training",
                "validation set"],
    "gcp": ["Google cloud computing", "cloud server", "remote compute"],
    "nfs": ["shared network storage", "mounted drive across machines",
            "file sharing between servers"],
    "dhcp": ["automatic IP assignment", "network address configuration",
             "device gets IP address"],
    "poe": ["power over ethernet", "power network device through cable",
            "ethernet powered device"],
    "vlan": ["virtual network segment", "network isolation", "traffic separation"],
    "ci": ["automated testing on push", "continuous integration",
           "build verification"],
    "cd": ["automated deployment", "continuous delivery", "auto-deploy"],
    "hr": ["human resources department", "workplace complaint",
           "employment issue"],
    "uat": ["user acceptance testing", "verify feature works for user",
            "manual testing"],
}

# Behavioral verb -> situation mapping
BEHAVIOR_SITUATION_MAP: Final[dict[str, list[str]]] = {
    "cite": ["presenting research findings", "writing project document",
             "making factual claim"],
    "verify": ["about to ship code", "completing a task",
               "checking work before submission"],
    "test": ["ready to deploy code", "finished implementing feature",
             "preparing release"],
    "review": ["merging pull request", "approving code change",
               "evaluating contribution"],
    "document": ["finishing feature implementation", "completing milestone",
                 "recording decision"],
    "update": ["after completing work", "state changed",
               "new information available"],
    "deploy": ["shipping to production", "releasing code",
               "pushing to server"],
    "commit": ["saving code changes", "recording progress",
               "checkpointing work"],
    "build": ["compiling project", "creating artifact",
              "preparing release"],
    "report": ["summarizing findings", "presenting results",
               "communicating status"],
    "type": ["writing new Python code", "modifying function signature",
             "adding new module"],
    "annotate": ["defining function interface", "declaring variable",
                 "creating data structure"],
    "format": ["cleaning up code", "preparing for review",
               "standardizing style"],
    "lint": ["checking code quality", "finding style issues",
             "pre-commit check"],
    "rebalance": ["adjusting portfolio weights", "changing position mix",
                  "strategy allocation change"],
    "elaborate": ["explaining code to user", "providing details",
                  "expanding on topic"],
    "suggest": ["proposing approach", "recommending solution",
                "offering alternative"],
    "recommend": ["advising on approach", "proposing strategy",
                  "suggesting direction"],
    "consider": ["evaluating options", "weighing alternatives",
                 "thinking about approach"],
    "propose": ["pitching new idea", "suggesting change",
                "recommending modification"],
}


# ---------------------------------------------------------------------------
# Step 1: Extract directives from a project
# ---------------------------------------------------------------------------

def find_md_files(project_root: Path) -> list[Path]:
    """Find all .md files in a project, respecting skip dirs."""
    md_files: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md"):
                md_files.append(Path(root) / f)
    # Also check for CLAUDE.md specifically
    claude_md: Path = project_root / "CLAUDE.md"
    if claude_md.exists() and claude_md not in md_files:
        md_files.append(claude_md)
    return md_files


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks (line-based for markdown)."""
    lines: list[str] = text.split("\n")
    sentences: list[str] = []
    for line in lines:
        stripped: str = line.strip()
        if not stripped:
            continue
        # Skip headings, table rows, code blocks
        skip: bool = False
        for pat in SKIP_PATTERNS:
            if pat.match(stripped):
                skip = True
                break
        if skip:
            continue
        # Clean markdown formatting
        cleaned: str = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
        cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
        cleaned = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", cleaned)
        # Remove leading list markers
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
        if len(cleaned) > 10:  # skip very short fragments
            sentences.append(cleaned)
    return sentences


def _is_directive_sentence(sentence: str, source_file: str) -> bool:
    """Filter out narrative sentences that happen to contain directive words.

    A directive sentence typically:
    - Is imperative ("do X", "use X", "run X")
    - Addresses the reader ("you", "the agent")
    - Is in a rules/config file (CLAUDE.md, REQUIREMENTS.md, etc.)
    - Contains action verbs with prohibitions ("never use", "always run")
    - Is short and prescriptive rather than long and narrative

    Narrative sentences (findings, descriptions, logs) are filtered out.
    """
    lower: str = sentence.lower()

    # High-priority source files: always treat as directives
    priority_files: list[str] = [
        "claude.md", "requirements.md", "decisions.md",
        "knowledge.md", "overrides.md",
    ]
    src_lower: str = source_file.lower()
    if any(pf in src_lower for pf in priority_files):
        return True

    # Narrative indicators: past-tense findings, status reports, data
    narrative_patterns: list[re.Pattern[str]] = [
        re.compile(r"\b(finding|found|showed|observed|produced|resulted)\b", re.I),
        re.compile(r"\b(was|were|had been)\s+(never|always)\b", re.I),
        re.compile(r"^\d{4}-\d{2}-\d{2}"),  # date-stamped entries
        re.compile(r"\b(status|result|output|log|trace|error)\s*:", re.I),
        re.compile(r"\b\d+\.\d+%"),  # percentage data
        re.compile(r"\b(m\d{3}|s\d{2}|t\d{2}|r\d+)\b", re.I),  # milestone/task IDs
    ]
    narrative_score: int = sum(
        1 for p in narrative_patterns if p.search(lower)
    )

    # Directive indicators: imperative mood, second person, prescriptive
    directive_patterns: list[re.Pattern[str]] = [
        re.compile(r"\b(you|agent|user)\b", re.I),
        re.compile(r"\b(use|run|check|verify|ensure|update|read|see)\b", re.I),
        re.compile(r"\b(policy|rule|protocol|gate|requirement)\b", re.I),
        re.compile(r"^(do not|never|always|must)\b", re.I),
        re.compile(r"\b(before|after|when|whenever|if you)\b", re.I),
    ]
    directive_score: int = sum(
        1 for p in directive_patterns if p.search(lower)
    )

    # If clearly narrative, reject
    if narrative_score >= 2 and directive_score == 0:
        return False

    # If clearly directive, accept
    if directive_score >= 1:
        return True

    # Ambiguous: accept if short (< 200 chars, likely a rule) or reject
    return len(sentence) < 200


def extract_directives(project_name: str, project_root: Path) -> list[Directive]:
    """Extract directive/behavioral beliefs from all .md files."""
    md_files: list[Path] = find_md_files(project_root)
    directives: list[Directive] = []
    seen_texts: set[str] = set()

    for md_file in md_files:
        try:
            text: str = md_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue

        sentences: list[str] = split_sentences(text)
        rel_path: str = str(md_file.relative_to(project_root))

        for sentence in sentences:
            # Check each directive pattern
            for pattern in DIRECTIVE_PATTERNS:
                match: re.Match[str] | None = pattern.search(sentence)
                if match is not None:
                    # Filter: is this actually a directive, not narrative?
                    if not _is_directive_sentence(sentence, rel_path):
                        break
                    # Deduplicate
                    norm: str = sentence.lower().strip()
                    if norm not in seen_texts:
                        seen_texts.add(norm)
                        directives.append(Directive(
                            text=sentence,
                            source_file=rel_path,
                            pattern_matched=match.group(0),
                            project=project_name,
                        ))
                    break  # one match per sentence is enough

    return directives


def extract_all_sentences(project_root: Path) -> list[str]:
    """Extract all sentences from all .md files (the retrieval corpus)."""
    md_files: list[Path] = find_md_files(project_root)
    all_sentences: list[str] = []

    for md_file in md_files:
        try:
            text: str = md_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError):
            continue
        all_sentences.extend(split_sentences(text))

    return all_sentences


# ---------------------------------------------------------------------------
# Step 2: Generate situation-based queries (rule-based, no LLM)
# ---------------------------------------------------------------------------

def _extract_tool_names(text: str) -> list[str]:
    """Extract tool/command names from directive text."""
    # Look for backtick-quoted terms
    backtick_terms: list[str] = re.findall(r"`([^`]+)`", text)
    # Look for common command patterns
    cmd_patterns: list[str] = re.findall(
        r"\b(async_bash|await_job|pyright|docker|git\s+\w+|ssh|scp|rsync|"
        r"gcloud|pip|conda|uv|make|curl|wget|npm|pytest|mypy|ruff|black|"
        r"sftp|apt|brew|cargo|go|rustc|gcc|javac|mvn|gradle)\b",
        text, re.IGNORECASE,
    )
    return backtick_terms + cmd_patterns


def _extract_domain_terms(text: str) -> list[str]:
    """Extract domain-specific jargon from directive text.

    Uses word-boundary matching to avoid false positives like
    'ci' matching inside 'citizen' or 'dte' inside 'Dead'.
    """
    found: list[str] = []
    text_lower: str = text.lower()
    for term in DOMAIN_TERM_MAP:
        # Use word-boundary regex to avoid substring false positives
        pattern: str = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, text_lower):
            found.append(term)
    return found


def _extract_behavior_verbs(text: str) -> list[str]:
    """Extract behavioral verbs from directive text.

    Uses word-boundary matching to avoid substring false positives
    like 'cite' matching inside 'excited'.
    """
    found: list[str] = []
    text_lower: str = text.lower()
    for verb in BEHAVIOR_SITUATION_MAP:
        pattern: str = r"\b" + re.escape(verb) + r"\b"
        if re.search(pattern, text_lower):
            found.append(verb)
    return found


def _get_content_words(text: str) -> set[str]:
    """Get content words (non-stopword, non-punctuation) from text."""
    stop_words: set[str] = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "can", "could", "must", "ought", "need",
        "dare", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "both", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so",
        "than", "too", "very", "just", "because", "but", "and", "or", "if",
        "while", "that", "this", "it", "its", "which", "who", "whom",
        "what", "these", "those", "i", "me", "my", "we", "our", "you",
        "your", "he", "him", "his", "she", "her", "they", "them", "their",
        "always", "never", "don't", "must", "banned", "stop", "mandatory",
        "required", "important", "shall", "forbidden", "every", "any",
    }
    words: list[str] = re.findall(r"[a-z][a-z0-9_-]+", text.lower())
    return {w for w in words if w not in stop_words and len(w) > 2}


def generate_queries(directive: Directive) -> QuerySet:
    """Generate 3 situation-based queries for a directive.

    Strategy:
    1. If directive mentions tools/commands, use tool purpose mappings.
    2. If directive has domain jargon, use plain-language descriptions.
    3. If directive has behavioral verbs, use situation mappings.
    4. Fallback: use generic topic-area query (marked low_confidence).
    """
    text: str = directive.text
    queries: list[str] = []
    low_confidence: bool = False

    # Strategy 1: Tool/command names -> purpose queries
    tools: list[str] = _extract_tool_names(text)
    for tool in tools:
        tool_key: str = tool.lower().strip()
        if tool_key in TOOL_PURPOSE_MAP:
            purposes: list[str] = TOOL_PURPOSE_MAP[tool_key]
            for purpose in purposes:
                if len(queries) < 3:
                    queries.append(purpose)

    # Strategy 2: Domain jargon -> plain descriptions
    domain_terms: list[str] = _extract_domain_terms(text)
    for term in domain_terms:
        descriptions: list[str] = DOMAIN_TERM_MAP[term]
        for desc in descriptions:
            if len(queries) < 3 and desc not in queries:
                queries.append(desc)

    # Strategy 3: Behavioral verbs -> situations
    verbs: list[str] = _extract_behavior_verbs(text)
    for verb in verbs:
        situations: list[str] = BEHAVIOR_SITUATION_MAP[verb]
        for sit in situations:
            if len(queries) < 3 and sit not in queries:
                queries.append(sit)

    # Strategy 4: Fallback -- extract topic words and build generic queries
    if len(queries) < 3:
        content_words: set[str] = _get_content_words(text)
        # Remove directive signal words, keep topic words
        topic_words: list[str] = sorted(content_words)[:5]
        if topic_words:
            # Generate generic activity queries
            fallback_templates: list[str] = [
                f"working on {' '.join(topic_words[:3])}",
                f"handling {' '.join(topic_words[1:4])} task",
                f"approaching {' '.join(topic_words[:2])} problem",
            ]
            for tmpl in fallback_templates:
                if len(queries) < 3 and tmpl not in queries:
                    queries.append(tmpl)
                    low_confidence = True

    # Ensure we always have exactly 3
    while len(queries) < 3:
        queries.append(f"general project task context")
        low_confidence = True

    return QuerySet(queries=queries[:3], low_confidence=low_confidence)


# ---------------------------------------------------------------------------
# Step 3: FTS5 retrieval testing
# ---------------------------------------------------------------------------

def build_fts5_index(sentences: list[str]) -> sqlite3.Connection:
    """Build an in-memory FTS5 index over all sentences."""
    conn: sqlite3.Connection = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE corpus USING fts5(content, tokenize='porter')"
    )
    for sent in sentences:
        conn.execute("INSERT INTO corpus(content) VALUES (?)", (sent,))
    conn.commit()
    return conn


def fts5_search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = TOP_K,
) -> list[str]:
    """Search FTS5 index, return top-k matching texts."""
    # Build OR query from words
    words: list[str] = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", query)
    if not words:
        return []
    fts_query: str = " OR ".join(words)
    try:
        rows: list[tuple[str]] = conn.execute(
            "SELECT content FROM corpus WHERE corpus MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_query, top_k),
        ).fetchall()
        return [str(r[0]) for r in rows]
    except sqlite3.OperationalError:
        return []


def test_retrievability(
    conn: sqlite3.Connection,
    directive: Directive,
    query_set: QuerySet,
) -> GapResult:
    """Test whether any of the 3 queries retrieves the directive text."""
    fts5_hits: dict[str, list[str]] = {}
    text_reachable: bool = False
    directive_lower: str = directive.text.lower().strip()

    for query in query_set.queries:
        results: list[str] = fts5_search(conn, query)
        fts5_hits[query] = results[:5]  # store top-5 for debugging

        # Check if directive text appears in results
        for result in results:
            if _texts_match(directive_lower, result.lower().strip()):
                text_reachable = True
                break

    return GapResult(
        directive=directive,
        queries=query_set,
        fts5_hits=fts5_hits,
        text_reachable=text_reachable,
    )


def _texts_match(a: str, b: str) -> bool:
    """Check if two texts are effectively the same directive."""
    # Exact match
    if a == b:
        return True
    # One contains the other (directives may be substrings of longer sentences)
    if a in b or b in a:
        return True
    # High word overlap (>= 70% Jaccard on content words)
    words_a: set[str] = set(re.findall(r"[a-z][a-z0-9]+", a))
    words_b: set[str] = set(re.findall(r"[a-z][a-z0-9]+", b))
    if not words_a or not words_b:
        return False
    intersection: int = len(words_a & words_b)
    union: int = len(words_a | words_b)
    if union == 0:
        return False
    jaccard: float = intersection / union
    return jaccard >= 0.7


# ---------------------------------------------------------------------------
# Step 4: Classify gap category
# ---------------------------------------------------------------------------

def classify_gap(directive: Directive) -> str:
    """Classify a vocabulary-gap directive into a category."""
    text_lower: str = directive.text.lower()

    # Tool ban: mentions specific tools/commands with negative language
    tools: list[str] = _extract_tool_names(directive.text)
    negative_words: list[str] = [
        "banned", "never", "don't", "do not", "must not", "shall not",
        "forbidden", "stop", "not use", "avoid", "prohibit",
    ]
    has_negative: bool = any(w in text_lower for w in negative_words)
    if tools and has_negative:
        return "tool_ban"

    # Emphatic prohibition: ALL CAPS, exclamation marks, STOP
    has_emphasis: bool = bool(re.search(r"[A-Z]{3,}", directive.text))
    has_exclaim: bool = "!" in directive.text
    if (has_emphasis or has_exclaim) and has_negative:
        return "emphatic_prohibition"

    # Domain jargon: contains domain-specific terms
    domain_terms: list[str] = _extract_domain_terms(directive.text)
    if len(domain_terms) >= 2:
        return "domain_jargon"

    # Cross-domain constraint: mentions specific platform/service names
    platform_terms: list[str] = [
        "gcp", "aws", "azure", "docker", "kubernetes", "willow",
        "archon", "mintaka", "alnilam", "alnitak",
    ]
    if any(t in text_lower for t in platform_terms):
        return "cross_domain_constraint"

    # Implicit rule: process/behavioral rules without specific tool mention
    process_words: list[str] = [
        "before", "after", "whenever", "every time", "each time",
        "when you", "if you", "make sure", "ensure",
    ]
    if any(w in text_lower for w in process_words):
        return "implicit_rule"

    # Domain jargon (single term -- less confident)
    if domain_terms:
        return "domain_jargon"

    return "other"


# ---------------------------------------------------------------------------
# Step 5: Assess HRR bridgeability
# ---------------------------------------------------------------------------

def assess_hrr_bridgeability(
    directive: Directive,
    all_directives: list[Directive],
) -> tuple[bool, list[str]]:
    """Check if a vocab-gap directive shares context with other directives.

    Bridgeability criteria:
    1. Co-located in the same file (shares file-level context)
    2. Referenced in the same section (shares heading-level context)
    3. Another directive in the same project mentions similar topic words

    Returns (bridgeable, list_of_colocated_directive_texts).
    """
    colocated: list[str] = []

    # Find directives in the same file
    for other in all_directives:
        if other.text == directive.text:
            continue
        if other.source_file == directive.source_file:
            colocated.append(other.text[:80])

    # If at least one other directive is in the same file, it's bridgeable
    bridgeable: bool = len(colocated) > 0

    # Even if not in same file, check for topic overlap with any directive
    if not bridgeable:
        my_words: set[str] = _get_content_words(directive.text)
        for other in all_directives:
            if other.text == directive.text:
                continue
            other_words: set[str] = _get_content_words(other.text)
            overlap: int = len(my_words & other_words)
            if overlap >= 2:
                colocated.append(other.text[:80])
                bridgeable = True
                break

    return bridgeable, colocated[:5]


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def analyze_project(project_name: str, project_path: Path) -> ProjectResult:
    """Run the full vocab-gap analysis on a single project."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {project_name} ({project_path})")
    print(f"{'='*60}")

    # Step 1: Extract directives
    directives: list[Directive] = extract_directives(project_name, project_path)
    print(f"  Directives extracted: {len(directives)}")

    # Extract full corpus for FTS5
    all_sentences: list[str] = extract_all_sentences(project_path)
    print(f"  Total sentences in corpus: {len(all_sentences)}")

    # Step 2+3: Build FTS5 index and test each directive
    conn: sqlite3.Connection = build_fts5_index(all_sentences)

    gap_directives: list[GapResult] = []
    reachable_count: int = 0
    gap_count: int = 0
    directive_results: list[dict[str, Any]] = []

    for directive in directives:
        # Step 2: Generate queries
        query_set: QuerySet = generate_queries(directive)

        # Step 3: Test FTS5 retrievability
        result: GapResult = test_retrievability(conn, directive, query_set)

        if result.text_reachable:
            reachable_count += 1
        else:
            gap_count += 1
            # Step 4: Classify gap
            result.gap_category = classify_gap(directive)
            # Step 5: HRR bridgeability
            bridgeable: bool
            colocated: list[str]
            bridgeable, colocated = assess_hrr_bridgeability(
                directive, directives,
            )
            result.hrr_bridgeable = bridgeable
            result.colocated_directives = colocated
            gap_directives.append(result)

        # Only store gap directives in detail (saves output size)
        if not result.text_reachable:
            directive_results.append(_gap_result_to_dict(result))

    conn.close()

    # Aggregate gap categories
    gap_categories: dict[str, int] = {}
    for cat in GAP_CATEGORIES:
        gap_categories[cat] = 0
    for gap in gap_directives:
        cat_val: str = gap.gap_category if gap.gap_category is not None else "other"
        gap_categories[cat_val] = gap_categories.get(cat_val, 0) + 1

    # HRR bridgeability rate
    hrr_bridgeable_count: int = sum(
        1 for g in gap_directives if g.hrr_bridgeable is True
    )
    hrr_bridgeable_rate: float = (
        hrr_bridgeable_count / gap_count if gap_count > 0 else 0.0
    )

    total: int = len(directives)
    gap_rate: float = gap_count / total if total > 0 else 0.0

    print(f"  Text-reachable: {reachable_count}")
    print(f"  Vocabulary gaps: {gap_count}")
    print(f"  Gap rate: {gap_rate:.1%}")
    print(f"  HRR bridgeable: {hrr_bridgeable_count}/{gap_count}")
    print(f"  Gap categories: {gap_categories}")

    return ProjectResult(
        project=project_name,
        path=str(project_path),
        total_directives=total,
        total_sentences=len(all_sentences),
        gap_count=gap_count,
        gap_rate=gap_rate,
        gap_categories=gap_categories,
        hrr_bridgeable_count=hrr_bridgeable_count,
        hrr_bridgeable_rate=hrr_bridgeable_rate,
        directives=directive_results,
    )


def _gap_result_to_dict(result: GapResult) -> dict[str, Any]:
    """Convert a GapResult to a serializable dict."""
    return {
        "text": result.directive.text[:200],
        "source_file": result.directive.source_file,
        "pattern_matched": result.directive.pattern_matched,
        "queries": result.queries.queries,
        "low_confidence_query": result.queries.low_confidence,
        "text_reachable": result.text_reachable,
        "gap_category": result.gap_category,
        "hrr_bridgeable": result.hrr_bridgeable,
        "colocated_directives": result.colocated_directives,
        "fts5_top_hits": {
            q: [h[:80] for h in hits[:2]]
            for q, hits in result.fts5_hits.items()
        },
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    results: list[ProjectResult],
    output_path: Path,
) -> None:
    """Generate the markdown report."""
    lines: list[str] = []
    lines.append("# Experiment 53: Vocabulary Gap Prevalence Across Projects")
    lines.append("")
    lines.append("**Date:** 2026-04-10")
    lines.append("**Status:** Complete")
    lines.append("")

    # Summary table
    lines.append("## 1. Prevalence Summary")
    lines.append("")
    lines.append(
        "| Project | Directives | Corpus Size | Gaps | Gap Rate | "
        "HRR Bridgeable |"
    )
    lines.append(
        "|---------|-----------|-------------|------|----------|"
        "----------------|"
    )

    total_directives: int = 0
    total_gaps: int = 0
    total_bridgeable: int = 0

    for r in results:
        total_directives += r.total_directives
        total_gaps += r.gap_count
        total_bridgeable += r.hrr_bridgeable_count
        lines.append(
            f"| {r.project} | {r.total_directives} | {r.total_sentences} | "
            f"{r.gap_count} | {r.gap_rate:.1%} | "
            f"{r.hrr_bridgeable_count}/{r.gap_count} |"
        )

    overall_rate: float = total_gaps / total_directives if total_directives > 0 else 0.0
    overall_bridge: float = (
        total_bridgeable / total_gaps if total_gaps > 0 else 0.0
    )
    lines.append(
        f"| **TOTAL** | **{total_directives}** | -- | **{total_gaps}** | "
        f"**{overall_rate:.1%}** | "
        f"**{total_bridgeable}/{total_gaps} ({overall_bridge:.0%})** |"
    )
    lines.append("")

    # Gap categories
    lines.append("## 2. Gap Categories (across all projects)")
    lines.append("")
    all_cats: dict[str, int] = {}
    for cat in GAP_CATEGORIES:
        all_cats[cat] = 0
    for r in results:
        for cat, count in r.gap_categories.items():
            all_cats[cat] = all_cats.get(cat, 0) + count

    lines.append("| Category | Count | % of Gaps |")
    lines.append("|----------|-------|-----------|")
    for cat in GAP_CATEGORIES:
        count: int = all_cats[cat]
        pct: float = count / total_gaps if total_gaps > 0 else 0.0
        lines.append(f"| {cat} | {count} | {pct:.0%} |")
    lines.append("")

    # Tool ban + domain jargon share
    tool_domain: int = all_cats.get("tool_ban", 0) + all_cats.get(
        "domain_jargon", 0
    )
    tool_domain_pct: float = (
        tool_domain / total_gaps if total_gaps > 0 else 0.0
    )

    # Hypothesis evaluation
    lines.append("## 3. Hypothesis Evaluation")
    lines.append("")

    h1_pass: bool = overall_rate >= 0.05
    lines.append(
        f"**H1:** Gap prevalence >= 5% across projects: "
        f"{'SUPPORTED' if h1_pass else 'NOT SUPPORTED'} "
        f"(observed: {overall_rate:.1%})"
    )
    lines.append("")

    h2_pass: bool = tool_domain_pct >= 0.50
    lines.append(
        f"**H2:** Tool bans + domain jargon >= 50% of gaps: "
        f"{'SUPPORTED' if h2_pass else 'NOT SUPPORTED'} "
        f"(observed: {tool_domain_pct:.0%})"
    )
    lines.append("")

    h3_pass: bool = overall_bridge >= 0.80
    lines.append(
        f"**H3:** >= 80% of gaps are HRR-bridgeable: "
        f"{'SUPPORTED' if h3_pass else 'NOT SUPPORTED'} "
        f"(observed: {overall_bridge:.0%})"
    )
    lines.append("")

    # H4: doc-rich (alpha-seek, optimus-prime) vs doc-light (debserver, code-monkey)
    doc_rich: list[ProjectResult] = [
        r for r in results if r.project in ("alpha-seek", "optimus-prime")
    ]
    doc_light: list[ProjectResult] = [
        r for r in results if r.project in ("debserver", "code-monkey")
    ]
    rich_rate: float = (
        sum(r.gap_count for r in doc_rich)
        / max(sum(r.total_directives for r in doc_rich), 1)
    )
    light_rate: float = (
        sum(r.gap_count for r in doc_light)
        / max(sum(r.total_directives for r in doc_light), 1)
    )
    h4_pass: bool = rich_rate < light_rate
    lines.append(
        f"**H4:** Doc-rich projects have lower gap rates: "
        f"{'SUPPORTED' if h4_pass else 'NOT SUPPORTED'} "
        f"(rich: {rich_rate:.1%}, light: {light_rate:.1%})"
    )
    lines.append("")

    null_holds: bool = overall_rate < 0.03
    lines.append(
        f"**Null hypothesis** (gap < 3%, HRR negligible): "
        f"{'HOLDS' if null_holds else 'REJECTED'} "
        f"(observed: {overall_rate:.1%})"
    )
    lines.append("")

    # Conclusion
    lines.append("## 4. Conclusion")
    lines.append("")
    if overall_rate >= 0.10:
        lines.append(
            f"Vocabulary gap prevalence is {overall_rate:.1%}, well above the "
            f"10% threshold. HRR is essential infrastructure -- text methods "
            f"alone leave a significant fraction of directives unreachable."
        )
    elif overall_rate >= 0.05:
        lines.append(
            f"Vocabulary gap prevalence is {overall_rate:.1%}, above the 5% "
            f"threshold but below 10%. HRR provides meaningful value for "
            f"recovering directives that text methods miss."
        )
    elif overall_rate >= 0.03:
        lines.append(
            f"Vocabulary gap prevalence is {overall_rate:.1%}, marginal. "
            f"HRR is a useful optimization but not strictly necessary."
        )
    else:
        lines.append(
            f"Vocabulary gap prevalence is {overall_rate:.1%}, below the 3% "
            f"threshold. HRR adds negligible value for directive retrieval."
        )
    lines.append("")

    if overall_bridge >= 0.80 and overall_rate >= 0.05:
        lines.append(
            f"Of the {total_gaps} vocabulary-gap directives, "
            f"{total_bridgeable} ({overall_bridge:.0%}) are HRR-bridgeable "
            f"via co-location or topic overlap with text-reachable directives. "
            f"This confirms HRR's mechanism: typed edges connect isolated "
            f"beliefs to the reachable graph."
        )
    lines.append("")

    # Per-project details
    lines.append("## 5. Per-Project Gap Details")
    lines.append("")
    for r in results:
        lines.append(f"### {r.project}")
        lines.append("")
        gap_directives_list: list[dict[str, Any]] = r.directives
        if not gap_directives_list:
            lines.append("No vocabulary gaps found.")
            lines.append("")
            continue

        max_examples: int = 10
        shown: int = 0
        if len(gap_directives_list) > max_examples:
            lines.append(
                f"Showing {max_examples} of {len(gap_directives_list)} "
                f"vocabulary-gap directives:"
            )
            lines.append("")

        for d in gap_directives_list:
            if shown >= max_examples:
                break
            shown += 1
            text_preview: str = d["text"][:120]
            lines.append(f"- **Directive:** \"{text_preview}\"")
            lines.append(f"  - Source: `{d['source_file']}`")
            lines.append(f"  - Category: {d['gap_category']}")
            lines.append(f"  - Queries: {d['queries']}")
            lines.append(f"  - HRR bridgeable: {d['hrr_bridgeable']}")
            lines.append(
                f"  - Low-confidence query: {d['low_confidence_query']}"
            )
            lines.append("")

    # Methodology note
    lines.append("## 6. Methodology Notes")
    lines.append("")
    lines.append(
        "- Directives extracted via regex pattern matching on .md files "
        "(always/never/banned/must not/mandatory/etc.)"
    )
    lines.append(
        "- Queries generated rule-based: tool purpose mappings, domain term "
        "translations, behavioral verb situation mappings"
    )
    lines.append(
        "- FTS5 with porter stemming, OR-query, top-30 retrieval"
    )
    lines.append(
        "- Text match: exact, substring, or >= 70% Jaccard word overlap"
    )
    lines.append(
        "- No LLM calls used in any part of the pipeline"
    )
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run Experiment 53."""
    results: list[ProjectResult] = []

    for project_name, project_path in PROJECTS.items():
        if not project_path.exists():
            print(f"WARNING: {project_path} does not exist, skipping")
            continue
        result: ProjectResult = analyze_project(project_name, project_path)
        results.append(result)

    # Write JSON results
    output_dir: Path = Path(__file__).parent
    json_path: Path = output_dir / "exp53_results.json"

    # Cap per-project directive samples to keep JSON under 200KB
    max_json_samples: int = 20
    trimmed_results: list[dict[str, Any]] = []
    for r in results:
        rd: dict[str, Any] = asdict(r)
        full_count: int = len(rd["directives"])
        rd["directives"] = rd["directives"][:max_json_samples]
        if full_count > max_json_samples:
            rd["directives_truncated_from"] = full_count
        trimmed_results.append(rd)

    json_output: dict[str, Any] = {
        "experiment": "exp53_vocab_gap_prevalence",
        "date": "2026-04-10",
        "projects": trimmed_results,
        "summary": {
            "total_directives": sum(r.total_directives for r in results),
            "total_gaps": sum(r.gap_count for r in results),
            "overall_gap_rate": (
                sum(r.gap_count for r in results)
                / max(sum(r.total_directives for r in results), 1)
            ),
            "overall_hrr_bridgeable_rate": (
                sum(r.hrr_bridgeable_count for r in results)
                / max(sum(r.gap_count for r in results), 1)
            ),
        },
    }

    json_path.write_text(
        json.dumps(json_output, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"JSON results written to {json_path}")

    # Write markdown report
    report_path: Path = output_dir / "exp53_vocab_gap_results.md"
    generate_report(results, report_path)


if __name__ == "__main__":
    main()
