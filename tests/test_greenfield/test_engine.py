import json
from pathlib import Path
from types import SimpleNamespace

import git
import pytest
from rich.console import Console

from onep.config import load_config
from onep.greenfield.engine import GreenfieldEngine
from onep.greenfield.gates import GreenfieldGateRunner
from onep.greenfield.git_session import GreenfieldGitSession
from onep.greenfield.models import (
    AcceptanceContract,
    AcceptanceItem,
    GreenfieldOptions,
    GreenfieldRun,
    SlicePlan,
)
from onep.strategy.models import StrategyItem
from onep.strategy.gates import PatchScopeGate
from onep.strategy.repair import AttemptStagnationDetector
from onep.llm.cost import CostTracker
from onep.llm.adapters import TokenUsage
from onep.persistence.models import Project, ProjectMode
from onep.persistence.state import save_state
from onep.strategy.optimize_engine import EngineAttemptResult
from onep.greenfield.recorder import GreenfieldRecorder


class FakeLLM:
    def __init__(self):
        self.last_usage = TokenUsage()

    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "greenfield_engineer":
            return """{
              "acceptance": [{"id":"REQ-1","priority":"P0","behavior":"value is one","verification":{"commands":["pytest -q"],"evidence":[]}}],
              "architecture": {"selected":"Python","rationale":"minimal"},
              "slices": [{"id":"core","title":"Core","objective":"set value","acceptance_ids":["REQ-1"],"expected_files":["app.py","test_app.py"],"focused_commands":[]}]
            }"""
        return '{"passed":true,"blocking_issues":[],"summary":"ok"}'


