from onep.greenfield.models import (
    AcceptanceContract, AcceptanceItem, GreenfieldOptions, SlicePlan,
)


def test_acceptance_requires_evidence_for_p0_and_p1():
    contract = AcceptanceContract([
        AcceptanceItem("A-1", "P0", "works", status="passed"),
    ])
    assert contract.required_complete is False

    contract.items[0].commands = ["pytest -q"]
    assert contract.required_complete is True


def test_options_round_trip():
    options = GreenfieldOptions(
        max_rounds=8, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    )
    assert GreenfieldOptions.from_dict(options.to_dict()) == options


def test_default_and_legacy_round_limit_are_one_hundred():
    assert GreenfieldOptions().max_rounds == 100
    assert GreenfieldOptions.from_dict({"max_rounds": 12}).max_rounds == 100


def test_default_and_legacy_repair_limit_are_eight():
    assert GreenfieldOptions().max_repairs_per_slice == 8
    assert GreenfieldOptions.from_dict({"max_repairs_per_slice": 3}).max_repairs_per_slice == 8


def test_model_scalar_list_fields_are_not_split_into_characters():
    item = AcceptanceItem.from_dict({
        "id": "A1", "verification": {
            "commands": "pytest tests/test_api.py -q",
            "evidence": "integration test passes",
        },
    })
    plan = SlicePlan.from_dict({
        "id": "S1", "acceptance_ids": "A1",
        "expected_files": "src/api.py",
        "focused_commands": "pytest tests/test_api.py -q",
    })

    assert item.commands == ["pytest tests/test_api.py -q"]
    assert item.evidence == ["integration test passes"]
    assert plan.acceptance_ids == ["A1"]
    assert plan.expected_files == ["src/api.py"]
    assert plan.focused_commands == ["pytest tests/test_api.py -q"]


def test_legacy_character_lists_are_collapsed_on_resume():
    item = AcceptanceItem.from_dict({
        "verification": {"evidence": list("tests pass")},
    })
    plan = SlicePlan.from_dict({
        "focused_commands": list("pytest -q"),
    })

    assert item.evidence == ["tests pass"]
    assert plan.focused_commands == ["pytest -q"]
