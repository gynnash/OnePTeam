from onep.greenfield.models import AcceptanceContract, AcceptanceItem, SlicePlan
from onep.greenfield.verification import (
    build_final_verification,
    build_slice_verification,
    can_reuse_verification,
    should_review_slice,
)


def _contract(*, command: str = "pytest tests/test_api.py -q") -> AcceptanceContract:
    return AcceptanceContract(
        [AcceptanceItem("A1", "P0", "API works", commands=[command] if command else [])]
    )


def test_final_plan_removes_only_pytest_commands_covered_by_full_suite():
    plan = build_final_verification(
        discovered=["pytest -q", "ruff check ."],
        acceptance=["python -m src.cli --help"],
        slice_focused=[
            "pytest tests/test_api.py -q",
            "pytest src/test_internal.py -q",
            "python -m src.smoke",
        ],
        explicit=["pytest -q"],
    )

    assert plan.commands == (
        "pytest -q",
        "ruff check .",
        "python -m src.cli --help",
        "pytest src/test_internal.py -q",
        "python -m src.smoke",
    )


def test_final_plan_keeps_focused_pytest_without_broad_suite():
    plan = build_final_verification(
        discovered=["ruff check ."],
        acceptance=[],
        slice_focused=["pytest tests/test_api.py -q"],
        explicit=[],
    )

    assert "pytest tests/test_api.py -q" in plan.commands


def test_slice_plan_skips_review_only_with_strong_low_risk_evidence():
    slice_plan = SlicePlan(
        "S1",
        "Core",
        "implement core",
        ["A1"],
        ["src/core.py", "tests/test_api.py"],
        ["pytest tests/test_api.py -q"],
    )

    verification = build_slice_verification(
        slice_plan,
        _contract(),
        slice_plan.focused_commands,
        ["pytest -q", "ruff check ."],
    )

    assert verification.commands == (
        "pytest tests/test_api.py -q",
        "ruff check .",
    )
    assert verification.review_required is False


def test_slice_review_remains_for_weak_or_high_risk_evidence():
    weak = SlicePlan("S1", "Core", "core", ["A1"], ["src/core.py"], [])
    risky = SlicePlan(
        "S2",
        "Config",
        "config",
        ["A1"],
        ["src/config.py"],
        ["pytest tests/test_api.py -q"],
    )

    assert should_review_slice(weak, _contract()) is True
    assert should_review_slice(risky, _contract()) is True
    assert should_review_slice(risky, _contract(command="")) is True


def test_slice_review_uses_actual_safe_focused_commands():
    declared = SlicePlan(
        "S1",
        "Core",
        "core",
        ["A1"],
        ["src/core.py"],
        ["cat output.txt | head"],
    )

    verification = build_slice_verification(
        declared,
        _contract(),
        focused=[],
        mandatory=["ruff check ."],
    )

    assert verification.review_required is True


def test_verification_reuse_requires_exact_accepted_fingerprint():
    assert can_reuse_verification("abc", "abc", accepted=True) is True
    assert can_reuse_verification("abc", "def", accepted=True) is False
    assert can_reuse_verification("abc", "abc", accepted=False) is False
