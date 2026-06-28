from click.testing import CliRunner

from onep.cli.optimize_cmd import optimize_cmd
from tests.test_strategy.optimize_fakes import install_fake_optimize_services


def test_optimize_generates_plan_before_execution_and_scans_integration(
    tmp_path, monkeypatch
):
    services = install_fake_optimize_services(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        optimize_cmd,
        [str(services.source), "--max-rounds", "1", "--name", "demo"],
    )
    assert result.exit_code == 0, result.output
    assert services.generated == ["si-1"]
    assert services.coordinator.executed == ["si-1"]
    assert services.analyzed_paths == [
        services.git.instances[0].integration_worktree
    ]


def test_optimize_records_successful_plan_in_final_report(tmp_path, monkeypatch):
    services = install_fake_optimize_services(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        optimize_cmd,
        [str(services.source), "--max-rounds", "1", "--name", "demo"],
    )
    assert result.exit_code == 0
    assert "[integrated] Cache" in services.recorder.instances[0].report


def test_budget_mode_rejects_models_without_pricing(tmp_path, monkeypatch):
    from types import SimpleNamespace

    services = install_fake_optimize_services(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "onep.cli.optimize_cmd.load_config",
        lambda: SimpleNamespace(
            project=SimpleNamespace(root_dir=str(tmp_path / "home")),
            pipeline=SimpleNamespace(test_timeout=5, stage_output_tokens={}),
            llm=SimpleNamespace(pricing={}),
        ),
    )
    result = CliRunner().invoke(
        optimize_cmd,
        [str(services.source), "--max-rounds", "1",
         "--name", "demo", "--max-cost", "1"],
    )
    assert result.exit_code != 0
    assert "Missing pricing" in result.output