class ClarifyingLLM(FakeLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        return '{"clarification_question":"Should data be shared between users?"}'


class EarlyCompletionLLM(FakeLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "greenfield_engineer":
            return """{
              "acceptance": [{"id":"REQ-1","priority":"P0","behavior":"value is one","verification":{"commands":["pytest -q"],"evidence":[]}}],
              "architecture": {"selected":"Python","rationale":"minimal"},
              "slices": [
                {"id":"core","title":"Core","objective":"set value","acceptance_ids":["REQ-1"],"expected_files":["app.py","test_app.py"],"focused_commands":[]},
                {"id":"extra","title":"Extra","objective":"unnecessary follow-up","acceptance_ids":["REQ-1"],"expected_files":["extra.py"],"focused_commands":[]}
              ]
            }"""
        return super().invoke(system_prompt, user_prompt, stage_name)


class RepairingOptimizer:
    def __init__(self):
        self.calls = 0
        self.feedback = []
        self.summaries = []

    def execute_attempt(self, item, source_path, workspace, llm, feedback="", **kwargs):
        self.calls += 1
        self.feedback.append(feedback)
        self.summaries.append(item.summary)
        root = Path(source_path)
        (root / "app.py").write_text(f"VALUE = {1 if self.calls > 1 else 10}\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"
        )
        return EngineAttemptResult("implemented")


class InterruptingOptimizer:
    def execute_attempt(self, item, source_path, workspace, llm, **kwargs):
        (Path(source_path) / "app.py").write_text("partial\n")
        raise KeyboardInterrupt


class TransientThenCompleteOptimizer:
    def __init__(self):
        self.calls = 0

    def execute_attempt(self, item, source_path, workspace, llm, **kwargs):
        self.calls += 1
        root = Path(source_path)
        (root / "app.py").write_text("VALUE = 1\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\ndef test_value(): assert VALUE == 1\n"
        )
        if self.calls == 1:
            raise ConnectionError("incomplete chunked read")
        return EngineAttemptResult("implemented")


class AlwaysInterruptedWithValidPatchOptimizer:
    def __init__(self):
        self.calls = 0

    def execute_attempt(self, item, source_path, workspace, llm, **kwargs):
        self.calls += 1
        root = Path(source_path)
        (root / "app.py").write_text("VALUE = 1\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\ndef test_value(): assert VALUE == 1\n"
        )
        raise ConnectionError("incomplete chunked read")


class AlwaysInterruptedWithoutPatchOptimizer:
    def __init__(self):
        self.calls = 0

    def execute_attempt(self, item, source_path, workspace, llm, **kwargs):
        self.calls += 1
        raise ConnectionError("incomplete chunked read")


class LimitThenCompleteOptimizer:
    def __init__(self):
        self.calls = 0
        self.feedback = []

    def execute_attempt(self, item, source_path, workspace, llm, feedback="", **kwargs):
        self.calls += 1
        self.feedback.append(feedback)
        root = Path(source_path)
        (root / "app.py").write_text("VALUE = 1\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\ndef test_value(): assert VALUE == 1\n"
        )
        return EngineAttemptResult(
            "implemented",
            termination_reason=("tool_round_limit" if self.calls == 1 else "completed"),
        )


def _repo(path):
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("# demo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    return repo


def test_engine_repairs_failed_test_and_commits(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    optimizer = RepairingOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=4,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    assert optimizer.calls == 2
    assert "Structured repair brief" in optimizer.feedback[1]
    assert "pytest-discoverable" in optimizer.summaries[0]
    assert repo.active_branch.name.startswith("onep/greenfield-")
    assert (tmp_path / "app.py").read_text() == "VALUE = 1\n"
    assert (tmp_path / ".onep" / "greenfield" / "acceptance.yaml").exists()
    assert "## Installation" in (tmp_path / "README.md").read_text()
    assert (tmp_path / "docs" / "CODE_GUIDE.md").exists()
    assert (tmp_path / "docs" / "IMPLEMENTATION_PLAN.md").exists()


def test_completion_docs_use_product_entrypoint_not_python_pytest(tmp_path):
    pipeline = tmp_path / "src" / "pipeline.py"
    pipeline.parent.mkdir()
    pipeline.write_text('if __name__ == "__main__":\n    raise SystemExit(0)\n')

    usage = GreenfieldEngine._infer_usage_command(
        tmp_path, ["python -m pytest -q", "ruff check ."]
    )

    assert usage == "python -m src.pipeline"


def test_engine_stops_early_when_complete_requirement_is_satisfied(
    tmp_path, monkeypatch
):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    console = Console(record=True)
    engine = GreenfieldEngine(console=console, llm=EarlyCompletionLLM())
    optimizer = RepairingOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=5,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    assert optimizer.calls == 2
    run_file = next((tmp_path / ".onep" / "greenfield" / "runs").glob("*/run.yaml"))
    assert "status: skipped_satisfied" in run_file.read_text()
    assert "需求已满足" in console.export_text()
    assert "## Source modules" in (tmp_path / "docs" / "CODE_GUIDE.md").read_text()


def test_non_interactive_ambiguity_persists_blocked_state(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build app")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)

    success = GreenfieldEngine(llm=ClarifyingLLM()).run(
        project, GreenfieldOptions(non_interactive=True)
    )

    assert success is False
    run_files = list((tmp_path / ".onep" / "greenfield" / "runs").glob("*/run.yaml"))
    assert len(run_files) == 1
    assert "status: blocked" in run_files[0].read_text()


def test_engine_rolls_back_interrupted_attempt(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    engine.optimizer = InterruptingOptimizer()

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=2,
            max_repairs_per_slice=1,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is False
    assert not (tmp_path / "app.py").exists()
    assert git.Repo(tmp_path).git.status("--porcelain") == ""


def test_engine_retries_transient_model_error_without_losing_wip(
    tmp_path,
    monkeypatch,
):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    console = Console(record=True)
    engine = GreenfieldEngine(console=console, llm=FakeLLM())
    optimizer = TransientThenCompleteOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=1,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    assert optimizer.calls == 2
    assert (tmp_path / "app.py").read_text() == "VALUE = 1\n"
    output = console.export_text()
    assert "model_api_interrupted:ConnectionError" in output
    assert "incomplete chunked read" in output
    assert "已保存WIP=2个文件" in output
    assert "当前修复不计数" in output


def test_transport_exhaustion_with_wip_falls_back_to_gates(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    console = Console(record=True)
    engine = GreenfieldEngine(console=console, llm=FakeLLM())
    optimizer = AlwaysInterruptedWithValidPatchOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=1,
            max_repairs_per_slice=1,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    assert optimizer.calls == 3
    output = console.export_text()
    assert "模型传输连续中断，但已产生实质代码" in output
    assert "Reviewer 判断当前 WIP" in output


def test_transport_exhaustion_without_wip_has_precise_failure_type(
    tmp_path, monkeypatch
):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    optimizer = AlwaysInterruptedWithoutPatchOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=1,
            max_repairs_per_slice=1,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is False
    assert optimizer.calls == 3
    run_file = next((tmp_path / ".onep/greenfield/runs").glob("*/run.yaml"))
    assert "failure_reason: model_api_interrupted" in run_file.read_text()


def test_engine_uses_gates_when_model_limit_has_a_real_patch(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(
        tmp_path,
        __import__(
            "onep.persistence.models", fromlist=["PipelineState"]
        ).PipelineState(),
    )
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    optimizer = LimitThenCompleteOptimizer()
    engine.optimizer = optimizer

    success = engine.run(
        project,
        GreenfieldOptions(
            max_rounds=5,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    assert optimizer.calls == 1


def test_greenfield_scope_includes_command_paths_and_scaffolding():
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=[],
        expected_files=["src/collectors/arxiv_collector.py"],
        focused_commands=[
            "python src/collect --all",
            "python src/test_dedup.py --input test/duplicates.json",
        ],
    )
    item = StrategyItem("collect", "src/collectors/arxiv_collector.py")

    candidate = GreenfieldEngine._scope_candidate(item, plan)

    assert Path("src/collect.py") in candidate.files
    assert Path("src/__init__.py") in candidate.files
    assert Path("src/collectors/__init__.py") in candidate.files
    assert Path("test/__init__.py") in candidate.files
    assert Path("requirements.txt") in candidate.files


def test_greenfield_scope_includes_modules_used_by_slice_acceptance_commands():
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=["AC1"],
        expected_files=["config/sources.yaml", "src/db.py"],
    )
    contract = AcceptanceContract(
        [
            AcceptanceItem(
                id="AC1",
                priority="P0",
                behavior="load configured sources",
                commands=[
                    "python -c 'from src.config import load_sources; print(load_sources())'"
                ],
            )
        ]
    )
    item = StrategyItem("collect", "src/db.py")

    candidate = GreenfieldEngine._scope_candidate(item, plan, contract)

    assert Path("src/config.py") in candidate.files


def test_greenfield_scope_follows_changed_local_imports(tmp_path):
    (tmp_path / "src/collectors").mkdir(parents=True)
    (tmp_path / "src/collectors/arxiv_collector.py").write_text(
        "from .base import BaseCollector\n"
    )
    (tmp_path / "src/collectors/base.py").write_text("class BaseCollector: pass\n")
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=[],
        expected_files=["src/collectors/arxiv_collector.py"],
    )
    item = StrategyItem("collect", "src/collectors/arxiv_collector.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = ["src/collectors/arxiv_collector.py", "src/collectors/base.py"]

    GreenfieldEngine._expand_scope_from_local_imports(candidate, changed, tmp_path)

    assert PatchScopeGate().check(candidate, changed).passed


def test_greenfield_scope_allows_conventional_pytest_tests_and_fixtures():
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=[],
        expected_files=["src/db.py"],
    )
    item = StrategyItem("collect", "src/db.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = ["src/db.py", "tests/test_db.py", "tests/fixtures/items.json"]

    GreenfieldEngine._expand_scope_for_tests(candidate, changed)

    assert PatchScopeGate().check(candidate, changed).passed


def test_greenfield_scope_allows_any_asset_in_declared_fixture_directory():
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=[],
        expected_files=["src/collector.py", "tests/fixtures/arxiv"],
    )
    item = StrategyItem("collect", "src/collector.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = [
        "src/collector.py",
        "tests/fixtures/arxiv/response.xml",
        "tests/fixtures/arxiv/page.html",
    ]

    GreenfieldEngine._expand_scope_for_tests(candidate, changed)
    GreenfieldEngine._expand_scope_for_declared_directories(candidate, changed)

    assert PatchScopeGate().check(candidate, changed).passed


def test_greenfield_scope_allows_modules_inside_declared_package():
    plan = SlicePlan(
        id="collect",
        title="Collect",
        objective="collect",
        acceptance_ids=[],
        expected_files=["src/trendagent/__init__.py", "src/trendagent/store.py"],
    )
    item = StrategyItem("collect", "src/trendagent/store.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = ["src/trendagent/store.py", "src/trendagent/cli.py"]

    GreenfieldEngine._expand_scope_for_declared_packages(candidate, changed)

    assert PatchScopeGate().check(candidate, changed).passed


def test_round_budget_is_refreshed_for_each_explicit_run():
    engine = GreenfieldEngine(llm=FakeLLM())
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        options=GreenfieldOptions(max_rounds=2),
        round_number=12,
    )
    engine._round_start = run.round_number

    engine._check_budget_rounds(run, CostTracker())
    run.round_number = 14
    with __import__("pytest").raises(RuntimeError, match="Maximum engineering rounds"):
        engine._check_budget_rounds(run, CostTracker())


class _PlanRecorder:
    def __init__(self):
        self.traces = []

    def trace(self, stage, message, color=None):
        self.traces.append((stage, message))

    def save_slice(self, plan):
        pass

    def save_contract(self, contract):
        pass

    def save_run(self):
        pass


def test_existing_greenfield_plan_is_normalized_and_enriched():
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        options=GreenfieldOptions(test_commands=["pytest -q"]),
        slices=[
            SlicePlan(
                id="SL1",
                title="Collect",
                objective="collect",
                acceptance_ids=["AC1"],
                expected_files=["src/db.py"],
                focused_commands=["python src/collect --all"],
            )
        ],
    )
    contract = AcceptanceContract(
        [
            AcceptanceItem(
                id="AC1",
                priority="P0",
                behavior="load config",
                commands=["python -c 'from src.config import load_sources'"],
            )
        ]
    )

    GreenfieldEngine._normalize_slice_plans(run, contract, _PlanRecorder())

    plan = run.slices[0]
    assert plan.focused_commands[0].startswith("python src/collect.py")
    assert "src/collect.py" in plan.expected_files
    assert "src/config.py" in plan.expected_files
    assert "tests/test_collect.py" in plan.expected_files
    assert "tests/test_db.py" in plan.expected_files


def test_empty_focused_commands_are_rebuilt_from_declared_tests():
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        options=GreenfieldOptions(test_commands=["pytest -q"]),
        slices=[
            SlicePlan(
                id="S1",
                title="Core",
                objective="core",
                acceptance_ids=["A1"],
                expected_files=["src/app.py", "tests/unit/test_app.py"],
            )
        ],
    )
    contract = AcceptanceContract(
        [
            AcceptanceItem(
                id="A1",
                priority="P0",
                behavior="works",
            )
        ]
    )

    GreenfieldEngine._normalize_slice_plans(run, contract, _PlanRecorder())

    assert run.slices[0].focused_commands == [
        "python -m pytest tests/unit/test_app.py -q"
    ]


def test_recovered_wip_without_new_model_edits_still_runs_gates():
    assert (
        GreenfieldEngine._repair_made_no_progress(
            repair_mode=True,
            diff="existing-wip",
            diff_before_attempt="existing-wip",
            was_exception_retry=False,
            recovered_wip_attempt=True,
        )
        is False
    )
    assert (
        GreenfieldEngine._repair_made_no_progress(
            repair_mode=True,
            diff="existing-wip",
            diff_before_attempt="existing-wip",
            was_exception_retry=False,
            recovered_wip_attempt=False,
        )
        is True
    )


def test_plan_normalization_drops_runtime_outputs_and_suffixless_fake_python():
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        slices=[
            SlicePlan(
                id="SL1",
                title="Run",
                objective="run",
                acceptance_ids=["AC1"],
                expected_files=["src/run.py", "tmp/2024-W45", "tmp/result.json"],
                focused_commands=["python -m pytest tests/test_run.py -v"],
            )
        ],
    )
    contract = AcceptanceContract(
        [
            AcceptanceItem(
                id="AC1",
                priority="P0",
                behavior="run",
                commands=[
                    "python -m src.run --output-dir tmp/2024-W45 "
                    "--output tmp/result.json --store data/items.db"
                ],
            )
        ]
    )

    GreenfieldEngine._normalize_slice_plans(run, contract, _PlanRecorder())

    expected = run.slices[0].expected_files
    assert "src/run.py" in expected
    assert "tests/test_run.py" in expected
    assert not any(value.startswith("tmp/") for value in expected)
    assert "data/items.db" not in expected
    assert "tmp/2024-W45.py" not in expected


def test_missing_command_paths_ignores_outputs_but_requires_inputs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/run.py").write_text("pass\n")
    (tmp_path / "configs").mkdir()
    commands = [
        "python src/run.py --config configs/weekly.yaml "
        "--output tmp/result.json --output-dir tmp/2024-W45",
        "python -m pytest tests/test_integration.py -v",
    ]

    missing = GreenfieldEngine._missing_command_paths(commands, tmp_path)

    assert "configs/weekly.yaml" in missing
    assert "tests/test_integration.py" in missing
    assert "tmp/result.json" not in missing
    assert "tmp/2024-W45" not in missing


def test_pytest_node_ids_are_validated_as_files(tmp_path):
    target = tmp_path / "tests/test_config.py"
    target.parent.mkdir()
    target.write_text("def test_load(): pass\n")

    missing = GreenfieldEngine._missing_command_paths(
        ["pytest tests/test_config.py::test_load -q"], tmp_path
    )

    assert missing == []


def test_plan_normalization_resolves_test_module_package_collision():
    recorder = _PlanRecorder()
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        options=GreenfieldOptions(test_commands=["pytest -q"]),
        slices=[
            SlicePlan(
                id="S1",
                title="Collectors",
                objective="collect",
                acceptance_ids=[],
                expected_files=[
                    "tests/test_collectors.py (new)",
                    "tests/test_collectors/__init__.py",
                    "tests/test_collectors/test_arxiv.py",
                ],
            )
        ],
    )

    GreenfieldEngine._normalize_slice_plans(run, AcceptanceContract([]), recorder)

    expected = run.slices[0].expected_files
    assert "tests/test_collectors.py" not in expected
    assert "tests/test_collectors/test_exports.py" in expected
    assert any(stage == "PLAN_CHECK" for stage, _ in recorder.traces)


def test_broad_test_command_detection_keeps_focused_tests():
    assert GreenfieldEngine._is_broad_test_command("pytest -q")
    assert GreenfieldEngine._is_broad_test_command("python -m pytest tests/ -q")
    assert not GreenfieldEngine._is_broad_test_command(
        "python -m pytest tests/test_run.py -q"
    )


def test_slice_gate_dedup_runs_full_pytest_once_but_keeps_lint():
    mandatory = [
        "pytest -q",
        "pytest tests/test_config.py -q",
        "ruff check .",
    ]

    assert GreenfieldEngine._dedupe_slice_gates(["pytest -q"], mandatory) == [
        "ruff check ."
    ]
    assert GreenfieldEngine._dedupe_slice_gates(
        ["pytest tests/test_config.py -q"], mandatory
    ) == ["pytest tests/test_config.py -q", "ruff check ."]


def test_unchanged_assessment_is_skipped(tmp_path):
    class FakeGit:
        @staticmethod
        def status(*args):
            return ""

    session = SimpleNamespace(
        workspace=tmp_path,
        repo=SimpleNamespace(
            git=FakeGit(),
            head=SimpleNamespace(commit=SimpleNamespace(hexsha="abc123")),
        ),
    )
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=str(tmp_path),
    )
    contract = AcceptanceContract(
        [
            AcceptanceItem(
                id="AC1",
                priority="P0",
                behavior="integration",
                commands=["pytest tests/test_integration.py -q"],
            )
        ]
    )
    console = Console(record=True)
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, console)
    engine = GreenfieldEngine(console=console, llm=FakeLLM())
    gate_runner = SimpleNamespace()

    first = engine._requirements_satisfied(
        run, contract, session, gate_runner, recorder, CostTracker()
    )
    second = engine._requirements_satisfied(
        run, contract, session, gate_runner, recorder, CostTracker()
    )

    assert first is False and second is False
    output = console.export_text()
    assert output.count("检查当前代码是否已经满足完整用户需求") == 1
    assert "跳过重复完整评估" in output


def test_assessment_fingerprint_ignores_runtime_status():
    class FakeGit:
        status_value = "?? output/weekly_scan.log"

        @classmethod
        def status(cls, *args):
            return cls.status_value

    session = SimpleNamespace(
        repo=SimpleNamespace(
            git=FakeGit(),
            head=SimpleNamespace(commit=SimpleNamespace(hexsha="abc123")),
        )
    )
    contract = AcceptanceContract([])
    first = GreenfieldEngine._assessment_fingerprint(session, ["pytest -q"], contract)
    FakeGit.status_value = "?? logs/debug.log"
    second = GreenfieldEngine._assessment_fingerprint(session, ["pytest -q"], contract)

    assert first == second


def test_recorder_restores_failed_wip_and_logs_safe_progress(tmp_path):
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=str(tmp_path),
    )
    console = Console(record=True)
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, console)
    plan = SlicePlan("SL1", "Core", "core", [], ["src/app.py"])
    source = tmp_path / "src/app.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    recorder.save_wip(plan, ["src/app.py"], tmp_path)
    source.unlink()

    restored = recorder.restore_wip(plan, tmp_path)
    recorder.engineer_event(
        {
            "type": "tool_requested",
            "payload": {
                "tool_name": "file_write",
                "tool_args": {"path": "src/app.py", "content": "SECRET-CONTENT"},
            },
        }
    )
    recorder.engineer_event(
        {
            "type": "model_message",
            "payload": {"content": "将实现入口、配置加载和集成测试。"},
        }
    )
    recorder.engineer_summary("实现完成。", ["src/app.py"], "completed")

    assert restored == ["src/app.py"]
    assert source.read_text() == "VALUE = 1\n"
    output = console.export_text()
    assert "file_write" not in output
    assert "将实现入口、配置加载和集成测试" in output
    assert "变更文件: src/app.py" in output
    assert "SECRET-CONTENT" not in output
    events = (tmp_path / ".onep/run/events.jsonl").read_text()
    assert "file_write" in events


