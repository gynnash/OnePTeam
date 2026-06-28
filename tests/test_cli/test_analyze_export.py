from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from onep.cli.analyze import analyze_cmd
from onep.strategy.reporting import AnalysisReport, AnalysisReportService


def test_analyze_passes_export_path_to_strategy_pipeline(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "report.md"
    captured = {}

    monkeypatch.setattr(
        "onep.cli.analyze.load_config",
        lambda: SimpleNamespace(project=SimpleNamespace(root_dir=str(tmp_path / "home"))),
    )
    monkeypatch.setattr("onep.cli.analyze.init_db", lambda: None)
    monkeypatch.setattr("onep.cli.analyze.insert_project", lambda project: None)

    def run(source_path, workspace, project_name, **kwargs):
        captured["export_path"] = kwargs["export_path"]
        AnalysisReportService().write(
            AnalysisReport(project_name, str(source_path)), kwargs["export_path"]
        )

    monkeypatch.setattr("onep.cli.analyze._run_strategy_mode", run)
    result = CliRunner().invoke(
        analyze_cmd,
        [str(source), "--name", "demo", "--no-dialogue", "--export", str(output)],
    )
    assert result.exit_code == 0, result.output
    assert captured["export_path"] == output
    assert output.exists()
