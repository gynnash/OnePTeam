"""Project creation shared by CLI and Web."""

from __future__ import annotations

from pathlib import Path
import re
import uuid

import git

from onep.domain import Problem
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import PipelineState, Project, ProjectMode
from onep.persistence.state import save_state
from onep.tools.git import GitTool


def default_project_name(requirement: str) -> str:
    clean = re.sub(r"[^\w一-鿿]", "", requirement or "")[:20]
    return clean or f"project-{uuid.uuid4().hex[:6]}"


def create_project(
    requirement: str,
    name: str | None = None,
    workspace: Path | None = None,
    options=None,
) -> Project:
    init_db()
    name = name or default_project_name(requirement)
    workspace = Path(workspace or resolve_workspace(Path.cwd())).resolve()
    try:
        repository = git.Repo(workspace)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        repository = None

    if repository is not None:
        dirty = repository.git.status("--porcelain").splitlines()
        if dirty:
            raise Problem(
                code="git_worktree_dirty",
                title="Git working tree is dirty",
                detail="Commit or stash these files first: " + ", ".join(dirty),
                actionable=True,
                suggested_actions=("open_changes", "retry_preflight"),
            )

    (workspace / "docs").mkdir(parents=True, exist_ok=True)
    readme = workspace / "README.md"
    readme_created = not readme.exists()
    if readme_created:
        readme.write_text(f"# {name}\n\n{requirement}\n", encoding="utf-8")

    git_tool = GitTool(workspace=str(workspace))
    if repository is None:
        git_tool.run(operation="init")
    repository = git.Repo(workspace)
    if not repository.head.is_valid() or readme_created:
        git_tool.run(operation="add", paths="README.md")
        git_tool.run(
            operation="commit",
            message="chore: initialize onep greenfield project",
        )
    exclude_runtime(repository)

    project = Project(
        name=name,
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace),
    )
    project.requirement = requirement
    insert_project(project)

    if options is None:
        from onep.greenfield.models import GreenfieldOptions

        options = GreenfieldOptions()
    save_state(
        workspace,
        PipelineState(artifacts={"greenfield_options": options.to_dict()}),
    )
    return project


def resolve_workspace(current_dir: Path) -> Path:
    current_dir = current_dir.resolve()
    try:
        repository = git.Repo(current_dir, search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return current_dir
    if repository.bare or repository.working_tree_dir is None:
        raise Problem(
            code="git_worktree_required",
            title="Git working tree required",
            detail="Current Git repository must have a working tree",
        )
    return Path(repository.working_tree_dir).resolve()


def exclude_runtime(repository: git.Repo) -> None:
    exclude = Path(repository.git_dir) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    content = exclude.read_text() if exclude.exists() else ""
    if ".onep/" not in content.splitlines():
        separator = "" if not content or content.endswith("\n") else "\n"
        exclude.write_text(content + separator + ".onep/\n")