def test_recorder_preserves_deleted_files_in_wip(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=str(tmp_path)
    )
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, Console())
    plan = SlicePlan("S1", "cleanup", "cleanup", [], ["obsolete.py"])
    obsolete = tmp_path / "obsolete.py"
    obsolete.write_text("old\n")
    obsolete.unlink()

    recorder.save_wip(plan, ["obsolete.py"], tmp_path)
    obsolete.write_text("old\n")
    restored = recorder.restore_wip(plan, tmp_path)

    assert restored == ["obsolete.py"]
    assert not obsolete.exists()
    manifest = json.loads(
        (tmp_path / ".onep/run/slices/S1/wip/manifest.json").read_text()
    )
    assert manifest["deleted"] == ["obsolete.py"]


def test_recorder_does_not_persist_runtime_outputs_as_wip(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=str(tmp_path)
    )
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, Console())
    plan = SlicePlan("S1", "core", "core", [], ["src/app.py"])
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n")
    (tmp_path / "output").mkdir()
    (tmp_path / "output/weekly.log").write_text("runtime\n")

    recorder.save_wip(plan, ["src/app.py", "output/weekly.log"], tmp_path)

    manifest = json.loads(
        (tmp_path / ".onep/run/slices/S1/wip/manifest.json").read_text()
    )
    assert manifest["files"] == ["src/app.py"]


