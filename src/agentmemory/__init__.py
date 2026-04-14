"""agentmemory: SQLite-backed persistent memory for AI coding agents."""
from __future__ import annotations

from agentmemory.models import Belief, Observation
from agentmemory.store import MemoryStore

__version__ = "0.1.0"

__all__ = [
    "MemoryStore",
    "Belief",
    "Observation",
    "__version__",
]
