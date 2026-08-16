# tests/test_harness/test_engine.py
from pathlib import Path
from types import SimpleNamespace

import git
from rich.console import Console

from onep.greenfield.models import (
    AcceptanceContract,
    GreenfieldOptions,
    GreenfieldRun,
    SlicePlan,
)
from onep.greenfield.recorder import GreenfieldRecorder
from onep.harness.engine import HarnessEngine
from onep.harness.models import HarnessOptions, StopReason
from onep.harness.persistence import load_harness_run, stop_requested
from onep.llm.adapters import TokenUsage
from onep.persistence.models import Project, ProjectMode, ProjectStatus
from onep.persistence.state import load_state, save_state
from onep.strategy.optimize_engine import EngineAttemptResult
from onep.strategy.optimize_models import PlanRecord, PlanStatus


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


def test_run_pipeline_routes_through_harness(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.orchestrator.runner.init_db", lambda: None
    )
    monkeypatch.setattr(
        "onep.orchestrator.runner.list_projects",
        lambda: [_project(tmp_path)],
    )

    calls = []

    class _RecordingHarness:
        def __init__(self, console=None):
            self.console = console

        def run(self, project, options=None):
            calls.append((project.name, options))
            return True

    monkeypatch.setattr(
        "onep.orchestrator.runner.HarnessEngine", _RecordingHarness
    )
    from onep.orchestrator.runner import run_pipeline
    from onep.greenfield.models import GreenfieldOptions

    options = GreenfieldOptions(test_commands=["pytest -q"])
    assert run_pipeline("demo", options=options) is True
    assert calls[0][0] == "demo"
    assert calls[0][1] is options


def test_user_stop_flag_cleared_on_resume_transition(tmp_path, monkeypatch):
    """Important 1: the stop flag must not wedge the next resume.

    A stop request left behind after a user_stop break must be cleared
    whenever a run transitions to running; otherwise every subsequent
    `onep run` stops again at PLAN and never resumes.
    """
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FakeLLM())
    engine.kernel.optimizer = WritingOptimizer()
    options = GreenfieldOptions(
        max_rounds=4, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    )

    assert engine.run(_project(tmp_path), options) is True

    # Simulate a stop request that was left in place after a user_stop break.
    flag = tmp_path / ".onep" / "harness" / "stop_requested"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()
    assert stop_requested(tmp_path) is True

    # Resuming must clear the stale flag instead of stopping again.
    assert engine.run(_project(tmp_path), options) is True
    assert stop_requested(tmp_path) is False


def test_harness_adopts_legacy_greenfield_run(tmp_path, monkeypatch):
    """Important 2: a kernel-era in-flight run is adopted on upgrade.

    Projects created before the harness lands persist their greenfield
    run id in state.yaml artifacts; the harness must resume that run
    (with its committed branch work) instead of restarting discovery.
    """
    repo = _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FakeLLM())
    engine.kernel.optimizer = WritingOptimizer()
    options = GreenfieldOptions(
        max_rounds=4, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    )

    base_branch = repo.active_branch.name
    base_commit = repo.head.commit.hexsha
    legacy_branch = "onep/greenfield-legacy-001"
    repo.git.checkout("-b", legacy_branch)
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    (tmp_path / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_value():\n    assert VALUE == 1\n"
    )
    repo.index.add(["app.py", "test_app.py"])
    repo.index.commit("feat: legacy slice core")
    repo.git.checkout(base_branch)

    legacy = GreenfieldRun(
        id="legacy-001",
        project_name="demo",
        requirement="build value",
        workspace=str(tmp_path),
        options=options,
        base_branch=base_branch,
        base_commit=base_commit,
        run_branch=legacy_branch,
    )
    legacy.slices = [SlicePlan(
        id="core", title="Core", objective="set value",
        acceptance_ids=["REQ-1"],
        expected_files=["app.py", "test_app.py"],
        focused_commands=[],
    )]
    run_dir = tmp_path / ".onep" / "greenfield" / "runs" / legacy.id
    recorder = GreenfieldRecorder(run_dir, legacy, Console())
    recorder.save_run()
    recorder.save_slice(legacy.slices[0])
    recorder.save_contract(AcceptanceContract.from_dict({
        "requirements": [{
            "id": "REQ-1", "priority": "P0", "behavior": "value is one",
            "verification": {"commands": ["pytest -q"], "evidence": []},
        }],
    }))
    state = load_state(tmp_path)
    state.artifacts["greenfield_run_id"] = legacy.id
    save_state(tmp_path, state)

    assert engine.run(_project(tmp_path), options) is True
    run = load_harness_run(tmp_path)
    assert run.greenfield_run is not None
    assert run.greenfield_run.id == "legacy-001"
    assert run.greenfield_run.run_branch == legacy_branch


