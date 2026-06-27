"""Project context -- auto-generated overview of the codebase for agent injection."""
from __future__ import annotations

from pathlib import Path


def generate_project_context(source_path: str, workspace: Path,
                             llm_adapter=None) -> str:
    """Generate a project context overview using LLM analysis."""
    sp = Path(source_path)
    py_files = list(sp.rglob("*.py"))
    ts_files = list(sp.rglob("*.ts")) + list(sp.rglob("*.tsx"))
    has_pyproject = (sp / "pyproject.toml").exists()
    has_package_json = (sp / "package.json").exists()
    has_docker = (sp / "Dockerfile").exists() or (sp / "docker-compose.yml").exists()

    top_dirs = sorted(set(
        p.relative_to(sp).parts[0] for p in sp.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and p.name not in ("node_modules", "__pycache__", ".git")
    ))

    setup_files = []
    for pat in ["main.py", "app.py", "index.ts", "index.tsx", "cli.py"]:
        found = list(sp.rglob(pat))
        setup_files.extend(str(f.relative_to(sp)) for f in found[:3])

    if llm_adapter:
        prompt = (
            f"分析以下项目信息，生成一份简洁的项目概述。\n\n"
            f"源路径: {source_path}\n"
            f"Python 文件: {len(py_files)} 个\n"
            f"TypeScript 文件: {len(ts_files)} 个\n"
            f"顶层目录: {', '.join(top_dirs[:10])}\n"
            f"入口文件: {', '.join(setup_files[:10])}\n"
            f"有 pyproject.toml: {has_pyproject}\n"
            f"有 package.json: {has_package_json}\n"
            f"有 Docker: {has_docker}\n\n"
            f"输出 Markdown 格式的项目概述，包含:\n"
            f"1. Tech Stack\n"
            f"2. Directory Structure\n"
            f"3. Code Conventions\n"
            f"4. Key Patterns"
        )
        try:
            response = llm_adapter.invoke(
                system_prompt="你是一位项目分析专家。根据项目结构推断技术栈和编码规范。",
                user_prompt=prompt, stage_name="project_context",
            )
            path = workspace / "project_context.md"
            path.write_text(response)
            return response
        except Exception:
            pass
    return _fallback_context(source_path, py_files, ts_files, top_dirs,
                             setup_files, has_pyproject, has_package_json,
                             has_docker)


def _fallback_context(source_path: str, py_files: list, ts_files: list,
                      top_dirs: list, setup_files: list, has_pyproject: bool,
                      has_package_json: bool, has_docker: bool) -> str:
    lines = [
        f"# Project Context",
        f"Source: {source_path}",
        f"Python files: {len(py_files)}",
        f"TypeScript files: {len(ts_files)}",
        f"Top directories: {', '.join(top_dirs[:10])}",
    ]
    if has_pyproject:
        lines.append("Has pyproject.toml")
    if has_package_json:
        lines.append("Has package.json")
    if has_docker:
        lines.append("Has Docker config")
    return "\n".join(lines)


def load_project_context(workspace: Path, source_path: str = "") -> str:
    """Load saved project context."""
    path = workspace / "project_context.md"
    if path.exists():
        return path.read_text()
    if source_path:
        ctx = _fallback_context(source_path, [], [], [], [], False, False, False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ctx)
        return ctx
    return ""


def merge_manual_context(source_path: str, auto_context: str) -> str:
    """Merge CLAUDE.md or ONEP.md content into project context."""
    sp = Path(source_path)
    for name in ("CLAUDE.md", "ONEP.md", "AGENTS.md"):
        p = sp / name
        if p.exists():
            manual = p.read_text()[:3000]
            return auto_context + f"\n\n## Manual Context ({name})\n\n{manual}"
    return auto_context
