"""Abstract base class for all tools."""
from __future__ import annotations

from abc import ABC
from typing import Any


class BaseTool(ABC):
    """All tools inherit from this. Provides a common interface."""

    name: str = ""
    description: str = ""

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError
