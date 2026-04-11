"""Tests for the commit tracker module.

Covers config load/save, git query logic, threshold evaluation,
and nudge message generation. All git calls are mocked.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from agentmemory.commit_tracker import (
    CommitCheckResult,
    CommitTrackerConfig,
    check_commit_status,
    format_status,
    load_config,
    save_config,
)


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


def test_load_config_defaults(tmp_path: Path) -> None:
    """Missing config file returns defaults."""
    with patch("agentmemory.commit_tracker._CONFIG_PATH", tmp_path / "nope.json"):
        cfg: CommitTrackerConfig = load_config()
    assert cfg.enabled is True
    assert cfg.max_seconds == 900
    assert cfg.max_changes == 10


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Config survives a write/read cycle."""
    config_path: Path = tmp_path / "commit_tracker.json"
    with patch("agentmemory.commit_tracker._CONFIG_PATH", config_path):
        original = CommitTrackerConfig(enabled=False, max_seconds=600, max_changes=5)
        save_config(original)
        loaded: CommitTrackerConfig = load_config()

    assert loaded.enabled is False
    assert loaded.max_seconds == 600
    assert loaded.max_changes == 5


def test_load_config_corrupt_json(tmp_path: Path) -> None:
    """Corrupt config file returns defaults, does not raise."""
    config_path: Path = tmp_path / "commit_tracker.json"
    config_path.write_text("not json {{{")
    with patch("agentmemory.commit_tracker._CONFIG_PATH", config_path):
        cfg: CommitTrackerConfig = load_config()
    assert cfg.enabled is True


# ---------------------------------------------------------------------------
# Disabled tracker
# ---------------------------------------------------------------------------


def test_disabled_tracker_returns_early(tmp_path: Path) -> None:
    """When disabled, check returns immediately with checked=False."""
    config_path: Path = tmp_path / "commit_tracker.json"
    config_path.write_text(json.dumps({"enabled": False}))
    with patch("agentmemory.commit_tracker._CONFIG_PATH", config_path):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.checked is False
    assert result.nudge == ""


# ---------------------------------------------------------------------------
# Git interaction (mocked)
# ---------------------------------------------------------------------------


def _mock_git(responses: dict[str, tuple[str, str, int]]):
    """Return a mock for _run_git that returns canned responses by first arg."""
    def fake_run_git(args: list[str], cwd: Path) -> tuple[str, str, int]:
        key: str = args[0]
        if key == "log":
            key = "log"
        elif key == "status":
            key = "status"
        elif key == "rev-parse":
            key = "rev-parse"
        return responses.get(key, ("", "unknown command", 1))
    return fake_run_git


def test_not_a_git_repo(tmp_path: Path) -> None:
    """Non-git directory returns error, no crash."""
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({"rev-parse": ("", "not a git repo", 128)}),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.is_git_repo is False
    assert result.checked is False


def test_no_commits_yet(tmp_path: Path) -> None:
    """Repo with no commits produces a nudge about initial commit."""
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": ("", "no commits", 1),
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.is_git_repo is True
    assert "initial commit" in result.nudge.lower()


def test_time_threshold_exceeded(tmp_path: Path) -> None:
    """Nudge fires when time since last commit exceeds threshold."""
    old_time: str = (
        datetime.now(timezone.utc) - timedelta(minutes=20)
    ).isoformat()
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": (old_time, "", 0),
                "status": ("", "", 0),  # no changes
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.time_exceeded is True
    assert result.changes_exceeded is False
    assert "COMMIT NUDGE" in result.nudge


def test_changes_threshold_exceeded(tmp_path: Path) -> None:
    """Nudge fires when uncommitted change count exceeds threshold."""
    recent_time: str = (
        datetime.now(timezone.utc) - timedelta(seconds=30)
    ).isoformat()
    # 12 lines = 12 changes
    status_output: str = "\n".join(f" M file{i}.py" for i in range(12))
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": (recent_time, "", 0),
                "status": (status_output, "", 0),
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.changes_exceeded is True
    assert result.time_exceeded is False
    assert "12 uncommitted" in result.nudge


def test_both_thresholds_exceeded(tmp_path: Path) -> None:
    """Nudge message covers both conditions when both trip."""
    old_time: str = (
        datetime.now(timezone.utc) - timedelta(minutes=20)
    ).isoformat()
    status_output: str = "\n".join(f" M file{i}.py" for i in range(15))
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": (old_time, "", 0),
                "status": (status_output, "", 0),
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.time_exceeded is True
    assert result.changes_exceeded is True
    assert "15 uncommitted" in result.nudge
    assert "20m" in result.nudge


def test_within_thresholds_no_nudge(tmp_path: Path) -> None:
    """No nudge when both time and changes are within bounds."""
    recent_time: str = (
        datetime.now(timezone.utc) - timedelta(seconds=30)
    ).isoformat()
    status_output: str = " M file1.py\n M file2.py"
    config_path: Path = tmp_path / "commit_tracker.json"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": (recent_time, "", 0),
                "status": (status_output, "", 0),
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.nudge == ""
    assert result.uncommitted_changes == 2


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------


def test_format_status_disabled() -> None:
    result = CommitCheckResult()
    assert "disabled" in format_status(result)


def test_format_status_with_nudge() -> None:
    result = CommitCheckResult(
        checked=True,
        seconds_since_commit=1200,
        uncommitted_changes=15,
        threshold_seconds=900,
        threshold_changes=10,
        time_exceeded=True,
        changes_exceeded=True,
        nudge="COMMIT NUDGE: test",
    )
    output: str = format_status(result)
    assert "20m" in output
    assert "COMMIT NUDGE" in output


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------


def test_custom_thresholds_from_config(tmp_path: Path) -> None:
    """Custom max_seconds and max_changes are respected."""
    config_path: Path = tmp_path / "commit_tracker.json"
    config_path.write_text(json.dumps({
        "enabled": True,
        "max_seconds": 60,   # 1 minute
        "max_changes": 3,
    }))
    recent_time: str = (
        datetime.now(timezone.utc) - timedelta(seconds=90)
    ).isoformat()
    status_output: str = " M a.py\n M b.py\n M c.py\n M d.py"
    with (
        patch("agentmemory.commit_tracker._CONFIG_PATH", config_path),
        patch(
            "agentmemory.commit_tracker._run_git",
            _mock_git({
                "rev-parse": ("true", "", 0),
                "log": (recent_time, "", 0),
                "status": (status_output, "", 0),
            }),
        ),
    ):
        result: CommitCheckResult = check_commit_status(tmp_path)
    assert result.time_exceeded is True
    assert result.changes_exceeded is True
    assert result.threshold_seconds == 60
    assert result.threshold_changes == 3
