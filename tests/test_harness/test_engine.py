# tests/test_harness/test_engine.py
from pathlib import Path

import git

from onep.greenfield.models import GreenfieldOptions
from onep.harness.engine import HarnessEngine
from onep.harness.models import HarnessOptions, StopReason
from onep.harness.persistence import load_harness_run
from onep.llm.adapters import TokenUsage
from onep.persistence.models import Project, ProjectMode
from onep.strategy.optimize_engine import EngineAttemptResult


class FakeLLM:
    def __init__(self):
        self.last_usage = TokenUsage()
        self.brainstorm_calls = 0

    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "greenfield_engineer":
            return """{
              "acceptance": [{"id":"REQ-1","priority":"P0","behavior":"value is one",
                              "verification":{"commands":["pytest -q"],"evidence":[]}}],
              "architecture": {"selected":"Python","rationale":"minimal"},
              "slices": [{"id":"core","title":"Core","objective":"set value",
                          "acceptance_ids":["REQ-1"],
                          "expected_files":["app.py","test_app.py"],
                          "focused_commands":[]}]
            }"""
        if stage_name == "harness_brainstorm":
            self.brainstorm_calls += 1
            return '{"candidates": []}'
        return '{"passed":true,"blocking_issues":[],"summary":"ok"}'


class IteratingLLM(FakeLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_brainstorm":
            self.brainstorm_calls += 1
            if self.brainstorm_calls == 1:
                return ('{"candidates": [{"id": "I-001", "title": "Add CLI", '
                        '"description": "Expose VALUE via a CLI command"}]}')
            return '{"candidates": []}'
        return super().invoke(system_prompt, user_prompt, stage_name)


class WritingOptimizer:
    """Writes a passing implementation on the first attempt."""

    def __init__(self):
        self.calls = 0

    def execute_attempt(self, item, source_path, workspace, llm, **kwargs):
        self.calls += 1
        root = Path(source_path)
        (root / "app.py").write_text(f"VALUE = {self.calls}\n")
        (root / "test_app.py").write_text(
            "from app import VALUE\n\n"
            f"def test_value():\n    assert VALUE == {self.calls}\n"
        )
        return EngineAttemptResult("implemented")


def _repo(path):
    repo = git.Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.com")
    (path / "README.md").write_text("# demo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial")
    return repo


def _project(tmp_path):
    return Project("demo", ProjectMode.GREENFIELD, str(tmp_path), "build value")


def test_harness_runs_full_loop_and_stops_goals_satisfied(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FakeLLM())
    engine.kernel.optimizer = WritingOptimizer()

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run is not None
    assert run.status == "completed"
    assert run.iteration == 1
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert len(run.quality_history) == 1
    assert run.quality_history[0].hard_gates_passed is True
    assert len(run.work_items) == 1
    assert run.work_items[0].status == "completed"
    assert (tmp_path / "app.py").read_text() == "VALUE = 1\n"


def test_harness_iterates_when_brainstorm_finds_work(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    llm = IteratingLLM()
    engine = HarnessEngine(llm=llm)
    engine.kernel.optimizer = WritingOptimizer()

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.iteration == 2
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert len(run.quality_history) == 2
    integrated = [c for c in run.improvement_candidates
                  if c.status == "integrated"]
    assert [c.id for c in integrated] == ["I-001"]
    assert any(w.id == "iter1-1" and w.status == "completed"
               for w in run.work_items)
    assert repo.active_branch.name.startswith("onep/greenfield-")


def test_harness_stops_on_max_iteration(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    llm = IteratingLLM()
    engine = HarnessEngine(llm=llm)
    engine.kernel.optimizer = WritingOptimizer()

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=1,
            max_repairs_per_slice=2,
            test_commands=["pytest -q"],
            deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.stop_state["reason"] == StopReason.MAX_ITERATION.value
    assert run.iteration == 1


def test_harness_persists_options_on_first_run(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FakeLLM())
    engine.kernel.optimizer = WritingOptimizer()

    engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=9, test_commands=["pytest -q"], deploy_mode="none",
        ),
    )
    run = load_harness_run(tmp_path)
    assert isinstance(run.options, HarnessOptions)
    assert run.options.max_rounds == 9
    assert run.greenfield_run is not None
