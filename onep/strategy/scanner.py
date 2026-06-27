"""Scanner utilities: file walking, batching, and result filtering."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ScanResult:
    file_path: str
    is_strategy: bool
    reason: str


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
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def get_strategy_files(results: list[ScanResult]) -> list[str]:
    """Filter scan results to only strategy-relevant files."""
    return [r.file_path for r in results if r.is_strategy]


def load_batch_results(workspace: Path) -> list[dict]:
    """Load analysis items from JSONL file in workspace."""
    path = workspace / "analysis_items.jsonl"
    if not path.exists():
        return []
    items = []
    for line in path.read_text().strip().split("\n"):
        if line.strip():
            items.append(json.loads(line))
    return items
