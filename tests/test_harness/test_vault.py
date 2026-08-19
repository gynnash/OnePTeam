from pathlib import Path

import pytest

from onep.harness.vault import (
    VaultWriter,
    global_vault_root,
    project_vault_root,
    section_for_type,
)


def test_sanitize_slugs():
    assert VaultWriter.sanitize("Delay Abstraction!") == "delay-abstraction"
    assert VaultWriter.sanitize("  How to Wire  ") == "how-to-wire"
    assert VaultWriter.sanitize("") == "note"
    assert VaultWriter.sanitize("a" * 200) == "a" * 80
    assert VaultWriter.sanitize("延迟抽象") == "延迟抽象"


def test_write_note_creates_frontmatter_and_body(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    path = writer.write_note(
        "Decisions",
        "use-flat-layout",
        {
            "type": "decision",
            "project": "demo",
            "iteration": 1,
            "tags": ["demo"],
            "created": "2026-08-17",
            "related": [],
        },
        "# Use Flat Layout\n\nBecause simpler.",
    )
    assert path == tmp_path / "project" / "Decisions" / "use-flat-layout.md"
    text = path.read_text()
    assert text.startswith("---\n")
    assert "type: decision" in text
    assert "# Use Flat Layout" in text


def test_write_note_rejects_path_traversal(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    with pytest.raises(ValueError):
        writer.note_path("../../etc", "evil")


def test_write_note_global_section_goes_to_global_root(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    path = writer.write_note(
        "Engineering/Principles",
        "delay-abstraction",
        {"type": "principle"},
        "# Delay Abstraction",
    )
    assert (
        path
        == tmp_path / "global" / "Engineering" / "Principles" / "delay-abstraction.md"
    )


def test_section_for_type_routing():
    assert section_for_type("decision") == "Decisions"
    assert section_for_type("failure") == "Failures"
    assert section_for_type("insight") == "Insights"
    assert section_for_type("discovery") == "Insights"
    assert section_for_type("problem") == "Sessions"
    assert section_for_type("nonsense") == "Sessions"


def test_write_event_note_routes_and_links(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    event = {
        "type": "decision",
        "iteration": 2,
        "problem": "how to wire",
        "selected": "flat",
        "reason": "simpler",
        "evidence": "gate passed",
        "files": ["app.py"],
        "outcome": "accepted",
    }
    path = writer.write_event_note(
        event,
        "demo",
        2,
        related=["how-to-flatten"],
    )
    slug = writer.event_note_slug(event)
    assert path == tmp_path / "project" / "Decisions" / f"{slug}.md"
    text = path.read_text()
    assert "type: decision" in text
    assert "[[how-to-flatten]]" in text
    assert "## Selected" in text
    assert "`app.py`" in text


def test_write_project_moc_lists_wikilinks_deduped(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    events = [
        {"type": "decision", "problem": "how to wire"},
        {"type": "decision", "problem": "how to wire"},
        {"type": "failure", "problem": "gate failed"},
    ]
    path = writer.write_project_moc(
        "demo", "build value", "completed", events, architecture="flat"
    )
    text = path.read_text()
    assert path == tmp_path / "project" / "Project.md"
    assert "## Decisions" in text
    assert "## Failures" in text
    decision_slug = writer.event_note_slug(events[0])
    failure_slug = writer.event_note_slug(events[2])
    assert text.count(f"[[{decision_slug}]]") == 1
    assert f"[[{failure_slug}]]" in text
    assert "- Status: completed" in text
    assert "- Architecture: flat" in text


def test_write_json_sanitizes_filename(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    path = writer.write_json(
        "Engineering/Articles",
        "../../demo.article.graph.json",
        {"nodes": [{"id": "n1"}]},
    )
    assert (
        path
        == tmp_path / "global" / "Engineering" / "Articles" / "demo.article.graph.json"
    )


def test_global_vault_root_config_and_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "onep.harness.vault._config_path", lambda: tmp_path / "config.yaml"
    )
    (tmp_path / "config.yaml").write_text(
        "knowledge:\n  vault_root: /tmp/custom-vault\n"
    )
    assert global_vault_root() == Path("/tmp/custom-vault")
    (tmp_path / "config.yaml").write_text("pipeline:\n  test_timeout: 5\n")
    assert global_vault_root() == Path.home() / ".onep" / "vault"


def test_global_vault_root_defaults_on_wrong_config_shape(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "onep.harness.vault._config_path", lambda: tmp_path / "config.yaml"
    )
    (tmp_path / "config.yaml").write_text("knowledge: true\n")
    assert global_vault_root() == Path("~/.onep/vault").expanduser()


def test_project_vault_root_supports_relative_override(tmp_path):
    config = tmp_path / ".onep" / "config.yaml"
    config.parent.mkdir()
    config.write_text("knowledge:\n  project_vault_root: docs/engineering-memory\n")
    assert project_vault_root(tmp_path) == tmp_path / "docs" / "engineering-memory"
