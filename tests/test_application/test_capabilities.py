import pytest

from onep.application import Capability, CapabilityRegistry
from onep.domain import Problem


def noop(payload, context):
    return payload


def test_registry_describes_non_legacy_capabilities():
    registry = CapabilityRegistry([
        Capability("project.list", "List projects", noop),
        Capability("legacy.run", "Legacy", noop, legacy=True),
    ])

    assert registry.get("project.list").title == "List projects"
    assert [item["id"] for item in registry.describe()] == ["project.list"]


def test_registry_rejects_duplicates_and_unknown_ids():
    registry = CapabilityRegistry([Capability("project.list", "List", noop)])

    with pytest.raises(ValueError):
        registry.register(Capability("project.list", "Again", noop))
    with pytest.raises(Problem) as error:
        registry.get("missing")

    assert error.value.code == "capability_not_found"
