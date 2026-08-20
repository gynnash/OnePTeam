"""Deterministic completion decision shared by the harness and kernel."""

from __future__ import annotations

from dataclasses import dataclass

from onep.greenfield.models import AcceptanceContract


@dataclass(frozen=True)
class AcceptanceDecision:
    satisfied: bool
    missing: tuple[str, ...]
    failed_commands: tuple[str, ...] = ()
    blocker_count: int = 0
    fingerprint: str = ""


def evaluate_acceptance(
    contract: AcceptanceContract,
    *,
    hard_gates_passed: bool,
    failed_commands: tuple[str, ...] = (),
    blocker_count: int = 0,
    fingerprint: str = "",
) -> AcceptanceDecision:
    """Reduce executable evidence to one authoritative completion decision."""
    required = [
        item for item in contract.items if item.priority in {"P0", "P1"}
    ]
    missing = tuple(
        item.id
        for item in required
        if item.status != "passed" or not (item.commands or item.evidence)
    )
    satisfied = bool(required) and not missing and hard_gates_passed
    satisfied = satisfied and not failed_commands and blocker_count == 0
    return AcceptanceDecision(
        satisfied=satisfied,
        missing=missing,
        failed_commands=failed_commands,
        blocker_count=max(0, blocker_count),
        fingerprint=fingerprint,
    )