def test_recorder_aggregates_repeated_failures_but_persists_each_one(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=str(tmp_path)
    )
    console = Console(record=True)
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, console)

    for _ in range(5):
        recorder.failure(
            "RETRY",
            "model_api_interrupted:ConnectionError",
            "ConnectionError: incomplete chunked read",
            context="切片=S1; 下次修复=1/8",
        )
    recorder.failure(
        "RETRY",
        "model_api_interrupted:TimeoutError",
        "TimeoutError: provider timed out after 30s",
        context="切片=S1; 下次修复=2/8",
    )

    output = console.export_text()
    assert output.count("incomplete chunked read") == 3
    assert "同类失败累计 3 次" in output
    assert "provider timed out after 30s" in output
    events = (tmp_path / ".onep/run/events.jsonl").read_text()
    assert events.count('"type": "failure_observed"') == 6
    assert '"repeat_count": 5' in events


def test_recorder_prints_failed_tool_details_without_verbose_mode(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=str(tmp_path)
    )
    console = Console(record=True)
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, console)
    recorder.begin_engineer_attempt()
    recorder.engineer_event(
        {
            "type": "tool_requested",
            "payload": {
                "tool_name": "shell",
                "tool_args": {"command": "python -m pytest tests/test_app.py -q"},
            },
        }
    )
    recorder.engineer_event(
        {
            "type": "tool_completed",
            "payload": {
                "tool_name": "shell",
                "tool_result": (
                    "FAILED tests/test_app.py::test_value - AssertionError\n[exit: 1]"
                ),
            },
        }
    )

    output = console.export_text()
    assert "[TOOL_FAIL]" in output
    assert "tests/test_app.py::test_value" in output
    assert "command=python -m pytest" in output
    assert "tests/test_app.py -q" in output
    assert "[exit: 1]" in output


