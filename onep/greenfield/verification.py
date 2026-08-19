"""Readable verification planning for the Greenfield development loop.

This module decides *what* to verify. Command validation and execution remain in
``greenfield.gates`` so orchestration, policy, and process execution stay
separate without introducing a generic workflow framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re
import shlex

from onep.greenfield.models import AcceptanceContract, SlicePlan


VerificationLevel = Literal["slice", "final"]


@dataclass(frozen=True)
class VerificationPlan:
    level: VerificationLevel
    focused_commands: tuple[str, ...] = ()
    mandatory_commands: tuple[str, ...] = ()
    review_required: bool = True

    @property
    def commands(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.focused_commands, *self.mandatory_commands)))


def _parts(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def is_pytest_command(command: str) -> bool:
    parts = _parts(command)
    return bool(parts) and (
        parts[0] == "pytest"
        or parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"])
    )


def _pytest_args(command: str) -> list[str]:
    parts = _parts(command)
    if parts[:3] in (["python", "-m", "pytest"], ["python3", "-m", "pytest"]):
        return parts[3:]
    if parts and parts[0] == "pytest":
        return parts[1:]
    return []


def _pytest_targets(command: str) -> list[str]:
    return [
        value.split("::", 1)[0]
        for value in _pytest_args(command)
        if not value.startswith("-")
        and not re.fullmatch(r"\d*(?:>|<|>>|<<)&?\d*", value)
    ]


def is_broad_test_command(command: str) -> bool:
    if not is_pytest_command(command):
        return False
    targets = _pytest_targets(command)
    return not targets or all(
        value.rstrip("/") in {".", "test", "tests"} for value in targets
    )


def is_test_command(command: str) -> bool:
    parts = _parts(command)
    return bool(
        parts
        and (
            is_pytest_command(command)
            or parts[:2] in (["npm", "test"], ["go", "test"], ["cargo", "test"])
            or parts[:3] == ["npm", "run", "test"]
            or (parts[0] in {"pnpm", "yarn"} and "test" in parts[1:])
            or (
                parts[0] == "./gradlew"
                and any("test" in value.lower() for value in parts[1:])
            )
            or parts[:2] == ["mvn", "test"]
        )
    )


def dedupe_slice_gates(
    focused: list[str],
    mandatory: list[str],
) -> list[str]:
    """Avoid running a broad suite in the same attempt as focused tests."""
    if not focused:
        return list(dict.fromkeys(mandatory))
    focused_runs_full_suite = any(is_broad_test_command(command) for command in focused)
    return list(
        dict.fromkeys(
            command
            for command in mandatory
            if not (
                is_test_command(command)
                if focused_runs_full_suite
                else is_broad_test_command(command)
            )
        )
    )


_HIGH_RISK_PATH = re.compile(
    r"(?:^|/)(?:api|auth|cli|config|deploy|migration|persistence|schema|scheduler)(?:/|\.|$)"
    r"|(?:^|/)(?:Dockerfile|compose\.ya?ml|docker-compose\.ya?ml)$"
    r"|^\.github/",
    re.IGNORECASE,
)
_CROSS_CUTTING_PREFIXES = (
    "final-regression-hardening",
    "final-architecture-hardening",
    "deployment-hardening",
)


def should_review_slice(plan: SlicePlan, contract: AcceptanceContract) -> bool:
    """Use a slice reviewer when executable evidence is weak or risk is high."""
    if plan.id.startswith(_CROSS_CUTTING_PREFIXES):
        return True
    if not plan.focused_commands or not plan.acceptance_ids:
        return True
    selected = [item for item in contract.items if item.id in plan.acceptance_ids]
    if not selected or any(not item.commands for item in selected):
        return True
    return any(_HIGH_RISK_PATH.search(path) for path in plan.expected_files)


def build_slice_verification(
    plan: SlicePlan,
    contract: AcceptanceContract,
    focused: list[str],
    mandatory: list[str],
) -> VerificationPlan:
    return VerificationPlan(
        level="slice",
        focused_commands=tuple(dict.fromkeys(focused)),
        mandatory_commands=tuple(dedupe_slice_gates(focused, mandatory)),
        review_required=not focused or should_review_slice(plan, contract),
    )


def _covered_by_broad_pytest(command: str, broad_commands: list[str]) -> bool:
    """Conservatively remove only normal test/test(s) pytest targets."""
    if not is_pytest_command(command) or is_broad_test_command(command):
        return False
    targets = _pytest_targets(command)
    if not targets or not all(
        target == "test" or target == "tests" or target.startswith(("test/", "tests/"))
        for target in targets
    ):
        return False
    return any(is_broad_test_command(value) for value in broad_commands)


def build_final_verification(
    discovered: list[str],
    acceptance: list[str],
    slice_focused: list[str],
    explicit: list[str],
) -> VerificationPlan:
    """Build one complete, non-redundant final gate list.

    Explicit user commands and acceptance commands are protected. Slice-local
    pytest commands are omitted only when a protected broad pytest command
    demonstrably covers their conventional ``test/`` or ``tests/`` target.
    """
    protected = list(dict.fromkeys([*discovered, *acceptance, *explicit]))
    commands = list(protected)
    for command in slice_focused:
        if command in commands or _covered_by_broad_pytest(command, protected):
            continue
        commands.append(command)
    return VerificationPlan(
        level="final",
        mandatory_commands=tuple(commands),
        review_required=True,
    )


def can_reuse_verification(
    current_fingerprint: str,
    accepted_fingerprint: str,
    *,
    accepted: bool,
) -> bool:
    """Reuse only an acceptance performed by this engine on the exact state."""
    return bool(
        accepted
        and current_fingerprint
        and accepted_fingerprint
        and current_fingerprint == accepted_fingerprint
    )
