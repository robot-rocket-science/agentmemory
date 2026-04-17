"""Configuration system for agentmemory.

Stores settings in ~/.agentmemory/config.json. Provides typed access
with sensible defaults. Settings are user-configurable via /mem:settings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_CONFIG_PATH: Path = Path.home() / ".agentmemory" / "config.json"

_DEFAULTS: dict[str, dict[str, int | bool | str]] = {
    "wonder": {
        "max_agents": 4,
    },
    "reason": {
        "max_agents": 3,
        "depth": 2,
    },
    "core": {
        "default_top": 10,
    },
    "locked": {
        "max_cap": 100,
        "warn_at": 80,
    },
    "ingest": {
        "use_llm": True,
    },
    "obsidian": {
        "vault_path": "",
        "beliefs_subfolder": "beliefs",
        "auto_sync": False,
    },
}


def load_config() -> dict[str, Any]:
    """Load config from disk, merging with defaults."""
    config: dict[str, Any] = {}
    if _CONFIG_PATH.exists():
        try:
            raw: str = _CONFIG_PATH.read_text(encoding="utf-8")
            loaded: object = json.loads(raw)
            if isinstance(loaded, dict):
                config = cast("dict[str, Any]", loaded)
        except (json.JSONDecodeError, OSError):
            pass

    # Deep merge defaults under missing keys
    merged: dict[str, Any] = {}
    for section, defaults in _DEFAULTS.items():
        user_raw: object = config.get(section, {})
        user_section: dict[str, Any] = cast("dict[str, Any]", user_raw) if isinstance(user_raw, dict) else {}
        merged_section: dict[str, int | bool | str] = {}
        for key, default_val in defaults.items():
            raw_val: object = user_section.get(key, default_val)
            if raw_val is None:
                merged_section[key] = default_val
            elif isinstance(default_val, bool):
                # Bool defaults expect bool values
                if isinstance(raw_val, bool):
                    merged_section[key] = raw_val
                else:
                    merged_section[key] = str(raw_val).lower() in ("true", "1", "yes")
            elif isinstance(default_val, str):
                merged_section[key] = str(raw_val)
            else:
                merged_section[key] = int(str(raw_val))
        merged[section] = merged_section

    # Preserve any extra keys the user added
    for key, val in config.items():
        if key not in merged:
            merged[key] = val

    return merged


def save_config(config: dict[str, Any]) -> Path:
    """Save config to disk. Returns the path written."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    return _CONFIG_PATH


def get_setting(section: str, key: str) -> int:
    """Get a single integer setting value with defaults applied."""
    config: dict[str, Any] = load_config()
    section_raw: object = config.get(section, {})
    if isinstance(section_raw, dict):
        section_data: dict[str, Any] = cast("dict[str, Any]", section_raw)
        raw_val: object = section_data.get(key)
        if raw_val is not None:
            return int(str(raw_val))
    default_section: dict[str, int | bool | str] | None = _DEFAULTS.get(section)
    if default_section is not None:
        val: int | bool | str = default_section.get(key, 0)
        return int(str(val))
    return 0


def get_str_setting(section: str, key: str) -> str:
    """Get a single string setting value with defaults applied."""
    config: dict[str, Any] = load_config()
    section_raw: object = config.get(section, {})
    if isinstance(section_raw, dict):
        section_data: dict[str, Any] = cast("dict[str, Any]", section_raw)
        raw_val: object = section_data.get(key)
        if raw_val is not None:
            return str(raw_val)
    default_section: dict[str, int | bool | str] | None = _DEFAULTS.get(section)
    if default_section is not None:
        val: int | bool | str = default_section.get(key, "")
        return str(val)
    return ""


def get_bool_setting(section: str, key: str) -> bool:
    """Get a single boolean setting value with defaults applied."""
    config: dict[str, Any] = load_config()
    section_raw: object = config.get(section, {})
    if isinstance(section_raw, dict):
        section_data: dict[str, Any] = cast("dict[str, Any]", section_raw)
        raw_val: object = section_data.get(key)
        if raw_val is not None:
            if isinstance(raw_val, bool):
                return raw_val
            return str(raw_val).lower() in ("true", "1", "yes")
    default_section: dict[str, int | bool | str] | None = _DEFAULTS.get(section)
    if default_section is not None:
        val: int | bool | str = default_section.get(key, False)
        return bool(val)
    return False
