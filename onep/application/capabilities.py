"""Explicit capability registry shared by every user interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from onep.domain import Problem


CapabilityHandler = Callable[[dict[str, Any], Any], dict[str, Any]]


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    handler: CapabilityHandler
    mutating: bool = False
    background: bool = False
    legacy: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "mutating": self.mutating,
            "background": self.background,
            "legacy": self.legacy,
            "input_schema": self.input_schema,
        }


class CapabilityRegistry:
    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        self._items: dict[str, Capability] = {}
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        if not capability.id or capability.id in self._items:
            raise ValueError(f"duplicate or empty capability id: {capability.id!r}")
        self._items[capability.id] = capability

    def get(self, capability_id: str) -> Capability:
        try:
            return self._items[capability_id]
        except KeyError as exc:
            raise Problem(
                code="capability_not_found",
                title="Capability not found",
                detail=f"Unknown capability: {capability_id}",
            ) from exc

    def describe(self) -> list[dict[str, Any]]:
        return [
            capability.describe()
            for capability in sorted(self._items.values(), key=lambda item: item.id)
            if not capability.legacy
        ]
