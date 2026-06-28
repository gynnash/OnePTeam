import json

from onep.strategy.reporting import AnalysisReport, AnalysisReportService


def test_report_renders_counts_parameters_and_cost(tmp_path):
    report = AnalysisReport(
        project_name="demo",
        source_path="/repo",
        scanned_files=100,
        strategy_files=7,
        items=[{"title": "Cache", "impact": "high", "file_location": "a.py:1",
                "tags": ["cache"], "summary": "missing eviction"}],
        parameters={"mode": "strategy"},
        total_cost=1.25,
    )
    service = AnalysisReportService()
    content = service.render(report, "md")
    assert "扫描文件: 100" in content
    assert "策略密集文件: 7" in content
    assert "成本: $1.25" in content
    output = service.write(report, tmp_path / "report.json")
    assert json.loads(output.read_text())["project_name"] == "demo"


def test_report_rejects_path_outside_workspace(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="路径超出"):
        AnalysisReportService().safe_output_path(tmp_path, "../outside.md")
