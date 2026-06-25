from pathlib import Path
from unittest import mock

from onep.config import _config_dir
from onep.persistence.database import init_db, insert_project, get_project, list_projects
from onep.persistence.models import Project, ProjectMode, ProjectStatus


@mock.patch("onep.persistence.database._config_dir")
def test_insert_and_get_project(mock_config_dir, tmp_path: Path):
    mock_config_dir.return_value = tmp_path
    init_db()

    p = Project(
        name="test-app",
        mode=ProjectMode.GREENFIELD,
        workspace_path="/tmp/ws",
    )
    insert_project(p)

    loaded = get_project(p.id)
    assert loaded is not None
    assert loaded.name == "test-app"
    assert loaded.mode == ProjectMode.GREENFIELD


@mock.patch("onep.persistence.database._config_dir")
def test_list_projects(mock_config_dir, tmp_path: Path):
    mock_config_dir.return_value = tmp_path
    init_db()

    insert_project(Project(name="a", mode=ProjectMode.GREENFIELD, workspace_path="/tmp/a"))
    insert_project(Project(name="b", mode=ProjectMode.BROWNFIELD, workspace_path="/tmp/b"))

    projects = list_projects()
    assert len(projects) == 2
