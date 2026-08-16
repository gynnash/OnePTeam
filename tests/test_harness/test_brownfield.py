from pathlib import Path

from onep.harness.brownfield import BrownfieldUnderstandStage
from onep.harness.understand import detect_mode


def test_detect_mode_empty_dir_is_greenfield(tmp_path):
    (tmp_path / "readme.md").write_text("# empty\n")
    assert detect_mode(tmp_path, "build a thing") == "greenfield"
    assert detect_mode(tmp_path, "") == "greenfield"


def test_detect_mode_code_without_requirement_is_brownfield(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert detect_mode(tmp_path, "") == "brownfield"
    assert detect_mode(tmp_path, "   ") == "brownfield"


def test_detect_mode_code_with_requirement_is_mixed(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert detect_mode(tmp_path, "add auth") == "mixed"


class ScanLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, system_prompt=None, user_prompt=None, stage_name=None):
        self.calls.append(stage_name)
        return "{}"


def _item():
    from onep.strategy.models import StrategyItem
    return StrategyItem(
        id="si-1", title="Cache", file_location="app.py:1",
        summary="cache issue", tags=["cache"], impact="medium",
    )


def test_brownfield_understand_scans_plans_and_builds_candidates(tmp_path):
    from types import SimpleNamespace

    def fake_analyzer(source, llm, tracker=None, project_name="",
                       source_files=None, **kwargs):
        return [_item()]

    def fake_planner(item, workspace, llm_adapter, plan_index=1,
                     memory_context=""):
        return SimpleNamespace(
            plan_path=str(Path(workspace) / f"{plan_index}.md"),
            plan_markdown=f"# plan {plan_index}",
            expected_files=("cache.py",),
            dependencies=(),
            test_commands=("pytest -q tests/test_cache.py",),
            risk_flags=(),
        )

    stage = BrownfieldUnderstandStage(
        ScanLLM(), analyzer=fake_analyzer, planner=fake_planner,
    )
    candidates, plans = stage.run(
        tmp_path, "demo", ("pytest -q",),
    )
    assert [candidate.id for candidate in candidates] == ["si-1"]
    assert candidates[0].test_commands == ("pytest -q",)
    assert candidates[0].focused_test_commands == (
        "pytest -q tests/test_cache.py",)
    assert plans == {"si-1": "# plan 1"}
