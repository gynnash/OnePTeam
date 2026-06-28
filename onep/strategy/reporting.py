"""Shared analysis report rendering and export."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AnalysisReport:
    project_name: str
    source_path: str
    scanned_files: int = 0
    strategy_files: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    total_cost: float = 0.0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AnalysisReportService:
    @staticmethod
    def item_dict(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item)
        return {
            "title": item.title,
            "file_location": item.file_location,
            "summary": item.summary,
            "tags": list(item.tags),
            "impact": item.impact,
            "plan_path": item.plan_path,
        }

    def from_items(
        self,
        project_name: str,
        source_path: str,
        items: list[Any],
        **kwargs,
    ) -> AnalysisReport:
        return AnalysisReport(
            project_name=project_name,
            source_path=source_path,
            items=[self.item_dict(item) for item in items],
            **kwargs,
        )

    def from_workbench(self, workbench: Any, **kwargs) -> AnalysisReport:
        return self.from_items(
            workbench.project_name,
            workbench.source_path,
            workbench.items,
            **kwargs,
        )

    def render(self, report: AnalysisReport, fmt: str = "md") -> str:
        if fmt == "json":
            data = asdict(report)
            data["project"] = report.project_name
            return json.dumps(data, ensure_ascii=False, indent=2)
        if fmt != "md":
            raise ValueError(f"unsupported report format: {fmt}")
        lines = [
            f"# 策略分析报告: {report.project_name}",
            "",
            "## 概览",
            f"- 源路径: {report.source_path}",
            f"- 扫描文件: {report.scanned_files}",
            f"- 策略密集文件: {report.strategy_files}",
            f"- 优化方向: {len(report.items)}",
            f"- 成本: ${report.total_cost:.2f}",
            "",
            "## 参数",
        ]
        lines.extend(
            f"- {key}: {value}" for key, value in sorted(report.parameters.items())
        )
        lines.extend(["", "## 优化方向", ""])
        for index, item in enumerate(report.items, 1):
            lines.extend([
                f"### {index}. [{item.get('impact', '?')}] "
                f"{item.get('title', '?')}",
                f"- 文件: {item.get('file_location', '?')}",
                f"- 标签: {', '.join(item.get('tags') or []) or '无'}",
                f"- 摘要: {item.get('summary', '')}",
                "",
            ])
        lines.extend(["## 附录", f"- 导出时间: {report.generated_at}"])
        return "\n".join(lines)

    def safe_output_path(self, workspace: Path, output: str | Path) -> Path:
        root = Path(workspace).resolve()
        path = Path(output)
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("路径超出工作区范围") from exc
        return path

    def write(
        self,
        report: AnalysisReport,
        output: Path,
        fmt: str | None = None,
    ) -> Path:
        output = Path(output)
        selected = fmt or ("json" if output.suffix.lower() == ".json" else "md")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.render(report, selected), encoding="utf-8")
        return output
