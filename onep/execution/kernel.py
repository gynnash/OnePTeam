"""Stable application-facing name for the single-writer engineering kernel."""

from onep.greenfield.engine import GreenfieldEngine


# Keep persisted imports compatible while the greenfield-specific internals are
# gradually reduced. This is an alias, not another orchestration layer.
ExecutionKernel = GreenfieldEngine

__all__ = ["ExecutionKernel"]
