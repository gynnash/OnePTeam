"""Incremental, symbol-level repository map for bounded agent context."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


_SOURCE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
}
_IGNORED_DIRS = {
    ".git", ".onep", ".venv", "venv", "node_modules", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache",
}


@dataclass(frozen=True)
class RepoMapRefresh:
    changed: tuple[str, ...]
    deleted: tuple[str, ...]


class RepoMapIndex:
    def __init__(self, workspace: Path) -> None:
        self.path = Path(workspace) / "repo_map.json"
        self.entries: dict[str, dict[str, Any]] = {}
        self._load()

    def refresh(self, source: Path) -> RepoMapRefresh:
        source = Path(source).resolve()
        files = self._source_files(source)
        current = {str(path.relative_to(source)): path for path in files}
        changed = []
        for relative, path in current.items():
            try:
                content = path.read_text(errors="replace")
            except OSError:
                continue
            digest = _sha(content)
            if self.entries.get(relative, {}).get("hash") == digest:
                continue
            self.entries[relative] = self._entry(relative, content, digest)
            changed.append(relative)
        deleted = sorted(set(self.entries) - set(current))
        for relative in deleted:
            self.entries.pop(relative, None)
        self._save()
        return RepoMapRefresh(tuple(sorted(changed)), tuple(deleted))

    def affected_paths(self, changed: tuple[str, ...]) -> tuple[str, ...]:
        """Return changed files plus direct importers and nearby tests."""
        affected = set(changed)
        stems = {Path(path).stem for path in changed}
        for relative, entry in self.entries.items():
            imports = set(entry.get("imports") or ())
            if imports & stems:
                affected.add(relative)
            if _is_test(relative) and any(stem in relative for stem in stems):
                affected.add(relative)
        return tuple(sorted(affected))

    def paths(self, source: Path, relative_paths: tuple[str, ...]) -> list[Path]:
        root = Path(source).resolve()
        result = []
        for relative in relative_paths:
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                continue
            if path.is_file():
                result.append(path)
        return result

    def render(
        self,
        relevant_paths: tuple[str, ...] = (),
        max_chars: int = 12_000,
    ) -> str:
        relevant = set(relevant_paths)
        ordered = sorted(
            self.entries.items(),
            key=lambda item: (item[0] not in relevant, item[0]),
        )
        lines = ["## Repository Map"]
        for relative, entry in ordered:
            symbols = ", ".join(entry.get("symbols") or ()) or "-"
            imports = ", ".join(entry.get("imports") or ()) or "-"
            line = f"- {relative}: symbols=[{symbols}]; imports=[{imports}]"
            if sum(len(value) + 1 for value in lines) + len(line) > max_chars:
                lines.append("- ... repository map truncated to context budget")
                break
            lines.append(line)
        return "\n".join(lines)

    def _entry(self, relative: str, content: str, digest: str) -> dict[str, Any]:
        if Path(relative).suffix == ".py":
            symbols, imports = _python_structure(content)
        else:
            symbols, imports = _generic_structure(content)
        return {
            "hash": digest,
            "symbols": symbols,
            "imports": imports,
        }

    def _source_files(self, source: Path) -> list[Path]:
        return sorted(
            path for path in source.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _SOURCE_SUFFIXES
            and not any(part in _IGNORED_DIRS for part in path.parts)
        )

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self.entries = {
                str(path): value for path, value in raw.items()
                if isinstance(value, dict)
            }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.entries, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _python_structure(content: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [], []
    symbols = []
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[-1])
    return symbols[:80], sorted(set(imports))[:80]


def _generic_structure(content: str) -> tuple[list[str], list[str]]:
    symbols = re.findall(
        r"(?:class|function|interface|type|func|struct)\s+([A-Za-z_]\w*)",
        content,
    )
    imports = re.findall(
        r"(?:from\s+['\"]([^'\"]+)['\"]|import\s+.*?from\s+['\"]([^'\"]+)['\"])",
        content,
    )
    flattened = [Path(left or right).stem for left, right in imports]
    return list(dict.fromkeys(symbols))[:80], sorted(set(flattened))[:80]


def _is_test(path: str) -> bool:
    name = Path(path).name.lower()
    return "test" in Path(path).parts or name.startswith("test_") or ".test." in name


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