def test_user_stop_skips_finalize_tail_and_pauses(tmp_path, monkeypatch):
    """Minor 3: a user_stop with an unsatisfied contract must not run the
    finalize tail (which would fail the gates and mark the project FAILED)."""
    _repo(tmp_path)
    seen_projects = []
    monkeypatch.setattr("onep.harness.engine.update_project", seen_projects.append)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    flag = tmp_path / ".onep" / "harness" / "stop_requested"

    class StopDuringUnderstand(FakeLLM):
        """Sets the stop flag while the run is in flight (during UNDERSTAND)."""

        def __init__(self, flag_path):
            super().__init__()
            self.flag_path = Path(flag_path)
            self.requested = False

        def invoke(self, system_prompt, user_prompt, stage_name):
            if not self.requested:
                self.requested = True
                self.flag_path.parent.mkdir(parents=True, exist_ok=True)
                self.flag_path.touch()
            return super().invoke(system_prompt, user_prompt, stage_name)

    engine = HarnessEngine(llm=StopDuringUnderstand(flag))
    engine.kernel.optimizer = WritingOptimizer()

    def _must_not_run(name):
        def _inner(*args, **kwargs):
            raise AssertionError(f"{name} must not run after a user stop")
        return _inner

    monkeypatch.setattr(
        engine.kernel, "_final_verify", _must_not_run("_final_verify")
    )
    monkeypatch.setattr(
        engine.kernel, "_commit_completion_docs",
        _must_not_run("_commit_completion_docs"),
    )

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.status == "stopped"
    assert run.stop_state["reason"] == "user_stop"
    assert any(p.status == ProjectStatus.PAUSED for p in seen_projects)
    assert not any(p.status == ProjectStatus.FAILED for p in seen_projects)


def test_harness_resume_runs_sanitize_and_design_docs(tmp_path, monkeypatch):
    """Minor 4: the resume path must re-run sanitize/normalize/design-docs
    exactly like the first-run path, so the persisted plan stays consistent."""
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FakeLLM())
    engine.kernel.optimizer = WritingOptimizer()
    options = GreenfieldOptions(
        max_rounds=4, max_repairs_per_slice=2,
        test_commands=["pytest -q"], deploy_mode="none",
    )

    assert engine.run(_project(tmp_path), options) is True
    run = load_harness_run(tmp_path)
    assert run.greenfield_run is not None and run.greenfield_run.slices

    calls = []
    monkeypatch.setattr(
        engine.kernel, "_sanitize_generated_commands",
        lambda *a, **k: calls.append("sanitize"),
    )
    monkeypatch.setattr(
        engine.kernel, "_write_design_docs",
        lambda *a, **k: calls.append("design"),
    )

    # Resume: slices already exist, so the resume branch must still run
    # the plan-consistency steps.
    assert engine.run(_project(tmp_path), options) is True
    assert calls == ["sanitize", "design"]


class ResearchLLM(FakeLLM):
    """P1 loop plus a full research stage producing evidence."""

    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_researcher":
            return ('{"questions": ["cli patterns"]}'
                    if "questions" in user_prompt or "Produce focused" in user_prompt
                    else '{"cards": [{"repo": "cli/repo", "pattern": "builder", '
                         '"module_boundaries": ["parse"], "data_flow": "in->out", '
                         '"evidence_files": ["src/parse.py"], '
                         '"strengths": ["clean"], "weaknesses": ["slow"]}], '
                         '"evidence": [{"claim": "builders win", '
                         '"source_repos": ["cli/repo"], "detail": "fits"}], '
                         '"tradeoffs": []}')
        if stage_name == "harness_architect":
            return ('{"architecture": {"selected": "builder-with-citations", '
                    '"rationale": "evidence"}, "evidence_citations": ['
                    '{"claim": "builders win", "source_repo": "cli/repo", '
                    '"detail": "adopt"}]}')
        return super().invoke(system_prompt, user_prompt, stage_name)