def test_failed_tool_console_context_redacts_credentials(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=str(tmp_path)
    )
    console = Console(record=True)
    recorder = GreenfieldRecorder(tmp_path / ".onep/run", run, console)
    recorder.begin_engineer_attempt()
    recorder.engineer_event(
        {
            "type": "tool_requested",
            "payload": {
                "tool_name": "shell",
                "tool_args": {"command": "API_KEY=super-secret python app.py"},
            },
        }
    )
    recorder.engineer_event(
        {
            "type": "tool_completed",
            "payload": {"tool_name": "shell", "tool_result": "Error: unauthorized"},
        }
    )

    output = console.export_text()
    assert "API_KEY=***" in output
    assert "super-secret" not in output


def test_final_test_failure_builds_focused_hardening_slice():
    class FailedCommand:
        command = "pytest -q"

    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        slices=[
            SlicePlan(
                id="final-regression-hardening",
                title="old",
                objective="old",
                acceptance_ids=[],
                expected_files=[],
            )
        ],
    )

    plan = GreenfieldEngine._final_test_repair_plan(
        run,
        FailedCommand(),
        "FAILED tests/test_app.py::test_value",
    )

    assert plan.id == "final-regression-hardening-2"
    assert plan.focused_commands == ["pytest -q"]
    assert "test_value" in plan.objective
    assert "Do not weaken" in plan.objective


