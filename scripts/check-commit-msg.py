#!/usr/bin/env python3
"""Enforce conventional commit message prefixes."""

from __future__ import annotations

import re
import sys

PREFIXES: list[str] = [
    "feat",
    "fix",
    "docs",
    "test",
    "refactor",
    "perf",
    "chore",
    "experiment",
    "benchmark",
    "style",
    "ci",
    "build",
    "revert",
    "hotfix",
]

PATTERN: str = r"^(" + "|".join(PREFIXES) + r")(\(.+\))?!?: .+"


def main() -> None:
    msg: str = open(sys.argv[1]).read().strip()

    # Allow merge commits
    if msg.startswith("Merge "):
        sys.exit(0)

    if not re.match(PATTERN, msg):
        print(f"Bad commit message: {msg!r}")
        print(f"Must start with one of: {', '.join(PREFIXES)}")
        print("Example: feat: add batch ingestion")
        print("Example: fix(scoring): correct decay half-life")
        sys.exit(1)


if __name__ == "__main__":
    main()