class StubClient:
    def __init__(self):
        self.searches = []

    def search_repos(self, query, max_results=10):
        self.searches.append(query)
        from onep.harness.github_client import RepoInfo
        return [RepoInfo(full_name="cli/repo", stargazers_count=900,
                         pushed_at="2026-06-01T00:00:00Z")]

    def filter_repos(self, repos, max_repos=3, min_stars=100, max_age_days=730):
        return repos[:max_repos]

    def fetch_readme(self, full_name, max_chars=8000):
        return "# cli repo\n"

    def fetch_top_tree(self, full_name, max_entries=30):
        return ["src", "README.md"]


def test_harness_research_evidence_reaches_architecture_doc(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    llm = ResearchLLM()
    client = StubClient()
    engine = HarnessEngine(llm=llm)
    engine.kernel.optimizer = WritingOptimizer()
    monkeypatch.setattr(engine.research, "client", client)

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    )
    assert success is True
    run = load_harness_run(tmp_path)
    reports = run.research_reports
    assert reports and reports[0]["mode"] == "full"
    assert reports[0]["evidence"][0]["source_repos"] == ["cli/repo"]
    architecture_md = (tmp_path / "docs" / "ARCHITECTURE.md").read_text()
    assert "evidence_citations" in architecture_md
    assert "cli/repo" in architecture_md
    assert client.searches == ["cli patterns"]


def _brownfield_project(tmp_path):
    return Project("demo", ProjectMode.BROWNFIELD, str(tmp_path), "")


class BrownfieldFakeLLM(FakeLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_brainstorm":
            return '{"candidates": []}'
        return super().invoke(system_prompt, user_prompt, stage_name)


class BrownfieldCoordinator:
    executed = []

    def __init__(self, engine, test_runner, reviewer, git_session,
                 llm=None, recorder=None, cost_tracker=None,
                 project_context="", **kwargs):
        pass

    def develop_plan(self, candidate, plan_text, session):
        self.executed.append(candidate.id)
        record = PlanRecord(candidate, status=PlanStatus.COMMITTED)
        record.commit_sha = "beef42"
        return record

    def integrate_plan(self, record, session, commands):
        record.status = PlanStatus.INTEGRATED
        return record


class BrownfieldSession:
    def __init__(self, source_path, run_dir, run_id):
        self.source_path = source_path
        self.branches = []

    def create_integration_branch(self):
        self.branches.append("integration")
        return "integration"

    def create_plan_session(self, plan_id, title):
        self.branches.append(plan_id)
        return SimpleNamespace(
            branch_name=f"plan-{plan_id}", worktree=self.source_path,
            base_commit="c0ffee",
        )


def test_harness_brownfield_loop_scans_builds_and_stops(tmp_path, monkeypatch):
    from onep.strategy.models import StrategyItem

    repo = _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "app.py").write_text("value = 1\n")
    repo.index.add(["pyproject.toml", "app.py"])
    repo.index.commit("source")

    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source",
        lambda source, llm, tracker=None, project_name="", source_files=None,
        **kwargs: [StrategyItem(
            id="si-1", title="Cache", file_location="app.py:1",
            summary="cache issue", tags=["cache"], impact="medium",
        )],
    )
    monkeypatch.setattr(
        "onep.harness.engine.generate_optimize_plan",
        lambda item, workspace, llm_adapter, plan_index=1, memory_context="":
        SimpleNamespace(
            plan_path=str(Path(workspace) / "plan.md"),
            plan_markdown="# plan",
            expected_files=("app.py",),
            dependencies=(),
            test_commands=("pytest -q",),
            risk_flags=(),
        ),
    )
    monkeypatch.setattr(
        "onep.harness.brownfield.GitRunSession", BrownfieldSession)
    BrownfieldCoordinator.executed.clear()
    monkeypatch.setattr(
        "onep.harness.brownfield.OptimizeCoordinator",
        BrownfieldCoordinator,
    )
    # The scope gate / integration runner is bypassed by the fake
    # coordinator; integration commands resolve from the manifest.
    engine = HarnessEngine(llm=BrownfieldFakeLLM())

    success = engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, test_commands=["pytest -q"], deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.mode == "brownfield"
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert run.iteration == 1
    assert [item.id for item in run.work_items] == ["si-1"]
    assert all(item.status == "completed" for item in run.work_items)
    assert len(run.quality_history) == 1
    assert run.quality_history[0].hard_gates_passed is True
    assert BrownfieldCoordinator.executed == ["si-1"]


