"""Replaceable local worktree environment used by tools and safety gates."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class CommandExecution:
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class LocalWorktreeEnvironment:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, relative: str | Path) -> Path:
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path is outside workspace: {relative}") from exc
        return target

    def read_text(self, relative: str | Path) -> str:
        path = self.resolve(relative)
        if not path.exists():
            raise FileNotFoundError(str(relative))
        return path.read_text()

    def write_text(self, relative: str | Path, content: str) -> None:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def list_entries(self, relative: str | Path = ".") -> list[Path]:
        path = self.resolve(relative)
        if not path.exists():
            raise FileNotFoundError(str(relative))
        return sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name))

    def run(self, command: str, timeout: float) -> CommandExecution:
        try:
            process = subprocess.run(
                ["/bin/sh", "-lc", command],
                cwd=self.root,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
            return CommandExecution(
                command=command,
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandExecution(
                command=command,
                exit_code=124,
                stdout=exc.stdout if isinstance(exc.stdout, str) else "",
                stderr=exc.stderr if isinstance(exc.stderr, str) else "",
                timed_out=True,
            )
