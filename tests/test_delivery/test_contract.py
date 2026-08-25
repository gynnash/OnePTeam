import pytest

from onep.delivery.contract import (
    AcceptanceRule,
    DeliveryContract,
    DeliveryContractError,
    DeliveryRequirement,
    DeliveryWorkItem,
)


def _contract(*, dependencies=()):
    return DeliveryContract(
        contract_id="dc_run",
        version=1,
        status="active",
        objective="deliver behavior",
        baseline_fingerprint="sha256:base",
        requirements=(
            DeliveryRequirement(
                "REQ-1",
                "observable behavior",
                "P0",
                (AcceptanceRule("AR-1", "command", "pytest -q"),),
            ),
        ),
        work_items=(
            DeliveryWorkItem(
                "WI-1",
                "slice",
                "implement behavior",
                ("REQ-1",),
                dependencies,
            ),
        ),
    )


def test_contract_round_trips_and_validates(tmp_path):
    contract = _contract()
    path = tmp_path / "contract.yaml"

    contract.save(path)

    assert DeliveryContract.load(path) == contract


def test_contract_rejects_unknown_dependency():
    with pytest.raises(DeliveryContractError, match="unknown dependencies"):
        _contract(dependencies=("missing",)).validate()


def test_contract_rejects_dependency_cycle():
    first = DeliveryWorkItem("WI-1", "one", "one", ("REQ-1",), ("WI-2",))
    second = DeliveryWorkItem("WI-2", "two", "two", ("REQ-1",), ("WI-1",))
    contract = _contract()
    cyclic = DeliveryContract(**{**contract.__dict__, "work_items": (first, second)})

    with pytest.raises(DeliveryContractError, match="cycle"):
        cyclic.validate()


def test_contract_allows_only_explicit_state_transitions():
    active = _contract()

    assert active.transition("completed").status == "completed"
    with pytest.raises(DeliveryContractError, match="invalid contract transition"):
        active.transition("proposed")
