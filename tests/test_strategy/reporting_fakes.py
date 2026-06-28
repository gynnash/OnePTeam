from onep.strategy.models import StrategyItem, WorkbenchState


def make_workbench_with_item(tmp_path):
    return WorkbenchState(
        project_name="demo",
        source_path=str(tmp_path / "source"),
        items=[
            StrategyItem(
                title="Cache",
                file_location="cache.py:1",
                summary="missing eviction",
                tags=["cache"],
                impact="high",
            )
        ],
    )
