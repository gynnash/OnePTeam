from pathlib import Path
from types import SimpleNamespace

import git
from rich.console import Console

from onep.greenfield.engine import GreenfieldEngine
from onep.greenfield.models import (
    AcceptanceContract, AcceptanceItem, GreenfieldOptions, GreenfieldRun,
    SlicePlan,
)
from onep.strategy.models import StrategyItem
from onep.strategy.gates import PatchScopeGate
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
            "implemented", termination_reason=(
                "tool_round_limit" if self.calls == 1 else "completed"
            )
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
    save_state(tmp_path, __import__("onep.persistence.models", fromlist=["PipelineState"]).PipelineState())
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    optimizer = RepairingOptimizer()
    engine.optimizer = optimizer

    success = engine.run(project, GreenfieldOptions(
        max_rounds=4, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    ))

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


def test_engine_stops_early_when_complete_requirement_is_satisfied(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(tmp_path, __import__("onep.persistence.models", fromlist=["PipelineState"]).PipelineState())
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    console = Console(record=True)
    engine = GreenfieldEngine(console=console, llm=EarlyCompletionLLM())
    optimizer = RepairingOptimizer()
    engine.optimizer = optimizer

    success = engine.run(project, GreenfieldOptions(
        max_rounds=5, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    ))

    assert success is True
    assert optimizer.calls == 2
    run_file = next((tmp_path / ".onep" / "greenfield" / "runs").glob("*/run.yaml"))
    assert "status: skipped_satisfied" in run_file.read_text()
    assert "需求已满足" in console.export_text()
    assert "## Source modules" in (tmp_path / "docs" / "CODE_GUIDE.md").read_text()


def test_non_interactive_ambiguity_persists_blocked_state(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build app")
    save_state(tmp_path, __import__("onep.persistence.models", fromlist=["PipelineState"]).PipelineState())
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
    save_state(tmp_path, __import__("onep.persistence.models", fromlist=["PipelineState"]).PipelineState())
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    engine.optimizer = InterruptingOptimizer()

    success = engine.run(project, GreenfieldOptions(
        max_rounds=2, max_repairs_per_slice=1,
        test_commands=["pytest -q"], deploy_mode="none",
    ))

    assert success is False
    assert not (tmp_path / "app.py").exists()
    assert git.Repo(tmp_path).git.status("--porcelain") == ""


def test_engine_does_not_test_until_model_implementation_completes(tmp_path, monkeypatch):
    _repo(tmp_path)
    project = Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")
    save_state(tmp_path, __import__("onep.persistence.models", fromlist=["PipelineState"]).PipelineState())
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda project: None)
    engine = GreenfieldEngine(llm=FakeLLM())
    optimizer = LimitThenCompleteOptimizer()
    engine.optimizer = optimizer

    success = engine.run(project, GreenfieldOptions(
        max_rounds=5, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    ))

    assert success is True
    assert optimizer.calls == 2
    assert "implementation_incomplete" in optimizer.feedback[1]


def test_greenfield_scope_includes_command_paths_and_scaffolding():
    plan = SlicePlan(
        id="collect", title="Collect", objective="collect", acceptance_ids=[],
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
        id="collect", title="Collect", objective="collect",
        acceptance_ids=["AC1"], expected_files=["config/sources.yaml", "src/db.py"],
    )
    contract = AcceptanceContract([AcceptanceItem(
        id="AC1", priority="P0", behavior="load configured sources",
        commands=[
            "python -c 'from src.config import load_sources; print(load_sources())'"
        ],
    )])
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
        id="collect", title="Collect", objective="collect", acceptance_ids=[],
        expected_files=["src/collectors/arxiv_collector.py"],
    )
    item = StrategyItem("collect", "src/collectors/arxiv_collector.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = ["src/collectors/arxiv_collector.py", "src/collectors/base.py"]

    GreenfieldEngine._expand_scope_from_local_imports(candidate, changed, tmp_path)

    assert PatchScopeGate().check(candidate, changed).passed


def test_greenfield_scope_allows_conventional_pytest_tests_and_fixtures():
    plan = SlicePlan(
        id="collect", title="Collect", objective="collect", acceptance_ids=[],
        expected_files=["src/db.py"],
    )
    item = StrategyItem("collect", "src/db.py")
    candidate = GreenfieldEngine._scope_candidate(item, plan)
    changed = ["src/db.py", "tests/test_db.py", "tests/fixtures/items.json"]

    GreenfieldEngine._expand_scope_for_tests(candidate, changed)

    assert PatchScopeGate().check(candidate, changed).passed


def test_round_budget_is_refreshed_for_each_explicit_run():
    engine = GreenfieldEngine(llm=FakeLLM())
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=".",
        options=GreenfieldOptions(max_rounds=2), round_number=12,
    )
    engine._round_start = run.round_number

    engine._check_budget_rounds(run, CostTracker())
    run.round_number = 14
    with __import__("pytest").raises(RuntimeError, match="Maximum engineering rounds"):
        engine._check_budget_rounds(run, CostTracker())


