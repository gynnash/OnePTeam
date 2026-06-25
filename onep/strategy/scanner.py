"""Layer 1: Strategy file scanner. Walks a codebase and classifies files as strategy-relevant or not."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ScanResult:
    file_path: str
    is_strategy: bool
    reason: str


def _walk_files(source_path: Path) -> list[Path]:
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


def _batch_files(files: list[Path], max_batch_size: int = 20) -> list[list[Path]]:
    batches = []
    for i in range(0, len(files), max_batch_size):
        batches.append(files[i:i + max_batch_size])
    return batches


def _build_scan_prompt(file_paths: list[Path], source_root: Path) -> str:
    relative_paths = [str(p.relative_to(source_root)) for p in file_paths]
    file_list = "\n".join(relative_paths)
    return f"""Analyze the following files and determine whether each one contains business strategy or algorithm strategy logic.

Strategy logic includes:
- Recommendation, ranking, or matching algorithms
- LLM prompt chains, agent workflows, or model routing
- Caching, rate-limiting, or resource allocation strategies
- Business rules, pricing, fraud detection, or risk scoring
- Any non-trivial decision logic that impacts system behavior

NOT strategy logic:
- Pure utility functions (string formatting, date helpers)
- Configuration constants or enums
- Simple CRUD without decision logic
- Boilerplate (middleware, logging setup, routes registration)
- Test files

Files to analyze:
{file_list}

For each file, respond with a JSON object (one per line):
{{"file": "<path>", "is_strategy": true/false, "reason": "<one sentence in Chinese>"}}

Respond with exactly one JSON line per file, no other text."""


def scan_files(source_path: Path, llm_adapter=None) -> list[ScanResult]:
    all_files = _walk_files(source_path)
    batches = _batch_files(all_files)
    results: list[ScanResult] = []
    for batch in batches:
        if llm_adapter is not None:
            prompt = _build_scan_prompt(batch, source_path)
            response = llm_adapter.invoke(
                system_prompt="你是一位代码分析师。只输出JSON，每行一个文件的分析结果。",
                user_prompt=prompt,
                stage_name="analyzer",
            )
            for line in response.strip().split("\n"):
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    results.append(ScanResult(
                        file_path=obj["file"],
                        is_strategy=obj["is_strategy"],
                        reason=obj.get("reason", ""),
                    ))
        else:
            for f in batch:
                results.append(ScanResult(
                    file_path=str(f.relative_to(source_path)),
                    is_strategy=True,
                    reason="LLM不可用，默认标记为策略文件待人工审查",
                ))
    return results


def get_strategy_files(results: list[ScanResult]) -> list[str]:
    return [r.file_path for r in results if r.is_strategy]
