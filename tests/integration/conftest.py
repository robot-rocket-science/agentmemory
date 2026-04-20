"""Shared fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Return a path for a persistent test database (survives across store instances)."""
    return tmp_path / "cross_session.db"
