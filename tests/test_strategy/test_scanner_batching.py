from onep.strategy.scanner import (
    ScanResult,
    aggregate_chunk_results,
    build_content_batches,
)


def test_content_batches_cover_every_file(tmp_path):
    files = []
    for index in range(20):
        path = tmp_path / f"f{index}.py"
        path.write_text(str(index) * 6000)
        files.append(path)
    batches = build_content_batches(
        tmp_path, files, max_file_chars=6000, max_batch_chars=10000
    )
    joined = "\n".join(batch.render() for batch in batches)
    for path in files:
        assert f"### {path.name}" in joined


def test_large_file_is_split_without_losing_tail(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("A" * 5000 + "TAIL")
    batches = build_content_batches(
        tmp_path, [path], max_file_chars=1000, max_batch_chars=1500
    )
    assert "TAIL" in "\n".join(batch.render() for batch in batches)
    assert len(batches) > 1


def test_oversized_file_chunks_aggregate_to_one_result(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("\n".join(f"line_{i} = {i}" for i in range(5000)))
    batches = build_content_batches(tmp_path, [path], max_tokens=500)
    entries = [entry for batch in batches for entry in batch.entries]
    results = [
        ScanResult(
            "large.py",
            index == len(entries) - 1,
            f"part {index}",
            entry.chunk_id,
        )
        for index, entry in enumerate(entries)
    ]
    aggregated = aggregate_chunk_results(entries, results)
    assert len(aggregated) == 1
    assert aggregated[0].file_path == "large.py"
    assert aggregated[0].is_strategy


def test_missing_llm_entry_gets_explicit_fallback(tmp_path):
    path = tmp_path / "missing.py"
    path.write_text("x = 1\n")
    entries = build_content_batches(tmp_path, [path])[0].entries
    result = aggregate_chunk_results(list(entries), [])
    assert result[0].is_strategy
    assert "未返回" in result[0].reason


def test_every_rendered_batch_stays_within_token_budget(tmp_path):
    from onep.strategy.scanner import estimate_tokens

    path = tmp_path / "long.py"
    path.write_text("value = 1\n" * 5000)
    batches = build_content_batches(tmp_path, [path], max_tokens=300)
    assert all(estimate_tokens(batch.render()) <= 300 for batch in batches)
