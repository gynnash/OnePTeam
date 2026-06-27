"""Memory system — persistent, searchable memory for agents and projects."""

from __future__ import annotations


def __getattr__(name: str):
    """Lazy-import MemoryManager to avoid circular / missing-module errors
    during development when only sub-modules are loaded."""
    if name == "MemoryManager":
        from onep.memory.manager import MemoryManager as _mgr

        return _mgr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["MemoryManager"]
