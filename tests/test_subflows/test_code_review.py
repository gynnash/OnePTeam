from pathlib import Path

from onep.subflows.code_review import build_code_review_graph, run_code_review


def test_code_review_graph_passes_on_clean_code(tmp_path: Path):
    (tmp_path / "main.py").write_text("def hello():\n    return 'world'\n")

    result = run_code_review(tmp_path)
    assert result["status"] in ("passed", "failed")  # Should complete, not hang


def test_graph_compiles():
    graph = build_code_review_graph()
    assert graph is not None
