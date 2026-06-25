from pathlib import Path
from onep.strategy.scanner import (
    walk_files, batch_files, parse_scan_response, get_strategy_files, ScanResult,
)


def test_walk_files_skips_git_and_cache(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def foo(): pass")
    (tmp_path / "src" / "utils.py").write_text("def bar(): pass")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("...")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-313.pyc").write_text("...")
    files = walk_files(tmp_path)
    relative = [str(f.relative_to(tmp_path)) for f in files]
    assert "src/main.py" in relative
    assert "src/utils.py" in relative
    assert ".git/config" not in relative
    assert "__pycache__/main.cpython-313.pyc" not in relative


def test_batch_files():
    files = [Path(f"file_{i}.py") for i in range(25)]
    batches = batch_files(files, max_batch_size=10)
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 5


def test_parse_scan_response():
    response = '{"file": "a.py", "is_strategy": true, "reason": "ranking logic"}\n{"file": "b.py", "is_strategy": false, "reason": "utility"}'
    results = parse_scan_response(response)
    assert len(results) == 2
    assert results[0].is_strategy is True
    assert results[0].reason == "ranking logic"


def test_get_strategy_files():
    results = [
        ScanResult("a.py", True, "contains ranking logic"),
        ScanResult("b.py", False, "pure utility"),
        ScanResult("c.py", True, "prompt chain"),
    ]
    assert get_strategy_files(results) == ["a.py", "c.py"]
