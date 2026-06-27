import json
from pathlib import Path
from click.testing import CliRunner
from onep.cli.export_cmd import export_group


def test_export_json(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "analysis_items.jsonl").write_text(
        json.dumps({"title":"test","file_location":"f.py:1","tags":["perf"],
                     "impact":"high","summary":"test issue"}, ensure_ascii=False) + "\n"
    )
    (ws / "workbench.yaml").write_text(
        "project_name: test\nsource_path: /tmp/src\nscan_complete: true\n"
        "analysis_complete: true\nitems: []\n"
    )

    # Mock list_projects to return a fake project pointing to our ws
    from onep.persistence import models
    fake_project = models.Project(
        name="test", mode=models.ProjectMode.BROWNFIELD,
        workspace_path=str(ws),
    )

    def mock_list():
        return [fake_project]
    monkeypatch.setattr("onep.cli.export_cmd.list_projects", mock_list)

    runner = CliRunner()
    out = tmp_path / "report.md"
    result = runner.invoke(export_group, ["test", "--output", str(out)])
    assert result.exit_code == 0
    content = out.read_text()
    assert "# 策略分析报告: test" in content
    assert "test issue" in content


def test_export_json_format(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "analysis_items.jsonl").write_text(
        json.dumps({"title":"test","file_location":"f.py:1","tags":["perf"],
                     "impact":"high","summary":"test issue"}, ensure_ascii=False) + "\n"
    )
    (ws / "workbench.yaml").write_text(
        "project_name: test\nsource_path: /tmp/src\nscan_complete: true\n"
        "analysis_complete: true\nitems: []\n"
    )

    from onep.persistence import models
    fake_project = models.Project(
        name="test", mode=models.ProjectMode.BROWNFIELD,
        workspace_path=str(ws),
    )
    monkeypatch.setattr("onep.cli.export_cmd.list_projects", lambda: [fake_project])

    runner = CliRunner()
    out = tmp_path / "report.json"
    result = runner.invoke(export_group, ["test", "--output", str(out), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert data["project"] == "test"
    assert len(data["items"]) == 1
