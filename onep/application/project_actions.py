"""Small project read/action handlers shared by CLI, Web, and workers."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from onep.domain import Problem


ARTIFACTS = {
    "prd": ("docs/PRD.md", "Product requirements"),
    "design": ("docs/DESIGN.md", "UI/UX design"),
    "architecture": ("docs/ARCHITECTURE.md", "Architecture"),
    "test_report": ("docs/TEST_REPORT.md", "Test report"),
    "deploy_log": ("docs/DEPLOY_LOG.md", "Deployment log"),
    "readme": ("README.md", "Project README"),
}


def _project(payload, context):
    from onep.application.defaults import resolve_project

    ref = str(payload.get("project") or context.project_id).strip()
    if not ref:
        raise Problem("project_required", "Project is required")
    return resolve_project(ref)


def project_detail(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    from onep.web.state import run_detail

    run = run_detail(Path(project.workspace_path))
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "mode": project.mode.value,
            "status": project.status.value,
            "workspace_path": project.workspace_path,
            "requirement": project.requirement,
        },
        "run": run,
        "artifacts": artifact_list(payload, context)["artifacts"],
    }


def artifact_list(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path).resolve()
    return {
        "artifacts": [
            {
                "id": artifact_id,
                "title": title,
                "path": relative,
                "exists": (workspace / relative).is_file(),
            }
            for artifact_id, (relative, title) in ARTIFACTS.items()
        ]
    }


def artifact_read(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    artifact_id = str(payload.get("artifact") or "").strip()
    if artifact_id not in ARTIFACTS:
        raise Problem("artifact_not_found", "Artifact not found", artifact_id)
    relative, title = ARTIFACTS[artifact_id]
    path = Path(project.workspace_path).resolve() / relative
    if not path.is_file():
        raise Problem("artifact_not_found", "Artifact not found", relative)
    return {
        "id": artifact_id,
        "title": title,
        "path": relative,
        "content": path.read_text(encoding="utf-8"),
    }


def candidate_list(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    from onep.harness.interventions import merged_candidates
    from onep.harness.persistence import load_harness_run

    workspace = Path(project.workspace_path)
    run = load_harness_run(workspace)
    return {"candidates": merged_candidates(run, workspace) if run else []}


def candidate_decide(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    candidate_id = str(payload.get("candidate_id") or "").strip()
    decision = str(payload.get("decision") or "").strip()
    if decision not in {"approve", "reject", "rescore"}:
        raise Problem("invalid_decision", "Invalid candidate decision", decision)
    from onep.harness.interventions import record_candidate_decision

    entry = record_candidate_decision(
        Path(project.workspace_path),
        candidate_id,
        decision,
        score=payload.get("score") if decision == "rescore" else None,
        note=str(payload.get("note") or ""),
    )
    return {"decision": entry}


def article_generate(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path).resolve()
    from onep.harness.article import ArticleSynthesizer
    from onep.harness.persistence import load_harness_run, run_directory
    from onep.harness.vault import VaultWriter, global_vault_root
    from onep.llm.adapters import LLMAdapter

    run = load_harness_run(workspace)
    if run is None:
        raise Problem("run_not_found", "No autonomous run found", project.name)
    result = ArticleSynthesizer(
        LLMAdapter(), VaultWriter(global_vault_root())
    ).synthesize(workspace, run_directory(run, workspace), run)
    return {key: str(result[key]) for key in ("title", "article_path", "graph_path")}


def memory_status(_payload, _context) -> dict[str, Any]:
    from onep.memory.manager import MemoryManager

    return MemoryManager().status()


def memory_search(payload, _context) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise Problem("query_required", "Search query is required")
    from onep.memory.manager import MemoryManager

    return {
        "results": MemoryManager().search(
            query, top_k=min(max(int(payload.get("top") or 10), 1), 100)
        )
    }


def analysis_export(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path)
    from onep.strategy.persistence import load_workbench
    from onep.strategy.reporting import AnalysisReportService
    from onep.strategy.scanner import load_analysis_items

    workbench = load_workbench(workspace)
    items = load_analysis_items(workspace)
    if not items and workbench:
        items = [
            {
                "title": item.title,
                "file_location": item.file_location,
                "tags": item.tags,
                "impact": item.impact,
                "summary": item.summary,
                "plan_path": item.plan_path,
            }
            for item in workbench.items
        ]
    if not items:
        raise Problem("analysis_not_found", "No analysis results found", project.name)
    fmt = str(payload.get("format") or "md")
    if fmt not in {"md", "json"}:
        raise Problem("format_invalid", "Export format must be md or json", fmt)
    service = AnalysisReportService()
    report = service.from_items(
        project.name, workbench.source_path if workbench else "unknown", items
    )
    return {
        "filename": f"{project.name}-analysis.{fmt}",
        "content": service.render(report, fmt),
        "media_type": "application/json" if fmt == "json" else "text/markdown",
    }


def project_delete(payload, context) -> dict[str, Any]:
    project = _project(payload, context)
    workspace = Path(project.workspace_path).resolve()
    deleted_files = False
    if payload.get("delete_files"):
        from onep.config import load_config

        managed = (
            Path(load_config().project.root_dir).expanduser().resolve() / "projects"
        )
        if workspace.exists() and workspace.is_relative_to(managed):
            shutil.rmtree(workspace)
            deleted_files = True
        elif workspace.exists():
            raise Problem(
                "external_workspace_protected",
                "External workspace was not deleted",
                str(workspace),
                actionable=True,
                suggested_actions=("retry_without_delete_files",),
            )
    from onep.persistence.database import delete_project

    delete_project(project.id)
    return {"deleted": True, "deleted_files": deleted_files, "project_id": project.id}
