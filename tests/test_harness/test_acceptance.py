from onep.greenfield.models import AcceptanceContract, AcceptanceItem
from onep.harness.acceptance import evaluate_acceptance


def _contract(*, status="passed", evidence=True):
    return AcceptanceContract(
        [
            AcceptanceItem(
                id="REQ-1",
                priority="P0",
                behavior="works",
                commands=["pytest -q"] if evidence else [],
                status=status,
            )
        ]
    )


def test_acceptance_requires_current_hard_gate_evidence():
    decision = evaluate_acceptance(
        _contract(), hard_gates_passed=False, failed_commands=("pytest -q",)
    )

    assert decision.satisfied is False
    assert decision.failed_commands == ("pytest -q",)


def test_acceptance_rejects_status_without_executable_evidence():
    decision = evaluate_acceptance(
        _contract(evidence=False), hard_gates_passed=True
    )

    assert decision.satisfied is False
    assert decision.missing == ("REQ-1",)


def test_acceptance_rejects_review_blocker_and_preserves_fingerprint():
    decision = evaluate_acceptance(
        _contract(),
        hard_gates_passed=True,
        blocker_count=1,
        fingerprint="tree-1",
    )

    assert decision.satisfied is False
    assert decision.blocker_count == 1
    assert decision.fingerprint == "tree-1"


def test_acceptance_passes_only_with_all_hard_evidence():
    assert evaluate_acceptance(
        _contract(), hard_gates_passed=True, fingerprint="tree-1"
    ).satisfied
