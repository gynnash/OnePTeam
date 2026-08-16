"""UNDERSTAND stage — produce the acceptance baseline for the run."""
from __future__ import annotations

from pathlib import Path

from onep.greenfield.engine import GreenfieldEngine
from onep.greenfield.models import AcceptanceContract, GreenfieldRun
from onep.greenfield.recorder import GreenfieldRecorder
from onep.llm.cost import CostTracker


class HarnessUnsupportedMode(RuntimeError):
    """The harness does not yet route this workspace mode through the loop."""


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