def test_reviewer_test_diagnosis_is_only_used_for_pytest_commands():
    assert GreenfieldEngine._is_pytest_command("pytest -q")
    assert GreenfieldEngine._is_pytest_command("python -m pytest tests/test_app.py -v")
    assert not GreenfieldEngine._is_pytest_command("python -m src.main --help")
    assert not GreenfieldEngine._is_pytest_command("ruff check .")


def test_final_hardening_slice_is_cross_cutting_even_after_plan_enrichment():
    plan = SlicePlan(
        id="final-regression-hardening-2",
        title="Final regression hardening",
        objective="fix full suite",
        acceptance_ids=[],
        expected_files=["tests/test_one.py"],
    )

    assert GreenfieldEngine._is_cross_cutting_hardening(plan)


def test_passing_gates_suppress_reviewer_prediction_that_test_would_fail():
    review = SimpleNamespace(
        findings=[
            "tests/test_similarity.py: test_no_urls expects 1.0 but production returns 0.7"
        ],
        summary="predicted failure",
    )
    tests = SimpleNamespace(passed=True)

    assert GreenfieldEngine._credible_review_findings(review, tests) == []


def test_passing_gates_do_not_suppress_real_uncovered_review_finding():
    review = SimpleNamespace(
        findings=["src/main.py: parsed --source option is never consumed"],
        summary="unused configuration",
    )
    tests = SimpleNamespace(passed=True)

    assert GreenfieldEngine._credible_review_findings(review, tests) == review.findings


