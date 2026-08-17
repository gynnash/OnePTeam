"""HarnessRun YAML persistence and the user stop-request flag."""
from __future__ import annotations

from pathlib import Path

import yaml

from onep.harness.models import HarnessRun


def harness_run_path(workspace: Path) -> Path:
    return Path(workspace) / ".onep" / "harness" / "run.yaml"


def save_harness_run(run: HarnessRun) -> None:
    path = harness_run_path(Path(run.workspace))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(run.to_dict(), default_flow_style=False))


def load_harness_run(workspace: Path) -> HarnessRun | None:
    path = harness_run_path(workspace)
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None
    try:
        return HarnessRun.from_dict(raw)
    except (KeyError, TypeError, ValueError):
        return None


def stop_requested(workspace: Path) -> bool:
    return (
        Path(workspace) / ".onep" / "harness" / "stop_requested"
    ).exists()


def clear_stop_request(workspace: Path) -> None:
    (Path(workspace) / ".onep" / "harness" / "stop_requested").unlink(
        missing_ok=True
    )
