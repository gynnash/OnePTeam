from onep.strategy.optimize_models import PlanCandidate
from onep.strategy.plan_scheduler import PlanScheduler


def candidate(item_id, files, dependencies=()):
    return PlanCandidate(
        id=item_id,
        title=item_id,
        summary="summary",
        files=set(files),
        dependencies=set(dependencies),
    )


def test_independent_plans_share_parallel_group():
    groups = PlanScheduler().groups(
        [candidate("a", ["a.py"]), candidate("b", ["b.py"])]
    )
    assert [[plan.id for plan in group] for group in groups] == [["a", "b"]]


def test_overlaps_and_dependencies_are_serialized():
    groups = PlanScheduler().groups(
        [
            candidate("a", ["shared.py"]),
            candidate("b", ["shared.py"]),
            candidate("c", ["c.py"], ["a"]),
        ]
    )
    assert [[p.id for p in group] for group in groups] == [
        ["a"],
        ["b"],
        ["c"],
    ]


def test_duplicate_fingerprint_is_scheduled_once():
    first = candidate("a", ["a.py"])
    duplicate = candidate("b", ["a.py"])
    duplicate.title = first.title
    assert len(PlanScheduler().new_candidates([first, duplicate], set())) == 1


def test_unknown_dependency_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="unknown dependency"):
        PlanScheduler().groups([candidate("a", ["a.py"], ["missing"])])


def test_integration_order_is_impact_then_discovery_order():
    scheduler = PlanScheduler()
    low = candidate("low", ["low.py"])
    low.impact = "low"
    low.discovery_index = 0
    medium_late = candidate("m2", ["m2.py"])
    medium_late.discovery_index = 2
    medium_early = candidate("m1", ["m1.py"])
    medium_early.discovery_index = 1
    assert [
        item.id for item in scheduler.integration_order(
            [low, medium_late, medium_early]
        )
    ] == ["m1", "m2", "low"]


def test_dependency_cycle_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="cycle"):
        PlanScheduler().groups([
            candidate("a", ["a.py"], ["b"]),
            candidate("b", ["b.py"], ["a"]),
        ])