def test_final_verification_marks_pending_acceptance_with_exact_command_evidence():
    item = AcceptanceItem(
        id="A4",
        priority="P1",
        behavior="collect blogs",
        commands=["python -m pytest tests/collector/test_blog_collector.py -v"],
    )
    contract = AcceptanceContract([item])
    result = SimpleNamespace(
        commands=[
            SimpleNamespace(
                command="python -m pytest tests/collector/test_blog_collector.py -v",
                passed=True,
            )
        ]
    )

    GreenfieldEngine._mark_final_acceptance(contract, result)

    assert item.status == "passed"
    assert item.evidence == ["final-verification:declared-commands-passed"]


def test_hardening_ids_are_unique_and_bounded_by_prefix_count():
    run = GreenfieldRun(
        id="run",
        project_name="demo",
        requirement="demo",
        workspace=".",
        slices=[
            SlicePlan("final-architecture-hardening", "one", "one", [], []),
            SlicePlan("final-architecture-hardening-2", "two", "two", [], []),
        ],
    )

    assert GreenfieldEngine._hardening_count(run, "final-architecture-hardening") == 2
    assert (
        GreenfieldEngine._next_hardening_id(run, "final-architecture-hardening")
        == "final-architecture-hardening-3"
    )


class AlwaysFailingOptimizer:
    def execute_attempt(self, item, source_path, workspace, llm, feedback="", **kwargs):
        root = Path(source_path)
        (root / "app.py").write_text("VALUE = 9\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"
        )
        return EngineAttemptResult("implemented")


