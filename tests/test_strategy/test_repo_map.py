from onep.strategy.repo_map import RepoMapIndex


def test_repo_map_extracts_symbols_and_refreshes_incrementally(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    app = source / "app.py"
    app.write_text("import cache\n\nclass App:\n    pass\n")
    cache = source / "cache.py"
    cache.write_text("def load():\n    return 1\n")
    index = RepoMapIndex(tmp_path / "workspace")

    first = index.refresh(source)
    assert first.changed == ("app.py", "cache.py")
    assert index.entries["app.py"]["symbols"] == ["App"]
    assert index.refresh(source).changed == ()

    cache.write_text("def load():\n    return 2\n")
    changed = index.refresh(source)
    assert changed.changed == ("cache.py",)
    assert index.affected_paths(changed.changed) == ("app.py", "cache.py")


def test_repo_map_removes_deleted_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "gone.py"
    path.write_text("value = 1\n")
    index = RepoMapIndex(tmp_path / "workspace")
    index.refresh(source)
    path.unlink()
    refresh = index.refresh(source)
    assert refresh.deleted == ("gone.py",)
    assert "gone.py" not in index.entries


def test_deleted_file_still_selects_its_importers(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("import cache\n")
    cache = source / "cache.py"
    cache.write_text("value = 1\n")
    index = RepoMapIndex(tmp_path / "workspace")
    index.refresh(source)
    cache.unlink()
    refresh = index.refresh(source)
    assert index.affected_paths(refresh.deleted) == ("app.py", "cache.py")
