"""UNDERSTAND stage — produce the acceptance baseline for the run."""
from __future__ import annotations

from pathlib import Path

from onep.greenfield.engine import GreenfieldEngine
from onep.greenfield.models import AcceptanceContract, GreenfieldRun
from onep.greenfield.recorder import GreenfieldRecorder
from onep.llm.cost import CostTracker


class HarnessUnsupportedMode(RuntimeError):
    """The harness does not yet route this workspace mode through the loop."""


# Documentation files are not source code: a docs-only workspace has no
# code to optimize and routes as greenfield.
_DOCUMENTATION_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}


def detect_mode(workspace: Path, requirement: str) -> str:
    """Adaptive UNDERSTAND routing: greenfield | brownfield | mixed.

    A workspace with no source files is greenfield regardless of
    requirement. Existing code + a requirement is mixed (the greenfield
    loop's repository summary feeds the gap analysis); existing code with
    no requirement is brownfield (pure optimization).
    """
    from onep.strategy.scanner import walk_files
    has_code = any(
        path.suffix.lower() not in _DOCUMENTATION_EXTENSIONS
        for path in walk_files(Path(workspace))
    )
    if not has_code:
        return "greenfield"
    if requirement.strip():
        return "mixed"
    return "brownfield"


class UnderstandStage:
    """Produce the acceptance contract for a greenfield goal via the kernel."""

    def __init__(self, kernel: GreenfieldEngine, mode: str = "greenfield"):
        self.kernel = kernel
        self.mode = mode

    def run(
        self,
        run: GreenfieldRun,
        workspace: Path,
        recorder: GreenfieldRecorder,
        tracker: CostTracker,
    ) -> AcceptanceContract:
        if self.mode != "greenfield":
            raise HarnessUnsupportedMode(
                "Brownfield harness unification lands in P2; "
                "use `onep optimize` meanwhile."
            )
        return self.kernel._discover(run, workspace, recorder, tracker)