def test_harness_brownfield_empty_scan_stops_immediately(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("source")

    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source",
        lambda *args, **kwargs: [],
    )
    engine = HarnessEngine(llm=BrownfieldFakeLLM())

    success = engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, test_commands=["pytest -q"], deploy_mode="none",
        ),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert run.work_items == []
    assert run.iteration == 0


def test_harness_brownfield_clears_stale_stop_flag(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("source")
    flag = tmp_path / ".onep" / "harness" / "stop_requested"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()

    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source", lambda *args, **kwargs: [])

    engine = HarnessEngine(llm=BrownfieldFakeLLM())
    assert engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(max_rounds=4, test_commands=["pytest -q"],
                          deploy_mode="none"),
    ) is True
    assert stop_requested(tmp_path) is False
    run = load_harness_run(tmp_path)
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value


def test_harness_brownfield_empty_workspace_falls_back_to_greenfield(tmp_path, monkeypatch):
    _repo(tmp_path)  # README-only repo: no code files
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source", lambda *args, **kwargs: [])
    engine = HarnessEngine(llm=BrownfieldFakeLLM())
    engine.kernel.optimizer = WritingOptimizer()
    assert engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(max_rounds=4, test_commands=["pytest -q"],
                          deploy_mode="none"),
    ) is True
    run = load_harness_run(tmp_path)
    assert run.mode == "greenfield"


def test_harness_brownfield_parks_candidate_when_plan_generation_fails(tmp_path, monkeypatch):
    """A planner failure mid-backlog must park the candidate without
    leaving it marked integrated (no orphan work item, run still completes)."""
    from onep.strategy.models import StrategyItem

    repo = _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "app.py").write_text("value = 1\n")
    repo.index.add(["pyproject.toml", "app.py"])
    repo.index.commit("source")

    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source",
        lambda source, llm, tracker=None, project_name="", source_files=None,
        **kwargs: [StrategyItem(
            id="si-1", title="Cache", file_location="app.py:1",
            summary="cache issue", tags=["cache"], impact="medium",
        )],
    )
    calls = {"n": 0}

    def flaky_planner(item, workspace, llm_adapter, plan_index=1,
                      memory_context=""):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(
                plan_path=str(Path(workspace) / "plan.md"),
                plan_markdown="# plan", expected_files=("app.py",),
                dependencies=(), test_commands=("pytest -q",),
                risk_flags=(),
            )
        raise RuntimeError("planner boom")

    monkeypatch.setattr(
        "onep.harness.engine.generate_optimize_plan", flaky_planner)
    monkeypatch.setattr(
        "onep.harness.brownfield.GitRunSession", BrownfieldSession)
    BrownfieldCoordinator.executed.clear()
    monkeypatch.setattr(
        "onep.harness.brownfield.OptimizeCoordinator", BrownfieldCoordinator)

    class BrainstormOnceBrownfieldLLM(BrownfieldFakeLLM):
        def invoke(self, system_prompt, user_prompt, stage_name):
            if stage_name == "harness_brainstorm":
                if not getattr(self, "gave_candidate", False):
                    self.gave_candidate = True
                    return ('{"candidates": [{"id": "B-001", '
                            '"title": "Add CLI", "description": '
                            '"Expose VALUE via a CLI command"}]}')
                return '{"candidates": []}'
            return super().invoke(system_prompt, user_prompt, stage_name)

    engine = HarnessEngine(llm=BrainstormOnceBrownfieldLLM())
    success = engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(max_rounds=4, test_commands=["pytest -q"],
                          deploy_mode="none"),
    )

    assert success is True
    run = load_harness_run(tmp_path)
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert run.iteration == 2
    parked = [c for c in run.improvement_candidates
              if c.status == "parked"]
    assert [c.id for c in parked] == ["B-001"]
    assert not any(w.id == "iter1-1" for w in run.work_items)


