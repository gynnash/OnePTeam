"""Scanner utilities: file walking, batching, and result filtering."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ScanResult:
    file_path: str
    is_strategy: bool
    reason: str
    chunk_id: str | None = None


@dataclass(frozen=True)
class ScanContentEntry:
    relative_path: str
    content: str
    chunk_index: int = 1
    chunk_count: int = 1

    @property
    def chunk_id(self) -> str:
        value = f"{self.relative_path}:{self.chunk_index}:{self.chunk_count}"
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def render(self) -> str:
        part = (
            f" (part {self.chunk_index}/{self.chunk_count})"
            if self.chunk_count > 1 else ""
        )
        return (
            f"### {self.relative_path}{part}\n"
            f"返回 JSON 时 file 字段必须使用: {self.relative_path}\n"
            f"返回 JSON 时 chunk_id 字段必须使用: {self.chunk_id}\n"
            f"```\n{self.content}\n```"
        )


@dataclass(frozen=True)
class ScanContentBatch:
    entries: tuple[ScanContentEntry, ...]
    estimated_tokens: int

    def render(self) -> str:
        return "\n\n".join(entry.render() for entry in self.entries)


def estimate_tokens(text: str) -> int:
    """Conservative provider-independent token estimate."""
    return max(1, (len(text) + 2) // 3)


def walk_files(source_path: Path) -> list[Path]:
    """Walk a directory and return all source files, skipping noise."""
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 "dist", "build", ".next", "target", "vendor", ".idea"}
    skip_extensions = {".pyc", ".pyo", ".class", ".o", ".so", ".dll",
                       ".exe", ".bin", ".png", ".jpg", ".svg", ".ico",
                       ".lock", ".min.js", ".min.css", ".map"}
    files = []
    for entry in source_path.rglob("*"):
        if entry.is_file():
            if any(part in skip_dirs for part in entry.parts):
                continue
            if entry.suffix in skip_extensions or entry.name.endswith(tuple(skip_extensions)):
                continue
            files.append(entry)
    return files


def batch_files(files: list[Path], max_batch_size: int = 20) -> list[list[Path]]:
    """Split a file list into batches for parallel LLM processing."""
    batches = []
    for i in range(0, len(files), max_batch_size):
        batches.append(files[i:i + max_batch_size])
    return batches


def build_content_batches(
    source_path: Path,
    files: list[Path],
    max_tokens: int = 20_000,
    max_file_chars: int = 6000,
    max_batch_chars: int = 60000,
) -> list[ScanContentBatch]:
    """Build bounded prompt blocks while covering every file and file tail."""
    if max_tokens <= 0 or max_file_chars <= 0 or max_batch_chars <= 0:
        raise ValueError("batch character limits must be positive")
    max_tokens = min(max_tokens, max(1, max_batch_chars // 3))
    max_chunk_tokens = min(
        max(1, max_tokens - 120),
        max(1, max_file_chars // 3),
    )
    entries: list[ScanContentEntry] = []
    for file_path in files:
        relative = str(file_path.relative_to(source_path))
        try:
            content = file_path.read_text(errors="replace")
        except OSError:
            content = "[无法读取]"
        chunks = _line_chunks(content, max_chunk_tokens)
        for part, chunk in enumerate(chunks, 1):
            entries.append(ScanContentEntry(
                relative, chunk, part, len(chunks)
            ))

    batches: list[ScanContentBatch] = []
    current: list[ScanContentEntry] = []
    used_tokens = 0
    for entry in entries:
        tokens = estimate_tokens(entry.render())
        separator_tokens = 1 if current else 0
        if tokens > max_tokens:
            raise RuntimeError(
                f"scanner entry exceeds token budget: {entry.chunk_id}"
            )
        if current and used_tokens + separator_tokens + tokens > max_tokens:
            batches.append(ScanContentBatch(tuple(current), used_tokens))
            current = []
            used_tokens = 0
            separator_tokens = 0
        current.append(entry)
        used_tokens += separator_tokens + tokens
    if current:
        batches.append(ScanContentBatch(tuple(current), used_tokens))
    included = {entry.relative_path for batch in batches for entry in batch.entries}
    expected = {str(path.relative_to(source_path)) for path in files}
    if included != expected:
        raise RuntimeError(f"scanner coverage mismatch: {expected - included}")
    return batches


def _line_chunks(content: str, max_tokens: int) -> list[str]:
    if not content:
        return [""]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in content.splitlines(keepends=True):
        line_tokens = estimate_tokens(line)
        if current and current_tokens + line_tokens > max_tokens:
            chunks.append("".join(current))
            current = []
            current_tokens = 0
        if line_tokens > max_tokens:
            size = max_tokens * 3
            if current:
                chunks.append("".join(current))
                current = []
                current_tokens = 0
            chunks.extend(line[index:index + size] for index in range(0, len(line), size))
        else:
            current.append(line)
            current_tokens += line_tokens
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def aggregate_chunk_results(
    entries: list[ScanContentEntry],
    results: list[ScanResult],
) -> list[ScanResult]:
    """Aggregate chunk-level responses to exactly one result per source file."""
    expected = []
    for entry in entries:
        if entry.relative_path not in expected:
            expected.append(entry.relative_path)
    by_chunk: dict[str, list[ScanResult]] = {
        entry.chunk_id: [] for entry in entries
    }
    single_chunks = {
        entry.relative_path: entry.chunk_id
        for entry in entries if entry.chunk_count == 1
    }
    for result in results:
        chunk_id = result.chunk_id or single_chunks.get(result.file_path)
        if chunk_id in by_chunk:
            by_chunk[chunk_id].append(result)
    by_file: dict[str, list[ScanResult]] = {path: [] for path in expected}
    for entry in entries:
        matches = by_chunk[entry.chunk_id]
        if len(matches) == 1:
            by_file[entry.relative_path].append(matches[0])
        else:
            reason = (
                "LLM 未返回该分片结果，保留待人工审查"
                if not matches else
                "LLM 对该分片返回重复结果，保留待人工审查"
            )
            by_file[entry.relative_path].append(
                ScanResult(
                    entry.relative_path, True, reason, entry.chunk_id
                )
            )
    aggregated = []
    for path in expected:
        matches = by_file[path]
        strategy = any(match.is_strategy for match in matches)
        reasons = list(dict.fromkeys(
            match.reason for match in matches if match.reason
        ))
        aggregated.append(ScanResult(path, strategy, "; ".join(reasons)))
    return aggregated


def aggregate_file_results(
    paths: list[str], results: list[ScanResult]
) -> list[ScanResult]:
    final = []
    for path in dict.fromkeys(paths):
        matches = [result for result in results if result.file_path == path]
        if not matches:
            final.append(ScanResult(
                path, True, "文件没有最终扫描结果，保留待人工审查"
            ))
            continue
        final.append(ScanResult(
            path,
            any(result.is_strategy for result in matches),
            "; ".join(dict.fromkeys(
                result.reason for result in matches if result.reason
            )),
        ))
    return final


def parse_scan_response(response: str) -> list[ScanResult]:
    """Parse LLM JSONL response into ScanResult objects."""
    results = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            results.append(ScanResult(
                file_path=obj["file"],
                is_strategy=obj["is_strategy"],
                reason=obj.get("reason", ""),
                chunk_id=obj.get("chunk_id"),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def get_strategy_files(results: list[ScanResult]) -> list[str]:
    """Filter scan results to only strategy-relevant files."""
    return [r.file_path for r in results if r.is_strategy]


def save_batch_results(workspace: Path, batch_index: int, results: list) -> None:
    """Append batch scan results to JSONL file."""
    path = workspace / "scan_results.jsonl"
    with open(path, "a") as f:
        for r in results:
            record = {"batch": batch_index, "file": r.file_path,
                      "is_strategy": r.is_strategy, "reason": r.reason}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def load_batch_results(workspace: Path) -> list[dict]:
    """Load all previously saved scan results."""
    path = workspace / "scan_results.jsonl"
    if not path.exists():
        return []
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def get_completed_batch_indices(workspace: Path) -> set[int]:
    """Get set of batch indices already completed."""
    path = workspace / "scan_results.jsonl"
    if not path.exists():
        return set()
    indices = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                indices.add(json.loads(line)["batch"])
    return indices


def load_analysis_items(workspace: Path) -> list[dict]:
    """Load analysis items from JSONL file in workspace."""
    path = workspace / "analysis_items.jsonl"
    if not path.exists():
        return []
    items = []
    for line in path.read_text().strip().split("\n"):
        if line.strip():
            items.append(json.loads(line))
    return items
