import pytest

from onep.web.knowledge import (
    article_content, list_articles, list_notes, note_reader,
    reasoning_graph, vault_root,
)
from tests.test_web.fixtures import seed_project, seed_vault


@pytest.fixture
def vault(tmp_path, monkeypatch):
    workspace = seed_project(tmp_path, monkeypatch, name="demo")
    return workspace, seed_vault(workspace, tmp_path, monkeypatch)


def test_list_notes_project_vault(vault):
    workspace, roots = vault
    notes = list_notes(workspace, "project")
    assert len(notes) == 2  # Project.md MOC + the seeded experiment note
    note = next(n for n in notes if n["path"].startswith("Experiments/"))
    assert note["title"] == "experiment"
    assert note["slug"].startswith("0-experiment-experiment-")
    assert note["type"] == "experiment"
    assert note["iteration"] == 1


def test_list_notes_global_vault(vault):
    workspace, roots = vault
    notes = list_notes(workspace, "global")
    assert any(note["slug"] == "demo" for note in notes)


def test_vault_root_unknown_vault_raises(vault):
    workspace, roots = vault
    with pytest.raises(ValueError):
        vault_root(workspace, "nope")


def test_note_reader(vault):
    workspace, roots = vault
    notes = list_notes(workspace, "project")
    event_note = next(n for n in notes if n["path"].startswith("Experiments/"))
    content = note_reader(workspace, "project", event_note["path"])
    assert content is not None
    assert "all tests pass" in content["body"]
    assert content["frontmatter"]["type"] == "experiment"
    assert content["frontmatter"]["iteration"] == 1


def test_note_reader_rejects_traversal(vault):
    workspace, roots = vault
    assert note_reader(workspace, "project", "../run.yaml") is None
    assert note_reader(workspace, "global", "..%2F..%2Fetc%2Fpasswd") is None
    assert note_reader(workspace, "project", "missing.md") is None


def test_reasoning_graph(vault):
    workspace, roots = vault
    graph = reasoning_graph(workspace)
    assert graph["nodes"], "expected at least one node"
    assert graph["edges"] == []
    ids = {node["id"] for node in graph["nodes"]}
    for node in graph["nodes"]:
        assert node["id"] in ids
        assert node["vault"] in ("project", "global")


def test_articles_list_and_content(vault):
    workspace, roots = vault
    articles = list_articles()
    assert len(articles) == 1
    assert articles[0]["slug"] == "demo"
    content = article_content("demo")
    assert content["title"] == "Demo Journey"
    assert "summary of the demo run" in content["markdown"]
    assert content["graph"] == {"nodes": [], "edges": []}
    assert article_content("missing") is None