def test_harness_in_loop_design_docs_are_committed(tmp_path, monkeypatch):
    """Evidence-bearing round >= 2 must not leave the tree dirty:
    pause/resume requires a clean session (GreenfieldGitSession raises
    ValueError on dirty tracked files)."""
    from onep.greenfield.engine import DISCOVERY_PROMPT  # noqa: F401 (context)

    stop_flag = tmp_path / ".onep" / "harness" / "stop_requested"

    class IteratingResearchLLM(ResearchLLM):
        def __init__(self):
            super().__init__()
            self.brainstorm_calls = 0
            self.flagged = False

        def invoke(self, system_prompt, user_prompt, stage_name):
            if stage_name == "harness_brainstorm":
                self.brainstorm_calls += 1
                if self.brainstorm_calls == 1:
                    return ('{"candidates": [{"id": "I-001", '
                            '"title": "Add CLI", '
                            '"description": "Expose VALUE via a CLI command", '
                            '"evidence": "REQ-1 ok"}]}')
                return '{"candidates": []}'
            output = super().invoke(system_prompt, user_prompt, stage_name)
            # Request a user stop right after the first evidence-bearing
            # in-loop design round: the run pauses at the next PLAN with
            # nothing left to sweep the design docs into a later commit.
            if (
                stage_name == "harness_researcher"
                and self.brainstorm_calls >= 1
                and not self.flagged
            ):
                self.flagged = True
                stop_flag.parent.mkdir(parents=True, exist_ok=True)
                stop_flag.touch()
            return output

    repo = _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    llm = IteratingResearchLLM()
    engine = HarnessEngine(llm=llm)
    engine.kernel.optimizer = WritingOptimizer()
    monkeypatch.setattr(engine.research, "client", StubClient())

    success = engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    )
    assert success is True
    run = load_harness_run(tmp_path)
    assert run.iteration == 2
    assert run.stop_state["reason"] == StopReason.USER_STOP.value
    # Pause/resume parity: the working tree must be clean after the run.
    assert not repo.is_dirty(untracked_files=True)


class KnowledgeLLM(FakeLLM):
    """P1/P2 loop plus a distiller that emits one decision event per call."""

    def __init__(self):
        super().__init__()
        self.distill_calls = 0

    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_distiller":
            self.distill_calls += 1
            return ('{"events": [{"type": "decision", '
                    '"problem": "how to structure the module", '
                    '"options": ["flat", "nested"], "selected": "flat", '
                    '"reason": "simpler imports", '
                    '"evidence": "gate passed after attempt", '
                    '"files": ["app.py"], "outcome": "accepted", '
                    '"generalizable": true}]}')
        return super().invoke(system_prompt, user_prompt, stage_name)


def test_harness_distills_events_into_project_vault(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    llm = KnowledgeLLM()
    engine = HarnessEngine(llm=llm, vault_root=tmp_path / "global-vault")
    engine.kernel.optimizer = WritingOptimizer()

    assert engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    ) is True

    run = load_harness_run(tmp_path)
    assert run.knowledge_events
    assert run.knowledge_events[0]["type"] == "decision"
    assert llm.distill_calls >= 2
    knowledge_dir = tmp_path / ".onep" / "knowledge"
    moc = knowledge_dir / "Project.md"
    assert moc.exists()
    moc_text = moc.read_text()
    assert "## Decisions" in moc_text
    assert "[[how-to-structure-the-module]]" in moc_text
    decision_notes = list((knowledge_dir / "Decisions").glob("*.md"))
    assert decision_notes
    assert "type: decision" in decision_notes[0].read_text()