def _kernel_setup(tmp_path):
    _repo(tmp_path)
    engine = GreenfieldEngine(llm=FakeLLM())
    run = GreenfieldRun(
        id="gf-x", project_name="demo", requirement="demo",
        workspace=str(tmp_path),
        options=GreenfieldOptions(
            max_repairs_per_slice=2, test_commands=["pytest -q"],
        ),
    )
    plan = SlicePlan(
        "core", "Core", "set value", ["REQ-1"],
        ["app.py", "test_app.py"], [],
    )
    run.slices = [plan]
    contract = AcceptanceContract([
        AcceptanceItem(
            id="REQ-1", priority="P0", behavior="value is one",
            commands=["pytest -q"],
        ),
    ])
    session = GreenfieldGitSession(tmp_path, "gf-x")
    session.start()
    run_dir = tmp_path / ".onep" / "greenfield" / "runs" / "gf-x"
    recorder = GreenfieldRecorder(run_dir, run, Console())
    return engine, run, plan, contract, session, recorder


def test_execute_slice_fires_distill_checkpoints(tmp_path):
    engine, run, plan, contract, session, recorder = _kernel_setup(tmp_path)
    engine.optimizer = RepairingOptimizer()
    calls = []
    engine._execute_slice(
        run, plan, contract, session, ["pytest -q"],
        GreenfieldGateRunner(load_config().pipeline.test_timeout),
        recorder, CostTracker(0.0), AttemptStagnationDetector(3),
        distill=lambda checkpoint, payload: calls.append((checkpoint, payload)),
    )
    assert [name for name, _ in calls] == ["review_complete", "slice_complete"]
    _, payload = calls[1]
    assert payload["plan_id"] == "core"
    assert payload["commit_sha"] == plan.commit_sha
    assert "app.py" in payload["changed"]


def test_execute_slice_repair_failed_checkpoint(tmp_path):
    engine, run, plan, contract, session, recorder = _kernel_setup(tmp_path)
    engine.optimizer = AlwaysFailingOptimizer()
    run.options.max_repairs_per_slice = 0
    calls = []
    with pytest.raises(RuntimeError, match="Repair attempts exhausted"):
        engine._execute_slice(
            run, plan, contract, session, ["pytest -q"],
            GreenfieldGateRunner(load_config().pipeline.test_timeout),
            recorder, CostTracker(0.0), AttemptStagnationDetector(3),
            distill=lambda checkpoint, payload: calls.append((checkpoint, payload)),
        )
    assert calls[-1][0] == "repair_failed"
    payload = calls[-1][1]
    assert payload["loop_stagnant"] is False
    assert payload["retry_count"] == 1
    assert payload["failure_type"] == "test_failed"
