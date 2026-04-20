"""Deterministic commit tracker for agentmemory.

Tracks time since last git commit and number of uncommitted changes.
Compares against configurable thresholds and produces a plain-text nudge.
All logic is pure datetime arithmetic and subprocess calls -- no LLM.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

_CONFIG_PATH: Final[Path] = Path.home() / ".agentmemory" / "commit_tracker.json"

# Defaults
_DEFAULT_MAX_SECONDS: Final[int] = 900   # 15 minutes
_DEFAULT_MAX_CHANGES: Final[int] = 10


@dataclass
class CommitTrackerConfig:
    """User-configurable commit tracker settings."""

    enabled: bool = True
    max_seconds: int = _DEFAULT_MAX_SECONDS
    max_changes: int = _DEFAULT_MAX_CHANGES


@dataclass
class CommitCheckResult:
    """Deterministic result of a commit status check."""

    checked: bool = False           # False if tracker disabled or not a git repo
    is_git_repo: bool = False
    last_commit_iso: str = ""       # ISO 8601 timestamp of last commit
    seconds_since_commit: int = 0
    uncommitted_changes: int = 0
    threshold_seconds: int = 0
    threshold_changes: int = 0
    time_exceeded: bool = False
    changes_exceeded: bool = False
    nudge: str = ""                 # Empty string = no nudge needed
    errors: list[str] = field(default_factory=lambda: list[str]())


def load_config() -> CommitTrackerConfig:
    """Load config from disk. Returns defaults if file missing or corrupt."""
    if not _CONFIG_PATH.exists():
        return CommitTrackerConfig()
    try:
        raw: dict[str, object] = json.loads(_CONFIG_PATH.read_text())
        return CommitTrackerConfig(
            enabled=bool(raw.get("enabled", True)),
            max_seconds=int(raw.get("max_seconds", _DEFAULT_MAX_SECONDS)),  # type: ignore[arg-type]
            max_changes=int(raw.get("max_changes", _DEFAULT_MAX_CHANGES)),  # type: ignore[arg-type]
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return CommitTrackerConfig()


def save_config(config: CommitTrackerConfig) -> Path:
    """Write config to disk. Returns the path written."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2) + "\n")
    return _CONFIG_PATH


def _run_git(args: list[str], cwd: Path) -> tuple[str, str, int]:
    """Run a git command. Returns (stdout, stderr, returncode)."""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def check_commit_status(project_dir: Path) -> CommitCheckResult:
    """Check time since last commit and number of uncommitted changes.

    Pure deterministic logic:
    1. Verify project_dir is a git repo
    2. Get last commit timestamp via `git log`
    3. Count uncommitted changes via `git status --porcelain`
    4. Compare against config thresholds
    5. Build nudge message if either threshold exceeded

    Returns a CommitCheckResult with all fields populated.
    """
    config: CommitTrackerConfig = load_config()
    out = CommitCheckResult(
        threshold_seconds=config.max_seconds,
        threshold_changes=config.max_changes,
    )

    if not config.enabled:
        return out

    resolved: Path = project_dir.expanduser().resolve()
    if not resolved.is_dir():
        out.errors.append(f"Not a directory: {resolved}")
        return out

    # Check if git repo
    _, _, rc = _run_git(["rev-parse", "--is-inside-work-tree"], resolved)
    if rc != 0:
        out.errors.append(f"Not a git repository: {resolved}")
        return out
    out.is_git_repo = True
    out.checked = True

    # Get last commit time
    stdout, stderr, rc = _run_git(
        ["log", "-1", "--format=%cI"], resolved
    )
    if rc != 0 or not stdout:
        # Repo may have no commits yet
        out.errors.append(stderr if stderr else "No commits found")
        out.nudge = (
            "No commits exist in this repository yet. "
            "You should create an initial commit."
        )
        return out

    out.last_commit_iso = stdout
    try:
        last_commit_dt: datetime = datetime.fromisoformat(stdout)
        now: datetime = datetime.now(timezone.utc)
        delta_seconds: float = (now - last_commit_dt).total_seconds()
        out.seconds_since_commit = int(delta_seconds)
    except ValueError as exc:
        out.errors.append(f"Could not parse commit time: {exc}")
        return out

    # Count uncommitted changes
    stdout, _, rc = _run_git(["status", "--porcelain"], resolved)
    if rc == 0 and stdout:
        out.uncommitted_changes = len(stdout.splitlines())

    # Evaluate thresholds
    out.time_exceeded = out.seconds_since_commit > config.max_seconds
    out.changes_exceeded = out.uncommitted_changes >= config.max_changes

    # Build nudge
    if out.time_exceeded or out.changes_exceeded:
        out.nudge = _build_nudge(out)

    return out


def _build_nudge(result: CommitCheckResult) -> str:
    """Build a deterministic nudge message from check results."""
    parts: list[str] = []

    minutes: int = result.seconds_since_commit // 60
    seconds: int = result.seconds_since_commit % 60

    if minutes > 0:
        time_str: str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"

    if result.time_exceeded and result.changes_exceeded:
        parts.append(
            f"COMMIT NUDGE: It has been {time_str} since your last commit "
            f"and there are {result.uncommitted_changes} uncommitted changes "
            f"(thresholds: {result.threshold_seconds // 60}m / "
            f"{result.threshold_changes} changes). "
            f"You should commit now or ask the user if they want to commit."
        )
    elif result.time_exceeded:
        parts.append(
            f"COMMIT NUDGE: It has been {time_str} since your last commit "
            f"(threshold: {result.threshold_seconds // 60}m). "
            f"You should commit now or ask the user if they want to commit."
        )
    elif result.changes_exceeded:
        parts.append(
            f"COMMIT NUDGE: There are {result.uncommitted_changes} uncommitted "
            f"changes (threshold: {result.threshold_changes}). "
            f"You should commit now or ask the user if they want to commit."
        )

    return " ".join(parts)


def format_status(result: CommitCheckResult) -> str:
    """Format a CommitCheckResult as human-readable text for CLI output."""
    if not result.checked:
        if result.errors:
            return f"Commit tracker: {result.errors[0]}"
        return "Commit tracker: disabled"

    lines: list[str] = []
    minutes: int = result.seconds_since_commit // 60
    seconds: int = result.seconds_since_commit % 60

    if minutes > 0:
        time_str: str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"

    lines.append(f"Time since last commit: {time_str}")
    lines.append(f"Uncommitted changes: {result.uncommitted_changes}")
    lines.append(
        f"Thresholds: {result.threshold_seconds // 60}m / "
        f"{result.threshold_changes} changes"
    )

    if result.nudge:
        lines.append(f"\n{result.nudge}")

    if result.errors:
        for err in result.errors:
            lines.append(f"Warning: {err}")

    return "\n".join(lines)
