"""Deterministic identity for the current source tree, including uncommitted data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import subprocess


ALGORITHM = "onep-tree-v1"
_EXCLUDED_PARTS = {
    ".git",
    ".onep",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
}


@dataclass(frozen=True)
class TreeFingerprint:
    algorithm: str
    digest: str
    head_sha: str
    entry_count: int
    exclude_rules_digest: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _field(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _excluded(relative: str) -> bool:
    return any(part in _EXCLUDED_PARTS for part in PurePosixPath(relative).parts)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
    )


def _paths(root: Path) -> tuple[list[str], str]:
    try:
        raw = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        head = _git(root, "rev-parse", "HEAD").decode().strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        paths = []
        for path in root.rglob("*"):
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if not _excluded(relative) and (path.is_file() or path.is_symlink()):
                paths.append(relative)
        return sorted(set(paths), key=lambda value: value.encode("utf-8")), "null"
    paths = [
        value.decode("utf-8", "surrogateescape") for value in raw.split(b"\0") if value
    ]
    return (
        sorted(
            {value for value in paths if not _excluded(value)},
            key=lambda value: value.encode("utf-8", "surrogateescape"),
        ),
        head or "null",
    )


def fingerprint_tree(workspace: str | Path) -> TreeFingerprint:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace is not a directory: {root}")
    paths, head = _paths(root)
    rules = "\n".join(sorted(_EXCLUDED_PARTS)).encode()
    rules_digest = f"sha256:{sha256(rules).hexdigest()}"
    digest = sha256()
    _field(digest, ALGORITHM.encode())
    _field(digest, rules_digest.encode())
    _field(digest, head.encode())
    for relative in paths:
        path = root / relative
        encoded_path = relative.encode("utf-8", "surrogateescape")
        try:
            path.lstat()
        except FileNotFoundError:
            kind = b"deleted"
            content_digest = sha256(b"").digest()
        else:
            if path.is_symlink():
                kind = b"symlink"
                content_digest = sha256(
                    os.readlink(path).encode("utf-8", "surrogateescape")
                ).digest()
            elif path.is_file():
                kind = b"file"
                content_digest = sha256(path.read_bytes()).digest()
            else:
                continue
        _field(digest, encoded_path)
        _field(digest, kind)
        _field(digest, content_digest)
    return TreeFingerprint(
        algorithm=ALGORITHM,
        digest=f"sha256:{digest.hexdigest()}",
        head_sha=head,
        entry_count=len(paths),
        exclude_rules_digest=rules_digest,
    )
