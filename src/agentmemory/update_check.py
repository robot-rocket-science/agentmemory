"""Version update check with 24-hour caching.

Queries PyPI for the latest version of agentmemory-rrs and caches the
result locally. Returns an update notification string if a newer version
is available, or empty string if up to date or check fails.

Design:
  - Non-blocking: 2-second timeout on HTTP request
  - Cached: only checks PyPI once per 24 hours
  - Silent on failure: network errors, timeouts, parse errors all return ""
  - No dependencies: uses only stdlib (urllib)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final, cast

_AGENTMEMORY_HOME: Final[Path] = Path.home() / ".agentmemory"
_CACHE_FILE: Final[Path] = _AGENTMEMORY_HOME / ".update_cache.json"
_PYPI_URL: Final[str] = "https://pypi.org/pypi/agentmemory-rrs/json"
_CACHE_TTL_SECONDS: Final[int] = 86400  # 24 hours
_REQUEST_TIMEOUT: Final[int] = 2  # seconds
_PACKAGE_NAME: Final[str] = "agentmemory-rrs"


def _get_installed_version() -> str:
    """Get currently installed version from package metadata."""
    try:
        from importlib.metadata import version

        return version(_PACKAGE_NAME)
    except Exception:
        pass
    # Fallback: read from pyproject.toml if in dev
    pyproject: Path = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=")[1].strip().strip('"')
    return "0.0.0"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple."""
    parts: list[int] = []
    for segment in v.strip().split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def _read_cache() -> dict[str, str | float]:
    """Read cached update check result."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        data: object = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            typed: dict[str, Any] = cast(dict[str, Any], data)
            return {str(k): v for k, v in typed.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_cache(latest_version: str) -> None:
    """Write update check result to cache."""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str | float] = {
        "latest_version": latest_version,
        "checked_at": time.time(),
    }
    try:
        _CACHE_FILE.write_text(json.dumps(cache) + "\n", encoding="utf-8")
    except OSError:
        pass


def _fetch_latest_version() -> str | None:
    """Query PyPI for the latest version. Returns None on failure."""
    import urllib.request
    import urllib.error

    try:
        req: urllib.request.Request = urllib.request.Request(
            _PYPI_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw: dict[str, Any] = cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))
            if "info" in raw:
                info: dict[str, Any] = cast(dict[str, Any], raw["info"])
                if "version" in info:
                    return str(info["version"])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def check_for_update() -> str:
    """Check if a newer version is available on PyPI.

    Returns a one-line notification string if an update is available,
    or empty string if up to date, cached, or check fails.
    Caches result for 24 hours.
    """
    # Check cache first
    cache: dict[str, str | float] = _read_cache()
    checked_at: float = float(cache.get("checked_at", 0))
    now: float = time.time()

    if now - checked_at < _CACHE_TTL_SECONDS:
        # Use cached result
        cached_latest: str = str(cache.get("latest_version", ""))
        if not cached_latest:
            return ""
        installed: str = _get_installed_version()
        if _parse_version(cached_latest) > _parse_version(installed):
            return (
                f"Update available: v{installed} -> v{cached_latest}. "
                f"Run: pip install --upgrade {_PACKAGE_NAME}"
            )
        return ""

    # Cache expired or missing -- fetch from PyPI
    latest: str | None = _fetch_latest_version()
    if latest is None:
        # Network failure -- write cache with empty to avoid retrying for 24h
        _write_cache("")
        return ""

    _write_cache(latest)
    installed = _get_installed_version()
    if _parse_version(latest) > _parse_version(installed):
        return (
            f"Update available: v{installed} -> v{latest}. "
            f"Run: pip install --upgrade {_PACKAGE_NAME}"
        )
    return ""
