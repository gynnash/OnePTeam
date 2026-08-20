"""HarnessRun YAML persistence and the user stop-request flag."""

from __future__ import annotations

from pathlib import Path
import os
import tempfile

import yaml

from onep.harness.models import HARNESS_SCHEMA_VERSION, HarnessRun


class HarnessStateCorrupt(RuntimeError):
    """A persisted run exists but cannot be safely resumed."""


def harness_run_path(workspace: Path) -> Path:
    return Path(workspace) / ".onep" / "harness" / "run.yaml"


def run_directory(run: HarnessRun, workspace: Path | None = None) -> Path:
    """Canonical recorder directory; mixed runs use the greenfield backend."""
    root = Path(workspace or run.workspace)
    if run.greenfield_run is not None:
        return root / ".onep" / "greenfield" / "runs" / run.greenfield_run.id
    return root / ".onep" / "optimize" / "runs" / run.id


def save_harness_run(run: HarnessRun) -> None:
    path = harness_run_path(Path(run.workspace))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix="run-", suffix=".yaml.tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                run.to_dict(),
                handle,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_harness_run(workspace: Path) -> HarnessRun | None:
    path = harness_run_path(workspace)
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HarnessStateCorrupt(f"cannot read harness state {path}: {exc}") from exc
    version = int(raw.get("schema_version") or 1)
    if version > HARNESS_SCHEMA_VERSION:
        raise HarnessStateCorrupt(
            f"harness state schema {version} is newer than supported "
            f"schema {HARNESS_SCHEMA_VERSION}"
        )
    try:
        return HarnessRun.from_dict(raw)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise HarnessStateCorrupt(f"invalid harness state {path}: {exc}") from exc


def stop_requested(workspace: Path) -> bool:
    return (Path(workspace) / ".onep" / "harness" / "stop_requested").exists()


def clear_stop_request(workspace: Path) -> None:
    (Path(workspace) / ".onep" / "harness" / "stop_requested").unlink(missing_ok=True)