def test_harness_brownfield_records_per_candidate_events(tmp_path, monkeypatch):
    from onep.strategy.models import StrategyItem
    from onep.harness.knowledge_models import load_run_events

    repo = _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    (tmp_path / "app.py").write_text("value = 1\n")
    repo.index.add(["pyproject.toml", "app.py"])
    repo.index.commit("baseline")
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source",
        lambda source, llm, tracker=None, project_name="", source_files=None,
        **kwargs: [StrategyItem(
            id="si-1", title="Cache", file_location="app.py:1",
            summary="cache issue", tags=["cache"], impact="medium",
        )],
    )
    monkeypatch.setattr(
        "onep.harness.engine.generate_optimize_plan",
        lambda item, workspace, llm_adapter, plan_index=1, memory_context="":
        SimpleNamespace(
            plan_path=str(Path(workspace) / "plans" / "plan-1.md"),
            plan_markdown="# plan 1",
            expected_files=("app.py",),
            dependencies=(),
            test_commands=("pytest -q",),
            risk_flags=(),
        ),
    )
    monkeypatch.setattr(
        "onep.harness.brownfield.GitRunSession", BrownfieldSession)
    received = []

    class RecordingCoordinator(BrownfieldCoordinator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            received.append(kwargs.get("recorder"))

    monkeypatch.setattr(
        "onep.harness.brownfield.OptimizeCoordinator", RecordingCoordinator)

    engine = HarnessEngine(
        llm=BrownfieldFakeLLM(), vault_root=tmp_path / "vault")
    assert engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, test_commands=["pytest -q"], deploy_mode="none",
        ),
    ) is True

    assert received and received[0] is not None
    run = load_harness_run(tmp_path)
    run_dir = tmp_path / ".onep" / "optimize" / "runs" / run.id
    assert (run_dir / "run.yaml").exists()
    event_types = [event["type"] for event in load_run_events(run_dir)]
    assert "harness_run_started" in event_types
    assert "round_end" in event_types
    assert "harness_run_completed" in event_types


class FailingDistillerLLM(FakeLLM):
    """P1/P2 loop whose distiller stage always raises."""

    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_distiller":
            raise RuntimeError("distill boom")
        return super().invoke(system_prompt, user_prompt, stage_name)


def test_harness_distill_failure_does_not_break_run(tmp_path, monkeypatch):
    """A failing distiller must not break the build loop or finalize tail."""
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(llm=FailingDistillerLLM())
    engine.kernel.optimizer = WritingOptimizer()

    assert engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    ) is True

    run = load_harness_run(tmp_path)
    assert run.status == "completed"
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert run.knowledge_events == []


def test_harness_brownfield_zero_items_records_completed_event(tmp_path, monkeypatch):
    """P2 empty-scan exit records a harness_run_completed event."""
    from onep.harness.knowledge_models import load_run_events

    repo = _repo(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("source")

    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    monkeypatch.setattr(
        "onep.harness.engine.analyze_source", lambda *args, **kwargs: [])
    engine = HarnessEngine(llm=BrownfieldFakeLLM())

    assert engine.run(
        _brownfield_project(tmp_path),
        GreenfieldOptions(max_rounds=4, test_commands=["pytest -q"],
                          deploy_mode="none"),
    ) is True
    run = load_harness_run(tmp_path)
    assert run.stop_state["reason"] == StopReason.GOALS_SATISFIED.value
    assert run.iteration == 0
    run_dir = tmp_path / ".onep" / "optimize" / "runs" / run.id
    event_types = [event["type"] for event in load_run_events(run_dir)]
    assert "harness_run_completed" in event_types


class KnowledgeLLMWithCross(KnowledgeLLM):
    def invoke(self, system_prompt, user_prompt, stage_name):
        if stage_name == "harness_cross_distiller":
            return ('{"principles": [{"title": "Delay Abstraction", '
                    '"summary": "Wait for the second consumer.", '
                    '"tags": ["design"]}], "patterns": []}')
        return super().invoke(system_prompt, user_prompt, stage_name)


def test_harness_cross_distills_generalizable_insights(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("onep.harness.engine.update_project", lambda p: None)
    monkeypatch.setattr("onep.greenfield.engine.update_project", lambda p: None)
    engine = HarnessEngine(
        llm=KnowledgeLLMWithCross(), vault_root=tmp_path / "global-vault")
    engine.kernel.optimizer = WritingOptimizer()
    assert engine.run(
        _project(tmp_path),
        GreenfieldOptions(
            max_rounds=4, max_repairs_per_slice=2,
            test_commands=["pytest -q"], deploy_mode="none",
        ),
    ) is True
    principle = (tmp_path / "global-vault" / "Engineering"
                 / "Principles" / "delay-abstraction.md")
    assert principle.exists()
    text = principle.read_text()
    assert "type: principle" in text
    assert "## Source" in text
