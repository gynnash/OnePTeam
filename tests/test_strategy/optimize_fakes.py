from pathlib import Path
from types import SimpleNamespace

from onep.llm.adapters import TokenUsage
from onep.strategy.models import StrategyItem
from onep.strategy.optimize_models import PlanRecord, PlanStatus


class FakeLLM:
    last_usage = TokenUsage()


class FakeGitSession:
    instances = []

    def __init__(self, source, run_dir, run_id):
        self.source = Path(source)
        self.run_dir = Path(run_dir)
        self.integration_worktree = self.source / "integration-view"
        self.integration_worktree.mkdir(exist_ok=True)
        self.base_commit = "base"
        self.base_branch = "main"
        self.integration_commit = "integrated"
        self.instances.append(self)

    def create_integration_branch(self):
        return "onep/integration"

    def create_plan_group(self, candidates):
        return {
            candidate.id: SimpleNamespace(
                branch_name=f"onep/{candidate.id}",
                base_commit="base",
                worktree=self.integration_worktree,
            )
            for candidate in candidates
        }

    def cleanup(self):
        pass


class FakeRecorder:
    instances = []

    def __init__(self, run_dir, run):
        self.run = run
        self.events = []
        self.plans = []
        self.instances.append(self)

    def record_event(self, kind, payload):
        self.events.append((kind, payload))

    def save_plan(self, plan, text):
        self.plans.append(plan)
        self.run.plans = [
            current for current in self.run.plans
            if current.candidate.id != plan.candidate.id
        ] + [plan]

    def save_state(self):
        pass

    def save_report(self, report):
        self.report = report


class FakeCoordinator:
    executed = []

    def __init__(self, *args, **kwargs):
        pass

    def develop_plan(self, candidate, plan_text, session):
        self.executed.append(candidate.id)
        return PlanRecord(candidate, status=PlanStatus.COMMITTED)

    def integrate_plan(self, record, session, commands):
        record.status = PlanStatus.INTEGRATED
        return record


def install_fake_optimize_services(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    import git

    repo = git.Repo.init(source)
    with repo.config_writer() as config:
        config.set_value("user", "name", "test")
        config.set_value("user", "email", "test@example.com")
    (source / "app.py").write_text("value = 1\n")
    repo.index.add(["app.py"])
    repo.index.commit("initial")

    root = tmp_path / "onep-home"
    config = SimpleNamespace(
        project=SimpleNamespace(root_dir=str(root)),
        pipeline=SimpleNamespace(test_timeout=5),
    )
    FakeGitSession.instances.clear()
    FakeRecorder.instances.clear()
    FakeCoordinator.executed.clear()
    generated = []
    analyzed_paths = []

    def analyze(path, llm, tracker, project_name=""):
        analyzed_paths.append(Path(path))
        return [
            StrategyItem(
                id="si-1",
                title="Cache",
                file_location="app.py:1",
                summary="cache issue",
                tags=["cache"],
                impact="medium",
            )
        ]

    def generate(item, workspace, **kwargs):
        generated.append(item.id)
        path = Path(workspace) / "plan.md"
        path.write_text("# plan")
        return SimpleNamespace(
            plan_path=str(path),
            plan_markdown="# plan",
            expected_files=("app.py",),
            dependencies=(),
            test_commands=("pytest",),
            risk_flags=(),
        )

    monkeypatch.setattr("onep.cli.optimize_cmd.load_config", lambda: config)
    monkeypatch.setattr("onep.cli.optimize_cmd.init_db", lambda: None)
    monkeypatch.setattr("onep.cli.optimize_cmd.insert_project", lambda project: None)
    monkeypatch.setattr("onep.cli.optimize_cmd.LLMAdapter", FakeLLM)
    monkeypatch.setattr("onep.cli.optimize_cmd.GitRunSession", FakeGitSession)
    monkeypatch.setattr("onep.cli.optimize_cmd.OptimizeRunRecorder", FakeRecorder)
    monkeypatch.setattr("onep.cli.optimize_cmd.OptimizeCoordinator", FakeCoordinator)
    monkeypatch.setattr("onep.cli.optimize_cmd._analyze", analyze)
    monkeypatch.setattr("onep.cli.optimize_cmd.generate_optimize_plan", generate)
    monkeypatch.setattr("onep.cli.optimize_cmd._memory_context", lambda *a: "")
    monkeypatch.setattr("onep.cli.optimize_cmd.load_project_context", lambda *a: "")
    return SimpleNamespace(
        source=source,
        generated=generated,
        analyzed_paths=analyzed_paths,
        coordinator=FakeCoordinator,
        recorder=FakeRecorder,
        git=FakeGitSession,
    )
