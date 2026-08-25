from onep.delivery.contract import (
    AcceptanceRule,
    DeliveryContract,
    DeliveryRequirement,
    DeliveryWorkItem,
)
from onep.delivery.evidence import EvidenceLedger
from onep.harness.acceptance import evaluate_delivery_acceptance


def _contract():
    return DeliveryContract(
        contract_id="dc_run",
        version=2,
        status="active",
        objective="deliver",
        baseline_fingerprint="sha256:base",
        requirements=(
            DeliveryRequirement(
                "REQ-1",
                "behavior",
                "P0",
                (AcceptanceRule("AR-1", "command", "pytest -q"),),
            ),
        ),
        work_items=(DeliveryWorkItem("WI-1", "slice", "implement", ("REQ-1",)),),
    )


def test_candidate_never_satisfies_acceptance(tmp_path):
    contract = _contract()
    ledger = EvidenceLedger(tmp_path)
    ledger.submit_candidate(
        contract_id=contract.contract_id,
        contract_version=contract.version,
        work_item_id="WI-1",
        tree_fingerprint="sha256:tree",
        summary="done",
    )

    decision = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:tree",
        hard_gates_passed=True,
    )

    assert decision.satisfied is False
    assert decision.missing == ("AR-1",)


def test_verified_evidence_is_bound_to_tree_and_can_be_invalidated(tmp_path):
    contract = _contract()
    ledger = EvidenceLedger(tmp_path)
    record = ledger.record_verified_command(
        contract_id=contract.contract_id,
        contract_version=contract.version,
        requirement_ids=("REQ-1",),
        acceptance_rule_ids={"REQ-1": ("AR-1",)},
        work_item_id="WI-1",
        tree_fingerprint="sha256:tree",
        command="pytest -q",
        passed=True,
        exit_code=0,
        duration_seconds=1.2,
        stdout="1 passed",
        stderr="",
        timeout_seconds=30,
    )[0]

    accepted = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:tree",
        hard_gates_passed=True,
    )
    stale = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:other",
        hard_gates_passed=True,
    )
    ledger.invalidate(record.evidence_id, "tree_changed")
    invalidated = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:tree",
        hard_gates_passed=True,
    )

    assert accepted.satisfied is True
    assert accepted.evidence_ids == (record.evidence_id,)
    assert stale.satisfied is False
    assert invalidated.satisfied is False
    assert ledger.events()[0]["event_type"] == "evidence_verified"


def test_verified_evidence_expires_when_validation_environment_changes(
    tmp_path, monkeypatch
):
    contract = _contract()
    ledger = EvidenceLedger(tmp_path)
    monkeypatch.setenv("CI", "one")
    ledger.record_verified_command(
        contract_id=contract.contract_id,
        contract_version=contract.version,
        requirement_ids=("REQ-1",),
        acceptance_rule_ids={"REQ-1": ("AR-1",)},
        work_item_id="WI-1",
        tree_fingerprint="sha256:tree",
        command="pytest -q",
        passed=True,
        exit_code=0,
        duration_seconds=1,
        stdout="passed",
        stderr="",
        timeout_seconds=30,
    )
    monkeypatch.setenv("CI", "two")

    decision = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:tree",
        hard_gates_passed=True,
    )

    assert decision.satisfied is False
    assert decision.missing == ("AR-1",)


def test_verified_evidence_must_match_the_rule_command(tmp_path):
    contract = _contract()
    ledger = EvidenceLedger(tmp_path)
    ledger.record_verified_command(
        contract_id=contract.contract_id,
        contract_version=contract.version,
        requirement_ids=("REQ-1",),
        acceptance_rule_ids={"REQ-1": ("AR-1",)},
        work_item_id="WI-1",
        tree_fingerprint="sha256:tree",
        command="python -m pytest -q",
        passed=True,
        exit_code=0,
        duration_seconds=1,
        stdout="passed",
        stderr="",
        timeout_seconds=30,
    )

    decision = evaluate_delivery_acceptance(
        contract,
        ledger,
        tree_fingerprint="sha256:tree",
        hard_gates_passed=True,
    )

    assert decision.satisfied is False
    assert decision.missing == ("AR-1",)