class _PlanRecorder:
    def save_slice(self, plan):
        pass

    def save_contract(self, contract):
        pass

    def save_run(self):
        pass


def test_existing_greenfield_plan_is_normalized_and_enriched():
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=".",
        options=GreenfieldOptions(test_commands=["pytest -q"]),
        slices=[SlicePlan(
            id="SL1", title="Collect", objective="collect",
            acceptance_ids=["AC1"], expected_files=["src/db.py"],
            focused_commands=["python src/collect --all"],
        )],
    )
    contract = AcceptanceContract([AcceptanceItem(
        id="AC1", priority="P0", behavior="load config",
        commands=["python -c 'from src.config import load_sources'"],
    )])

    GreenfieldEngine._normalize_slice_plans(run, contract, _PlanRecorder())

    plan = run.slices[0]
    assert plan.focused_commands[0].startswith("python src/collect.py")
    assert "src/collect.py" in plan.expected_files
    assert "src/config.py" in plan.expected_files
    assert "tests/test_collect.py" in plan.expected_files
    assert "tests/test_db.py" in plan.expected_files


def test_plan_normalization_drops_runtime_outputs_and_suffixless_fake_python():
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo", workspace=".",
        slices=[SlicePlan(
            id="SL1", title="Run", objective="run", acceptance_ids=["AC1"],
            expected_files=["src/run.py", "tmp/2024-W45", "tmp/result.json"],
            focused_commands=["python -m pytest tests/test_run.py -v"],
        )],
    )
    contract = AcceptanceContract([AcceptanceItem(
        id="AC1", priority="P0", behavior="run",
        commands=[
            "python -m src.run --output-dir tmp/2024-W45 "
            "--output tmp/result.json"
        ],
    )])

    GreenfieldEngine._normalize_slice_plans(run, contract, _PlanRecorder())

    expected = run.slices[0].expected_files
    assert "src/run.py" in expected
    assert "tests/test_run.py" in expected
    assert not any(value.startswith("tmp/") for value in expected)
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


def test_broad_test_command_detection_keeps_focused_tests():
    assert GreenfieldEngine._is_broad_test_command("pytest -q")
    assert GreenfieldEngine._is_broad_test_command("python -m pytest tests/ -q")
    assert not GreenfieldEngine._is_broad_test_command(
        "python -m pytest tests/test_run.py -q"
    )


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
        id="run", project_name="demo", requirement="demo",
        workspace=str(tmp_path),
    )
    contract = AcceptanceContract([AcceptanceItem(
        id="AC1", priority="P0", behavior="integration",
        commands=["pytest tests/test_integration.py -q"],
    )])
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


def test_recorder_restores_failed_wip_and_logs_safe_progress(tmp_path):
    run = GreenfieldRun(
        id="run", project_name="demo", requirement="demo",
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
    recorder.engineer_event({
        "type": "tool_requested",
        "payload": {"tool_name": "file_write", "tool_args": {
            "path": "src/app.py", "content": "SECRET-CONTENT"
        }},
    })
    recorder.engineer_event({
        "type": "model_message",
        "payload": {"content": "将实现入口、配置加载和集成测试。"},
    })
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
