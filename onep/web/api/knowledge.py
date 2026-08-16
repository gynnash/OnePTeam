"""REST endpoints for the knowledge vault and articles."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from onep.web import knowledge as knowledge_views
from onep.web.api.projects import _project_by_name

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _workspace(project: str) -> Path:
    """Project workspace; the global vault root does not depend on any
    workspace, so global-vault requests may omit `project`."""
    if not project:
        raise HTTPException(status_code=400, detail="project is required")
    return Path(_project_by_name(project).workspace_path)


def _workspace_for_vault(project: str, vault: str) -> Path:
    if vault == "project":
        return _workspace(project)
    # The global vault root ignores the workspace entirely.
    return Path(project).expanduser() if project else Path.home()


@router.get("/notes")
def notes_list(
    project: str = "",
    vault: str = Query("project", pattern="^(project|global)$"),
):
    return {"notes": knowledge_views.list_notes(
        _workspace_for_vault(project, vault), vault)}


@router.get("/notes/content")
def note_content(
    project: str = "",
    vault: str = Query("project", pattern="^(project|global)$"),
    path: str = Query("", max_length=1024),
):
    note = knowledge_views.note_reader(
        _workspace_for_vault(project, vault), vault, path)
    if note is None:
        raise HTTPException(status_code=404, detail=f"note not found: {path}")
    return note


@router.get("/graph")
def graph(project: str = ""):
    return knowledge_views.reasoning_graph(_workspace(project))


@router.get("/articles")
def articles_list():
    return {"articles": knowledge_views.list_articles()}


@router.get("/articles/{slug}")
def article_detail(slug: str):
    content = knowledge_views.article_content(slug)
    if content is None:
        raise HTTPException(status_code=404, detail=f"article not found: {slug}")
    return content
