"""File-level scan result cache keyed by content hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


class ScanCache:
    def __init__(self, workspace: Path):
        self.path = workspace / "scan_cache.jsonl"
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    self._data[entry["file"]] = entry

    def get(self, file_path: str, content: str) -> dict | None:
        h = file_hash(content)
        entry = self._data.get(file_path)
        if entry and entry.get("hash") == h:
            return entry
        return None

    def put(self, file_path: str, content: str, is_strategy: bool,
            reason: str, recheck_verdict: str = "",
            recheck_reason: str = "") -> None:
        h = file_hash(content)
        entry = {
            "file": file_path,
            "hash": h,
            "is_strategy": is_strategy,
            "reason": reason,
            "recheck_verdict": recheck_verdict,
            "recheck_reason": recheck_reason,
        }
        self._data[file_path] = entry
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
